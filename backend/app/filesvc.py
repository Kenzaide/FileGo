"""Shared file logic: access rules, serializers, chunked upload, chunked download, deletion."""
import hashlib
import logging
import os
import re
import shutil
import time
import urllib.parse

from flask import Response, current_app, request, stream_with_context
from sqlalchemy import func, select, update

from . import monitor
from .constants import ALLOWED_EXTENSIONS, BUFFER_OPTIONS_KB, CATEGORIES
from .errors import ApiError
from .extensions import db
from .models import File, Subject, Transfer, TransferLog, iso, new_id, utcnow
from .storage import new_stored_name, path_for, storage_root
from .validators import clean_text

log = logging.getLogger("filego.files")

SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MB = 1024 * 1024


# ---------------------------------------------------------------- access rules

def is_recipient(user_id, file_id):
    return (
        db.session.scalar(
            select(Transfer.id).where(Transfer.file_id == file_id, Transfer.recipient_id == user_id).limit(1)
        )
        is not None
    )


def can_read(user, f):
    if f.visibility == "public" or f.owner_id == user.id or user.role == "admin":
        return True
    return is_recipient(user.id, f.id)


def get_readable_file(file_id, user):
    """404 (never 403) when the file is private and the user has no access."""
    f = db.session.get(File, file_id)
    if f is None or not can_read(user, f):
        raise ApiError("not_found", "File not found.", 404)
    return f


def require_manage(user, f):
    if f.owner_id != user.id and user.role != "admin":
        raise ApiError("forbidden", "Only the owner or an administrator can do that.", 403)


# ---------------------------------------------------------------- serializers

def file_dict(f):
    subject = f.subject
    return {
        "id": f.id,
        "name": f.name,
        "originalName": f.original_name,
        "subject": subject.label,
        "subjectId": subject.id,
        "subjectCode": subject.code,
        "subjectName": subject.name,
        "category": f.category,
        "kind": f.kind,
        "size": f.size,
        "sha256": f.sha256,
        "ownerId": f.owner_id,
        "owner": f.owner.name,
        "ownerUsername": f.owner.username,
        "visibility": f.visibility,
        "downloads": f.downloads,
        "previewable": f.kind.lower() in ("pdf", "png", "jpg", "jpeg", "gif", "webp"),
        "date": f.created_at.strftime("%Y-%m-%d"),
        "createdAt": iso(f.created_at),
    }


def transfer_dict(t, seconds=None):
    return {
        "id": t.id,
        "fileId": t.file_id,
        "name": t.file.name,
        "kind": t.file.kind,
        "senderId": t.sender_id,
        "sender": t.sender.name,
        "recipientId": t.recipient_id,
        "recipient": t.recipient.name,
        "status": "Downloaded" if t.downloaded_at else "Delivered",
        "size": t.file.size,
        "seconds": seconds,
        "direction": "direct",
        "date": t.created_at.strftime("%Y-%m-%d"),
        "createdAt": iso(t.created_at),
        "downloadedAt": iso(t.downloaded_at),
    }


def download_name(f):
    """The title, with the original extension appended when the title has none."""
    ext = f.kind.lower()
    return f.name if f.name.lower().endswith("." + ext) else f"{f.name}.{ext}"


def content_disposition(disposition, filename):
    fallback = re.sub(r'[^A-Za-z0-9._ -]', "_", filename.encode("ascii", "ignore").decode()) or "download"
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{urllib.parse.quote(filename, safe='')}"


# ---------------------------------------------------------------- request helpers

def paging():
    def num(name, default, lo, hi):
        try:
            v = int(request.args.get(name, default))
        except ValueError:
            raise ApiError("validation_error", f"{name} must be a number.", 400)
        return max(lo, min(hi, v))

    return num("page", 1, 1, 10**6), num("perPage", 50, 1, 200)


def resolve_subject(value, default_name=None):
    value = clean_text(value or "", 120)
    if not value and default_name:
        value = default_name
    if not value:
        raise ApiError("validation_error", "Subject is required.", 400)
    low = value.lower()
    for s in db.session.scalars(select(Subject).where(Subject.is_active.is_(True))):
        if s.id == value or (s.code and s.code.lower() == low) or s.name.lower() == low or s.label.lower() == low:
            return s
    raise ApiError("validation_error", "Unknown subject.", 400)


def resolve_category(value, default=None):
    value = clean_text(value or "", 60) or default
    for c in CATEGORIES:
        if value and c.lower() == value.lower():
            return c
    raise ApiError("validation_error", "Category must be one of: " + ", ".join(CATEGORIES) + ".", 400)


