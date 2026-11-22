import hashlib
import os
import urllib.parse

import pytest

from app.extensions import db
from app.models import File, Transfer, TransferLog
from conftest import DOCX, PDF, PNG, upload


def logs(app, **filters):
    with app.app_context():
        return db.session.query(TransferLog).filter_by(**filters).order_by(TransferLog.created_at).all()


# ---------------------------------------------------------------- upload

def test_upload_stores_file_with_correct_hash(app, alex, stored_files):
    before = len(stored_files())
    r = upload(alex, "My Notes.pdf", PDF, title="Week 1 Reviewer")
    assert r.status_code == 201
    f = r.get_json()["file"]
    assert f["name"] == "Week 1 Reviewer"
    assert f["kind"] == "PDF"
    assert f["size"] == len(PDF)
    assert f["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert f["visibility"] == "public"
    assert f["ownerId"] == "u2" and f["owner"] == "Alex Rivera"
    assert f["subject"] == "CMSC310 · Computer Architecture and Organization"
    assert f["downloads"] == 0
    assert len(stored_files()) == before + 1
    with app.app_context():
        row = db.session.get(File, f["id"])
        assert "notes" not in row.stored_name.lower()
        assert len(row.stored_name) == 32
        with open(os.path.join(app.config["STORAGE_DIR"], row.stored_name[:2], row.stored_name), "rb") as fh:
            assert fh.read() == PDF


def test_upload_writes_completed_log_with_timing(app, alex):
    r = upload(alex, "a.pdf", PDF)
    log = logs(app, type="upload", user_id="u2")[0]
    assert log.id == r.get_json()["logId"]
    assert log.status == "completed"
    assert log.size == log.bytes_transferred == len(PDF)
    assert log.buffer_kb == 256
    assert log.server_mode == "waitress"
    assert log.client_device == "desktop"
    assert log.server_seconds >= 0 and log.write_seconds >= 0 and log.hash_seconds >= 0
    assert log.file_id == r.get_json()["file"]["id"]


def test_upload_needs_login_and_csrf(api, alex):
    assert upload(api).status_code == 401
    alex.csrf = None
    assert upload(alex).status_code == 403


@pytest.mark.parametrize("name", ["virus.exe", "page.html", "image.svg", "sheet.xlsx", "a.zip", "noext", "x.js", ".pdf.exe"])
def test_blocked_extensions(alex, name, stored_files):
    before = len(stored_files())
    r = upload(alex, name, PDF)
    assert r.status_code == 400
    assert r.get_json()["error"]["code"] == "unsupported_type"
    assert len(stored_files()) == before


def test_path_traversal_filename_is_harmless(app, alex, stored_files):
    r = upload(alex, "../../evil.pdf", PDF)
    assert r.status_code == 201
    f = r.get_json()["file"]
    assert f["originalName"] == "evil.pdf"
    with app.app_context():
        row = db.session.get(File, f["id"])
        full = os.path.realpath(os.path.join(app.config["STORAGE_DIR"], row.stored_name[:2], row.stored_name))
        assert full.startswith(os.path.realpath(app.config["STORAGE_DIR"]) + os.sep)
    parent = os.path.dirname(os.path.dirname(app.config["STORAGE_DIR"]))
    assert not os.path.exists(os.path.join(parent, "evil.pdf"))


def test_windows_style_traversal_name(alex):
    r = upload(alex, "..\\..\\evil.pdf", PDF)
    assert r.get_json()["file"]["originalName"] == "evil.pdf"


def test_magic_bytes_must_match_extension(app, alex, stored_files, tmp_files):
    before = len(stored_files())
    r = upload(alex, "fake.pdf", b"this is not a pdf at all, just text")
    assert r.status_code == 400
    assert len(stored_files()) == before
    assert tmp_files() == []
    with app.app_context():
        assert db.session.query(File).count() == 6
    failed = logs(app, status="failed")
    assert len(failed) == 1 and failed[0].type == "upload"


def test_png_and_docx_accepted_wrong_type_rejected(alex):
    assert upload(alex, "pic.png", PNG).status_code == 201
    assert upload(alex, "doc.docx", DOCX).status_code == 201
    assert upload(alex, "pic.jpg", PNG).status_code == 400  # PNG bytes named .jpg
    assert upload(alex, "doc2.pptx", PDF).status_code == 400


def test_text_file_with_binary_data_rejected(alex):
    assert upload(alex, "ok.txt", b"plain text\nline two").status_code == 201
    assert upload(alex, "bad.txt", b"abc\x00def").status_code == 400


def test_tiny_files_are_checked_too(alex):
    assert upload(alex, "tiny.pdf", b"%PDF").status_code == 400


def test_empty_file_rejected(alex):
    # a browser sends Content-Length: 0 for an empty file
    assert upload(alex, "empty.txt", b"", content_length=0).status_code == 400
    # no Content-Length at all (chunked clients) is refused
    assert upload(alex, "empty.txt", b"").status_code == 411


def test_oversize_rejected_without_leftovers(app, alex, stored_files, tmp_files):
    app.config["MAX_UPLOAD_MB"] = 1
    before = len(stored_files())
    r = upload(alex, "big.pdf", b"%PDF-1.4\n" + b"x" * (1024 * 1024))
    assert r.status_code == 413
    assert r.get_json()["error"]["code"] == "too_large"
    assert len(stored_files()) == before and tmp_files() == []
    failed = logs(app, status="failed")
    assert len(failed) == 1 and "limit" in failed[0].error


def test_upload_at_exact_limit_is_accepted(app, alex):
    app.config["MAX_UPLOAD_MB"] = 1
    data = b"%PDF-1.4\n" + b"x" * (1024 * 1024 - 9)
    assert len(data) == 1024 * 1024
    assert upload(alex, "edge.pdf", data).status_code == 201


def test_invalid_subject_category_visibility(alex):
    assert upload(alex, subject="Underwater Basket Weaving").status_code == 400
    assert upload(alex, subject="").status_code == 400
    assert upload(alex, category="Memes").status_code == 400
    assert upload(alex, visibility="friends").status_code == 400


def test_subject_accepts_code_name_or_id(alex):
    for s in ("CMSC306", "cmsc306", "Networks & Communication", "s2", "CMSC306 · Networks & Communication"):
        r = upload(alex, subject=s)
        assert r.status_code == 201, s
        assert r.get_json()["file"]["subjectCode"] == "CMSC306"


def test_missing_filename_header(alex):
    r = alex.post("/api/files?subject=General&category=Other", data=PDF, content_type="application/octet-stream")
    assert r.status_code == 400


def test_expected_sha256_match_and_mismatch(app, alex, stored_files):
    good = hashlib.sha256(PDF).hexdigest()
    r = upload(alex, "ok.pdf", PDF, headers={"X-Expected-SHA256": good})
    assert r.status_code == 201
    log = logs(app, type="upload", status="completed")[-1]
    assert log.sha256_verified is True and log.sha256_expected == good
    before = len(stored_files())
    r = upload(alex, "bad.pdf", PDF, headers={"X-Expected-SHA256": "0" * 64})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "hash_mismatch"
    assert len(stored_files()) == before
    failed = logs(app, status="failed")[-1]
    assert failed.sha256_verified is False
    assert upload(alex, "bad2.pdf", PDF, headers={"X-Expected-SHA256": "xyz"}).status_code == 400


def test_title_defaults_to_original_name(alex):
    assert upload(alex, "Lecture 3.pdf", PDF).get_json()["file"]["name"] == "Lecture 3.pdf"


def test_incomplete_upload_is_logged_and_leaves_nothing(app, alex, stored_files, tmp_files):
    before = len(stored_files())
    r = upload(alex, "cut.pdf", PDF, content_length=len(PDF) + 500)
    assert r.status_code == 400
    assert len(stored_files()) == before and tmp_files() == []
    failed = logs(app, status="failed")
    assert len(failed) == 1


def test_buffer_size_admin_only_override(app, alex, student):
    upload(alex, "a.pdf", PDF, bufferKb="64")  # ignored for students
    assert logs(app, user_id="u2")[-1].buffer_kb == 256
    assert upload(student, "b.pdf", PDF, bufferKb="64").status_code == 201
    assert logs(app, user_id="u1", type="upload")[-1].buffer_kb == 64
    assert upload(student, "c.pdf", PDF, bufferKb="100").status_code == 400


def test_chunked_reading_handles_files_larger_than_buffer(app, alex):
    data = b"%PDF-1.4\n" + os.urandom(1024 * 1024 + 123)
    r = upload(alex, "multi.pdf", data)
    assert r.status_code == 201
    assert r.get_json()["file"]["sha256"] == hashlib.sha256(data).hexdigest()


def test_mobile_device_detected(app, alex):
    upload(alex, "m.pdf", PDF, headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Mobile"})
    assert logs(app, type="upload", user_id="u2")[-1].client_device == "mobile"


# ---------------------------------------------------------------- library list

def test_library_lists_only_public_files(alex, jamie):
    upload(alex, "pub.pdf", PDF, title="Alex Public")
    upload(alex, "priv.pdf", PDF, title="Alex Private", visibility="private")
    names = [f["name"] for f in jamie.get("/api/files?scope=library").get_json()["items"]]
    assert "Alex Public" in names and "Alex Private" not in names


def test_library_response_shape_and_paging(alex):
    r = alex.get("/api/files?scope=library&perPage=2&page=1").get_json()
    assert set(r) == {"items", "total", "page", "perPage"}
    assert r["total"] == 6 and len(r["items"]) == 2 and r["perPage"] == 2
    page3 = alex.get("/api/files?scope=library&perPage=2&page=3").get_json()
    assert len(page3["items"]) == 2
    assert alex.get("/api/files?perPage=9999").get_json()["perPage"] == 200


def test_library_search_by_name_owner_subject(alex):
    def names(qs):
        return [f["name"] for f in alex.get("/api/files?" + qs).get_json()["items"]]

    assert names("q=reviewer") == ["Sample - Computer Architecture Reviewer.pdf"]
    assert len(names("q=jamie")) == 2  # owner search (f2, f4)
    assert len(names("q=CMSC309")) == 1
    assert len(names("q=networks")) == 1
    assert names("q=%25") == []  # % is literal
    assert names("q=nothing-matches") == []


def test_library_filters(alex):
    def names(qs):
        return [f["name"] for f in alex.get("/api/files?" + qs).get_json()["items"]]

    assert len(names("subject=CMSC310")) == 1
    assert len(names("subject=Data Structures")) == 1
    assert len(names("category=Reviewer")) == 2
    assert len(names("category=Reviewer&subject=CMSC310")) == 1
    assert len(names("subject=all&category=all")) == 6


def test_bad_scope(alex):
    assert alex.get("/api/files?scope=everything").status_code == 400


def test_list_requires_login(api):
    assert api.get("/api/files").status_code == 401


def test_my_files_scope_includes_private(alex, jamie):
    upload(alex, "p.pdf", PDF, title="Mine Private", visibility="private")
    mine = [f["name"] for f in alex.get("/api/files?scope=mine").get_json()["items"]]
    assert "Mine Private" in mine
    assert all(f["ownerId"] == "u2" for f in alex.get("/api/files?scope=mine").get_json()["items"])
    assert jamie.get("/api/files?scope=mine").get_json()["total"] == 2


# ---------------------------------------------------------------- download and preview

def test_download_returns_exact_bytes_with_safe_headers(jamie):
    fid = "f1"
    r = jamie.get(f"/api/files/{fid}/download")
    body = r.data
    assert r.status_code == 200
    assert hashlib.sha256(body).hexdigest() == r.headers["X-File-SHA256"]
    assert r.headers["Content-Disposition"].startswith("attachment;")
    assert "Sample - Computer Architecture Reviewer.pdf" in urllib.parse.unquote(r.headers["Content-Disposition"])
    assert r.headers["Content-Type"] == "application/octet-stream"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Content-Length"] == str(len(body))


def test_download_counter_counts_others_not_owner(app, alex, jamie, student):
    # f1 is owned by alex
    assert alex.get("/api/files/f1/download").data
    with app.app_context():
        assert db.session.get(File, "f1").downloads == 0
    assert jamie.get("/api/files/f1/download").data
    assert student.get("/api/files/f1/download").data
    with app.app_context():
        assert db.session.get(File, "f1").downloads == 2
    assert alex.get("/api/stats/me").get_json()["downloads"] == 2


def test_every_download_is_logged_including_owner(app, alex, jamie):
    alex.get("/api/files/f1/download").data
    jamie.get("/api/files/f1/download").data
    mine = logs(app, type="download", user_id="u2")
    theirs = logs(app, type="download", user_id="u3")
    assert len(mine) == 1 and len(theirs) == 1
    d = theirs[0]
    assert d.status == "completed" and d.size == d.bytes_transferred > 0
    assert d.buffer_kb == 256 and d.server_seconds >= 0 and d.file_id == "f1"


def test_download_needs_login(api):
    assert api.get("/api/files/f1/download").status_code == 401


def test_download_name_gets_extension_when_title_has_none(alex, jamie):
    fid = upload(alex, "Lecture.pdf", PDF, title="Week 2 Notes").get_json()["file"]["id"]
    r = jamie.get(f"/api/files/{fid}/download")
    r.data
    assert 'filename="Week 2 Notes.pdf"' in r.headers["Content-Disposition"]


def test_download_name_unicode_is_encoded(alex, jamie):
    fid = upload(alex, "x.pdf", PDF, title="Résumé – Ñandú").get_json()["file"]["id"]
    r = jamie.get(f"/api/files/{fid}/download")
    r.data
    cd = r.headers["Content-Disposition"]
    assert "filename*=UTF-8''" in cd and "R%C3%A9sum%C3%A9" in cd
    cd.encode("latin-1")  # header must be plain ASCII/latin-1 safe


def test_download_missing_bytes_returns_clean_error(app, alex):
    from app.storage import path_for

    with app.app_context():
        os.remove(path_for(db.session.get(File, "f1").stored_name))
    r = alex.get("/api/files/f1/download")
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "file_missing"


def test_admin_download_buffer_override(app, student):
    student.get("/api/files/f1/download?bufferKb=1024").data
    assert logs(app, type="download", user_id="u1")[-1].buffer_kb == 1024


def test_preview_pdf_is_inline_with_fixed_type(jamie):
    r = jamie.get("/api/files/f1/preview")
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "application/pdf"
    assert r.headers["Content-Disposition"].startswith("inline;")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]
    assert r.data.startswith(b"%PDF-")


def test_preview_image_is_sandboxed(alex, jamie):
    fid = upload(alex, "pic.png", PNG).get_json()["file"]["id"]
    r = jamie.get(f"/api/files/{fid}/preview")
    assert r.status_code == 200 and r.headers["Content-Type"] == "image/png"
    assert r.headers["Content-Security-Policy"].startswith("sandbox;")
    assert r.data == PNG


def test_preview_not_available_for_office_and_text(alex, jamie):
    docx = upload(alex, "d.docx", DOCX).get_json()["file"]["id"]
    txt = upload(alex, "t.txt", b"hello").get_json()["file"]["id"]
    assert jamie.get(f"/api/files/{docx}/preview").status_code == 415
    assert jamie.get(f"/api/files/{txt}/preview").status_code == 415


def test_preview_does_not_count_as_download(app, jamie):
    jamie.get("/api/files/f1/preview").data
    with app.app_context():
        assert db.session.get(File, "f1").downloads == 0
    assert logs(app, type="download") == []


# ---------------------------------------------------------------- my files: edit and delete

def test_owner_can_edit_title_subject_category_visibility(alex):
    fid = upload(alex, "e.pdf", PDF).get_json()["file"]["id"]
    r = alex.patch(f"/api/files/{fid}", json={
        "name": "Renamed", "subject": "CMSC306", "category": "Lecture Notes", "visibility": "private"})
    assert r.status_code == 200
    f = r.get_json()["file"]
    assert (f["name"], f["subjectCode"], f["category"], f["visibility"]) == ("Renamed", "CMSC306", "Lecture Notes", "private")


def test_edit_validation_changes_nothing(alex):
    fid = upload(alex, "e.pdf", PDF, title="Keep").get_json()["file"]["id"]
    r = alex.patch(f"/api/files/{fid}", json={"name": "Changed", "category": "Memes"})
    assert r.status_code == 400
    assert alex.get(f"/api/files/{fid}").get_json()["file"]["name"] == "Keep"
    assert alex.patch(f"/api/files/{fid}", json={"visibility": "friends"}).status_code == 400
    assert alex.patch(f"/api/files/{fid}", json={"name": "  "}).status_code == 400


def test_delete_removes_row_bytes_and_keeps_logs(app, alex, stored_files):
    fid = upload(alex, "d.pdf", PDF).get_json()["file"]["id"]
    before = len(stored_files())
    r = alex.delete(f"/api/files/{fid}")
    assert r.status_code == 200
    assert len(stored_files()) == before - 1
    assert alex.get(f"/api/files/{fid}").status_code == 404
    assert len(logs(app, type="upload", file_id=fid)) == 1  # history survives deletion


def test_delete_survives_locked_file_on_windows(app, alex, monkeypatch, stored_files):
    fid = upload(alex, "locked.pdf", PDF).get_json()["file"]["id"]
    real_remove = os.remove

    def locked(path, *a, **k):
        if os.sep + ".tmp" + os.sep not in path:
            raise PermissionError("file is in use")
        return real_remove(path, *a, **k)

    monkeypatch.setattr(os, "remove", locked)
    r = alex.delete(f"/api/files/{fid}")
    assert r.status_code == 200
    assert os.listdir(os.path.join(app.config["STORAGE_DIR"], ".trash"))
    with app.app_context():
        assert db.session.get(File, fid) is None


def test_verify_detects_corruption_and_missing(app, alex):
    r = alex.post("/api/files/f1/verify")
    assert r.status_code == 200 and r.get_json()["ok"] is True
    from app.storage import path_for

    with app.app_context():
        p = path_for(db.session.get(File, "f1").stored_name)
    with open(p, "ab") as fh:
        fh.write(b"tampered")
    bad = alex.post("/api/files/f1/verify").get_json()
    assert bad["ok"] is False and bad["actual"] != bad["expected"]
    os.remove(p)
    gone = alex.post("/api/files/f1/verify").get_json()
    assert gone["ok"] is False and gone["error"]


def test_stats_me(alex, jamie):
    s = alex.get("/api/stats/me").get_json()
    assert s == {"myFiles": 2, "received": 0, "sent": 0, "downloads": 0}
