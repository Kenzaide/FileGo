import os

import pytest

from app.extensions import db
from app.models import File, Transfer, TransferLog, User
from conftest import PDF, Api, send_file, upload


def logs(app, **filters):
    with app.app_context():
        return db.session.query(TransferLog).filter_by(**filters).all()


# ---------------------------------------------------------------- direct sending

def test_send_creates_private_file_and_transfer(alex):
    r = send_file(alex, "u3", "secret.pdf")
    assert r.status_code == 201
    data = r.get_json()
    assert data["file"]["visibility"] == "private"
    assert data["file"]["subject"] == "General" and data["file"]["category"] == "Other"
    t = data["transfer"]
    assert (t["senderId"], t["recipientId"], t["status"], t["direction"]) == ("u2", "u3", "Delivered", "direct")
    assert t["fileId"] == data["file"]["id"]


def test_send_can_never_be_public(alex, jamie):
    r = send_file(alex, "u3", "s.pdf", visibility="public")  # parameter is ignored
    assert r.get_json()["file"]["visibility"] == "private"
    names = [f["name"] for f in jamie.get("/api/files?scope=library").get_json()["items"]]
    assert "s.pdf" not in names


def test_send_validation(app, alex):
    assert send_file(alex, "u2").status_code == 400  # to self
    assert send_file(alex, "nobody").status_code == 404
    assert send_file(alex, "").status_code == 404
    assert send_file(alex, "u3", "bad.exe").status_code == 400
    assert send_file(alex, "u3", "fake.pdf", data=b"not a pdf").status_code == 400
    with app.app_context():
        db.session.get(User, "u3").is_active = False
        db.session.commit()
    assert send_file(alex, "u3").status_code == 404


def test_failed_send_leaves_no_file_or_transfer(app, alex, stored_files):
    before = len(stored_files())
    send_file(alex, "u3", "fake.pdf", data=b"not a pdf")
    with app.app_context():
        assert db.session.query(Transfer).count() == 0
        assert db.session.query(File).count() == 6
    assert len(stored_files()) == before
    assert len(logs(app, status="failed")) == 1


def test_inbox_and_sent_lists(alex, jamie):
    send_file(alex, "u3", "one.pdf", title="First")
    send_file(alex, "u3", "two.pdf", title="Second")
    inbox = jamie.get("/api/transfers?box=received").get_json()
    assert inbox["total"] == 2
    assert {i["name"] for i in inbox["items"]} == {"First", "Second"}
    assert all(i["sender"] == "Alex Rivera" and i["status"] == "Delivered" for i in inbox["items"])
    assert all(i["seconds"] is not None for i in inbox["items"])
    sent = alex.get("/api/transfers?box=sent").get_json()
    assert sent["total"] == 2 and sent["items"][0]["recipient"] == "Jamie Cruz"
    assert alex.get("/api/transfers?box=received").get_json()["total"] == 0
    assert jamie.get("/api/transfers?box=sent").get_json()["total"] == 0


def test_transfers_box_required(alex, api):
    assert alex.get("/api/transfers").status_code == 400
    assert alex.get("/api/transfers?box=all").status_code == 400
    assert api.get("/api/transfers?box=sent").status_code == 401


def test_recipient_downloads_and_status_changes(app, alex, jamie):
    fid = send_file(alex, "u3", "s.pdf").get_json()["file"]["id"]
    assert jamie.get("/api/transfers/unread-count").get_json()["count"] == 1
    r = jamie.get(f"/api/files/{fid}/download")
    assert r.data == PDF
    assert jamie.get("/api/transfers/unread-count").get_json()["count"] == 0
    assert jamie.get("/api/transfers?box=received").get_json()["items"][0]["status"] == "Downloaded"
    assert alex.get("/api/transfers?box=sent").get_json()["items"][0]["status"] == "Downloaded"
    assert len(logs(app, type="download", user_id="u3")) == 1


def test_private_send_download_does_not_count_for_sender(app, alex, jamie):
    fid = send_file(alex, "u3", "s.pdf").get_json()["file"]["id"]
    jamie.get(f"/api/files/{fid}/download").data
    with app.app_context():
        assert db.session.get(File, fid).downloads == 0
    assert alex.get("/api/stats/me").get_json()["downloads"] == 0


def test_stats_reflect_sharing(alex, jamie):
    send_file(alex, "u3", "s.pdf")
    upload(alex, "p.pdf", PDF)
    assert alex.get("/api/stats/me").get_json() == {"myFiles": 4, "received": 0, "sent": 1, "downloads": 0}
    assert jamie.get("/api/stats/me").get_json()["received"] == 1


def test_sent_file_is_invisible_to_others(make_api, alex):
    fid = send_file(alex, "u3", "s.pdf").get_json()["file"]["id"]
    sam = make_api()
    sam.post("/api/auth/register", json={"name": "Sam", "username": "sam", "password": "longenough1"})
    assert sam.login("sam", "longenough1").status_code == 200
    assert sam.get(f"/api/files/{fid}").status_code == 404
    assert sam.get(f"/api/files/{fid}/download").status_code == 404


