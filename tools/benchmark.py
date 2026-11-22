#!/usr/bin/env python3
"""FileGo benchmark tool: repeatable transfer experiments (Tests 1 to 5 of the evaluation plan).

Uploads and downloads generated random files through the real HTTP API, checks SHA-256 in both
directions, and writes every measurement to a CSV in tools/results/ plus a summary table.
The transfers also appear in the server's own history (client device "tool"), so the Performance
page shows them next to the numbers printed here.

Examples (run from the project folder; the server should be started with `python run.py --stream`):

  Test 1  python tools/benchmark.py --server http://192.168.43.10:5000 --user student --password demo123 \
              --test sizes --sizes 1,10,50 --repeat 5 --label "Test 1" --note "phone hotspot"
  Test 2  python tools/benchmark.py ... --test buffers --size-mb 10 --repeat 5 --label "Test 2"   (admin only)
  Test 3  python tools/benchmark.py ... --test concurrency --size-mb 10 --repeat 5 --label "Test 3"
  Test 4  python tools/benchmark.py ... --test repeat --size-mb 5 --repeat 20 --label "Test 4"
  Test 5  python tools/benchmark.py ... --test response --count 200 --label "Test 5 laptop"
          (for the phone, repeat Tests 1 or 5 from the browser or from Termux with the same label scheme)

The first transfer of every batch is a warm-up: it is performed but left out of the statistics.
Only the standard library and `requests` are needed.
"""
import argparse
import csv
import hashlib
import os
import platform
import statistics
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import requests

MB = 1024 * 1024
CHUNK = 256 * 1024
BUFFERS_KB = (64, 256, 1024)
TOOL_VERSION = "1.0"
RESULT_DIR = Path(__file__).resolve().parent / "results"

FIELDS = [
    "timestamp", "test", "operation", "group", "run", "warmup", "size_bytes", "buffer_kb", "threads",
    "ok", "error", "seconds", "throughput_mbps", "sha256_ok", "response_ms",
    "server_seconds", "write_seconds", "hash_seconds", "server_cpu_avg", "server_cpu_peak",
    "server_ram_proc_mb", "server_mode", "label", "network_note", "client_os", "python",
]


class BenchError(Exception):
    pass


# ------------------------------------------------------------------ small helpers

def stats_line(values):
    """min, mean, median, p95 and standard deviation of a list of numbers."""
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    p95 = v[min(len(v) - 1, max(0, int(round(0.95 * len(v) + 0.5)) - 1))]
    return {
        "n": len(v), "min": v[0], "mean": statistics.fmean(v), "median": statistics.median(v),
        "p95": p95, "stdev": statistics.stdev(v) if len(v) > 1 else 0.0, "max": v[-1],
    }


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def make_test_file(directory, size_bytes, name):
    """A random file that passes the server's PDF check (header bytes), of exactly size_bytes."""
    path = Path(directory) / name
    header = b"%PDF-1.4\n"
    with open(path, "wb") as fh:
        fh.write(header)
        left = max(0, size_bytes - len(header))
        while left > 0:
            n = min(left, MB)
            fh.write(os.urandom(n))
            left -= n
    return path


