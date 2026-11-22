import hashlib
import os

from app.extensions import db
from app.models import File


def test_health(api):
    r = api.get("/api/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"
    assert r.get_json()["database"] == "ok"


def test_ping_needs_no_login(api):
    r = api.get("/api/ping")
    assert r.status_code == 200
    assert r.get_json()["pong"] is True


def test_meta_lists_subjects_with_course_codes(api):
    data = api.get("/api/meta").get_json()
    labels = [s["label"] for s in data["subjects"]]
    assert "CMSC310 · Computer Architecture and Organization" in labels
    assert "CMSC306 · Networks & Communication" in labels
    assert "CMSC309 · Software Engineering" in labels
    assert "Automata Theory" in labels
    assert data["categories"] == [
        "Reviewer", "Lecture Notes", "Presentation", "Practice Questions", "Assignment", "Other"
    ]
    assert data["maxUploadMb"] == 100
    assert data["bufferOptionsKb"] == [64, 256, 1024]
    assert data["bufferKb"] == 256
    assert set(data["allowedExtensions"]) == {
        "pdf", "docx", "pptx", "txt", "png", "jpg", "jpeg", "gif", "webp"
    }
    assert "svg" not in data["allowedExtensions"] and "html" not in data["allowedExtensions"]
    assert data["registrationMode"] == "open"


def test_network_endpoint_shape(api):
    data = api.get("/api/network").get_json()
    assert data["port"] == 5000
    assert data["serverMode"] in ("waitress", "stream")
    assert isinstance(data["addresses"], list)
    assert len(data["urls"]) == len(data["addresses"])


def test_security_headers_and_404_format(api):
    r = api.get("/api/nope")
    assert r.status_code == 404
    assert r.get_json()["error"]["code"] == "not_found"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "same-origin"


def test_seed_sample_files_have_real_bytes_and_correct_hash(app):
    with app.app_context():
        files = db.session.query(File).all()
        assert len(files) == 6
        from app.storage import path_for

        for f in files:
            assert f.name.startswith("Sample - ")
            assert f.visibility == "public"
            path = path_for(f.stored_name)
            assert os.path.getsize(path) == f.size > 0
            with open(path, "rb") as fh:
                data = fh.read()
            assert hashlib.sha256(data).hexdigest() == f.sha256
            if f.kind == "PDF":
                assert data.startswith(b"%PDF-")
            if f.kind in ("DOCX", "PPTX"):
                assert data.startswith(b"PK")


def test_seed_is_idempotent(app):
    from app.seed_data import seed_demo

    with app.app_context():
        assert seed_demo() == (0, 0)
        assert db.session.query(File).count() == 6


def test_sqlite_foreign_keys_are_enforced(app):
    import sqlalchemy

    with app.app_context():
        assert db.session.execute(sqlalchemy.text("PRAGMA foreign_keys")).scalar() == 1
