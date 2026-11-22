import pytest

from app import create_app
from app.extensions import db
from app.seed_data import seed_demo


@pytest.fixture()
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key-not-for-real-use",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + (tmp_path / "test.db").as_posix(),
            "STORAGE_DIR": str(tmp_path / "storage"),
            "LOG_TO_FILE": False,
            "REGISTER_MAX_PER_IP": 1000,
        }
    )
    with app.app_context():
        seed_demo()
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


class Api:
    """Thin wrapper around the Flask test client that remembers the CSRF token."""

    def __init__(self, app):
        self.client = app.test_client()
        self.csrf = None

    def _headers(self, extra=None):
        h = {}
        if self.csrf:
            h["X-CSRF-Token"] = self.csrf
        if extra:
            h.update(extra)
        return h

    def request(self, method, url, json=None, headers=None, **kw):
        return self.client.open(url, method=method, json=json, headers=self._headers(headers), **kw)

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, json=None, **kw):
        return self.request("POST", url, json=json, **kw)

    def patch(self, url, json=None, **kw):
        return self.request("PATCH", url, json=json, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)

    def login(self, username, password="demo123"):
        r = self.client.post("/api/auth/login", json={"username": username, "password": password})
        if r.status_code == 200:
            self.csrf = r.get_json()["csrfToken"]
        return r


@pytest.fixture()
def api(app):
    return Api(app)


@pytest.fixture()
def make_api(app):
    return lambda: Api(app)


@pytest.fixture()
def student(make_api):
    a = make_api()
    assert a.login("student").status_code == 200
    return a


@pytest.fixture()
def alex(make_api):
    a = make_api()
    assert a.login("alex").status_code == 200
    return a


@pytest.fixture()
def jamie(make_api):
    a = make_api()
    assert a.login("jamie").status_code == 200
    return a
