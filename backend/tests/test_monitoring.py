import csv
import io
import time

from app import monitor
from app.extensions import db
from app.models import TransferLog
from conftest import PDF, send_file, upload


def all_logs(app, **filters):
    with app.app_context():
        return db.session.query(TransferLog).filter_by(**filters).order_by(TransferLog.created_at).all()


# ---------------------------------------------------------------- monitor module

def test_handle_reports_resource_numbers():
    h = monitor.begin()
    out = h.end()
    assert set(out) == {"cpu_avg", "cpu_peak", "ram_proc_mb_peak", "ram_system_percent", "concurrent_active"}
    assert out["ram_proc_mb_peak"] > 0
    assert 0 <= out["cpu_avg"] <= 100
    assert out["concurrent_active"] == 1


def test_end_is_idempotent_and_releases_the_slot():
    before = monitor.active_count()
    h = monitor.begin()
    assert monitor.active_count() == before + 1
    first = h.end()
    assert h.end() == first
    assert monitor.active_count() == before


def test_concurrency_peak_is_tracked_for_both_transfers():
    a = monitor.begin()
    b = monitor.begin()
    assert monitor.active_count() == 2
    assert a.end()["concurrent_active"] == 2
    assert b.end()["concurrent_active"] == 2
    c = monitor.begin()
    assert c.end()["concurrent_active"] == 1


def test_samples_are_shared_with_every_active_transfer():
    a = monitor.begin()
    b = monitor.begin()
    for _ in range(3):
        monitor.sample_once()
    assert len(a.cpu) >= 3 and len(b.cpu) >= 3
    a.end()
    b.end()


def test_experiment_state():
    monitor.set_experiment("Test 1", "5 GHz")
    assert monitor.get_experiment() == {"label": "Test 1", "networkNote": "5 GHz"}
    monitor.set_experiment("", "")
    assert monitor.get_experiment() == {"label": None, "networkNote": None}


# ---------------------------------------------------------------- upload and download rows carry the metrics

def test_upload_log_has_resource_metrics(app, alex):
    upload(alex, "a.pdf", PDF)
    log = all_logs(app, type="upload", user_id="u2")[0]
    assert log.cpu_avg is not None and log.cpu_peak >= log.cpu_avg
    assert log.ram_proc_mb_peak > 0
    assert log.ram_system_percent is not None
    assert log.concurrent_active == 1
    assert log.buffer_kb == 256


def test_failed_upload_also_has_metrics_and_releases_slot(app, alex):
    before = monitor.active_count()
    r = upload(alex, "a.pdf", b"not a pdf at all, sorry", content_length=None)
    assert r.status_code == 400
    log = all_logs(app, type="upload", user_id="u2")[0]
    assert log.status == "failed"
    assert log.ram_proc_mb_peak > 0
    assert monitor.active_count() == before


def test_download_log_has_metrics(app, alex, jamie):
    fid = upload(alex, "a.pdf", PDF).get_json()["file"]["id"]
    assert jamie.get(f"/api/files/{fid}/download").data == PDF
    log = all_logs(app, type="download", user_id="u3")[0]
    assert log.status == "completed"
    assert log.ram_proc_mb_peak > 0 and log.cpu_avg is not None
    assert log.concurrent_active == 1
    assert monitor.active_count() == 0


def test_admin_buffer_size_is_stored_per_transfer(app, student):
    upload(student, "a.pdf", PDF, bufferKb=64)
    upload(student, "b.pdf", PDF, bufferKb=1024)
    sizes = [l.buffer_kb for l in all_logs(app, type="upload", user_id="u1")]
    assert sizes == [64, 1024]


# ---------------------------------------------------------------- experiment label and note

