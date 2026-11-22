import os
import secrets
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

_KNOWN_DEFAULT_KEYS = {"", "change-me", "dev", "secret", "changeme"}


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def load_config():
    """Defaults, overridden by environment variables."""
    db_default = "sqlite:///" + (BACKEND_DIR / "filego.db").as_posix()
    return {
        "ENV_NAME": os.environ.get("FLASK_ENV", "development"),
        "SECRET_KEY": os.environ.get("SECRET_KEY", ""),
        "SQLALCHEMY_DATABASE_URI": os.environ.get("DATABASE_URL", db_default),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "STORAGE_DIR": os.environ.get("STORAGE_DIR", str(BACKEND_DIR / "storage")),
        "MAX_UPLOAD_MB": _env_int("MAX_UPLOAD_MB", 100),
        "BUFFER_KB": _env_int("BUFFER_KB", 256),
        "CORS_ORIGINS": [
            o.strip()
            for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")
            if o.strip()
        ],
        "REGISTRATION_MODE": os.environ.get("REGISTRATION_MODE", "open"),  # open | closed
        "PORT": _env_int("PORT", 5000),
        "SERVER_MODE": "waitress",  # run.py sets "stream" for --stream
        "COOKIE_SECURE": False,  # plain HTTP on the LAN (documented in README)
        "LOGIN_MAX_PER_USER": 5,
        "LOGIN_MAX_PER_IP": 20,
        "LOGIN_WINDOW_SECONDS": 15 * 60,
        "REGISTER_MAX_PER_IP": 20,
        "REGISTER_WINDOW_SECONDS": 60 * 60,
        "LOG_TO_FILE": True,
    }


def resolve_secret_key(config):
    """Production refuses to start without a real key; development stores a random one."""
    key = config.get("SECRET_KEY", "")
    if key and key not in _KNOWN_DEFAULT_KEYS:
        return key
    if config.get("ENV_NAME") == "production":
        raise RuntimeError("SECRET_KEY must be set to a strong random value in production.")
    instance = BACKEND_DIR / "instance"
    instance.mkdir(exist_ok=True)
    key_file = instance / "secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_hex(32)
    key_file.write_text(key)
    return key
