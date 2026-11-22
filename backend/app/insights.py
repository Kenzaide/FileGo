"""Transfer history, live server metrics, experiment summaries and CSV export (module 5)."""
import csv
import io
import statistics

import psutil
from flask import Blueprint, Response, current_app, g, jsonify, request
from sqlalchemy import func, select

from . import monitor
from .auth import _body, admin_required, login_required
from .errors import ApiError
from .extensions import db
from .filesvc import paging
from .models import TransferLog, iso
from .validators import clean_text

history_bp = Blueprint("history", __name__, url_prefix="/api/history")
metrics_bp = Blueprint("metrics", __name__, url_prefix="/api/metrics")

MB = 1024 * 1024
MAX_CLIENT_SECONDS = 6 * 3600

CSV_COLUMNS = [
    "id", "created_at", "user_id", "type", "status", "error", "file_id", "file_name", "size",
    "bytes_transferred", "buffer_kb", "server_seconds", "write_seconds", "hash_seconds",
    "client_seconds", "cpu_avg", "cpu_peak", "ram_proc_mb_peak", "ram_system_percent",
    "concurrent_active", "client_device", "server_mode", "label", "network_note",
    "sha256_expected", "sha256_verified", "response_ms",
]


# ---------------------------------------------------------------- helpers

def best_seconds(log):
    """Browser time when it was reported, else the server's own measurement."""
    return log.client_seconds or log.server_seconds


def speed_mbps(size, seconds):
    if not seconds or seconds <= 0 or not size:
        return None
    return round(size / MB / seconds, 4)


def log_dict(log):
    seconds = best_seconds(log)
    return {
        "id": log.id,
        "name": log.file_name,
        "fileId": log.file_id,
        "type": log.type,
        "status": log.status,
        "error": log.error,
        "size": log.size,
        "bytesTransferred": log.bytes_transferred,
        "seconds": seconds,
        "serverSeconds": log.server_seconds,
        "clientSeconds": log.client_seconds,
        "writeSeconds": log.write_seconds,
        "hashSeconds": log.hash_seconds,
        "speedMBps": speed_mbps(log.bytes_transferred or log.size, log.server_seconds),
        "clientSpeedMBps": speed_mbps(log.bytes_transferred or log.size, log.client_seconds),
        "bufferKb": log.buffer_kb,
        "cpuAvg": log.cpu_avg,
        "cpuPeak": log.cpu_peak,
        "ramProcMbPeak": log.ram_proc_mb_peak,
        "ramSystemPercent": log.ram_system_percent,
        "concurrentActive": log.concurrent_active,
        "clientDevice": log.client_device,
        "serverMode": log.server_mode,
        "label": log.label,
        "networkNote": log.network_note,
        "sha256Expected": log.sha256_expected,
        "sha256Verified": log.sha256_verified,
        "responseMs": log.response_ms,
        "userId": log.user_id,
        "date": log.created_at.strftime("%Y-%m-%d"),
        "createdAt": iso(log.created_at),
    }


