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

    def restore(self, entries: list[dict[str, Any]]):
        """Load a persisted snapshot without resetting entry metadata."""
        for raw in entries:
            if not isinstance(raw, dict):
                continue
            ticker = str(raw.get("ticker", "")).strip().upper()
            score = raw.get("score")
            if not ticker or isinstance(score, bool) or not isinstance(score, int):
                continue
            key = ticker
            if key in self._entries:
                continue
            alerts = raw.get("alerts", [])
            self._entries[key] = WatchlistEntry(
                ticker=ticker,
                score=score,
                reason=str(raw.get("reason", "")),
                added_at=str(raw.get("added_at", "")),
                alerts=[str(alert) for alert in alerts] if isinstance(alerts, list) else [],
                notified=raw.get("notified") is True,
            )

    def add(self, ticker: str, score: int, reason: str = "") -> bool:
        ticker = ticker.upper()
        existing = self._entries.get(ticker)
        if existing:
            existing.score = score
            existing.reason = reason
            return True
        if len(self._entries) >= self.max_entries:
            if score <= min(e.score for e in self._entries.values()):
                return False
            worst = min(self._entries.keys(), key=lambda t: self._entries[t].score)
            del self._entries[worst]

        self._entries[ticker.upper()] = WatchlistEntry(
            ticker=ticker, score=score, reason=reason,
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
