import os

from flask import Blueprint, Response, g, jsonify, request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import contains_eager

from .auth import _body, login_required
from .constants import PREVIEW_EXTENSIONS, ALLOWED_EXTENSIONS
from .errors import ApiError
from .extensions import db
from .filesvc import (
    content_disposition,
    delete_file,
    download_name,
    file_dict,
    get_readable_file,
    paging,
    receive_upload,
    require_manage,
    resolve_category,
    resolve_subject,
    resolve_visibility,
    send_download,
    verify_integrity,
)
from .models import File, Subject, Transfer, User
from .storage import path_for
from .validators import clean_text

bp = Blueprint("files", __name__, url_prefix="/api/files")
stats_bp = Blueprint("stats", __name__, url_prefix="/api/stats")


def _filters(user, scope):
    conds = []
    if scope == "mine":
        conds.append(File.owner_id == user.id)
    else:
        conds.append(File.visibility == "public")
    q = clean_text(request.args.get("q", ""), 120).lower()
    if q:
        conds.append(
            or_(
                func.lower(File.name).contains(q, autoescape=True),
                func.lower(User.name).contains(q, autoescape=True),
                func.lower(User.username).contains(q, autoescape=True),
                func.lower(Subject.name).contains(q, autoescape=True),
                func.lower(func.coalesce(Subject.code, "")).contains(q, autoescape=True),
            )
        )
    subject = clean_text(request.args.get("subject", ""), 120).lower()
    if subject and subject != "all":
        conds.append(
            or_(
                Subject.id == subject,
                func.lower(func.coalesce(Subject.code, "")) == subject,
                func.lower(Subject.name).contains(subject, autoescape=True),
            )
        )
    category = clean_text(request.args.get("category", ""), 60).lower()
    if category and category != "all":
        conds.append(func.lower(File.category) == category)
    return conds


@bp.get("")
@login_required
def list_files():
    scope = request.args.get("scope", "library")
    if scope not in ("library", "mine"):
        raise ApiError("validation_error", "scope must be library or mine.", 400)
    page, per_page = paging()
    conds = _filters(g.user, scope)
    joins = lambda s: s.join(User, File.owner_id == User.id).join(Subject, File.subject_id == Subject.id)
    total = db.session.scalar(joins(select(func.count(File.id))).where(*conds))
    rows = db.session.scalars(
        joins(select(File))
        .options(contains_eager(File.owner), contains_eager(File.subject))
        .where(*conds)
        .order_by(File.created_at.desc(), File.id)
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()
    return jsonify({"items": [file_dict(f) for f in rows], "total": total, "page": page, "perPage": per_page})


@bp.post("")
@login_required
def upload():
    """Raw streaming upload: file bytes are the request body, metadata is in the query string."""
    q = request.args
    subject = resolve_subject(q.get("subject"))
    category = resolve_category(q.get("category"))
    visibility = resolve_visibility(q.get("visibility"))
    file, _, log_row = receive_upload(g.user, visibility, subject, category, q.get("title", ""))
    return jsonify({"file": file_dict(file), "logId": log_row.id}), 201


@bp.get("/<file_id>")
@login_required
def details(file_id):
    return jsonify({"file": file_dict(get_readable_file(file_id, g.user))})


@bp.patch("/<file_id>")
@login_required
def update_file(file_id):
    f = get_readable_file(file_id, g.user)
    require_manage(g.user, f)
    data = _body()
    # Validate everything first so a bad field changes nothing.
    new = {}
    if "name" in data:
        name = clean_text(data["name"], 255)
        if not name:
            raise ApiError("validation_error", "Title cannot be empty.", 400)
        new["name"] = name
    if "subject" in data or "subjectId" in data:
        new["subject_id"] = resolve_subject(data.get("subjectId") or data.get("subject")).id
    if "category" in data:
        new["category"] = resolve_category(data["category"])
    if "visibility" in data:
        new["visibility"] = resolve_visibility(str(data["visibility"]))
    for key, value in new.items():
        setattr(f, key, value)
    db.session.commit()
    return jsonify({"file": file_dict(f)})


@bp.delete("/<file_id>")
@login_required
def remove_file(file_id):
    f = get_readable_file(file_id, g.user)
    require_manage(g.user, f)
    removed = delete_file(f)
    return jsonify({"ok": True, "removedTransfers": removed})


@bp.route("/<file_id>/download", methods=["GET", "HEAD"])
@login_required
def download(file_id):
    f = get_readable_file(file_id, g.user)
    return send_download(f, g.user)


@bp.get("/<file_id>/preview")
@login_required
def preview(file_id):
    f = get_readable_file(file_id, g.user)
    ext = f.kind.lower()
    if ext not in PREVIEW_EXTENSIONS:
        raise ApiError("unsupported_type", "This file type cannot be previewed. Download it instead.", 415)
    try:
        data = open(path_for(f.stored_name), "rb")
    except OSError:
        raise ApiError("file_missing", "The file's data is missing on the server.", 404)
    size = os.path.getsize(data.name)

    def chunks():
        with data:
            while True:
                chunk = data.read(256 * 1024)
                if not chunk:
                    break
                yield chunk

    resp = Response(chunks(), status=200)
    # Content type comes from the allowlist, never from the upload.
    resp.headers["Content-Type"] = ALLOWED_EXTENSIONS[ext]
    resp.headers["Content-Length"] = str(size)
    resp.headers["Content-Disposition"] = content_disposition("inline", download_name(f))
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"  # the app shows previews in its own pages
    if ext == "pdf":
        # Chrome's PDF viewer does not run inside a sandboxed response, so no `sandbox` here.
        resp.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'self'"
    else:
        resp.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; frame-ancestors 'self'"
    return resp


@bp.post("/<file_id>/verify")
@login_required
def verify(file_id):
    f = get_readable_file(file_id, g.user)
    return jsonify(verify_integrity(f))


@stats_bp.get("/me")
@login_required
def my_stats():
    uid = g.user.id
    my_files = db.session.scalar(select(func.count(File.id)).where(File.owner_id == uid))
    received = db.session.scalar(select(func.count(Transfer.id)).where(Transfer.recipient_id == uid))
    sent = db.session.scalar(select(func.count(Transfer.id)).where(Transfer.sender_id == uid))
    # How many times OTHER users downloaded the files I shared (owner's own downloads excluded).
    downloads = db.session.scalar(select(func.coalesce(func.sum(File.downloads), 0)).where(File.owner_id == uid))
    return jsonify({"myFiles": my_files, "received": received, "sent": sent, "downloads": int(downloads)})
