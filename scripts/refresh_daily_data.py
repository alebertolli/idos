"""Refresh public opportunity data; optional explicit subset for bounded E2E runs."""
import json
import os
import re
from datetime import datetime
from pathlib import Path

import yaml

from idos.data.journal import JournalRepository
from idos.timezone import AR_TZ
from idos.workers.base import WorkerStatus
from idos.workers.data.refresh_worker import DataRefreshWorker


def select_tickers(base: Path, explicit: str = "") -> list[str]:
    if explicit.strip():
        tickers = explicit.split(",")
    else:
        tickers = []
        for name in ("watchlist", "buylist"):
            path = base / "idos-journal" / "portfolio" / f"{name}.yml"
            data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
            tickers.extend(e["ticker"] for e in (data or {}).get("entries", []) if e.get("ticker"))
        journal = JournalRepository(base / "idos-journal")
        for opportunity in journal.list_all_opportunities():
            if opportunity.get("status") in {"SCREENED", "UNDER_RESEARCH", "APPROVED", "ENTRY_PENDING"}:
                tickers.append(opportunity["ticker"])
    result = sorted({str(t).strip().upper() for t in tickers if str(t).strip()})
    if any(not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=-]{0,19}", ticker) for ticker in result):
        raise ValueError("Invalid ticker selection")
    return result


def main() -> int:
    base = Path.cwd()
    tickers = select_tickers(base, os.environ.get("REFRESH_TICKERS", ""))
    print(f"[REFRESH] Selected {len(tickers)} public opportunity tickers: {tickers}")
    result = DataRefreshWorker({"universe_path": ""}).execute({"tickers": tickers})
    output = result.output or {}
    errors = output.get("errors", [])
    processed = output.get("tickers_processed", 0)
    summary = {"refreshed_at": datetime.now(AR_TZ).isoformat(), "tickers": tickers,
               "tickers_processed": processed, "errors": errors}
    (base / "cache").mkdir(exist_ok=True)
    (base / "cache" / "last_refresh.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[REFRESH] Processed {processed}/{len(tickers)}; source warnings: {len(errors)}")
    return int(result.status == WorkerStatus.FAILED or processed != len(tickers))


if __name__ == "__main__":
    raise SystemExit(main())