def test_admin_sets_experiment_and_it_applies_to_everyone(app, student, alex):
    r = student.request("PUT", "/api/metrics/experiment", json={"label": "Test 5", "networkNote": "phone hotspot, 2 m"})
    assert r.status_code == 200
    upload(alex, "a.pdf", PDF)
    log = all_logs(app, type="upload", user_id="u2")[0]
    assert (log.label, log.network_note) == ("Test 5", "phone hotspot, 2 m")
    student.request("PUT", "/api/metrics/experiment", json={"label": "", "networkNote": ""})
    upload(alex, "b.pdf", PDF)
    assert all_logs(app, type="upload", user_id="u2")[1].label is None


def test_students_cannot_set_experiment(alex):
    assert alex.request("PUT", "/api/metrics/experiment", json={"label": "x"}).status_code == 403


def test_experiment_headers_only_work_for_admins(app, student, alex):
    upload(student, "a.pdf", PDF, headers={"X-Experiment-Label": "Run A", "X-Network-Note": "wifi"})
    upload(alex, "b.pdf", PDF, headers={"X-Experiment-Label": "Hack"})
    assert all_logs(app, type="upload", user_id="u1")[0].label == "Run A"
    assert all_logs(app, type="upload", user_id="u2")[0].label is None


def test_experiment_is_readable_by_logged_in_users(alex, api):
    assert alex.get("/api/metrics/experiment").status_code == 200
    assert api.get("/api/metrics/experiment").status_code == 401


# ---------------------------------------------------------------- history

def test_history_lists_only_own_rows_newest_first(alex, jamie):
    upload(alex, "one.pdf", PDF)
    upload(alex, "two.pdf", PDF)
    upload(jamie, "other.pdf", PDF)
    body = alex.get("/api/history").get_json()
    assert body["total"] == 2
    assert [i["name"] for i in body["items"]] == ["two.pdf", "one.pdf"]
    item = body["items"][0]
    assert item["type"] == "upload" and item["status"] == "completed"
    assert item["seconds"] is not None and item["size"] == len(PDF)
    assert item["userId"] == "u2" and len(item["date"]) == 10
    for key in ("speedMBps", "bufferKb", "cpuAvg", "ramProcMbPeak", "serverMode", "clientDevice", "writeSeconds"):
        assert key in item


def test_history_filters_and_paging(alex, jamie):
    fid = upload(jamie, "j.pdf", PDF).get_json()["file"]["id"]
    assert alex.get(f"/api/files/{fid}/download").data == PDF
    upload(alex, "bad.pdf", b"nope nope nope nope nope")  # failed
    upload(alex, "good.pdf", PDF)
    assert alex.get("/api/history?type=download").get_json()["total"] == 1
    assert alex.get("/api/history?status=failed").get_json()["total"] == 1
    assert alex.get("/api/history?type=upload&status=completed").get_json()["total"] == 1
    page = alex.get("/api/history?perPage=2&page=2").get_json()
    assert page["total"] == 3 and len(page["items"]) == 1 and page["perPage"] == 2
    assert alex.get("/api/history?type=bogus").status_code == 400
    assert alex.get("/api/history?status=bogus").status_code == 400


def test_history_needs_login(api):
    assert api.get("/api/history").status_code == 401
    assert api.get("/api/history/export.csv").status_code == 401


def test_failed_transfer_is_visible_in_history_with_reason(alex):
    upload(alex, "bad.pdf", b"nope nope nope nope nope")
    item = alex.get("/api/history").get_json()["items"][0]
    assert item["status"] == "failed" and "match" in item["error"]


# ---------------------------------------------------------------- client timing

def test_client_timing_is_stored_and_preferred_for_display(alex):
    log_id = upload(alex, "a.pdf", PDF).get_json()["logId"]
    r = alex.post(f"/api/history/{log_id}/client-timing", json={"clientSeconds": 2.5, "clientDevice": "mobile"})
    assert r.status_code == 200
    item = alex.get("/api/history").get_json()["items"][0]
    assert item["clientSeconds"] == 2.5 and item["seconds"] == 2.5
    assert item["clientDevice"] == "mobile"
    assert item["serverSeconds"] is not None


