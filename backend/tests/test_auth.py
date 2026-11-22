from app.extensions import db
from app.models import Session, User, utcnow
from datetime import timedelta


def register(api, **over):
    body = {"name": "New Person", "username": "newbie", "password": "longenough1"}
    body.update(over)
    return api.client.post("/api/auth/register", json=body)


# ---------- registration ----------

def test_register_creates_student_and_logs_in(api):
    r = register(api)
    assert r.status_code == 201
    data = r.get_json()
    assert data["user"]["role"] == "student"
    assert data["user"]["username"] == "newbie"
    assert "password" not in str(data).lower().replace("mustchangepassword", "")
    assert data["csrfToken"]
    api.csrf = data["csrfToken"]
    assert api.get("/api/auth/me").status_code == 200


def test_register_cannot_choose_admin_role(api):
    r = register(api, role="admin")
    assert r.get_json()["user"]["role"] == "student"


def test_register_username_is_lowercased_and_unique(api):
    assert register(api, username="MixedCase").get_json()["user"]["username"] == "mixedcase"
    assert register(api, username="mixedcase").status_code == 409
    assert register(api, username="MIXEDCASE").status_code == 409


def test_register_validation(api):
    assert register(api, password="short").status_code == 400
    assert register(api, username="ab").status_code == 400
    assert register(api, username="bad name!").status_code == 400
    assert register(api, name="").status_code == 400
    assert register(api, name="x" * 81).status_code == 400
    assert register(api, email="not-an-email").status_code == 400


def test_register_duplicate_email(api):
    assert register(api, username="one", email="Same@Example.com").status_code == 201
    r = register(api, username="two", email="same@example.com")
    assert r.status_code == 409


def test_register_closed_mode(app, api):
    app.config["REGISTRATION_MODE"] = "closed"
    assert register(api).status_code == 403


def test_error_format(api):
    r = register(api, password="x")
    err = r.get_json()["error"]
    assert set(err) == {"code", "message"}


# ---------- login ----------

def test_seeded_demo_accounts_can_log_in(make_api):
    for username in ("student", "alex", "jamie"):
        r = make_api().login(username)
        assert r.status_code == 200, username
    assert make_api().login("student").get_json()["user"]["role"] == "admin"
    assert make_api().login("alex").get_json()["user"]["role"] == "student"


def test_login_by_email_and_case_insensitive_username(make_api):
    assert make_api().login("ALEX@filego.local").status_code == 200
    assert make_api().login("Alex").status_code == 200