class Client:
    """One logged-in session. Each thread of a concurrency test gets its own."""

    def __init__(self, server, username, password, label=None, note=None):
        self.server = server.rstrip("/")
        self.http = requests.Session()
        self.label, self.note = label, note
        r = self.http.post(self.server + "/api/auth/login", json={"username": username, "password": password}, timeout=30)
        if r.status_code != 200:
            raise BenchError(f"Login failed ({r.status_code}): {_message(r)}")
        body = r.json()
        self.csrf = body["csrfToken"]
        self.role = body["user"]["role"]
        self.user_id = body["user"]["id"]

    def headers(self, extra=None, label_suffix=""):
        h = {"X-CSRF-Token": self.csrf, "X-Client-Device": "tool"}
        if self.role == "admin":  # only administrators may tag transfers with an experiment label
            if self.label:
                h["X-Experiment-Label"] = (self.label + label_suffix)[:80]
            if self.note:
                h["X-Network-Note"] = self.note[:255]
        if extra:
            h.update(extra)
        return h

    def get_json(self, path, **kw):
        r = self.http.get(self.server + path, timeout=30, **kw)
        if r.status_code != 200:
            raise BenchError(f"GET {path} failed ({r.status_code}): {_message(r)}")
        return r.json()

    def upload(self, path, sha, buffer_kb=None, title="benchmark", warmup=False):
        params = {"title": title, "subject": "General", "category": "Other", "visibility": "private"}
        if buffer_kb and self.role == "admin":
            params["bufferKb"] = buffer_kb
        size = os.path.getsize(path)
        headers = self.headers(
            {"Content-Type": "application/octet-stream", "X-File-Name": "benchmark.pdf", "X-Expected-SHA256": sha,
             "Content-Length": str(size)},
            " (warm-up)" if warmup else "",
        )
        started = time.perf_counter()
        with open(path, "rb") as fh:
            r = self.http.post(self.server + "/api/files", params=params, data=fh, headers=headers, timeout=3600)
        seconds = time.perf_counter() - started
        if r.status_code != 201:
            return {"ok": False, "error": f"{r.status_code} {_message(r)}", "seconds": seconds, "file_id": None, "log_id": None}
        body = r.json()
        # Tell the server how long the upload took on this side (shown beside its own measurement).
        try:
            self.http.post(
                f"{self.server}/api/history/{body['logId']}/client-timing",
                json={"clientSeconds": max(seconds, 1e-6), "clientDevice": "tool"},
                headers={"X-CSRF-Token": self.csrf}, timeout=30,
            )
        except requests.RequestException:
            pass
        return {"ok": True, "error": "", "seconds": seconds, "file_id": body["file"]["id"], "log_id": body["logId"]}

    def download(self, file_id, expected_sha, size, buffer_kb=None, warmup=False):
        params = {"bufferKb": buffer_kb} if buffer_kb and self.role == "admin" else {}
        h = hashlib.sha256()
        got = 0
        started = time.perf_counter()
        try:
            with self.http.get(f"{self.server}/api/files/{file_id}/download", params=params,
                               headers=self.headers(label_suffix=" (warm-up)" if warmup else ""), stream=True, timeout=3600) as r:
                if r.status_code != 200:
                    return {"ok": False, "error": f"{r.status_code} {_message(r)}", "seconds": time.perf_counter() - started, "sha_ok": False}
                header_sha = r.headers.get("X-File-SHA256")
                for chunk in r.iter_content(CHUNK):
                    h.update(chunk)
                    got += len(chunk)
        except requests.RequestException as e:
            return {"ok": False, "error": f"connection: {e.__class__.__name__}", "seconds": time.perf_counter() - started, "sha_ok": False}
        seconds = time.perf_counter() - started
        digest = h.hexdigest()
        sha_ok = digest == expected_sha and header_sha == expected_sha and got == size
        return {"ok": sha_ok, "error": "" if sha_ok else "integrity check failed", "seconds": seconds, "sha_ok": sha_ok}

    def latest_log(self, type_):
        items = self.get_json("/api/history", params={"type": type_, "perPage": 1}).get("items", [])
        return items[0] if items else None

    def log_by_id(self, log_id):
        # The upload response gives the log id; find it in the newest rows.
        for row in self.get_json("/api/history", params={"type": "upload", "perPage": 20}).get("items", []):
            if row["id"] == log_id:
                return row
        return None

    def delete_file(self, file_id):
        try:
            self.http.delete(f"{self.server}/api/files/{file_id}", headers={"X-CSRF-Token": self.csrf}, timeout=30)
        except requests.RequestException:
            pass

    def ping(self):
        started = time.perf_counter()
        r = self.http.get(self.server + "/api/ping", timeout=30)
        return (time.perf_counter() - started) * 1000, r.status_code == 200

    def small_call(self):
        started = time.perf_counter()
        r = self.http.get(self.server + "/api/auth/me", timeout=30)
        return (time.perf_counter() - started) * 1000, r.status_code == 200


def _message(r):
    try:
        return r.json()["error"]["message"]
    except Exception:  # noqa: BLE001
        return (r.text or "")[:120]


# ------------------------------------------------------------------ recording