def resolve_visibility(value):
    value = (value or "public").lower()
    if value not in ("public", "private"):
        raise ApiError("validation_error", "Visibility must be public or private.", 400)
    return value


def client_device():
    h = (request.headers.get("X-Client-Device") or "").lower()
    if h in ("desktop", "mobile", "tool"):
        return h
    return "mobile" if re.search(r"Mobi|Android|iPhone|iPad", request.headers.get("User-Agent", "")) else "desktop"


def resolve_buffer_kb(user):
    default = current_app.config["BUFFER_KB"]
    raw = request.args.get("bufferKb")
    if raw is None or user.role != "admin":  # students cannot disturb experiments
        return default
    try:
        value = int(raw)
    except ValueError:
        value = None
    if value not in BUFFER_OPTIONS_KB:
        raise ApiError("validation_error", "bufferKb must be one of 64, 256, 1024.", 400)
    return value


def experiment_fields(user):
    """Label and network note for this transfer: the admin's current experiment, or admin headers."""
    exp = monitor.get_experiment()
    label, note = exp["label"], exp["networkNote"]
    if user.role == "admin":
        label = clean_text(request.headers.get("X-Experiment-Label") or "", 80) or label
        note = clean_text(request.headers.get("X-Network-Note") or "", 255) or note
    return {"label": label, "network_note": note}


# ---------------------------------------------------------------- upload (chunked)

def _magic_ok(ext, head):
    if ext == "pdf":
        return head.startswith(b"%PDF-")
    if ext in ("docx", "pptx"):
        return head.startswith(b"PK\x03\x04")
    if ext == "png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in ("jpg", "jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == "gif":
        return head[:6] in (b"GIF87a", b"GIF89a")
    if ext == "webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return True  # txt: checked for NUL bytes while streaming


class _Fail(Exception):
    def __init__(self, code, message, status):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _record_log(**fields):
    db.session.add(TransferLog(id=fields.pop("id", None) or new_id(), **fields))
    db.session.commit()


