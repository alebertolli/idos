"""Reevaluate explicit public opportunities from existing reports/cache, without LLM."""
import json
import os
import re
from datetime import datetime
from pathlib import Path

import yaml

from idos.data.journal import JournalRepository
from idos.decision.assessment_pipeline import run_full_pipeline
from idos.timezone import AR_TZ


def reassess(base: Path, selection: str) -> dict:
    tickers = sorted({s.strip().upper() for s in selection.split(",") if s.strip()})
    if not tickers or any(not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=-]{0,19}", t) for t in tickers):
        raise ValueError("Reassessment requires explicit valid tickers")
    journal = JournalRepository(base / "idos-journal")
    candidates = [o for o in journal.list_all_opportunities()
                  if o.get("ticker") in tickers and o.get("status") in
                  {"SCREENED", "UNDER_RESEARCH", "UNDER_DEEP_DD", "APPROVED", "ENTRY_PENDING"}]
    results, errors = [], []
    found = {o["ticker"] for o in candidates}
    for ticker in tickers:
        if ticker not in found:
            errors.append({"ticker": ticker, "error": "No eligible opportunity"})
    for opp in candidates:
        ticker, opp_id = opp["ticker"], opp["id"]
        try:
            path = journal.opportunity_path(ticker, opp_id) / "ddd_report.yml"
            report = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if (report.get("research_status") == "FAILED" or
                    not str(report.get("tesis_inversion") or "").strip() or
                    report.get("opp_id", opp_id) != opp_id):
                raise ValueError("Missing, failed or mismatched DDD report; Research required")
            result = run_full_pipeline(opp_id, ticker, base, cache_only=True)
            results.append(result)
        except Exception as exc:
            errors.append({"ticker": ticker, "opp_id": opp_id, "error": str(exc)})
    return {"generated_at": datetime.now(AR_TZ).isoformat(), "mode": "assessment_only",
            "tickers": tickers, "results": results, "errors": errors}


def main() -> int:
    summary = reassess(Path.cwd(), os.environ.get("TICKER", ""))
    Path("cache").mkdir(exist_ok=True)
    Path("cache/reassessment_results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[REASSESS] {len(summary['results'])} results; {len(summary['errors'])} errors; no LLM")
    for error in summary["errors"]:
        print(f"[REASSESS] ERROR {error['ticker']}: {error['error']}")
    return int(bool(summary["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
