"""Record an authenticated manager decision for a versioned Assessment proposal."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import math
import re
import sys
from uuid import uuid4

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from idos.decision.proposal_review import decision_proposal_fingerprint  # noqa: E402
from idos.decision.scenarios import (  # noqa: E402
    scenario_fingerprint,
    scenario_source_urls_from_report,
    validate_scenario_analysis,
    validate_board_scenario_confirmation,
)
from idos.timezone import AR_TZ  # noqa: E402


def record_decision_review(
    base_path: Path,
    ticker: str,
    opp_id: str,
    proposal_hash: str,
    decision: str,
    reviewer: str,
    note: str,
    sources_verified: bool = False,
) -> tuple[Path, Path]:
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

    opportunity_dir = (
        base_path / "idos-journal" / "companies" / ticker.upper()
        / "case_file" / "opportunities" / opp_id
    ).resolve()
    journal_root = (base_path / "idos-journal").resolve()
    if journal_root not in opportunity_dir.parents:
        raise ValueError("Opportunity path escapes the journal")
    proposal_path = opportunity_dir / "decision_proposal.yml"
    opportunity_path = opportunity_dir / "opportunity.yml"
    if not proposal_path.is_file() or not opportunity_path.is_file():
        raise FileNotFoundError("Opportunity and current Decision proposal are required")
    proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    opportunity = yaml.safe_load(opportunity_path.read_text(encoding="utf-8"))
    if not isinstance(proposal, dict) or not isinstance(opportunity, dict):
        raise ValueError("Opportunity or Decision proposal is malformed")
    if proposal.get("opportunity_id") != opp_id or opportunity.get("ticker", ticker).upper() != ticker.upper():
        raise ValueError("Decision proposal does not match the selected opportunity")
    if proposal.get("status") == "INVALIDATED_BY_NEW_RESEARCH":
        raise ValueError("Decision proposal was invalidated by newer Research; run Assessment again")
    actual_hash = decision_proposal_fingerprint(proposal)
    if proposal_hash != actual_hash:
        raise ValueError("Decision proposal hash is stale; run Assessment again before review")

    rules_passed = proposal.get("rules_passed") or []
    rules_failed = proposal.get("rules_failed") or []
    if not isinstance(rules_passed, list) or not isinstance(rules_failed, list):
        raise ValueError("Decision proposal rules are malformed")
    if decision == "approved":
        if proposal.get("recommendation") != "APPROVE" or rules_failed:
            raise ValueError("Only an APPROVE proposal with every authorization rule passed can be approved")
        if "RULE-008" not in rules_passed:
            raise ValueError("Approval requires a passed RULE-008 scenario assessment for every strategy")
        if "RULE-008" in rules_passed:
            report = yaml.safe_load((opportunity_dir / "ddd_report.yml").read_text(encoding="utf-8"))
            analysis = report.get("scenario_analysis") if isinstance(report, dict) else None
            errors = validate_scenario_analysis(
                analysis, trusted_source_urls=scenario_source_urls_from_report(report),
            )
            if errors:
                raise ValueError("Current Bear/Bull scenarios are invalid: " + "; ".join(errors))
            if analysis.get("quantification_status", "validated") != "validated":
                raise ValueError("RULE-008 approval requires quantitative Bear/Bull ranges")
            current_scenario_hash = scenario_fingerprint(analysis)
            if proposal.get("scenario_hash") != current_scenario_hash:
                raise ValueError("Current scenario set does not match the assessed proposal; rerun Assessment")
            board_review = {
                "status": "approved",
                "scenario_hash": current_scenario_hash,
                "reviewed_by": reviewer.strip(),
                "reviewed_at": datetime.now(AR_TZ).isoformat(),
                "note": note.strip(),
                "sources_verified": sources_verified,
            }
            reviewed, reason = validate_board_scenario_confirmation(
                analysis, board_review,
                trusted_source_urls=scenario_source_urls_from_report(report),
            )
            if not reviewed:
                raise ValueError("Decision Board scenario review is not current: " + reason)
        else:
            current_scenario_hash = None
    else:
        current_scenario_hash = proposal.get("scenario_hash")

    portfolio_path = base_path / "idos-config" / "portfolio.yml"
    portfolio_config = yaml.safe_load(portfolio_path.read_text(encoding="utf-8")) if portfolio_path.exists() else {}
    margin_of_safety = (portfolio_config or {}).get("margin_of_safety", 30.0)
    if isinstance(margin_of_safety, bool) or not isinstance(margin_of_safety, (int, float)) or not math.isfinite(margin_of_safety) or margin_of_safety < 0:
        raise ValueError("Configured margin_of_safety must be a finite non-negative number")
    conviction = opportunity.get("conviction") or {}
    target_price = conviction.get("intrinsic_value") or opportunity.get("intrinsic_value")
    current_price = conviction.get("current_price") or opportunity.get("current_price")
    if decision == "approved" and (
        isinstance(target_price, bool) or not isinstance(target_price, (int, float)) or not math.isfinite(target_price) or target_price <= 0
        or isinstance(current_price, bool) or not isinstance(current_price, (int, float)) or not math.isfinite(current_price) or current_price <= 0
    ):
        raise ValueError("Current and target prices are required before adding this opportunity to the public Buy List")

    resolution_path = opportunity_dir / "board_resolution.yml"
    previous = yaml.safe_load(resolution_path.read_text(encoding="utf-8")) if resolution_path.exists() else None
    if isinstance(previous, dict) and previous.get("status") in {"approved", "rejected"} and previous.get("proposal_hash") == actual_hash:
        raise ValueError("This proposal version already has a manager decision")

    now = datetime.now(AR_TZ)
    is_approved = decision == "approved"
    buylist_path = base_path / "idos-journal" / "portfolio" / "buylist.yml"
    buylist_data = yaml.safe_load(buylist_path.read_text(encoding="utf-8")) if buylist_path.exists() else {}
    entries = buylist_data.get("entries", []) if isinstance(buylist_data, dict) else []
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise ValueError("Existing Buy List is malformed; no changes were committed")
    if is_approved and any(entry.get("ticker", "").upper() == ticker.upper() and entry.get("opp_id") != opp_id for entry in entries):
        raise ValueError("A different opportunity for this ticker is already on the Buy List")
    entries = [entry for entry in entries if not (entry.get("ticker", "").upper() == ticker.upper() and entry.get("opp_id") == opp_id)]
    if is_approved:
        conviction_score = int(proposal.get("conviction_score") or 0)
        entries.append({
            "ticker": ticker.upper(),
            "opp_id": opp_id,
            "target_price": round(float(target_price), 2),
            "buy_zone_top": round(float(target_price) / (1 + float(margin_of_safety) / 100), 2),
            "max_position_pct": round(min(3.0, conviction_score / 100 * 5), 2),
            "conviction_score": conviction_score,
            "horizon": opportunity.get("horizon", "12-36 months"),
            "catalysts": opportunity.get("catalysts", []),
            "kb_last_update": proposal.get("generated_at") or now.isoformat(),
            "added_at": now.isoformat(),
            "monitoring": True,
        })

    decision_id = f"DEC-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
    review = {
        "approved": is_approved,
        "status": decision,
        "decision_id": decision_id,
        "decision_type": "BUY" if is_approved else "HOLD",
        "opportunity_id": opp_id,
        "proposal_hash": actual_hash,
        "scenario_hash": current_scenario_hash,
        "sources_verified": bool(sources_verified),
        "justification": note.strip(),
        "author": reviewer.strip(),
        "resolved_at": now.isoformat(),
    }
    decisions_dir = opportunity_dir / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    decision_path = decisions_dir / f"{decision_id}.yml"
    decision_path.write_text(yaml.safe_dump(review, allow_unicode=True, sort_keys=False), encoding="utf-8")
    resolution_path.write_text(yaml.safe_dump(review, allow_unicode=True, sort_keys=False), encoding="utf-8")

    proposal["status"] = "MANAGER_APPROVED" if is_approved else "MANAGER_REJECTED"
    proposal["manager_review"] = {
        "decision_id": decision_id,
        "decision": decision,
        "reviewed_by": reviewer.strip(),
        "reviewed_at": now.isoformat(),
        "sources_verified": bool(sources_verified),
    }
    proposal_path.write_text(yaml.safe_dump(proposal, allow_unicode=True, sort_keys=False), encoding="utf-8")
    opportunity["approved_for_buylist"] = is_approved
    opportunity["updated_at"] = now.isoformat()
    opportunity_path.write_text(yaml.safe_dump(opportunity, allow_unicode=True, sort_keys=False), encoding="utf-8")
    buylist_path.parent.mkdir(parents=True, exist_ok=True)
    buylist_path.write_text(yaml.safe_dump({"entries": entries}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return resolution_path, decision_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-path", type=Path, default=Path.cwd())
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--opp-id", required=True)
    parser.add_argument("--proposal-hash", required=True)
    parser.add_argument("--decision", choices=("approved", "rejected"), required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--sources-verified", choices=("true", "false"), default="false")
    args = parser.parse_args()
    resolution, record = record_decision_review(
        args.base_path, args.ticker, args.opp_id, args.proposal_hash,
        args.decision, args.reviewer, args.note, args.sources_verified == "true",
    )
    print(f"Manager decision recorded: {resolution}; immutable record: {record}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
