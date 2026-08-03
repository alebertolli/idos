from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from idos.timezone import AR_TZ

CATEGORY_DATOS = "datos"
SEVERITY_LOW = "baja"
SEVERITY_MEDIUM = "media"
SEVERITY_HIGH = "alta"


@dataclass
class ErrorRecord:
    id: str
    category: str
    severity: str
    ticker: str
    message: str
    ts: str
    detail: str = ""
    reported: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ErrorRecord":
        return cls(
            id=data.get("id", f"err-{uuid4().hex[:8]}"),
            category=data.get("category", CATEGORY_DATOS),
            severity=data.get("severity", SEVERITY_MEDIUM),
            ticker=data.get("ticker", ""),
            message=data.get("message", ""),
            ts=data.get("ts", ""),
            detail=data.get("detail", ""),
            reported=bool(data.get("reported", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "severity": self.severity,
            "ticker": self.ticker,
            "message": self.message,
            "ts": self.ts,
            "detail": self.detail,
            "reported": self.reported,
        }


class ErrorManager:
    """Centralized error management for the IDOS platform (SDD-16 §17.2).

    All workers MUST report errors through this service. Errors are persisted
    deduplicated by `date + ticker + message signature` in cache/data_errors.json.
    """

    def __init__(self, base_path: str | Path | None = None):
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.file = self.base_path / "cache" / "data_errors.json"

    def _load(self) -> list[dict[str, Any]]:
        if not self.file.exists():
            return []
        import json
        try:
            return json.loads(self.file.read_text(encoding="utf-8")) or []
        except Exception:
            return []

    def _save(self, records: list[dict[str, Any]]):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        import json
        self.file.write_text(
            json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _signature(self, ticker: str, message: str) -> str:
        return f"{ticker.upper()}::{message.strip()[:120]}"

    def report(
        self,
        category: str = CATEGORY_DATOS,
        severity: str = SEVERITY_MEDIUM,
        ticker: str = "",
        message: str = "",
        detail: str = "",
    ) -> ErrorRecord:
        now = datetime.now(AR_TZ)
        date_key = now.strftime("%Y-%m-%d")
        sig = self._signature(ticker, message)
        today_sig = f"{date_key}::{sig}"

        records = self._load()
        for r in records:
            if self._signature(r.get("ticker", ""), r.get("message", "")) == sig and \
               r.get("ts", "")[:10] == date_key:
                # Update existing record (keeps daily dedup), refresh timestamp
                order = {SEVERITY_HIGH: 3, SEVERITY_MEDIUM: 2, SEVERITY_LOW: 1}
                if order.get(severity, 0) > order.get(r.get("severity", ""), 0):
                    r["severity"] = severity
                r["ts"] = now.isoformat()
                if detail and not r.get("detail"):
                    r["detail"] = detail
                self._save(records)
                return ErrorRecord.from_dict(r)

        rec = ErrorRecord(
            id=f"err-{uuid4().hex[:8]}",
            category=category,
            severity=severity,
            ticker=ticker.upper(),
            message=message,
            ts=now.isoformat(),
            detail=detail,
        )
        records.append(rec.to_dict())
        # Cap to avoid unbounded growth
        records = records[-2000:]
        self._save(records)
        print(f"[ERROR-MGR] {severity.upper()}: [{ticker}] {message}")
        return rec

    def errors_since(self, days: int = 1) -> list[ErrorRecord]:
        """All records for the current day (deduplicated by signature)."""
        now = datetime.now(AR_TZ)
        from datetime import timedelta
        cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        records = self._load()
        seen: dict[str, ErrorRecord] = {}
        for r in records:
            ts = r.get("ts", "")
            if ts[:10] < cutoff:
                continue
            key = self._signature(r.get("ticker", ""), r.get("message", ""))
            # keep highest severity among duplicates of same signature/day
            order = {SEVERITY_HIGH: 3, SEVERITY_MEDIUM: 2, SEVERITY_LOW: 1}
            rec = ErrorRecord.from_dict(r)
            if key not in seen or order.get(rec.severity, 0) > order.get(seen[key].severity, 0):
                seen[key] = rec
        return list(seen.values())

    def mark_reported(self, date_key: str | None = None):
        """Mark all records for the given day as already reported (issue created)."""
        now = datetime.now(AR_TZ)
        key = date_key or now.strftime("%Y-%m-%d")
        records = self._load()
        changed = False
        for r in records:
            if r.get("ts", "")[:10] == key:
                r["reported"] = True
                changed = True
        if changed:
            self._save(records)

    def pending_reported(self, date_key: str | None = None) -> bool:
        now = datetime.now(AR_TZ)
        key = date_key or now.strftime("%Y-%m-%d")
        records = self._load()
        for r in records:
            if r.get("ts", "")[:10] == key and not r.get("reported"):
                return False
        return True
