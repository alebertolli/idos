import csv
import yaml
from pathlib import Path
from datetime import datetime
from typing import Any
from idos.timezone import AR_TZ

DEFAULT_MANUAL_SELECTION_LIMIT = 5

class OperabilityFilter:
    def __init__(self, operable_path: str = "idos-config/universe/operable.yml"):
        self.path = Path(operable_path)
        self._tickers: dict[str, dict] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
            self._tickers = {
                e["ticker"]: e for e in data.get("operable_tickers", [])
            }

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entries = sorted(self._tickers.values(), key=lambda x: x["ticker"])
        self.path.write_text(
            yaml.dump(
                {"operable_tickers": entries},
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def is_operable(self, ticker: str) -> bool:
        return ticker.upper() in self._tickers

    def validate_selection(
        self,
        tickers: list[str],
        limit: int = DEFAULT_MANUAL_SELECTION_LIMIT,
    ) -> list[str]:
        """Validate and normalize a bounded manual candidate selection."""
        selected = sorted(
            {
                str(ticker).upper().strip()
                for ticker in tickers
                if str(ticker).strip()
            }
        )
        if len(selected) > limit:
            raise ValueError(f"Manual candidate selection exceeds the {limit}-ticker limit")
        invalid = sorted(set(selected) - self.tickers)
        if invalid:
            raise ValueError(
                "Requested test tickers are not in the operable registry: "
                + ", ".join(invalid)
            )
        return selected

    def validate_manual_selection(
        self,
        raw_selection: str,
        limit: int = DEFAULT_MANUAL_SELECTION_LIMIT,
    ) -> list[str]:
        """Require a non-empty comma-separated selection for bounded manual runs."""
        tickers = [ticker.strip().upper() for ticker in raw_selection.split(",") if ticker.strip()]
        if not tickers:
            raise ValueError("Manual runs require at least one ticker from operable.yml")
        return self.validate_selection(tickers, limit=limit)

    def add(
        self,
        ticker: str,
        name: str = "",
        type: str = "us_equity",
        source: str = "manual",
        ratio: str = "",
        byma_symbol: str = "",
        notes: str = "",
    ) -> dict:
        ticker = ticker.upper()
        entry = {
            "ticker": ticker,
            "name": name or ticker,
            "type": type,
            "source": source,
            "updated_at": datetime.now(AR_TZ).strftime("%Y-%m-%d"),
        }
        if ratio:
            entry["ratio"] = ratio
        if byma_symbol:
            entry["byma_symbol"] = byma_symbol
        if notes:
            entry["notes"] = notes
        self._tickers[ticker] = entry
        self._save()
        return entry

    def remove(self, ticker: str) -> bool:
        ticker = ticker.upper()
        if ticker in self._tickers:
            del self._tickers[ticker]
            self._save()
            return True
        return False

    def list(self, type: str = "", source: str = "") -> list[dict]:
        results = list(self._tickers.values())
        if type:
            results = [e for e in results if e.get("type") == type]
        if source:
            results = [e for e in results if e.get("source") == source]
        return sorted(results, key=lambda x: x["ticker"])

    def check(self, ticker: str) -> dict | None:
        return self._tickers.get(ticker.upper())

    def import_csv(self, csv_path: str) -> tuple[int, int]:
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV not found: {csv_path}")
        added = 0
        skipped = 0
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticker = row.get("ticker", "").strip().upper()
                if not ticker:
                    skipped += 1
                    continue
                if ticker in self._tickers:
                    skipped += 1
                    continue
                self.add(
                    ticker=ticker,
                    name=row.get("name", ""),
                    type=row.get("type", "us_equity"),
                    source=row.get("source", "manual"),
                    ratio=row.get("ratio", ""),
                    byma_symbol=row.get("byma_symbol", ""),
                    notes=row.get("notes", ""),
                )
                added += 1
        self._save()
        return added, skipped

    def stats(self) -> dict[str, Any]:
        counts: dict[str, Any] = {
            "total": len(self._tickers),
            "by_type": {},
            "by_source": {},
            "last_updated": "",
        }
        for e in self._tickers.values():
            t = e.get("type", "unknown")
            counts["by_type"][t] = counts["by_type"].get(t, 0) + 1
            s = e.get("source", "unknown")
            counts["by_source"][s] = counts["by_source"].get(s, 0) + 1
        dates = [
            e.get("updated_at", "")
            for e in self._tickers.values()
            if e.get("updated_at")
        ]
        if dates:
            counts["last_updated"] = max(dates)
        return counts

    @property
    def tickers(self) -> set[str]:
        return set(self._tickers.keys())