def csv_cell(value):
    """Prevent spreadsheet formula injection from file names typed by users."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def csv_response(rows, filename):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for log in rows:
        out = []
        for col in CSV_COLUMNS:
            v = getattr(log, col)
            out.append(v.isoformat() + "Z" if col == "created_at" and v else csv_cell("" if v is None else v))
        writer.writerow(out)
    return Response(
        "\ufeff" + buf.getvalue(),  # BOM so Excel reads UTF-8
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _log_filters(user_id=None):
    conds = []
    if user_id is not None:
        conds.append(TransferLog.user_id == user_id)
    t = request.args.get("type")
    if t:
        if t not in ("upload", "download"):
            raise ApiError("validation_error", "type must be upload or download.", 400)
        conds.append(TransferLog.type == t)
    status = request.args.get("status")
    if status:
        if status not in ("completed", "failed"):
            raise ApiError("validation_error", "status must be completed or failed.", 400)
        conds.append(TransferLog.status == status)
    label = clean_text(request.args.get("label", ""), 80)
    if label:
        conds.append(TransferLog.label == label)
    return conds


# ---------------------------------------------------------------- history

@history_bp.get("")
@login_required
def history():
    page, per_page = paging()
    conds = _log_filters(g.user.id)
    total = db.session.scalar(select(func.count(TransferLog.id)).where(*conds))
    rows = db.session.scalars(
        select(TransferLog)
        .where(*conds)
        .order_by(TransferLog.created_at.desc(), TransferLog.id)
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()
    return jsonify({"items": [log_dict(r) for r in rows], "total": total, "page": page, "perPage": per_page})


@history_bp.get("/export.csv")
@login_required
def export_own():
    rows = db.session.scalars(
        select(TransferLog).where(*_log_filters(g.user.id)).order_by(TransferLog.created_at)
    ).all()
    return csv_response(rows, "filego-history.csv")


@history_bp.post("/<log_id>/client-timing")
@login_required
def client_timing(log_id):
    """The browser (or benchmark tool) reports how long the transfer took on its side."""
    log = db.session.get(TransferLog, log_id)
    if log is None or log.user_id != g.user.id:
        raise ApiError("not_found", "Log entry not found.", 404)
    data = _body()
    seconds = data.get("clientSeconds")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not (0 < seconds <= MAX_CLIENT_SECONDS):
        raise ApiError("validation_error", "clientSeconds must be a number between 0 and 21600.", 400)
    log.client_seconds = float(seconds)  # display only; never used for any security decision
    device = data.get("clientDevice")
    if device in ("desktop", "mobile", "tool"):
        log.client_device = device
    db.session.commit()
    return jsonify({"log": log_dict(log)})


# ---------------------------------------------------------------- live metrics

@metrics_bp.get("/live")
@login_required
def live():
    monitor.ensure_running()
    vm = psutil.virtual_memory()
    body = {
        "current": {**monitor.current(), "cpuCount": psutil.cpu_count(), "memoryTotalBytes": vm.total},
        "samples": monitor.live_samples(),
        "serverMode": current_app.config["SERVER_MODE"],
        "bufferKb": current_app.config["BUFFER_KB"],
        "windowSeconds": monitor.RING_SECONDS,
        "samplerRunning": monitor.running(),
        "experiment": monitor.get_experiment(),
    }
    if g.user.role == "admin":  # disk and network counters stay private to administrators
        du = psutil.disk_usage(current_app.config["STORAGE_DIR"])
        net = psutil.net_io_counters()
        body["system"] = {
            "diskTotalBytes": du.total,
            "diskUsedBytes": du.used,
            "diskFreeBytes": du.free,
            "netBytesSent": net.bytes_sent,
            "netBytesRecv": net.bytes_recv,
        }
    return jsonify(body)


@metrics_bp.route("/experiment", methods=["GET"])
@login_required
def get_experiment():
    return jsonify(monitor.get_experiment())


@metrics_bp.route("/experiment", methods=["PUT"])
@admin_required
def put_experiment():
    """Label and network note applied to every following transfer (Tests 1 to 5)."""
    data = _body()
    label = clean_text(data.get("label") or "", 80)
    note = clean_text(data.get("networkNote") or "", 255)
    monitor.set_experiment(label, note)
    return jsonify(monitor.get_experiment())


# ---------------------------------------------------------------- summary (graphs and report)

SIZE_BOUNDS_MB = [0.1, 0.5, 1, 5, 10, 25, 50, 100]


def _size_group(log):
    size = log.bytes_transferred or log.size or 0
    for bound in SIZE_BOUNDS_MB:
        if size <= bound * MB * 1.001:
            return f"≤ {bound:g} MB", bound
    return f"> {SIZE_BOUNDS_MB[-1]:g} MB", SIZE_BOUNDS_MB[-1] + 1


GROUPERS = {
    "size": _size_group,
    "buffer": lambda l: (f"{l.buffer_kb} KB" if l.buffer_kb else "unknown", l.buffer_kb or 0),
    "concurrency": lambda l: (f"{l.concurrent_active or 1} at once", l.concurrent_active or 1),
    "device": lambda l: (l.client_device or "unknown", l.client_device or ""),
    "label": lambda l: (l.label or "(no label)", l.label or ""),
}


def _mean(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None


def summarize(group_rows):
    done = [r for r in group_rows if r.status == "completed"]
    speeds = [speed_mbps(r.bytes_transferred or r.size, r.server_seconds) for r in done]
    speeds = [s for s in speeds if s is not None]
    client_speeds = [speed_mbps(r.bytes_transferred or r.size, r.client_seconds) for r in done]
    client_speeds = [s for s in client_speeds if s is not None]
    total = len(group_rows)
    return {
        "count": total,
        "completed": len(done),
        "failed": total - len(done),
        "successRate": round(len(done) / total * 100, 2) if total else None,
        "avgSpeedMBps": _mean(speeds),
        "medianSpeedMBps": round(statistics.median(speeds), 4) if speeds else None,
        "avgClientSpeedMBps": _mean(client_speeds),
        "avgSeconds": _mean([r.server_seconds for r in done]),
        "avgClientSeconds": _mean([r.client_seconds for r in done]),
        "avgWriteSeconds": _mean([r.write_seconds for r in done]),
        "avgHashSeconds": _mean([r.hash_seconds for r in done]),
        "avgResponseMs": _mean([r.response_ms for r in done]),
        "avgCpu": _mean([r.cpu_avg for r in done]),
        "peakCpu": max([r.cpu_peak for r in done if r.cpu_peak is not None], default=None),
        "avgRamProcMb": _mean([r.ram_proc_mb_peak for r in done]),
    }


@metrics_bp.get("/summary")
@login_required
def summary():
    group_by = request.args.get("groupBy", "size")
    if group_by not in GROUPERS:
        raise ApiError("validation_error", "groupBy must be one of: " + ", ".join(GROUPERS) + ".", 400)
    scope = request.args.get("scope", "mine")
    if scope not in ("mine", "all"):
        raise ApiError("validation_error", "scope must be mine or all.", 400)
    if scope == "all" and g.user.role != "admin":
        raise ApiError("forbidden", "Only administrators can see system-wide statistics.", 403)
    conds = _log_filters(g.user.id if scope == "mine" else None)
    if not request.args.get("type"):
        conds.append(TransferLog.type == "upload")  # uploads by default, like Tests 1 to 5
    rows = db.session.scalars(select(TransferLog).where(*conds).order_by(TransferLog.created_at)).all()

    groups = {}
    for r in rows:
        key, order = GROUPERS[group_by](r)
        groups.setdefault(key, (order, []))[1].append(r)
    items = [
        {"group": key, **summarize(rs)}
        for key, (order, rs) in sorted(groups.items(), key=lambda kv: (kv[1][0] == "", kv[1][0]))
    ]
    modes = sorted({r.server_mode for r in rows if r.server_mode})
    note = None
    if "waitress" in modes:
        note = (
            "Some rows were recorded in waitress mode, which receives the whole upload before the app runs. "
            "Their server time covers disk and hashing only. Use --stream for network experiments."
        )
    return jsonify(
        {
            "groupBy": group_by,
            "type": request.args.get("type", "upload"),
            "scope": scope,
            "items": items,
            "overall": summarize(rows),
            "serverModes": modes,
            "note": note,
        }
    )
