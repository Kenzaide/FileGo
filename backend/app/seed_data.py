"""Development seed: three demo accounts and six clearly fake sample files with real tiny bytes."""
import hashlib
import io
import zipfile

from sqlalchemy import select

from .auth import hash_password
from .extensions import db
from .models import File, User, utcnow
from .storage import new_stored_name, path_for

DEMO_PASSWORD = "demo123"

DEMO_USERS = [
    ("u1", "Demo Student", "student", "student@filego.local", "admin"),
    ("u2", "Alex Rivera", "alex", "alex@filego.local", "student"),
    ("u3", "Jamie Cruz", "jamie", "jamie@filego.local", "student"),
]

# id, title, subject id, category, owner id
SAMPLE_FILES = [
    ("f1", "Sample - Computer Architecture Reviewer.pdf", "s1", "Reviewer", "u2"),
    ("f2", "Sample - Data Structures Study Guide.docx", "s6", "Lecture Notes", "u3"),
    ("f3", "Sample - Networks Lecture Slides.pptx", "s2", "Presentation", "u2"),
    ("f4", "Sample - Software Engineering Practice Questions.txt", "s3", "Practice Questions", "u3"),
    ("f5", "Sample - Automata Theory Notes.pdf", "s4", "Lecture Notes", "u1"),
    ("f6", "Sample - Machine Learning Cheat Sheet.pdf", "s5", "Reviewer", "u1"),
]

MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt": "text/plain; charset=utf-8",
}


def make_pdf(text):
    """A tiny but valid one-page PDF."""
    stream = f"BT /F1 20 Tf 72 700 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def make_zip_office(label):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        z.writestr("README.txt", f"{label}\nSample file for the FileGo demo. Not real course material.\n")
    return buf.getvalue()


def sample_bytes(title, ext):
    label = title.rsplit(".", 1)[0]
    if ext == "pdf":
        return make_pdf(label.replace("(", "").replace(")", ""))
    if ext == "txt":
        return (
            f"{label}\n\nSample file for the FileGo demo. Not real course material.\n"
        ).encode()
    return make_zip_office(label)


def reset_all():
    db.drop_all()
    db.create_all()
    from . import ensure_subjects

    ensure_subjects()


def seed_demo():
    """Create the demo users and sample files. Safe to run twice (skips what exists)."""
    created_users = 0
    for uid, name, username, email, role in DEMO_USERS:
        if db.session.get(User, uid) or db.session.scalar(
            select(User.id).where(User.username == username)
        ):
            continue
        db.session.add(
            User(
                id=uid,
                name=name,
                username=username,
                email=email,
                password_hash=hash_password(DEMO_PASSWORD),
                role=role,
            )
        )
        created_users += 1
    db.session.commit()

    created_files = 0
    for fid, title, subject_id, category, owner_id in SAMPLE_FILES:
        if db.session.get(File, fid):
            continue
        ext = title.rsplit(".", 1)[1].lower()
        data = sample_bytes(title, ext)
        stored = new_stored_name()
        with open(path_for(stored), "wb") as fh:
            fh.write(data)
        db.session.add(
            File(
                id=fid,
                name=title,
                original_name=title,
                kind=ext.upper(),
                mime_type=MIME[ext],
                stored_name=stored,
                subject_id=subject_id,
                category=category,
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                owner_id=owner_id,
                visibility="public",
                downloads=0,
                created_at=utcnow(),
            )
        )
        created_files += 1
    db.session.commit()
    return created_users, created_files