def test_login_failure_is_generic(api):
    wrong_pw = api.client.post("/api/auth/login", json={"username": "alex", "password": "nope"})
    no_user = api.client.post("/api/auth/login", json={"username": "ghost", "password": "nope"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.get_json() == no_user.get_json()


def test_login_sets_httponly_cookie(api):
    r = api.client.post("/api/auth/login", json={"username": "alex", "password": "demo123"})
    cookie = r.headers["Set-Cookie"]
    assert "filego_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_session_token_is_stored_hashed(app, api):
    r = api.client.post("/api/auth/login", json={"username": "alex", "password": "demo123"})
    token = r.headers["Set-Cookie"].split("filego_session=")[1].split(";")[0]
    with app.app_context():
        assert db.session.query(Session).filter_by(token_hash=token).first() is None
        assert db.session.query(Session).count() == 1


def test_login_rate_limit_per_username(make_api):
    api = make_api()
    for _ in range(5):
        assert api.login("alex", "wrong").status_code == 401
    # 6th attempt is blocked, even with the correct password
    r = api.login("alex", "demo123")
    assert r.status_code == 429
    assert r.get_json()["error"]["code"] == "rate_limited"


def test_inactive_user_cannot_log_in(app, api):
    with app.app_context():
        db.session.get(User, "u2").is_active = False
        db.session.commit()
    assert api.login("alex").status_code == 401


# ---------- sessions, CSRF, logout ----------

def test_me_requires_login(api):
    r = api.get("/api/auth/me")
    assert r.status_code == 401
    assert r.get_json()["error"]["code"] == "unauthenticated"


def test_csrf_required_for_state_changes(alex):
    token = alex.csrf
    alex.csrf = None
    r = alex.post("/api/auth/logout")
    assert r.status_code == 403
    assert r.get_json()["error"]["code"] == "csrf_failed"
    alex.csrf = "wrong"
    assert alex.post("/api/auth/logout").status_code == 403
    alex.csrf = token
    assert alex.post("/api/auth/logout").status_code == 200


def test_logout_ends_session(alex):
    assert alex.post("/api/auth/logout").status_code == 200
    assert alex.get("/api/auth/me").status_code == 401


def test_me_returns_csrf_token_again(alex):
    assert alex.get("/api/auth/me").get_json()["csrfToken"] == alex.csrf


def test_deactivated_user_session_dies_immediately(app, alex):
    assert alex.get("/api/auth/me").status_code == 200
    with app.app_context():
        db.session.get(User, "u2").is_active = False
        db.session.commit()
    assert alex.get("/api/auth/me").status_code == 401


def test_idle_session_expires(app, alex):
    with app.app_context():
        s = db.session.query(Session).first()
        s.last_seen_at = utcnow() - timedelta(hours=13)
        db.session.commit()
    assert alex.get("/api/auth/me").status_code == 401


def test_absolute_session_expires(app, alex):
    with app.app_context():
        s = db.session.query(Session).first()
        s.expires_at = utcnow() - timedelta(minutes=1)
        db.session.commit()
    assert alex.get("/api/auth/me").status_code == 401


def test_list_and_revoke_sessions(make_api):
    a, b = make_api(), make_api()
    a.login("alex")
    b.login("alex")
    items = a.get("/api/auth/sessions").get_json()["items"]
    assert len(items) == 2
    assert sum(1 for i in items if i["current"]) == 1
    other = next(i for i in items if not i["current"])
    assert a.delete(f"/api/auth/sessions/{other['id']}").status_code == 200
    assert b.get("/api/auth/me").status_code == 401
    assert a.get("/api/auth/me").status_code == 200


def test_cannot_revoke_someone_elses_session(make_api):
    a, j = make_api(), make_api()
    a.login("alex")
    j.login("jamie")
    jamie_session = j.get("/api/auth/sessions").get_json()["items"][0]["id"]
    assert a.delete(f"/api/auth/sessions/{jamie_session}").status_code == 404


# ---------- profile and password ----------

def test_update_name(alex):
    r = alex.patch("/api/users/me", json={"name": "  Alexander Rivera "})
    assert r.status_code == 200
    assert r.get_json()["user"]["name"] == "Alexander Rivera"
    assert alex.get("/api/auth/me").get_json()["user"]["name"] == "Alexander Rivera"


def test_update_name_validation(alex):
    assert alex.patch("/api/users/me", json={"name": ""}).status_code == 400


def test_change_email_requires_current_password(alex):
    r = alex.patch("/api/users/me", json={"email": "new@example.com"})
    assert r.status_code == 403
    r = alex.patch("/api/users/me", json={"email": "new@example.com", "currentPassword": "demo123"})
    assert r.status_code == 200
    assert r.get_json()["user"]["email"] == "new@example.com"


def test_change_email_conflict(alex):
    r = alex.patch(
        "/api/users/me", json={"email": "jamie@filego.local", "currentPassword": "demo123"}
    )
    assert r.status_code == 409


def test_change_password(make_api):
    a, other_device = make_api(), make_api()
    a.login("alex")
    other_device.login("alex")
    bad = a.post("/api/users/me/password", json={"currentPassword": "wrong", "newPassword": "newpassword1"})
    assert bad.status_code == 403
    short = a.post("/api/users/me/password", json={"currentPassword": "demo123", "newPassword": "short"})
    assert short.status_code == 400
    ok = a.post(
        "/api/users/me/password", json={"currentPassword": "demo123", "newPassword": "newpassword1"}
    )
    assert ok.status_code == 200
    assert a.get("/api/auth/me").status_code == 200  # current session stays
    assert other_device.get("/api/auth/me").status_code == 401  # others are signed out
    assert make_api().login("alex", "demo123").status_code == 401
    assert make_api().login("alex", "newpassword1").status_code == 200


# ---------- user search ----------

def test_user_search_exposes_only_public_fields(alex):
    items = alex.get("/api/users").get_json()["items"]
    assert {u["username"] for u in items} == {"student", "jamie"}  # not self
    for u in items:
        assert set(u) == {"id", "name", "username"}


def test_user_search_query(alex):
    items = alex.get("/api/users?q=jam").get_json()["items"]
    assert [u["username"] for u in items] == ["jamie"]
    assert alex.get("/api/users?q=%25").get_json()["items"] == []  # % is literal, not a wildcard


def test_user_search_hides_inactive_and_needs_login(app, api, alex):
    with app.app_context():
        db.session.get(User, "u3").is_active = False
        db.session.commit()
    names = [u["username"] for u in alex.get("/api/users").get_json()["items"]]
    assert "jamie" not in names
    assert api.get("/api/users").status_code == 401
