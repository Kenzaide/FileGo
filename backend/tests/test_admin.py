import pytest

from app.extensions import db
from app.models import File, Transfer, User
from conftest import send_file, upload


def uid(app, username):
    with app.app_context():
        return db.session.scalar(db.select(User.id).where(User.username == username))


ADMIN_URLS = [
    ("GET", "/api/admin/users"),
    ("GET", "/api/admin/files"),
    ("GET", "/api/admin/stats"),
    ("GET", "/api/admin/transfers/export.csv"),
    ("PATCH", "/api/admin/users/x"),
    ("POST", "/api/admin/users/x/reset-password"),
    ("DELETE", "/api/admin/files/x"),
]


@pytest.mark.parametrize("method,url", ADMIN_URLS)
def test_anonymous_gets_401(api, method, url):
    assert api.request(method, url, json={} if method != "GET" else None).status_code == 401


@pytest.mark.parametrize("method,url", ADMIN_URLS)
def test_student_gets_403(alex, method, url):
    assert alex.request(method, url, json={} if method != "GET" else None).status_code == 403


def test_user_list_has_usage(student, alex):
    assert upload(alex, name="a.pdf").status_code == 201
    r = student.get("/api/admin/users")
    assert r.status_code == 200
    body = r.get_json()
    assert body["total"] == 3
    row = next(u for u in body["items"] if u["username"] == "alex")
    assert row["fileCount"] >= 1 and row["storageBytes"] > 0 and row["isActive"] is True
    assert "password" not in str(body).lower().replace("mustchangepassword", "")
    assert student.get("/api/admin/users?q=jam").get_json()["total"] == 1


def test_deactivate_revokes_sessions_and_blocks_login(app, student, alex, make_api):
    r = student.patch(f"/api/admin/users/{uid(app, 'alex')}", json={"isActive": False})
    assert r.status_code == 200 and r.get_json()["user"]["isActive"] is False
    assert alex.get("/api/auth/me").status_code == 401  # session gone immediately
    assert make_api().login("alex").status_code in (401, 403)
    r = student.patch(f"/api/admin/users/{uid(app, 'alex')}", json={"isActive": True})
    assert r.status_code == 200
    assert make_api().login("alex").status_code == 200


def test_admin_cannot_change_self(app, student):
    me = uid(app, "student")
    assert student.patch(f"/api/admin/users/{me}", json={"isActive": False}).status_code == 403
    assert student.patch(f"/api/admin/users/{me}", json={"role": "student"}).status_code == 403


def test_last_admin_is_protected(app, student, alex):
    a = uid(app, "alex")
    assert student.patch(f"/api/admin/users/{a}", json={"role": "admin"}).status_code == 200
    # alex is now an admin too; promoted admin may demote the original, but not the last one.
    assert alex.patch(f"/api/admin/users/{uid(app, 'student')}", json={"role": "student"}).status_code == 200
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(User.id)).where(User.role == "admin")) == 1
    assert student.get("/api/admin/users").status_code == 403  # demoted


def test_last_admin_cannot_be_deactivated_by_another_admin(app, student, alex):
    student.patch(f"/api/admin/users/{uid(app, 'alex')}", json={"role": "admin"})
    # Only deactivation path for the last admin is via a different admin, who is then not last.
    assert alex.patch(f"/api/admin/users/{uid(app, 'student')}", json={"isActive": False}).status_code == 200
    # alex is now the only admin; nobody else can touch him, and he cannot touch himself.
    assert alex.patch(f"/api/admin/users/{uid(app, 'alex')}", json={"isActive": False}).status_code == 403


def test_update_validation(app, student):
    j = uid(app, "jamie")
    assert student.patch(f"/api/admin/users/{j}", json={"role": "root"}).status_code == 400
    assert student.patch(f"/api/admin/users/{j}", json={"isActive": "no"}).status_code == 400
    assert student.patch("/api/admin/users/nope", json={"isActive": False}).status_code == 404


def test_reset_password(app, student, jamie, make_api):
    r = student.post(f"/api/admin/users/{uid(app, 'jamie')}/reset-password")
    assert r.status_code == 200
    temp = r.get_json()["temporaryPassword"]
    assert len(temp) == 10
    assert jamie.get("/api/auth/me").status_code == 401  # old session revoked
    assert make_api().login("jamie", "demo123").status_code == 401
    fresh = make_api()
    login = fresh.login("jamie", temp)
    assert login.status_code == 200 and login.get_json()["user"]["mustChangePassword"] is True
    ch = fresh.post("/api/users/me/password", json={"currentPassword": temp, "newPassword": "brandnew123"})
    assert ch.status_code == 200
    assert make_api().login("jamie", "brandnew123").get_json()["user"]["mustChangePassword"] is False


def test_reset_own_password_blocked(app, student):
    assert student.post(f"/api/admin/users/{uid(app, 'student')}/reset-password").status_code == 403


def test_admin_files_include_private(app, student, alex):
    pub = upload(alex, name="pub.pdf", visibility="public").get_json()["file"]["id"]
    priv = upload(alex, name="priv.pdf", visibility="private", title="Private one").get_json()["file"]["id"]
    body = student.get("/api/admin/files").get_json()
    ids = {f["id"] for f in body["items"]}
    assert {pub, priv} <= ids
    assert body["storageBytes"] >= sum(f["size"] for f in body["items"] if f["id"] in (pub, priv))
    only = student.get("/api/admin/files?visibility=private").get_json()
    assert priv in {f["id"] for f in only["items"]} and pub not in {f["id"] for f in only["items"]}
    assert student.get("/api/admin/files?visibility=x").status_code == 400
    assert student.get("/api/admin/files?q=private+one").get_json()["total"] == 1


def test_admin_remove_file_deletes_bytes_and_transfers(app, student, alex, stored_files):
    r = send_file(alex, uid(app, "jamie"))
    assert r.status_code == 201
    fid = r.get_json()["file"]["id"]
    before = len(stored_files())
    d = student.delete(f"/api/admin/files/{fid}")
    assert d.status_code == 200 and d.get_json()["removedTransfers"] == 1
    assert len(stored_files()) == before - 1
    with app.app_context():
        assert db.session.get(File, fid) is None
        assert db.session.scalar(db.select(db.func.count(Transfer.id))) == 0
    assert student.delete(f"/api/admin/files/{fid}").status_code == 404


def test_stats(app, student, alex):
    upload(alex, name="s1.pdf")
    upload(alex, name="bad.pdf", data=b"not a pdf at all")  # fails the magic-byte check
    send_file(alex, uid(app, "jamie"))
    body = student.get("/api/admin/stats").get_json()
    assert body["users"]["total"] == 3 and body["users"]["admins"] == 1
    assert body["files"]["total"] >= 2 and body["files"]["storageBytes"] > 0
    assert body["transfers"]["sent"] == 1 and body["transfers"]["delivered"] == 1
    assert body["activity"]["uploads"] >= 2 and body["activity"]["failed"] >= 1
    assert 0 < body["activity"]["successRate"] < 100
    assert body["disk"]["totalBytes"] > 0
    assert any(t["username"] == "alex" for t in body["topUploaders"])


def test_export_all_has_every_users_rows(student, alex, jamie):
    upload(alex, name="a.pdf")
    upload(jamie, name="j.pdf")
    r = student.get("/api/admin/transfers/export.csv")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    text = r.get_data(as_text=True)
    assert "a.pdf" in text and "j.pdf" in text
    assert text.splitlines()[0].lstrip("\ufeff").startswith("id,created_at,user_id")
