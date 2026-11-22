from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, select
from werkzeug.security import check_password_hash

from .auth import _body, delete_user_sessions, hash_password, login_required
from .errors import ApiError
from .extensions import db
from .models import User
from .validators import check_password, clean_email, clean_name, clean_text

bp = Blueprint("users", __name__, url_prefix="/api/users")


@bp.get("")
@login_required
def search_users():
    """Other active users, for the Send page. Only id, name and username are exposed."""
    q = clean_text(request.args.get("q", ""), 80).lower()
    stmt = select(User).where(User.is_active.is_(True), User.id != g.user.id)
    if q:
        stmt = stmt.where(
            func.lower(User.name).contains(q, autoescape=True)
            | User.username.contains(q, autoescape=True)
        )
    users = db.session.scalars(stmt.order_by(func.lower(User.name)).limit(50)).all()
    return jsonify({"items": [u.to_public() for u in users]})


@bp.patch("/me")
@login_required
def update_profile():
    data = _body()
    user = g.user
    if "name" in data:
        user.name = clean_name(data["name"])
    if "email" in data:
        new_email = clean_email(data["email"])
        if new_email != user.email:
            if new_email is not None:
                # Changing the email needs proof of the current password.
                pw = data.get("currentPassword")
                if not isinstance(pw, str) or not check_password_hash(user.password_hash, pw):
                    raise ApiError(
                        "invalid_credentials", "Enter your current password to change email.", 403
                    )
                taken = db.session.scalar(
                    select(User.id).where(User.email == new_email, User.id != user.id)
                )
                if taken:
                    raise ApiError("conflict", "That email is already registered.", 409)
            user.email = new_email
    db.session.commit()
    return jsonify({"user": user.to_dict()})


@bp.post("/me/password")
@login_required
def change_password():
    data = _body()
    user = g.user
    current = data.get("currentPassword")
    if not isinstance(current, str) or not check_password_hash(user.password_hash, current):
        raise ApiError("invalid_credentials", "Current password is incorrect.", 403)
    new_password = check_password(data.get("newPassword"))
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    # Every other device is signed out immediately.
    delete_user_sessions(user.id, except_session_id=g.session.id)
    db.session.commit()
    return jsonify({"ok": True})
