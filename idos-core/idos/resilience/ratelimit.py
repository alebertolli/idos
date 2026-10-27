from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from idos.timezone import AR_TZ

class RateLimiter:
    def __init__(self, max_calls: int = 10, window_seconds: int = 60):
        self.max_calls = max_calls
        self.window = window_seconds
        self._calls: dict[str, list[float]] = {}

    def _now(self) -> float:
        return datetime.now(AR_TZ).timestamp()

    def _prune(self, key: str):
        cutoff = self._now() - self.window
        self._calls[key] = [t for t in self._calls.get(key, []) if t > cutoff]

    def allow(self, key: str) -> bool:
        self._prune(key)
        return len(self._calls.get(key, [])) < self.max_calls

    def record(self, key: str):
        if key not in self._calls:
            self._calls[key] = []
        self._calls[key].append(self._now())

    def call(self, key: str) -> bool:
        if self.allow(key):
            self.record(key)
            return True
        return False

    def remaining(self, key: str) -> int:
        self._prune(key)
        return max(0, self.max_calls - len(self._calls.get(key, [])))

    def retry_after_seconds(self, key: str) -> float:
        """Seconds until the oldest call leaves the active rate window."""
        self._prune(key)
        calls = self._calls.get(key, [])
        if len(calls) < self.max_calls or not calls:
            return 0.0
        return max(0.0, calls[0] + self.window - self._now())

    def reset(self, key: str | None = None):
        if key:
            self._calls.pop(key, None)
        else:
            self._calls.clear()
