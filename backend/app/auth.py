import hashlib
import secrets
from datetime import timedelta
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import select
from werkzeug.security import check_password_hash, generate_password_hash

from .constants import SESSION_ABSOLUTE_DAYS, SESSION_COOKIE, SESSION_IDLE_HOURS
from .errors import ApiError
from .extensions import db
from .models import Session, User, iso, utcnow
from .validators import check_password, clean_email, clean_name, clean_username

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# A real hash so unknown usernames cost the same time as wrong passwords.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def hash_password(password):
    return generate_password_hash(password, method="scrypt")


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip():
    return request.remote_addr or "unknown"


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("bad_request", "Send a JSON object.", 400)
    return data


def create_session(user):
    token = secrets.token_urlsafe(32)
    now = utcnow()
    session = Session(
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_token=secrets.token_urlsafe(24),
        user_agent=(request.headers.get("User-Agent") or "")[:255],
        ip=client_ip(),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(days=SESSION_ABSOLUTE_DAYS),
    )
    db.session.add(session)
    user.last_login_at = now
    db.session.commit()
    return token, session


def attach_cookie(response, token):
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_ABSOLUTE_DAYS * 86400,
        httponly=True,
        samesite="Lax",
        secure=current_app.config["COOKIE_SECURE"],
        path="/",
    )
    return response


def clear_cookie(response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


def delete_user_sessions(user_id, except_session_id=None):
    stmt = db.delete(Session).where(Session.user_id == user_id)
    if except_session_id:
        stmt = stmt.where(Session.id != except_session_id)
    db.session.execute(stmt)


def _authenticate(admin=False):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise ApiError("unauthenticated", "Please log in.", 401)
    session = db.session.scalar(select(Session).where(Session.token_hash == hash_token(token)))
    now = utcnow()
    if (
        session is None
        or session.expires_at <= now
        or now - session.last_seen_at > timedelta(hours=SESSION_IDLE_HOURS)
    ):
        if session is not None:
            db.session.delete(session)
            db.session.commit()
        raise ApiError("unauthenticated", "Your session has expired. Please log in again.", 401)
    user = db.session.get(User, session.user_id)
    if user is None or not user.is_active:
        db.session.delete(session)
        db.session.commit()
        raise ApiError("unauthenticated", "This account is not available.", 401)
    if request.method not in SAFE_METHODS:
        sent = request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(sent, session.csrf_token):
            raise ApiError("csrf_failed", "Missing or invalid CSRF token.", 403)
    if admin and user.role != "admin":
        raise ApiError("forbidden", "Administrator access is required.", 403)
    if now - session.last_seen_at > timedelta(seconds=60):
        session.last_seen_at = now
        db.session.commit()
    g.user = user
    g.session = session


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        _authenticate()
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        _authenticate(admin=True)
        return fn(*args, **kwargs)

    return wrapper


def _session_reply(user, status=200):
    token, session = create_session(user)
    resp = jsonify({"user": user.to_dict(), "csrfToken": session.csrf_token})
    resp.status_code = status
    return attach_cookie(resp, token)


@bp.post("/register")
def register():
    cfg = current_app.config
    if cfg["REGISTRATION_MODE"] == "closed":
        raise ApiError("forbidden", "Registration is closed. Ask an administrator.", 403)
    limiter = current_app.extensions["register_limiter"]
    ip_key = "reg:" + client_ip()
    if limiter.count(ip_key, cfg["REGISTER_WINDOW_SECONDS"]) >= cfg["REGISTER_MAX_PER_IP"]:
        raise ApiError("rate_limited", "Too many registrations. Try again later.", 429)
    limiter.add(ip_key, cfg["REGISTER_WINDOW_SECONDS"])

    data = _body()
    name = clean_name(data.get("name"))
    username = clean_username(data.get("username"))
    email = clean_email(data.get("email"))
    password = check_password(data.get("password"))

    if db.session.scalar(select(User.id).where(User.username == username)):
        raise ApiError("conflict", "That username is already taken.", 409)
    if email and db.session.scalar(select(User.id).where(User.email == email)):
        raise ApiError("conflict", "That email is already registered.", 409)

    # Registration always creates a student. Admins come from the seed script or the CLI.
    user = User(
        name=name,
        username=username,
        email=email,
        password_hash=hash_password(password),
        role="student",
    )
    db.session.add(user)
    db.session.commit()
    return _session_reply(user, 201)


@bp.post("/login")
def login():
    cfg = current_app.config
    limiter = current_app.extensions["login_limiter"]
    window = cfg["LOGIN_WINDOW_SECONDS"]
    data = _body()
    ident = clean_text_ident(data.get("username"))
    password = data.get("password")
    user_key = "user:" + ident
    ip_key = "ip:" + client_ip()

    if (
        limiter.count(user_key, window) >= cfg["LOGIN_MAX_PER_USER"]
        or limiter.count(ip_key, window) >= cfg["LOGIN_MAX_PER_IP"]
    ):
        raise ApiError("rate_limited", "Too many failed attempts. Try again in 15 minutes.", 429)

    user = None
    if ident:
        column = User.email if "@" in ident else User.username
        user = db.session.scalar(select(User).where(column == ident))
    valid = False
    if isinstance(password, str):
        hash_to_check = user.password_hash if user else _DUMMY_HASH
        valid = check_password_hash(hash_to_check, password) and user is not None

    if not valid or not user.is_active:
        limiter.add(user_key, window)
        limiter.add(ip_key, window)
        raise ApiError("invalid_credentials", "Incorrect username or password.", 401)

    limiter.clear(user_key)
    return _session_reply(user)


def clean_text_ident(value):
    return str(value or "").strip().lower()[:255]


@bp.post("/logout")
@login_required
def logout():
    db.session.delete(g.session)
    db.session.commit()
    return clear_cookie(jsonify({"ok": True}))


@bp.get("/me")
@login_required
def me():
    return jsonify({"user": g.user.to_dict(), "csrfToken": g.session.csrf_token})


@bp.get("/sessions")
@login_required
def list_sessions():
    rows = db.session.scalars(
        select(Session).where(Session.user_id == g.user.id).order_by(Session.last_seen_at.desc())
    ).all()
    return jsonify(
        {
            "items": [
                {
                    "id": s.id,
                    "device": s.user_agent,
                    "ip": s.ip,
                    "createdAt": iso(s.created_at),
                    "lastSeenAt": iso(s.last_seen_at),
                    "current": s.id == g.session.id,
                }
                for s in rows
            ]
        }
    )


@bp.delete("/sessions/<session_id>")
@login_required
def revoke_session(session_id):
    s = db.session.get(Session, session_id)
    if s is None or s.user_id != g.user.id:
        raise ApiError("not_found", "Session not found.", 404)
    current = s.id == g.session.id
    db.session.delete(s)
    db.session.commit()
    resp = jsonify({"ok": True})
    return clear_cookie(resp) if current else resp
