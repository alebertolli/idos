"""Record an authenticated manager review for an exact Research scenario set."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import re
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from idos.decision.scenarios import (  # noqa: E402
    scenario_fingerprint,
    scenario_source_urls_from_report,
    validate_scenario_analysis,
)
from idos.timezone import AR_TZ  # noqa: E402


def record_scenario_review(
    base_path: Path,
    ticker: str,
    opp_id: str,
    scenario_hash: str,
    decision: str,
    reviewer: str,
    note: str,
    sources_verified: bool = False,
) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9.^=_-]{1,24}", ticker) or ticker in {".", ".."}:
        raise ValueError("Ticker has invalid characters")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", opp_id) or opp_id in {".", ".."}:
        raise ValueError("Opportunity id has invalid characters")
    if decision not in {"approved", "rejected"}:
        raise ValueError("Decision must be approved or rejected")
    if not reviewer.strip():
        raise ValueError("Authenticated reviewer identity is required")
    if not 10 <= len(note.strip()) <= 2000:
        raise ValueError("Review note must contain between 10 and 2000 characters")
    if decision == "approved" and sources_verified is not True:
        raise ValueError("Approval requires explicit source and source-date verification")

    opportunity_dir = (
        base_path / "idos-journal" / "companies" / ticker.upper()
        / "case_file" / "opportunities" / opp_id
    ).resolve()
    journal_root = (base_path / "idos-journal").resolve()
    if journal_root not in opportunity_dir.parents:
        raise ValueError("Opportunity path escapes the journal")
    report_path = opportunity_dir / "ddd_report.yml"
    if not report_path.is_file():
        raise FileNotFoundError(f"DDD report not found: {report_path}")
    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    analysis = report.get("scenario_analysis") if isinstance(report, dict) else None
    errors = validate_scenario_analysis(
        analysis, trusted_source_urls=scenario_source_urls_from_report(report),
    )
    if errors:
        raise ValueError("Scenario contract is invalid: " + "; ".join(errors))
    actual_hash = scenario_fingerprint(analysis)
    if scenario_hash != actual_hash:
        raise ValueError("Scenario hash is stale; review the latest Research output")

    review = {
        "status": decision,
        "scenario_hash": actual_hash,
        "reviewed_by": reviewer.strip(),
        "reviewed_at": datetime.now(AR_TZ).isoformat(),
        "note": note.strip(),
        "sources_verified": sources_verified,
    }
    review_path = opportunity_dir / "scenario_review.yml"
    review_path.write_text(yaml.safe_dump(review, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return review_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-path", type=Path, default=Path.cwd())
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--opp-id", required=True)
    parser.add_argument("--scenario-hash", required=True)
    parser.add_argument("--decision", choices=("approved", "rejected"), required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--sources-verified", choices=("true", "false"), default="false")
    args = parser.parse_args()
    path = record_scenario_review(
        args.base_path, args.ticker, args.opp_id, args.scenario_hash,
        args.decision, args.reviewer, args.note, args.sources_verified == "true",
    )
    print(f"Scenario review recorded: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