def test_client_timing_validation(alex):
    log_id = upload(alex, "a.pdf", PDF).get_json()["logId"]
    url = f"/api/history/{log_id}/client-timing"
    for bad in (0, -1, 99999999, "5", None, True):
        assert alex.post(url, json={"clientSeconds": bad}).status_code == 400
    assert alex.post(url, json={}).status_code == 400


def test_client_timing_only_for_own_rows(alex, jamie):
    log_id = upload(alex, "a.pdf", PDF).get_json()["logId"]
    assert jamie.post(f"/api/history/{log_id}/client-timing", json={"clientSeconds": 1}).status_code == 404
    assert alex.post("/api/history/missing/client-timing", json={"clientSeconds": 1}).status_code == 404


def test_transfer_list_uses_client_seconds_when_reported(alex, jamie):
    r = send_file(alex, "u3")
    alex.post(f"/api/history/{r.get_json()['logId']}/client-timing", json={"clientSeconds": 7})
    assert jamie.get("/api/transfers?box=received").get_json()["items"][0]["seconds"] == 7


# ---------------------------------------------------------------- live metrics

def test_live_metrics_shape(alex):
    body = alex.get("/api/metrics/live").get_json()
    cur = body["current"]
    assert 0 <= cur["cpu"] <= 100 and 0 <= cur["ramPercent"] <= 100
    assert cur["procMb"] > 0 and cur["cpuCount"] >= 1 and cur["memoryTotalBytes"] > 0
    assert isinstance(body["samples"], list)
    assert body["serverMode"] == "waitress" and body["windowSeconds"] == 300


def test_live_metrics_hide_disk_and_network_from_students(student, alex):
    assert "system" not in alex.get("/api/metrics/live").get_json()
    system = student.get("/api/metrics/live").get_json()["system"]
    assert system["diskFreeBytes"] > 0 and "netBytesSent" in system and "netBytesRecv" in system


def test_live_metrics_need_login(api):
    assert api.get("/api/metrics/live").status_code == 401


def test_sampler_thread_fills_the_graph_buffer(alex, monkeypatch):
    monitor.configure(enabled=True)
    try:
        monitor.ensure_running()
        deadline = time.time() + 5
        while not monitor.live_samples() and time.time() < deadline:
            time.sleep(0.1)
        samples = alex.get("/api/metrics/live").get_json()["samples"]
        assert samples and {"t", "cpu", "ramPercent", "procMb", "active"} <= set(samples[0])
    finally:
        monitor.configure(enabled=False)


# ---------------------------------------------------------------- summary

def seed_logs(app, rows):
    with app.app_context():
        for r in rows:
            base = dict(user_id="u2", file_name="x.pdf", type="upload", status="completed", size=10 * 1024 * 1024,
                        bytes_transferred=10 * 1024 * 1024, buffer_kb=256, server_seconds=2.0, write_seconds=0.5,
                        hash_seconds=0.3, cpu_avg=20.0, cpu_peak=40.0, ram_proc_mb_peak=100.0,
                        concurrent_active=1, client_device="desktop", server_mode="stream", label="Test 1")
            base.update(r)
            db.session.add(TransferLog(**base))
        db.session.commit()


def test_summary_by_size_computes_speed_and_success_rate(app, alex):
    mb = 1024 * 1024
    seed_logs(app, [
        dict(size=mb, bytes_transferred=mb, server_seconds=0.5),
        dict(size=mb, bytes_transferred=mb, server_seconds=1.0),
        dict(size=10 * mb, bytes_transferred=10 * mb, server_seconds=2.0),
        dict(size=10 * mb, bytes_transferred=0, server_seconds=None, status="failed", error="lost"),
    ])
    body = alex.get("/api/metrics/summary?groupBy=size").get_json()
    groups = {g["group"]: g for g in body["items"]}
    assert list(groups) == ["≤ 1 MB", "≤ 10 MB"]  # sorted by size
    one = groups["≤ 1 MB"]
    assert one["count"] == 2 and one["avgSpeedMBps"] == 1.5 and one["medianSpeedMBps"] == 1.5
    assert one["successRate"] == 100.0
    ten = groups["≤ 10 MB"]
    assert ten["count"] == 2 and ten["failed"] == 1 and ten["successRate"] == 50.0
    assert ten["avgSpeedMBps"] == 5.0 and ten["avgCpu"] == 20.0 and ten["avgRamProcMb"] == 100.0
    assert body["overall"]["count"] == 4 and body["serverModes"] == ["stream"] and body["note"] is None


