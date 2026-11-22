"""Live server metrics and per-transfer resource sampling (CMSC310 measurements).

A background sampler thread reads system CPU, system RAM and this process's RSS:
  - every 0.1 s while at least one transfer is active (each active transfer collects the samples),
  - every 1 s when idle (feeds the live dashboard graph).
Only this thread calls psutil.cpu_percent(), so the readings are not disturbed by request threads.
"""
import threading
import time
from collections import deque

import psutil

RING_SECONDS = 300  # live graph keeps the last 5 minutes
ACTIVE_INTERVAL = 0.1
IDLE_INTERVAL = 1.0
STALE_AFTER = 3600  # a handle nobody closed is dropped after an hour

_lock = threading.Lock()
_active = {}  # id -> Handle
_ring = deque(maxlen=RING_SECONDS)
_thread = None
_enabled = True
_proc = psutil.Process()
_next_id = 0

# Experiment label and network note applied to every transfer while set (see admin endpoint).
_experiment = {"label": None, "networkNote": None}


def configure(enabled):
    """Tests turn the thread off and sample directly."""
    global _enabled
    _enabled = enabled


def running():
    return _thread is not None and _thread.is_alive()


def _read():
    return {
        "cpu": psutil.cpu_percent(interval=None),
        "ramPercent": psutil.virtual_memory().percent,
        "procMb": _proc.memory_info().rss / (1024 * 1024),
    }


class Handle:
    """Collects samples for one transfer between begin() and end()."""

    def __init__(self, hid):
        self.id = hid
        self.started = time.time()
        self.cpu = []
        self.proc_mb = []
        self.ram_percent = None
        self.peak_concurrent = 1
        self._result = None

    def _add(self, s):
        self.cpu.append(s["cpu"])
        self.proc_mb.append(s["procMb"])
        self.ram_percent = s["ramPercent"]

    def end(self):
        """Stop sampling and return the metrics. Safe to call more than once."""
        with _lock:
            if self._result is not None:
                return dict(self._result)
            _active.pop(self.id, None)
        if not self.cpu:
            # Shorter than one sampler tick: reuse the sampler's latest reading. A fresh
            # cpu_percent() call here would cover only a few milliseconds and read 0.
            if running():
                cur = current()
                self._add({"cpu": cur["cpu"], "ramPercent": cur["ramPercent"], "procMb": cur["procMb"]})
            else:
                with _lock:
                    self._add(_read())
        cpu = self.cpu or [0.0]
        self._result = {
            "cpu_avg": round(sum(cpu) / len(cpu), 2),
            "cpu_peak": round(max(cpu), 2),
            "ram_proc_mb_peak": round(max(self.proc_mb), 2),
            "ram_system_percent": self.ram_percent,
            "concurrent_active": self.peak_concurrent,
        }
        return dict(self._result)


def begin():
    """Register a starting transfer and return its handle."""
    global _next_id
    ensure_running()
    now = time.time()
    with _lock:
        for hid in [h.id for h in _active.values() if now - h.started > STALE_AFTER]:
            _active.pop(hid, None)
        _next_id += 1
        h = Handle(_next_id)
        _active[h.id] = h
        n = len(_active)
        for other in _active.values():
            other.peak_concurrent = max(other.peak_concurrent, n)
    if not running():
        with _lock:
            h._add(_read())
    return h


def active_count():
    with _lock:
        return len(_active)


def sample_once(ring_bucket=None):
    """Take one reading, give it to every active transfer, and return it."""
    s = _read()
    with _lock:
        for h in _active.values():
            h._add(s)
        s["active"] = len(_active)
    return s


def _loop():
    bucket = []
    last_push = 0.0
    while True:
        try:
            s = sample_once()
            bucket.append(s)
            now = time.time()
            if now - last_push >= 1.0:
                n = len(bucket)
                point = {
                    "t": int(now * 1000),
                    "cpu": round(sum(b["cpu"] for b in bucket) / n, 1),
                    "ramPercent": s["ramPercent"],
                    "procMb": round(s["procMb"], 1),
                    "active": max(b["active"] for b in bucket),
                }
                with _lock:
                    _ring.append(point)
                bucket, last_push = [], now
        except Exception:  # noqa: BLE001 - the sampler must never die
            pass
        time.sleep(ACTIVE_INTERVAL if active_count() else IDLE_INTERVAL)


def ensure_running():
    global _thread
    if not _enabled or running():
        return
    with _lock:
        if running():
            return
        psutil.cpu_percent(interval=None)  # prime: the first call always returns 0
        _thread = threading.Thread(target=_loop, name="filego-sampler", daemon=True)
        _thread.start()


def live_samples():
    with _lock:
        return list(_ring)


def current():
    """One fresh reading for the live panel (does not disturb the sampler's CPU window)."""
    with _lock:
        last = _ring[-1] if _ring else None
    if last:
        return {"cpu": last["cpu"], "ramPercent": last["ramPercent"], "procMb": last["procMb"], "active": active_count()}
    s = _read()
    return {"cpu": s["cpu"], "ramPercent": s["ramPercent"], "procMb": round(s["procMb"], 1), "active": active_count()}


def get_experiment():
    return dict(_experiment)


def set_experiment(label, note):
    _experiment["label"] = label or None
    _experiment["networkNote"] = note or None
