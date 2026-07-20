from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from idos.timezone import AR_TZ

@dataclass
class WatchlistEntry:
    ticker: str
    score: int
    reason: str = ""
    added_at: str = ""
    alerts: list[str] = field(default_factory=list)
    notified: bool = False

class WatchlistManager:
    def __init__(self, max_entries: int = 50):
        self.max_entries = max_entries
        self._entries: dict[str, WatchlistEntry] = {}

    @property
    def entries(self) -> list[WatchlistEntry]:
        return sorted(self._entries.values(), key=lambda e: e.score, reverse=True)

    def add(self, ticker: str, score: int, reason: str = "") -> bool:
        if len(self._entries) >= self.max_entries:
            if score <= min(e.score for e in self._entries.values()):
                return False
            worst = min(self._entries.keys(), key=lambda t: self._entries[t].score)
            del self._entries[worst]

        self._entries[ticker.upper()] = WatchlistEntry(
            ticker=ticker.upper(), score=score, reason=reason,
            added_at=datetime.now(AR_TZ).isoformat(),
        )
        return True

    def remove(self, ticker: str) -> bool:
        return self._entries.pop(ticker.upper(), None) is not None

    def get(self, ticker: str) -> WatchlistEntry | None:
        return self._entries.get(ticker.upper())

    def update_score(self, ticker: str, score: int, reason: str = ""):
        entry = self._entries.get(ticker.upper())
        if entry:
            entry.score = score
            if reason:
                entry.reason = reason

    def add_alert(self, ticker: str, alert: str):
        entry = self._entries.get(ticker.upper())
        if entry:
            entry.alerts.append(alert)

    def get_alerts(self) -> list[dict[str, Any]]:
        alerts = []
        for e in self._entries.values():
            for a in e.alerts:
                alerts.append({"ticker": e.ticker, "alert": a})
        return alerts

    def get_top(self, n: int = 10) -> list[WatchlistEntry]:
        return self.entries[:n]

    def count(self) -> int:
        return len(self._entries)

    def clear(self):
        self._entries.clear()