class Recorder:
    def __init__(self, args, server_mode):
        self.rows = []
        self.args = args
        self.server_mode = server_mode
        self.lock = threading.Lock()

    def add(self, **kw):
        row = {k: "" for k in FIELDS}
        row.update(
            timestamp=datetime.now().isoformat(timespec="seconds"), server_mode=self.server_mode,
            label=self.args.label or "", network_note=self.args.note or "",
            client_os=f"{platform.system()} {platform.release()}", python=platform.python_version(),
        )
        row.update(kw)
        if row["seconds"] != "" and row["size_bytes"] not in ("", 0) and row["ok"]:
            row["throughput_mbps"] = round(row["size_bytes"] / MB / row["seconds"], 4)
        with self.lock:
            self.rows.append(row)
        return row

    def add_server_side(self, row, log):
        """Copy the server's own measurements for this transfer into the row."""
        if not log:
            return
        row.update(
            server_seconds=log.get("serverSeconds") if log.get("serverSeconds") is not None else "",
            write_seconds=log.get("writeSeconds") if log.get("writeSeconds") is not None else "",
            hash_seconds=log.get("hashSeconds") if log.get("hashSeconds") is not None else "",
            server_cpu_avg=log.get("cpuAvg") if log.get("cpuAvg") is not None else "",
            server_cpu_peak=log.get("cpuPeak") if log.get("cpuPeak") is not None else "",
            server_ram_proc_mb=log.get("ramProcMbPeak") if log.get("ramProcMbPeak") is not None else "",
            response_ms=log.get("responseMs") if log.get("responseMs") is not None else "",
        )


# ------------------------------------------------------------------ tests

def _one_cycle(client, rec, test, group, run, path, sha, size, buffer_kb, warmup, uploaded):
    """One upload followed by one download of the same file. Returns True when both succeeded."""
    up = client.upload(path, sha, buffer_kb, warmup=warmup)
    row = rec.add(test=test, operation="upload", group=group, run=run, warmup=warmup, size_bytes=size,
                  buffer_kb=buffer_kb or "", threads=1, ok=up["ok"], error=up["error"], seconds=round(up["seconds"], 6),
                  sha256_ok=up["ok"])
    if up["ok"]:
        uploaded.append(up["file_id"])
        rec.add_server_side(row, client.log_by_id(up["log_id"]))
    if not up["ok"]:
        return False
    dn = client.download(up["file_id"], sha, size, buffer_kb, warmup=warmup)
    row = rec.add(test=test, operation="download", group=group, run=run, warmup=warmup, size_bytes=size,
                  buffer_kb=buffer_kb or "", threads=1, ok=dn["ok"], error=dn["error"], seconds=round(dn["seconds"], 6),
                  sha256_ok=dn["sha_ok"])
    rec.add_server_side(row, client.latest_log("download"))
    return dn["ok"]


def test_sizes(client, rec, args, tmp, uploaded):
    for mb in args.sizes:
        size = int(mb * MB)
        path = make_test_file(tmp, size, f"bench_{mb}mb.pdf")
        sha = sha256_file(path)
        print(f"  file size {mb:g} MB ...")
        for run in range(args.repeat + 1):  # run 0 is the warm-up
            _one_cycle(client, rec, "sizes", f"{mb:g} MB", run, path, sha, size, args.buffer, run == 0, uploaded)


def test_buffers(client, rec, args, tmp, uploaded):
    if client.role != "admin":
        raise BenchError("The buffer test needs an administrator account (only admins may choose the buffer size).")
    size = int(args.size_mb * MB)
    path = make_test_file(tmp, size, "bench_buffer.pdf")
    sha = sha256_file(path)
    for kb in args.buffers:
        print(f"  buffer {kb} KB ...")
        for run in range(args.repeat + 1):
            _one_cycle(client, rec, "buffers", f"{kb} KB", run, path, sha, size, kb, run == 0, uploaded)