def test_summary_other_groupings(app, alex):
    seed_logs(app, [
        dict(buffer_kb=64, label="A", client_device="desktop", concurrent_active=1),
        dict(buffer_kb=1024, label="B", client_device="mobile", concurrent_active=2),
        dict(buffer_kb=256, label="B", client_device="mobile", concurrent_active=2),
    ])
    get = lambda g: [x["group"] for x in alex.get(f"/api/metrics/summary?groupBy={g}").get_json()["items"]]
    assert get("buffer") == ["64 KB", "256 KB", "1024 KB"]
    assert get("concurrency") == ["1 at once", "2 at once"]
    assert get("device") == ["desktop", "mobile"]
    assert get("label") == ["A", "B"]


def test_summary_defaults_to_uploads_and_supports_downloads(app, alex):
    seed_logs(app, [dict(type="upload"), dict(type="download", server_seconds=1.0)])
    assert alex.get("/api/metrics/summary").get_json()["overall"]["count"] == 1
    assert alex.get("/api/metrics/summary?type=download").get_json()["overall"]["count"] == 1


def test_summary_filters_by_label(app, alex):
    seed_logs(app, [dict(label="Test 1"), dict(label="Test 2"), dict(label="Test 2")])
    assert alex.get("/api/metrics/summary?label=Test 2").get_json()["overall"]["count"] == 2


def test_summary_warns_about_waitress_rows(app, alex):
    seed_logs(app, [dict(server_mode="waitress")])
    assert "--stream" in alex.get("/api/metrics/summary").get_json()["note"]


def test_summary_scope_is_private_by_default_and_all_is_admin_only(app, alex, jamie, student):
    seed_logs(app, [dict(user_id="u2"), dict(user_id="u3")])
    assert alex.get("/api/metrics/summary").get_json()["overall"]["count"] == 1
    assert jamie.get("/api/metrics/summary").get_json()["overall"]["count"] == 1
    assert alex.get("/api/metrics/summary?scope=all").status_code == 403
    assert student.get("/api/metrics/summary?scope=all").get_json()["overall"]["count"] == 2


def test_summary_validation_and_empty(alex, api):
    assert alex.get("/api/metrics/summary?groupBy=nope").status_code == 400
    assert alex.get("/api/metrics/summary?scope=nope").status_code == 400
    body = alex.get("/api/metrics/summary").get_json()
    assert body["items"] == [] and body["overall"]["count"] == 0 and body["overall"]["successRate"] is None
    assert api.get("/api/metrics/summary").status_code == 401


# ---------------------------------------------------------------- csv export

def read_csv(resp):
    text = resp.data.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def test_csv_export_has_every_column_and_only_own_rows(alex, jamie):
    upload(alex, "mine.pdf", PDF)
    upload(jamie, "theirs.pdf", PDF)
    r = alex.get("/api/history/export.csv")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    assert "attachment" in r.headers["Content-Disposition"]
    rows = read_csv(r)
    assert [row["file_name"] for row in rows] == ["mine.pdf"]
    assert rows[0]["buffer_kb"] == "256" and rows[0]["status"] == "completed"
    assert rows[0]["created_at"].endswith("Z")
    assert {"cpu_avg", "ram_proc_mb_peak", "concurrent_active", "label", "sha256_verified"} <= set(rows[0])


def test_csv_export_neutralizes_formula_injection(alex):
    upload(alex, "=HYPERLINK(1).pdf", PDF)
    assert read_csv(alex.get("/api/history/export.csv"))[0]["file_name"].startswith("'=")
