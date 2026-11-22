import uuid
from datetime import datetime, timezone

from .extensions import db


def new_id():
    return uuid.uuid4().hex


def utcnow():
    """Naive UTC timestamp (SQLite has no time zones; everything is stored as UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt):
    return dt.isoformat() + "Z" if dt else None


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    name = db.Column(db.String(255), nullable=False)
    username = db.Column(db.String(30), nullable=False, unique=True, index=True)
    email = db.Column(db.String(255), nullable=True, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="student")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    last_login_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "mustChangePassword": self.must_change_password,
            "createdAt": iso(self.created_at),
        }

    def to_public(self):
        return {"id": self.id, "name": self.name, "username": self.username}


class Session(db.Model):
    __tablename__ = "sessions"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    user_id = db.Column(
        db.String(32), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    csrf_token = db.Column(db.String(64), nullable=False)
    user_agent = db.Column(db.String(255), nullable=True)
    ip = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_seen_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)

    user = db.relationship("User")


class Subject(db.Model):
    __tablename__ = "subjects"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    code = db.Column(db.String(20), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    @property
    def label(self):
        return f"{self.code} · {self.name}" if self.code else self.name

    def to_dict(self):
        return {"id": self.id, "code": self.code, "name": self.name, "label": self.label}


class File(db.Model):
    __tablename__ = "files"
    __table_args__ = (
        db.Index("ix_files_visibility_created", "visibility", "created_at"),
    )

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    name = db.Column(db.String(255), nullable=False)  # display title
    original_name = db.Column(db.String(255), nullable=False)
    kind = db.Column(db.String(10), nullable=False)  # upper-case extension
    mime_type = db.Column(db.String(120), nullable=False)
    stored_name = db.Column(db.String(64), nullable=False, unique=True)
    subject_id = db.Column(db.String(32), db.ForeignKey("subjects.id"), nullable=False, index=True)
    category = db.Column(db.String(40), nullable=False)
    size = db.Column(db.BigInteger, nullable=False, default=0)
    sha256 = db.Column(db.String(64), nullable=False)
    owner_id = db.Column(db.String(32), db.ForeignKey("users.id"), nullable=False, index=True)
    visibility = db.Column(db.String(10), nullable=False, default="public")
    downloads = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    owner = db.relationship("User")
    subject = db.relationship("Subject")


class Transfer(db.Model):
    __tablename__ = "transfers"
    __table_args__ = (
        db.Index("ix_transfers_recipient_created", "recipient_id", "created_at"),
        db.Index("ix_transfers_sender_created", "sender_id", "created_at"),
    )

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    file_id = db.Column(
        db.String(32), db.ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    sender_id = db.Column(db.String(32), db.ForeignKey("users.id"), nullable=False)
    recipient_id = db.Column(db.String(32), db.ForeignKey("users.id"), nullable=False)
    downloaded_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    file = db.relationship("File")
    sender = db.relationship("User", foreign_keys=[sender_id])
    recipient = db.relationship("User", foreign_keys=[recipient_id])


class TransferLog(db.Model):
    """One row per upload or download attempt, successful or not."""

    __tablename__ = "transfer_logs"
    __table_args__ = (db.Index("ix_logs_user_created", "user_id", "created_at"),)

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    user_id = db.Column(db.String(32), db.ForeignKey("users.id"), nullable=False)
    file_id = db.Column(db.String(32), nullable=True)  # no FK: survives file deletion
    file_name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # upload | download
    status = db.Column(db.String(10), nullable=False)  # completed | failed
    error = db.Column(db.String(255), nullable=True)
    size = db.Column(db.BigInteger, nullable=False, default=0)
    bytes_transferred = db.Column(db.BigInteger, nullable=False, default=0)
    buffer_kb = db.Column(db.Integer, nullable=True)
    server_seconds = db.Column(db.Float, nullable=True)
    write_seconds = db.Column(db.Float, nullable=True)
    hash_seconds = db.Column(db.Float, nullable=True)
    client_seconds = db.Column(db.Float, nullable=True)
    cpu_avg = db.Column(db.Float, nullable=True)
    cpu_peak = db.Column(db.Float, nullable=True)
    ram_proc_mb_peak = db.Column(db.Float, nullable=True)
    ram_system_percent = db.Column(db.Float, nullable=True)
    concurrent_active = db.Column(db.Integer, nullable=True)
    client_device = db.Column(db.String(10), nullable=True)  # desktop | mobile | tool
    server_mode = db.Column(db.String(10), nullable=True)  # waitress | stream
    label = db.Column(db.String(80), nullable=True, index=True)
    network_note = db.Column(db.String(255), nullable=True)
    sha256_expected = db.Column(db.String(64), nullable=True)
    sha256_verified = db.Column(db.Boolean, nullable=True)
    response_ms = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