def test_concurrency(client, rec, args, tmp, uploaded, make_client):
    size = int(args.size_mb * MB)
    path = make_test_file(tmp, size, "bench_conc.pdf")
    sha = sha256_file(path)
    for n in (1, 2):
        print(f"  {n} simultaneous upload{'s' if n > 1 else ''} ...")
        clients = [client] + [make_client() for _ in range(n - 1)]
        for run in range(args.repeat + 1):
            warm = run == 0
            results = [None] * n
            barrier = threading.Barrier(n)

            def work(i):
                barrier.wait()
                results[i] = clients[i].upload(path, sha, args.buffer, warmup=warm)

            started = time.perf_counter()
            threads = [threading.Thread(target=work, args=(i,)) for i in range(n)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            wall = time.perf_counter() - started
            for i, res in enumerate(results):
                row = rec.add(test="concurrency", operation="upload", group=f"{n} at once", run=run, warmup=warm,
                              size_bytes=size, buffer_kb=args.buffer or "", threads=n, ok=res["ok"], error=res["error"],
                              seconds=round(res["seconds"], 6), sha256_ok=res["ok"])
                if res["ok"]:
                    uploaded.append(res["file_id"])
                    rec.add_server_side(row, clients[i].log_by_id(res["log_id"]))
            # Aggregate throughput: all bytes that arrived divided by the wall-clock time of the round.
            done = sum(1 for r in results if r["ok"])
            rec.add(test="concurrency", operation="upload-total", group=f"{n} at once", run=run, warmup=warm,
                    size_bytes=size * done, buffer_kb=args.buffer or "", threads=n, ok=done == n,
                    error="" if done == n else f"{n - done} failed", seconds=round(wall, 6), sha256_ok=done == n)


def test_repeat(client, rec, args, tmp, uploaded):
    size = int(args.size_mb * MB)
    path = make_test_file(tmp, size, "bench_repeat.pdf")
    sha = sha256_file(path)
    print(f"  {args.repeat} upload and download cycles of {args.size_mb:g} MB ...")
    for run in range(args.repeat + 1):
        _one_cycle(client, rec, "repeat", f"{args.size_mb:g} MB", run, path, sha, size, args.buffer, run == 0, uploaded)


def test_response(client, rec, args, tmp, uploaded):
    for name, call in (("ping", client.ping), ("small API call (auth/me)", client.small_call)):
        print(f"  {name} x {args.count} ...")
        for run in range(args.count + 1):
            try:
                ms, ok = call()
                err = ""
            except requests.RequestException as e:
                ms, ok, err = 0.0, False, e.__class__.__name__
            rec.add(test="response", operation=name, group=name, run=run, warmup=run == 0, threads=1, ok=ok, error=err,
                    seconds=round(ms / 1000, 6), response_ms=round(ms, 3), sha256_ok="")


# ------------------------------------------------------------------ report

def summarize(rows):
    """Print a table per (test, operation, group), leaving out warm-up runs. Returns the summary dicts."""
    groups = {}
    for r in rows:
        if r["warmup"] in (True, "True"):
            continue
        groups.setdefault((r["test"], r["operation"], r["group"]), []).append(r)
    out = []
    for (test, op, group), rs in groups.items():
        ok = [r for r in rs if r["ok"] in (True, "True")]
        times = [float(r["seconds"]) for r in ok if r["seconds"] != ""]
        speeds = [float(r["throughput_mbps"]) for r in ok if r["throughput_mbps"] != ""]
        cpu = [float(r["server_cpu_avg"]) for r in ok if r["server_cpu_avg"] != ""]
        ram = [float(r["server_ram_proc_mb"]) for r in ok if r["server_ram_proc_mb"] != ""]
        out.append({
            "test": test, "operation": op, "group": group, "runs": len(rs), "ok": len(ok),
            "success_rate": round(len(ok) / len(rs) * 100, 1) if rs else None,
            "integrity_ok": sum(1 for r in rs if r["sha256_ok"] in (True, "True")),
            "time": stats_line(times), "speed": stats_line(speeds),
            "cpu_avg": statistics.fmean(cpu) if cpu else None, "ram_mb": statistics.fmean(ram) if ram else None,
        })
    return out


def print_summary(summary):
    if not summary:
        print("No measurements.")
        return
    f = lambda v, d=3: "-" if v is None else f"{v:.{d}f}"
    head = f"{'test':<12}{'operation':<26}{'group':<26}{'n':>4}{'ok%':>7}  {'time s: min / mean / median / p95 / sd':<44}{'MB/s mean':>10}{'CPU%':>7}{'RAM MB':>8}"
    print("\n" + head + "\n" + "-" * len(head))
    for s in summary:
        t = s["time"]
        tt = "-" if not t else f"{t['min']:.3f} / {t['mean']:.3f} / {t['median']:.3f} / {t['p95']:.3f} / {t['stdev']:.3f}"
        sp = s["speed"]["mean"] if s["speed"] else None
        print(f"{s['test']:<12}{s['operation'][:25]:<26}{s['group']:<26}{s['runs']:>4}{f(s['success_rate'], 1):>7}  {tt:<44}{f(sp, 2):>10}{f(s['cpu_avg'], 0):>7}{f(s['ram_mb'], 0):>8}")
    print("(warm-up runs are left out of this table but kept in the CSV)")


def write_csv(rows, test, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}_{test}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:  # BOM: Excel reads UTF-8 correctly
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path


# ------------------------------------------------------------------ main

def parse_args(argv):
    p = argparse.ArgumentParser(description="FileGo transfer benchmark (Tests 1 to 5).", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--server", default="http://localhost:5000", help="server URL, e.g. http://192.168.43.10:5000")
    p.add_argument("--user", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--test", required=True, choices=["sizes", "buffers", "concurrency", "repeat", "response"])
    p.add_argument("--sizes", default="1,10,50", help="Test 1: file sizes in MB, comma separated")
    p.add_argument("--size-mb", type=float, default=10, help="Tests 2, 3 and 4: file size in MB")
    p.add_argument("--buffers", default="64,256,1024", help="Test 2: buffer sizes in KB (64, 256 and 1024 are allowed)")
    p.add_argument("--buffer", type=int, default=None, choices=BUFFERS_KB, help="buffer size in KB (administrators only; default: the server's)")
    p.add_argument("--repeat", type=int, default=5, help="measured runs per group (one extra warm-up run is added)")
    p.add_argument("--count", type=int, default=100, help="Test 5: requests per kind")
    p.add_argument("--label", default="", help="experiment label stored with every transfer (administrators)")
    p.add_argument("--note", default="", help="network conditions, e.g. 'phone hotspot 2.4GHz, laptop on AC'")
    p.add_argument("--out", default=str(RESULT_DIR), help="folder for the CSV")
    a = p.parse_args(argv)
    try:
        a.sizes = [float(x) for x in a.sizes.split(",") if x.strip()]
        a.buffers = [int(x) for x in a.buffers.split(",") if x.strip()]
    except ValueError:
        p.error("--sizes and --buffers must be comma separated numbers")
    if not a.sizes or any(not 0 < s <= 100 for s in a.sizes):
        p.error("--sizes must be between 0 and 100 MB")
    if any(b not in BUFFERS_KB for b in a.buffers):
        p.error("--buffers may only contain 64, 256 and 1024")
    if a.repeat < 1 or a.count < 1 or not 0 < a.size_mb <= 100:
        p.error("--repeat and --count must be at least 1 and --size-mb between 0 and 100")
    return a


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        client = Client(args.server, args.user, args.password, args.label, args.note)
        meta = client.get_json("/api/meta")
    except requests.RequestException:
        print(f"Cannot reach the server at {args.server}. Is it running, and is the address right?", file=sys.stderr)
        return 2
    except BenchError as e:
        print(f"Cannot start: {e}", file=sys.stderr)
        return 2
    mode = meta.get("serverMode", "unknown")
    print(f"FileGo benchmark {TOOL_VERSION} | server {args.server} ({mode} mode, {meta.get('bufferKb', '?')} KB default buffer) "
          f"| {platform.system()} {platform.release()} | Python {platform.python_version()}")
    if mode != "stream":
        print("WARNING: the server is not in --stream mode. Server time then covers disk and hashing only, "
              "not the network. Start it with: python run.py --stream")
    if args.label and client.role != "admin":
        print("Note: only administrators can tag transfers; this run is labelled in the CSV only.")

    rec = Recorder(args, mode)
    uploaded = []
    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="filego-bench-") as tmp:
            print(f"Test: {args.test}")
            if args.test == "sizes":
                test_sizes(client, rec, args, tmp, uploaded)
            elif args.test == "buffers":
                test_buffers(client, rec, args, tmp, uploaded)
            elif args.test == "concurrency":
                test_concurrency(client, rec, args, tmp, uploaded,
                                 lambda: Client(args.server, args.user, args.password, args.label, args.note))
            elif args.test == "repeat":
                test_repeat(client, rec, args, tmp, uploaded)
            else:
                test_response(client, rec, args, tmp, uploaded)
    except BenchError as e:
        print(f"Stopped: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted. Cleaning up what was uploaded.")
    finally:
        for fid in uploaded:
            client.delete_file(fid)  # the tool leaves nothing behind
        if uploaded:
            print(f"Cleaned up {len(uploaded)} uploaded test file(s).")

    path = write_csv(rec.rows, args.test, Path(args.out))
    summary = summarize(rec.rows)
    print_summary(summary)
    print(f"\nFinished in {time.perf_counter() - started:.1f} s. Raw results: {path}")
    counted = [r for r in rec.rows if r["warmup"] not in (True, "True") and r["operation"] != "upload-total"]
    failed = [r for r in counted if r["ok"] not in (True, "True")]
    if failed:
        print(f"{len(failed)} of {len(counted)} measured transfers failed (first error: {failed[0]['error']}).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