def test_deleting_sent_file_removes_it_from_inbox(app, alex, jamie, stored_files):
    fid = send_file(alex, "u3", "s.pdf").get_json()["file"]["id"]
    before = len(stored_files())
    r = alex.delete(f"/api/files/{fid}")
    assert r.get_json()["removedTransfers"] == 1
    assert jamie.get("/api/transfers?box=received").get_json()["total"] == 0
    assert alex.get("/api/transfers?box=sent").get_json()["total"] == 0
    assert len(stored_files()) == before - 1
    with app.app_context():
        assert db.session.query(Transfer).count() == 0  # database cascade
    assert len(logs(app, type="upload", file_id=fid)) == 1  # the log stays


def test_cascade_works_when_file_deleted_by_admin(app, alex, jamie, student):
    fid = send_file(alex, "u3", "s.pdf").get_json()["file"]["id"]
    assert student.delete(f"/api/files/{fid}").status_code == 200
    assert jamie.get("/api/transfers?box=received").get_json()["total"] == 0


# ---------------------------------------------------------------- authorization matrix

def register_sam(make_api):
    api = make_api()
    api.post("/api/auth/register", json={"name": "Sam Other", "username": "sam", "password": "longenough1"})
    assert api.login("sam", "longenough1").status_code == 200
    return api


KINDS = ["public", "private", "sent"]
ACTORS = ["anonymous", "owner", "recipient", "other", "admin"]

# status expected for (kind, actor, action)
READ = {
    "public":  dict(anonymous=401, owner=200, recipient=200, other=200, admin=200),
    "private": dict(anonymous=401, owner=200, recipient=404, other=404, admin=200),
    "sent":    dict(anonymous=401, owner=200, recipient=200, other=404, admin=200),
}
WRITE = {
    "public":  dict(anonymous=401, owner=200, recipient=403, other=403, admin=200),
    "private": dict(anonymous=401, owner=200, recipient=404, other=404, admin=200),
    "sent":    dict(anonymous=401, owner=200, recipient=403, other=404, admin=200),
}


@pytest.fixture()
def world(make_api, alex, jamie, student):
    """alex owns the file; jamie is the 'recipient' (only in the sent case); sam is another student."""
    actors = {
        "anonymous": make_api(),
        "owner": alex,
        "recipient": jamie,
        "other": register_sam(make_api),
        "admin": student,
    }

    def make_file(kind):
        if kind == "public":
            return upload(alex, "m.pdf", PDF).get_json()["file"]["id"]
        if kind == "private":
            return upload(alex, "m.pdf", PDF, visibility="private").get_json()["file"]["id"]
        return send_file(alex, "u3", "m.pdf").get_json()["file"]["id"]

    return actors, make_file


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("actor", ACTORS)
def test_matrix_read_details(world, kind, actor):
    actors, make_file = world
    fid = make_file(kind)
    assert actors[actor].get(f"/api/files/{fid}").status_code == READ[kind][actor]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("actor", ACTORS)
def test_matrix_download(world, kind, actor):
    actors, make_file = world
    fid = make_file(kind)
    r = actors[actor].get(f"/api/files/{fid}/download")
    assert r.status_code == READ[kind][actor]
    r.data


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("actor", ACTORS)
def test_matrix_preview_and_verify(world, kind, actor):
    actors, make_file = world
    fid = make_file(kind)
    assert actors[actor].get(f"/api/files/{fid}/preview").status_code == READ[kind][actor]
    assert actors[actor].post(f"/api/files/{fid}/verify").status_code == READ[kind][actor]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("actor", ACTORS)
def test_matrix_edit(world, kind, actor):
    actors, make_file = world
    fid = make_file(kind)
    r = actors[actor].patch(f"/api/files/{fid}", json={"name": "Changed"})
    assert r.status_code == WRITE[kind][actor]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("actor", ACTORS)
def test_matrix_delete(app, world, kind, actor):
    actors, make_file = world
    fid = make_file(kind)
    r = actors[actor].delete(f"/api/files/{fid}")
    assert r.status_code == WRITE[kind][actor]
    with app.app_context():
        still_there = db.session.get(File, fid) is not None
    assert still_there == (WRITE[kind][actor] != 200)


@pytest.mark.parametrize("actor", ["other", "recipient"])
def test_private_files_never_appear_in_lists_for_non_owners(world, actor):
    actors, make_file = world
    fid = make_file("private")
    for scope in ("library", "mine"):
        ids = [f["id"] for f in actors[actor].get(f"/api/files?scope={scope}").get_json()["items"]]
        assert fid not in ids


def test_private_404_has_same_shape_as_missing_file(world):
    actors, make_file = world
    fid = make_file("private")
    hidden = actors["other"].get(f"/api/files/{fid}").get_json()
    missing = actors["other"].get("/api/files/doesnotexist").get_json()
    assert hidden == missing


def test_anonymous_cannot_reach_transfers_or_stats(world):
    anon = world[0]["anonymous"]
    for url in ("/api/transfers?box=sent", "/api/transfers/unread-count", "/api/stats/me", "/api/users"):
        assert anon.get(url).status_code == 401
    assert send_file(anon, "u3").status_code == 401
