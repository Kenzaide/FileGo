import socket
import time

import psutil
from flask import Blueprint, current_app, jsonify
from sqlalchemy import select, text

from .constants import (
    ALLOWED_EXTENSIONS,
    APP_VERSION,
    BUFFER_OPTIONS_KB,
    CATEGORIES,
    PREVIEW_EXTENSIONS,
)
from .extensions import db
from .models import Subject

bp = Blueprint("meta", __name__, url_prefix="/api")


@bp.get("/health")
def health():
    try:
        db.session.execute(text("SELECT 1"))
        database = "ok"
    except Exception:  # noqa: BLE001 - report, do not crash
        database = "error"
    status = "ok" if database == "ok" else "degraded"
    return jsonify({"status": status, "database": database, "version": APP_VERSION})


@bp.get("/ping")
def ping():
    return jsonify({"pong": True, "serverTimeMs": int(time.time() * 1000)})


@bp.get("/meta")
def meta():
    cfg = current_app.config
    subjects = db.session.scalars(
        select(Subject).where(Subject.is_active.is_(True)).order_by(Subject.code.is_(None), Subject.code, Subject.name)
    ).all()
    return jsonify(
        {
            "version": APP_VERSION,
            "subjects": [s.to_dict() for s in subjects],
            "categories": CATEGORIES,
            "allowedExtensions": sorted(ALLOWED_EXTENSIONS),
            "previewExtensions": sorted(PREVIEW_EXTENSIONS),
            "maxUploadMb": cfg["MAX_UPLOAD_MB"],
            "bufferOptionsKb": BUFFER_OPTIONS_KB,
            "bufferKb": cfg["BUFFER_KB"],
            "registrationMode": cfg["REGISTRATION_MODE"],
            "serverMode": cfg["SERVER_MODE"],
        }
    )


def lan_addresses():
    """IPv4 addresses of this machine, excluding loopback and link-local."""
    found = []
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith(("127.", "169.254.")):
                    found.append({"interface": iface, "address": a.address})
    except Exception:  # noqa: BLE001
        pass
    return found


@bp.get("/network")
def network():
    cfg = current_app.config
    addresses = lan_addresses()
    port = cfg["PORT"]
    return jsonify(
        {
            "hostname": socket.gethostname(),
            "port": port,
            "serverMode": cfg["SERVER_MODE"],
            "addresses": addresses,
            "urls": [f"http://{a['address']}:{port}" for a in addresses],
        }
    )
