import threading
import time


class AttemptLimiter:
    """Small in-memory sliding-window counter. Resets when the server restarts."""

    def __init__(self):
        self._hits = {}
        self._lock = threading.Lock()

    def _prune(self, key, window, now):
        hits = [t for t in self._hits.get(key, []) if now - t < window]
        if hits:
            self._hits[key] = hits
        else:
            self._hits.pop(key, None)
        return hits

    def count(self, key, window):
        with self._lock:
            return len(self._prune(key, window, time.monotonic()))

    def add(self, key, window):
        with self._lock:
            now = time.monotonic()
            hits = self._prune(key, window, now)
            hits.append(now)
            self._hits[key] = hits

    def clear(self, key):
        with self._lock:
            self._hits.pop(key, None)
