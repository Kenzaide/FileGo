from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from .auth import login_required
from .errors import ApiError
from .extensions import db
from .filesvc import file_dict, paging, receive_upload, resolve_category, resolve_subject, transfer_dict
from .models import Transfer, TransferLog, User

bp = Blueprint("transfers", __name__, url_prefix="/api/transfers")


@bp.post("")
@login_required
def send():
    """Direct send: raw body is the file, query has recipientId (and optional title/subject/category).

    The file is always stored private; the recipient may read it because of the transfer row.
    """
    q = request.args
    recipient = db.session.get(User, q.get("recipientId", ""))
    if recipient is None or not recipient.is_active:
        raise ApiError("not_found", "Recipient not found.", 404)
    if recipient.id == g.user.id:
        raise ApiError("validation_error", "You cannot send a file to yourself.", 400)
    subject = resolve_subject(q.get("subject"), default_name="General")
    category = resolve_category(q.get("category"), default="Other")
    file, transfer, log_row = receive_upload(
        g.user, "private", subject, category, q.get("title", ""), recipient=recipient
    )
    return (
        jsonify(
            {
                "transfer": transfer_dict(transfer, seconds=log_row.server_seconds),
                "file": file_dict(file),
                "logId": log_row.id,
            }
        ),
        201,
    )


@bp.get("")
@login_required
def list_transfers():
    box = request.args.get("box")
    if box not in ("received", "sent"):
        raise ApiError("validation_error", "box must be received or sent.", 400)
    page, per_page = paging()
    column = Transfer.recipient_id if box == "received" else Transfer.sender_id
    where = column == g.user.id
    total = db.session.scalar(select(func.count(Transfer.id)).where(where))
    rows = db.session.scalars(
        select(Transfer)
        .options(selectinload(Transfer.file), selectinload(Transfer.sender), selectinload(Transfer.recipient))
        .where(where)
        .order_by(Transfer.created_at.desc(), Transfer.id)
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()
    # Duration comes from the matching upload log (browser time when reported, else server time).
    seconds = {}
    ids = [t.file_id for t in rows]
    if ids:
        for fid, client_s, server_s in db.session.execute(
            select(TransferLog.file_id, TransferLog.client_seconds, TransferLog.server_seconds).where(
                TransferLog.file_id.in_(ids), TransferLog.type == "upload", TransferLog.status == "completed"
            )
        ):
            seconds[fid] = client_s or server_s
    return jsonify(
        {
            "items": [transfer_dict(t, seconds=seconds.get(t.file_id)) for t in rows],
            "total": total,
            "page": page,
            "perPage": per_page,
        }
    )


@bp.get("/unread-count")
@login_required
def unread_count():
    n = db.session.scalar(
        select(func.count(Transfer.id)).where(
            Transfer.recipient_id == g.user.id, Transfer.downloaded_at.is_(None)
        )
    )
    return jsonify({"count": n})
