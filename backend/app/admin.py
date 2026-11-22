"""Basic administration (module 6): users, all files, storage and system-wide statistics."""
import secrets
import string

import psutil
from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import contains_eager

from .auth import _body, admin_required, delete_user_sessions, hash_password
from .errors import ApiError
from .extensions import db
from .filesvc import delete_file, file_dict, paging
from .insights import csv_response, speed_mbps
from .models import File, Subject, Transfer, TransferLog, User, iso
from .validators import clean_text

bp = Blueprint("admin", __name__, url_prefix="/api/admin")

# No look-alike characters (0/O, 1/l/I) so a temporary password can be read out loud.
TEMP_ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")


def _admin_count():
    return db.session.scalar(
        select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True))
    )


def _get_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        raise ApiError("not_found", "User not found.", 404)
    return user


def admin_user_dict(user, file_count=0, storage=0):
    return {
        **user.to_dict(),
        "isActive": user.is_active,
        "lastLoginAt": iso(user.last_login_at),
        "fileCount": file_count,
        "storageBytes": int(storage or 0),
    }


# ---------------------------------------------------------------- users

@bp.get("/users")
@admin_required
def users():
    page, per_page = paging()
    conds = []
    q = clean_text(request.args.get("q", ""), 80).lower()
    if q:
        conds.append(
            or_(
                func.lower(User.name).contains(q, autoescape=True),
                func.lower(User.username).contains(q, autoescape=True),
            )
        )
    total = db.session.scalar(select(func.count(User.id)).where(*conds))
    rows = db.session.scalars(
        select(User).where(*conds).order_by(User.created_at, User.id).limit(per_page).offset((page - 1) * per_page)
    ).all()
    usage = {
        owner_id: (count, size)
        for owner_id, count, size in db.session.execute(
            select(File.owner_id, func.count(File.id), func.coalesce(func.sum(File.size), 0)).group_by(File.owner_id)
        )
    }
    items = [admin_user_dict(u, *usage.get(u.id, (0, 0))) for u in rows]
    return jsonify({"items": items, "total": total, "page": page, "perPage": per_page})


@bp.patch("/users/<user_id>")
@admin_required
def update_user(user_id):
    user = _get_user(user_id)
    data = _body()
    if user.id == g.user.id and ("isActive" in data or "role" in data):
        raise ApiError("forbidden", "You cannot change your own role or deactivate your own account.", 403)

    if "isActive" in data:
        if not isinstance(data["isActive"], bool):
            raise ApiError("validation_error", "isActive must be true or false.", 400)
        if not data["isActive"] and user.role == "admin" and user.is_active and _admin_count() <= 1:
            raise ApiError("conflict", "The last remaining administrator cannot be deactivated.", 409)
    if "role" in data:
        if data["role"] not in ("admin", "student"):
            raise ApiError("validation_error", "role must be admin or student.", 400)
        if data["role"] == "student" and user.role == "admin" and user.is_active and _admin_count() <= 1:
            raise ApiError("conflict", "The last remaining administrator cannot be demoted.", 409)

    if "isActive" in data:
        user.is_active = data["isActive"]
        if not user.is_active:
            delete_user_sessions(user.id)  # revoked immediately
    if "role" in data:
        user.role = data["role"]
    db.session.commit()
    return jsonify({"user": admin_user_dict(user)})


@bp.post("/users/<user_id>/reset-password")
@admin_required
def reset_password(user_id):
    user = _get_user(user_id)
    if user.id == g.user.id:
        raise ApiError("forbidden", "Change your own password in Settings.", 403)
    temp = "".join(secrets.choice(TEMP_ALPHABET) for _ in range(10))
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    delete_user_sessions(user.id)
    db.session.commit()
    # Shown once to the administrator, who hands it to the student. Never logged or stored in plain text.
    return jsonify({"temporaryPassword": temp, "user": admin_user_dict(user)})


# ---------------------------------------------------------------- files

