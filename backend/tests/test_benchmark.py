"""The benchmark tool run against a real HTTP server (a threaded Werkzeug server inside the test)."""
import csv
import importlib.util
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.extensions import db
from app.models import File, TransferLog

TOOL = Path(__file__).resolve().parents[2] / "tools" / "benchmark.py"
spec = importlib.util.spec_from_file_location("filego_benchmark", TOOL)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


@pytest.fixture()
def server(app):
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    t.join(timeout=5)


@pytest.fixture()
def run(server, tmp_path):
    def _run(*extra, user="student", password="demo123"):
        out = tmp_path / "results"
        code = bench.main(["--server", server, "--user", user, "--password", password, "--out", str(out), *extra])
        files = sorted(out.glob("*.csv")) if out.exists() else []
        rows = []
        if files:
            with open(files[-1], newline="", encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh))
        return code, rows

    return _run


def file_count(app):
    with app.app_context():
        return db.session.scalar(db.select(db.func.count(File.id)))


def test_stats_line():
    s = bench.stats_line([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert s["min"] == 1 and s["max"] == 10 and s["mean"] == 5.5 and s["median"] == 5.5
    assert s["p95"] == 10 and round(s["stdev"], 3) == 3.028
    assert bench.stats_line([]) is None and bench.stats_line([None]) is None
    assert bench.stats_line([4])["stdev"] == 0.0


def test_make_test_file_exact_size_and_pdf_header(tmp_path):
    p = bench.make_test_file(tmp_path, 12345, "x.pdf")
    assert p.stat().st_size == 12345 and p.read_bytes().startswith(b"%PDF-")


def test_sizes_test_records_warmup_and_cleans_up(app, run):
    before = file_count(app)
    code, rows = run("--test", "sizes", "--sizes", "0.1,0.25", "--repeat", "2", "--label", "Test 1", "--note", "loopback")
    assert code == 0
    assert len(rows) == 2 * 3 * 2  # sizes x (warm-up + 2 runs) x (upload + download)
    assert sum(r["warmup"] == "True" for r in rows) == 4
    assert all(r["ok"] == "True" and r["sha256_ok"] == "True" for r in rows)
    assert all(r["label"] == "Test 1" and r["network_note"] == "loopback" for r in rows)
    up = next(r for r in rows if r["operation"] == "upload" and r["warmup"] == "False")
    assert float(up["seconds"]) > 0 and float(up["throughput_mbps"]) > 0 and up["server_seconds"] != ""
    assert file_count(app) == before  # nothing left behind


def test_server_sees_tool_rows_with_labels(app, run):
    run("--test", "repeat", "--size-mb", "0.1", "--repeat", "1", "--label", "Test 4")
    with app.app_context():
        logs = db.session.scalars(db.select(TransferLog)).all()
    assert logs and all(l.client_device == "tool" for l in logs)
    assert {l.label for l in logs} == {"Test 4 (warm-up)", "Test 4"}  # warm-up rows are tagged apart
    assert any(l.client_seconds for l in logs if l.type == "upload")


def test_buffers_test_covers_all_three_sizes(run):
    code, rows = run("--test", "buffers", "--size-mb", "0.3", "--repeat", "1")
    assert code == 0
    assert {r["buffer_kb"] for r in rows} == {"64", "256", "1024"}
    server_rows = [r for r in rows if r["operation"] == "upload"]
    assert all(r["server_seconds"] != "" for r in server_rows)


def test_buffers_test_needs_admin(run):
    code, rows = run("--test", "buffers", "--size-mb", "0.1", user="alex")
    assert code == 2 and rows == []


def test_concurrency_test_one_vs_two(app, run):
    before = file_count(app)
    code, rows = run("--test", "concurrency", "--size-mb", "0.3", "--repeat", "2")
    assert code == 0
    groups = {(r["group"], r["operation"]) for r in rows}
    assert {("1 at once", "upload"), ("2 at once", "upload"), ("2 at once", "upload-total")} <= groups
    assert sum(1 for r in rows if r["group"] == "2 at once" and r["operation"] == "upload") == 6
    assert file_count(app) == before


def test_repeat_test_success_rate_and_integrity(run):
    code, rows = run("--test", "repeat", "--size-mb", "0.2", "--repeat", "4")
    assert code == 0
    measured = [r for r in rows if r["warmup"] == "False"]
    assert len(measured) == 8 and all(r["sha256_ok"] == "True" for r in measured)
    summary = bench.summarize(rows)
    assert all(s["success_rate"] == 100.0 and s["runs"] == 4 for s in summary)  # warm-up excluded


def test_integrity_failure_is_detected(server, tmp_path, monkeypatch):
    """A download whose bytes differ from the stored SHA-256 must count as failed."""
    client = bench.Client(server, "student", "demo123")
    path = bench.make_test_file(tmp_path, 5000, "b.pdf")
    sha = bench.sha256_file(path)
    up = client.upload(path, sha)
    assert up["ok"]
    good = client.download(up["file_id"], sha, 5000)
    assert good["ok"] and good["sha_ok"]
    bad = client.download(up["file_id"], "0" * 64, 5000)
    assert not bad["ok"] and not bad["sha_ok"]
    client.delete_file(up["file_id"])


def test_upload_with_wrong_expected_hash_is_rejected(server, tmp_path):
    client = bench.Client(server, "student", "demo123")
    path = bench.make_test_file(tmp_path, 5000, "b.pdf")
    res = client.upload(path, "f" * 64)
    assert not res["ok"] and res["file_id"] is None


def test_response_test(run):
    code, rows = run("--test", "response", "--count", "5")
    assert code == 0
    assert {r["operation"] for r in rows} == {"ping", "small API call (auth/me)"}
    assert all(float(r["response_ms"]) > 0 for r in rows)


def test_bad_login_and_unreachable_server(run):
    assert run("--test", "repeat", user="alex", password="wrong-password")[0] == 2
    assert bench.main(["--server", "http://127.0.0.1:1", "--user", "a", "--password", "b", "--test", "response"]) == 2


@pytest.mark.parametrize("args", [["--sizes", "abc"], ["--sizes", "0"], ["--sizes", "500"], ["--buffers", "128"], ["--repeat", "0"], ["--size-mb", "0"]])
def test_bad_arguments_are_rejected(args):
    with pytest.raises(SystemExit):
        bench.parse_args(["--user", "u", "--password", "p", "--test", "sizes", *args])
