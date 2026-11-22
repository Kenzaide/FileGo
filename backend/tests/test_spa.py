import pytest

from app import create_app
from app.seed_data import seed_demo
from app.extensions import db


@pytest.fixture()
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>FileGo</title><div id=root></div>")
    (d / "assets" / "index-abc123.js").write_text("console.log('app')")
    (d / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("top secret outside dist")
    return d


def make_app(tmp_path, dist):
    return create_app({
        "TESTING": True, "SECRET_KEY": "test-secret-key-not-for-real-use",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///" + (tmp_path / "t.db").as_posix(),
        "STORAGE_DIR": str(tmp_path / "storage"), "LOG_TO_FILE": False,
        "PASSWORD_HASH_METHOD": "scrypt:1024:8:1", "FRONTEND_DIST": str(dist),
    })


@pytest.fixture()
def client(tmp_path, dist):
    app = make_app(tmp_path, dist)
    yield app.test_client()
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.mark.parametrize("path", ["/", "/library", "/inbox", "/my-files", "/admin", "/some/deep/link"])
def test_app_routes_return_the_shell(client, path):
    r = client.get(path)
    assert r.status_code == 200 and b'id=root' in r.data
    assert r.headers["Cache-Control"] == "no-cache"


def test_assets_are_served_and_cached(client):
    r = client.get("/assets/index-abc123.js")
    assert r.status_code == 200 and b"console.log" in r.data
    assert "immutable" in r.headers["Cache-Control"]
    assert client.get("/favicon.svg").status_code == 200


def test_missing_asset_is_404_not_the_shell(client):
    assert client.get("/assets/nope.js").status_code == 404
    assert client.get("/missing.png").status_code == 404


@pytest.mark.parametrize("path", ["/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt", "/..%2fsecret.txt"])
def test_cannot_escape_dist(client, path):
    r = client.get(path)
    assert b"top secret" not in r.data


def test_unknown_api_path_is_json_404(client):
    r = client.get("/api/nothing-here")
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"
    assert client.get("/api").status_code == 404


def test_api_still_works_beside_the_shell(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/ping").get_json()["pong"] is True


def test_wrong_method_on_shell_path(client):
    assert client.post("/library").status_code == 405


def test_not_built_message(tmp_path):
    app = make_app(tmp_path, tmp_path / "no-such-dist")
    r = app.test_client().get("/library")
    assert r.status_code == 503 and b"npm run build" in r.data
    assert app.test_client().get("/api/health").status_code == 200
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