@bp.get("/files")
@admin_required
def files():
    """Every file, public and private (administrators may access all files)."""
    page, per_page = paging()
    conds = []
    visibility = request.args.get("visibility")
    if visibility:
        if visibility not in ("public", "private"):
            raise ApiError("validation_error", "visibility must be public or private.", 400)
        conds.append(File.visibility == visibility)
    q = clean_text(request.args.get("q", ""), 120).lower()
    if q:
        conds.append(
            or_(
                func.lower(File.name).contains(q, autoescape=True),
                func.lower(User.name).contains(q, autoescape=True),
                func.lower(User.username).contains(q, autoescape=True),
            )
        )
    joins = lambda s: s.join(User, File.owner_id == User.id).join(Subject, File.subject_id == Subject.id)
    total = db.session.scalar(joins(select(func.count(File.id))).where(*conds))
    storage = db.session.scalar(joins(select(func.coalesce(func.sum(File.size), 0))).where(*conds))
    rows = db.session.scalars(
        joins(select(File))
        .options(contains_eager(File.owner), contains_eager(File.subject))
        .where(*conds)
        .order_by(File.created_at.desc(), File.id)
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()
    return jsonify(
        {"items": [file_dict(f) for f in rows], "total": total, "storageBytes": int(storage), "page": page, "perPage": per_page}
    )


@bp.delete("/files/<file_id>")
@admin_required
def remove_file(file_id):
    f = db.session.get(File, file_id)
    if f is None:
        raise ApiError("not_found", "File not found.", 404)
    removed = delete_file(f)
    return jsonify({"deleted": True, "removedTransfers": removed})


# ---------------------------------------------------------------- statistics and export

@bp.get("/stats")
@admin_required
def stats():
    scalar = lambda stmt: db.session.scalar(stmt) or 0
    uploads = db.session.execute(
        select(func.count(TransferLog.id), func.coalesce(func.sum(TransferLog.bytes_transferred), 0))
        .where(TransferLog.type == "upload", TransferLog.status == "completed")
    ).one()
    downloads = db.session.execute(
        select(func.count(TransferLog.id), func.coalesce(func.sum(TransferLog.bytes_transferred), 0))
        .where(TransferLog.type == "download", TransferLog.status == "completed")
    ).one()
    total_logs = scalar(select(func.count(TransferLog.id)))
    failed = scalar(select(func.count(TransferLog.id)).where(TransferLog.status == "failed"))
    speeds = [
        speed_mbps(b or s, secs)
        for b, s, secs in db.session.execute(
            select(TransferLog.bytes_transferred, TransferLog.size, TransferLog.server_seconds).where(
                TransferLog.type == "upload", TransferLog.status == "completed"
            )
        )
    ]
    speeds = [v for v in speeds if v is not None]
    per_subject = [
        {"subject": s.label, "files": n}
        for s, n in db.session.execute(
            select(Subject, func.count(File.id)).join(File, File.subject_id == Subject.id).group_by(Subject.id).order_by(func.count(File.id).desc())
        )
    ]
    top = [
        {"id": u.id, "name": u.name, "username": u.username, "files": n, "storageBytes": int(size)}
        for u, n, size in db.session.execute(
            select(User, func.count(File.id), func.coalesce(func.sum(File.size), 0))
            .join(File, File.owner_id == User.id)
            .group_by(User.id)
            .order_by(func.sum(File.size).desc())
            .limit(5)
        )
    ]
    du = psutil.disk_usage(current_app.config["STORAGE_DIR"])
    return jsonify(
        {
            "users": {
                "total": scalar(select(func.count(User.id))),
                "active": scalar(select(func.count(User.id)).where(User.is_active.is_(True))),
                "admins": scalar(select(func.count(User.id)).where(User.role == "admin")),
            },
            "files": {
                "total": scalar(select(func.count(File.id))),
                "public": scalar(select(func.count(File.id)).where(File.visibility == "public")),
                "private": scalar(select(func.count(File.id)).where(File.visibility == "private")),
                "storageBytes": int(scalar(select(func.sum(File.size)))),
                "downloads": int(scalar(select(func.sum(File.downloads)))),
            },
            "transfers": {
                "sent": scalar(select(func.count(Transfer.id))),
                "delivered": scalar(select(func.count(Transfer.id)).where(Transfer.downloaded_at.is_(None))),
                "downloaded": scalar(select(func.count(Transfer.id)).where(Transfer.downloaded_at.is_not(None))),
            },
            "activity": {
                "uploads": uploads[0],
                "uploadedBytes": int(uploads[1]),
                "downloads": downloads[0],
                "downloadedBytes": int(downloads[1]),
                "failed": failed,
                "successRate": round((total_logs - failed) / total_logs * 100, 2) if total_logs else None,
                "avgUploadSpeedMBps": round(sum(speeds) / len(speeds), 4) if speeds else None,
            },
            "disk": {"totalBytes": du.total, "usedBytes": du.used, "freeBytes": du.free},
            "bySubject": per_subject,
            "topUploaders": top,
        }
    )


@bp.get("/transfers/export.csv")
@admin_required
def export_all():
    rows = db.session.scalars(select(TransferLog).order_by(TransferLog.created_at)).all()
    return csv_response(rows, "filego-all-transfers.csv")