def _replace_with_retry(src, dst, tries=5):
    """Windows antivirus or the indexer can briefly lock a fresh file."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.1)


def _original_filename():
    raw = request.headers.get("X-File-Name", "")
    if not raw:
        raise ApiError("validation_error", "The X-File-Name header is required.", 400)
    name = urllib.parse.unquote(raw)
    name = clean_text(re.split(r"[\\/]", name)[-1], 255)  # basename only
    ext = name.rsplit(".", 1)[1].lower() if "." in name else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ApiError(
            "unsupported_type",
            "Allowed file types: " + ", ".join(sorted(ALLOWED_EXTENSIONS)) + ".",
            400,
        )
    return name, ext


def receive_upload(owner, visibility, subject, category, title, recipient=None):
    """Read the raw request body in chunks, hash it, store it, and create the rows.

    Returns (file, transfer_or_None, log). Any failure after validation writes a 'failed'
    transfer log row, removes the partial file, and creates no file or transfer row.
    """
    cfg = current_app.config
    started = time.perf_counter()
    original, ext = _original_filename()
    declared = request.content_length
    if declared is None:
        raise ApiError("length_required", "Content-Length is required for uploads.", 411)
    expected = (request.headers.get("X-Expected-SHA256") or "").strip().lower() or None
    if expected and not SHA_RE.match(expected):
        raise ApiError("validation_error", "X-Expected-SHA256 must be 64 hex characters.", 400)
    buffer_kb = resolve_buffer_kb(owner)
    max_bytes = cfg["MAX_UPLOAD_MB"] * MB
    if declared == 0:
        raise ApiError("validation_error", "The file is empty.", 400)

    base = dict(
        user_id=owner.id,
        file_name=original,
        type="upload",
        buffer_kb=buffer_kb,
        server_mode=cfg["SERVER_MODE"],
        client_device=client_device(),
        sha256_expected=expected,
        **experiment_fields(owner),
    )
    mon = None

    def fail(code, message, status, **extra):
        db.session.rollback()
        if mon is not None:
            extra = {**mon.end(), **extra}
        try:
            _record_log(status="failed", error=message[:255], **{**base, "size": declared}, **extra)
        except Exception:  # noqa: BLE001 - never hide the real error
            db.session.rollback()
            log.exception("Could not write failed-transfer log")
        raise ApiError(code, message, status)

    if declared > max_bytes:
        fail("too_large", f"File is larger than the {cfg['MAX_UPLOAD_MB']} MB limit.", 413)
    root = storage_root()
    if shutil.disk_usage(root).free < cfg["MIN_FREE_DISK_MB"] * MB + declared:
        fail("insufficient_storage", "The server is out of disk space.", 507)

    tmp_dir = os.path.join(root, ".tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, new_stored_name())
    mon = monitor.begin()
    hasher = hashlib.sha256()
    written = 0
    write_s = hash_s = 0.0
    head = b""
    magic_done = False
    first_at = last_at = None
    chunk_size = buffer_kb * 1024

    try:
        try:
            stream = request.stream
            with open(tmp_path, "wb") as out:
                while True:
                    chunk = stream.read(chunk_size)
                    if not chunk:
                        break
                    now = time.perf_counter()
                    if first_at is None:
                        first_at = now
                    written += len(chunk)
                    if written > declared or written > max_bytes:
                        raise _Fail("too_large", f"File is larger than the {cfg['MAX_UPLOAD_MB']} MB limit.", 413)
                    if not magic_done:
                        head = (head + chunk)[:16]
                        if len(head) >= 16:
                            magic_done = True
                            if not _magic_ok(ext, head):
                                raise _Fail("unsupported_type", "File content does not match its extension.", 400)
                    if ext == "txt" and b"\x00" in chunk:
                        raise _Fail("unsupported_type", "Text files cannot contain binary data.", 400)
                    t = time.perf_counter()
                    hasher.update(chunk)
                    hash_s += time.perf_counter() - t
                    t = time.perf_counter()
                    out.write(chunk)
                    write_s += time.perf_counter() - t
                    last_at = time.perf_counter()
            if written != declared:
                raise _Fail("incomplete_upload", "The upload ended before all data arrived.", 400)
            if not magic_done and not _magic_ok(ext, head):
                raise _Fail("unsupported_type", "File content does not match its extension.", 400)
        except _Fail:
            raise
        except OSError as e:
            if getattr(e, "errno", None) == 28:
                raise _Fail("insufficient_storage", "The server is out of disk space.", 507)
            raise _Fail("upload_interrupted", "The upload was interrupted.", 400)
        except Exception:  # noqa: BLE001 - client disconnects raise various werkzeug errors
            raise _Fail("upload_interrupted", "The connection was lost during upload.", 400)

        digest = hasher.hexdigest()
        timing = dict(
            bytes_transferred=written,
            server_seconds=(last_at - first_at) if first_at else 0.0,
            write_seconds=write_s,
            hash_seconds=hash_s,
            response_ms=((first_at - started) * 1000) if first_at else None,
            **mon.end(),
        )
        if expected and expected != digest:
            raise _Fail("hash_mismatch", "SHA-256 did not match: the file was corrupted in transfer.", 400)
    except _Fail as f:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        extra = dict(bytes_transferred=written, write_seconds=write_s, hash_seconds=hash_s)
        if first_at and last_at:
            extra["server_seconds"] = last_at - first_at
        if f.code == "hash_mismatch":
            extra["sha256_verified"] = False
        fail(f.code, f.message, f.status, **extra)

    # Rows first, then the atomic move of the bytes, then commit.
    stored = new_stored_name()
    final_path = path_for(stored)
    file = File(
        id=new_id(),
        name=clean_text(title, 255) or original,
        original_name=original,
        kind=ext.upper(),
        mime_type=ALLOWED_EXTENSIONS[ext],
        stored_name=stored,
        subject_id=subject.id,
        category=category,
        size=written,
        sha256=digest,
        owner_id=owner.id,
        visibility=visibility,
        downloads=0,
    )
    transfer = None
    log_row = TransferLog(
        id=new_id(),
        file_id=file.id,
        status="completed",
        size=written,
        sha256_verified=True if expected else None,
        **timing,
        **base,
    )
    try:
        db.session.add(file)
        db.session.flush()
        if recipient is not None:
            transfer = Transfer(id=new_id(), file_id=file.id, sender_id=owner.id, recipient_id=recipient.id)
            db.session.add(transfer)
        db.session.add(log_row)
        db.session.flush()
        _replace_with_retry(tmp_path, final_path)
        try:
            db.session.commit()
        except Exception:
            if os.path.exists(final_path):
                os.remove(final_path)
            raise
    except Exception:
        db.session.rollback()
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        log.exception("Storing upload failed")
        fail("storage_error", "The server could not store the file.", 500, bytes_transferred=written)
    return file, transfer, log_row


# ---------------------------------------------------------------- download (chunked)

def send_download(f, user):
    """Stream the stored bytes as an attachment, in chunks of the configured buffer size."""
    cfg = current_app.config
    buffer_kb = resolve_buffer_kb(user)
    path = path_for(f.stored_name)
    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": content_disposition("attachment", download_name(f)),
        "Content-Length": str(f.size),
        "X-File-SHA256": f.sha256,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }
    if request.method == "HEAD":
        return Response(status=200, headers=headers)
    try:
        fh = open(path, "rb")
    except OSError:
        raise ApiError("file_missing", "The file's data is missing on the server.", 404)

    file_id, file_name, size = f.id, f.name, f.size
    owner_id, public = f.owner_id, f.visibility == "public"
    user_id = user.id
    mode = cfg["SERVER_MODE"]
    device = client_device()
    started = time.perf_counter()
    app = current_app._get_current_object()

    exp = experiment_fields(user)

    def generate():
        sent = 0
        read_s = 0.0
        first_at = None
        ok = False
        mon = monitor.begin()
        try:
            while True:
                t = time.perf_counter()
                chunk = fh.read(buffer_kb * 1024)
                read_s += time.perf_counter() - t
                if not chunk:
                    break
                if first_at is None:
                    first_at = time.perf_counter()
                sent += len(chunk)
                yield chunk
            ok = sent == size
        finally:
            fh.close()
            end = time.perf_counter()
            resources = mon.end()
            with app.app_context():
                try:
                    _finish_download(
                        ok, user_id, file_id, file_name, size, sent, buffer_kb, mode, device,
                        server_seconds=(end - first_at) if first_at else 0.0,
                        read_seconds=read_s,
                        response_ms=((first_at - started) * 1000) if first_at else None,
                        count=ok and public and user_id != owner_id,
                        extra={**resources, **exp},
                    )
                except Exception:  # noqa: BLE001
                    db.session.rollback()
                    log.exception("Could not record download")

    return Response(stream_with_context(generate()), status=200, headers=headers)


def _finish_download(ok, user_id, file_id, file_name, size, sent, buffer_kb, mode, device,
                     server_seconds, read_seconds, response_ms, count, extra=None):
    if ok:
        # Atomic counter: never read-modify-write.
        if count:
            db.session.execute(update(File).where(File.id == file_id).values(downloads=File.downloads + 1))
        db.session.execute(
            update(Transfer)
            .where(Transfer.file_id == file_id, Transfer.recipient_id == user_id, Transfer.downloaded_at.is_(None))
            .values(downloaded_at=utcnow())
        )
    db.session.add(
        TransferLog(
            id=new_id(), user_id=user_id, file_id=file_id, file_name=file_name, type="download",
            status="completed" if ok else "failed",
            error=None if ok else "Download did not finish.",
            size=size, bytes_transferred=sent, buffer_kb=buffer_kb, server_seconds=server_seconds,
            write_seconds=read_seconds, hash_seconds=0.0, client_device=device, server_mode=mode,
            response_ms=response_ms, **(extra or {}),
        )
    )
    db.session.commit()


# ---------------------------------------------------------------- verify and delete

def verify_integrity(f):
    """Recompute SHA-256 of the stored bytes and compare with the stored value."""
    started = time.perf_counter()
    h = hashlib.sha256()
    actual = None
    error = None
    try:
        with open(path_for(f.stored_name), "rb") as fh:
            while True:
                chunk = fh.read(current_app.config["BUFFER_KB"] * 1024)
                if not chunk:
                    break
                h.update(chunk)
        actual = h.hexdigest()
    except OSError:
        error = "The file's data is missing on the server."
    return {
        "ok": actual is not None and actual == f.sha256,
        "expected": f.sha256,
        "actual": actual,
        "size": f.size,
        "seconds": round(time.perf_counter() - started, 4),
        "error": error,
    }


def remove_bytes(stored_name):
    """Windows cannot delete an open file. Never fail the user's request because of that."""
    path = path_for(stored_name)
    try:
        os.remove(path)
        return
    except FileNotFoundError:
        return
    except OSError:
        pass
    try:
        trash = os.path.join(storage_root(), ".trash")
        os.makedirs(trash, exist_ok=True)
        os.replace(path, os.path.join(trash, stored_name))
    except OSError:
        log.warning("Orphaned file left on disk: %s", path)


def delete_file(f):
    stored = f.stored_name
    removed = db.session.scalar(select(func.count(Transfer.id)).where(Transfer.file_id == f.id))
    db.session.delete(f)  # database first; transfers go with it (ON DELETE CASCADE)
    db.session.commit()
    remove_bytes(stored)
    return removed
