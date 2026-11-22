import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

import psutil
from flask import Flask, g, request
from flask_cors import CORS

from .config import BACKEND_DIR, load_config, resolve_secret_key
from .constants import SUBJECTS
from .errors import register_error_handlers
from .extensions import db
from .ratelimit import AttemptLimiter


def create_app(overrides=None):
    if sys.version_info < (3, 11):
        raise RuntimeError("FileGo needs Python 3.11 or newer.")

    app = Flask(__name__)
    app.config.update(load_config())
    if overrides:
        app.config.update(overrides)
    app.config["SECRET_KEY"] = resolve_secret_key(app.config)
    app.url_map.strict_slashes = False

    os.makedirs(app.config["STORAGE_DIR"], exist_ok=True)

    db.init_app(app)
    CORS(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=True,
    )
    app.extensions["login_limiter"] = AttemptLimiter()
    app.extensions["register_limiter"] = AttemptLimiter()

    register_error_handlers(app)
    _register_blueprints(app)
    _register_hooks(app)
    _setup_logging(app)

    from .cli import register_cli

    register_cli(app)

    with app.app_context():
        db.create_all()
        ensure_subjects()

    psutil.cpu_percent(interval=None)  # prime: the first call always returns 0
    return app


def _register_blueprints(app):
    from . import auth, files, meta, transfers, users

    app.register_blueprint(meta.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(users.bp)
    app.register_blueprint(files.bp)
    app.register_blueprint(files.stats_bp)
    app.register_blueprint(transfers.bp)


def _register_hooks(app):
    @app.before_request
    def _start_timer():
        g.request_started = time.perf_counter()

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.after_request
    def _log_request(resp):
        started = g.get("request_started")
        if started is not None and request.path.startswith("/api/"):
            ms = (time.perf_counter() - started) * 1000
            user_id = g.user.id if "user" in g else "-"
            logging.getLogger("filego.access").info(
                "%s %s %s %.1fms user=%s", request.method, request.path, resp.status_code, ms, user_id
            )
        return resp


def _setup_logging(app):
    """Rotating access/error log. Never logs passwords, tokens or file contents."""
    if app.testing or not app.config.get("LOG_TO_FILE"):
        return
    logger = logging.getLogger("filego")
    if logger.handlers:
        return
    log_dir = BACKEND_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    handler = RotatingFileHandler(log_dir / "filego.log", maxBytes=1_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def ensure_subjects():
    """The fixed subject list exists after every start."""
    from .models import Subject

    if db.session.query(Subject.id).first() is not None:
        return
    for sid, code, name in SUBJECTS:
        db.session.add(Subject(id=sid, code=code, name=name))
    db.session.commit()
