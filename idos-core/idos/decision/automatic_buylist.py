"""Automatic, auditable Buy List admission for fully qualified opportunities."""

from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path
from typing import Any

import yaml

from idos.decision.proposal_review import decision_proposal_fingerprint
from idos.decision.scenarios import (
    scenario_fingerprint,
    scenario_source_urls_from_report,
    validate_scenario_analysis,
)
from idos.timezone import AR_TZ


def authorize_buylist_if_eligible(
    base_path: str | Path,
    ticker: str,
    opp_id: str,
    proposal: dict[str, Any],
    opportunity: dict[str, Any],
    required_rule_ids: set[str],
) -> dict[str, Any]:
    """Persist a Buy List authorization only when every configured gate passes.

    Buy List authorization is a research decision; it never creates a position
    or executes an order. Missing data, malformed state, and ticker conflicts
    fail closed with a candidate-local reason.
    """
    rules_passed = proposal.get("rules_passed")
    rules_failed = proposal.get("rules_failed")
    if (
        not isinstance(rules_passed, list)
        or not isinstance(rules_failed, list)
        or rules_failed
        or not required_rule_ids.issubset(set(rules_passed))
    ):
        return {"approved": False, "reason": "authorization_rules_not_all_passed"}

    root = Path(base_path)
    opportunity_dir = _opportunity_dir(root, ticker, opp_id)
    opportunity_path = opportunity_dir / "opportunity.yml"
    proposal_path = opportunity_dir / "decision_proposal.yml"
    report_path = opportunity_dir / "ddd_report.yml"
    if not all(path.is_file() for path in (opportunity_path, proposal_path, report_path)):
        return {"approved": False, "reason": "current_assessment_or_research_missing"}

    try:
        saved_proposal = _read_mapping(proposal_path)
        saved_opportunity = _read_mapping(opportunity_path)
        report = _read_mapping(report_path)
    except (OSError, yaml.YAMLError, ValueError):
        return {"approved": False, "reason": "research_or_assessment_malformed"}

    if saved_opportunity.get("thesis_active") is False:
        return {"approved": False, "reason": "thesis_invalidated"}

    analysis = report.get("scenario_analysis")
    if "RULE-008" not in rules_passed or not isinstance(analysis, dict):
        return {"approved": False, "reason": "validated_scenarios_required"}
    scenario_errors = validate_scenario_analysis(
        analysis, trusted_source_urls=scenario_source_urls_from_report(report),
    )
    if scenario_errors or analysis.get("quantification_status", "validated") != "validated":
        detail = "; ".join(scenario_errors) or "scenario range is not quantitatively validated"
        return {"approved": False, "reason": f"scenario_validation_failed: {detail}"}
    scenario_hash = scenario_fingerprint(analysis)
    if proposal.get("scenario_hash") != scenario_hash:
        return {"approved": False, "reason": "scenario_assessment_is_stale"}

    conviction = saved_opportunity.get("conviction") or {}
    target = conviction.get("intrinsic_value") or saved_opportunity.get("intrinsic_value")
    price = conviction.get("current_price") or saved_opportunity.get("current_price")
    if _target_is_analyst_consensus(report, target, saved_opportunity):
        return {"approved": False, "reason": "analyst_consensus_is_not_intrinsic_value"}
    if not _positive_finite(target) or not _positive_finite(price):
        return {"approved": False, "reason": "current_and_target_prices_required"}

    buylist_path = root / "idos-journal" / "portfolio" / "buylist.yml"
    try:
        buylist = _read_mapping(buylist_path) if buylist_path.exists() else {"entries": []}
    except (OSError, yaml.YAMLError, ValueError):
        return {"approved": False, "reason": "buylist_state_malformed"}
    entries = buylist.get("entries", [])
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        return {"approved": False, "reason": "buylist_state_malformed"}
    conflict = next((entry for entry in entries
                     if str(entry.get("ticker", "")).upper() == ticker.upper()
                     and str(entry.get("opp_id", "")) != opp_id), None)
    if conflict:
        return {"approved": False, "reason": "another_opportunity_for_ticker_is_listed"}

    proposal_hash = decision_proposal_fingerprint(saved_proposal)
    decision_id = f"AUTO-{proposal_hash[:16]}"
    decision_path = opportunity_dir / "decisions" / f"{decision_id}.yml"
    now = datetime.now(AR_TZ).isoformat()
    if saved_proposal.get("status") == "AUTO_APPROVED" and decision_path.is_file():
        return {"approved": True, "decision_id": decision_id, "idempotent": True}

    try:
        portfolio_config_path = root / "idos-config" / "portfolio.yml"
        portfolio_config = _read_mapping(portfolio_config_path) if portfolio_config_path.exists() else {}
        margin = portfolio_config.get("margin_of_safety", 30.0)
        if isinstance(margin, bool) or not isinstance(margin, (int, float)) or not math.isfinite(margin) or margin < 0:
            return {"approved": False, "reason": "invalid_margin_of_safety_config"}
    except (OSError, yaml.YAMLError, ValueError):
        return {"approved": False, "reason": "portfolio_config_malformed"}

    score = int(proposal.get("conviction_score") or 0)
    entry = next((item for item in entries
                  if str(item.get("ticker", "")).upper() == ticker.upper()
                  and str(item.get("opp_id", "")) == opp_id), {})
    entry.update({
        "ticker": ticker.upper(),
        "opp_id": opp_id,
        "target_price": round(float(target), 2),
        "buy_zone_top": round(float(target) / (1 + float(margin) / 100), 2),
        "max_position_pct": _max_position_pct(root, saved_opportunity, score),
        "conviction_score": score,
        "horizon": saved_opportunity.get("horizon", "12-36 months"),
        "catalysts": saved_opportunity.get("catalysts", []),
        "kb_last_update": saved_proposal.get("generated_at") or now,
        "added_at": entry.get("added_at") or now,
        "monitoring": entry.get("monitoring", True),
        "authorization_mode": "automatic_rules",
        "decision_id": decision_id,
    })
    remaining = [item for item in entries if not (
        str(item.get("ticker", "")).upper() == ticker.upper()
        and str(item.get("opp_id", "")) == opp_id
    )]
    remaining.append(entry)

    saved_proposal["algorithm_recommendation"] = saved_proposal.get("recommendation")
    saved_proposal["recommendation"] = "APPROVE"
    saved_proposal["status"] = "AUTO_APPROVED"
    saved_proposal["automatic_authorization"] = {
        "policy": "all_configured_authorization_rules_v1",
        "rules_passed": sorted(required_rule_ids),
        "proposal_hash": proposal_hash,
        "scenario_hash": scenario_hash,
        "authorized_at": now,
        "scope": "buy_list_only",
    }
    resolution = {
        "approved": True,
        "status": "AUTO_APPROVED",
        "decision_id": decision_id,
        "decision_type": "BUY_LIST_ADMISSION",
        "opportunity_id": opp_id,
        "proposal_hash": proposal_hash,
        "scenario_hash": scenario_hash,
        "rules_applied": sorted(required_rule_ids),
        "sources_verified": True,
        "justification": "Se cumplieron todas las reglas de autorización y validaciones de evidencia configuradas. Autorización limitada a Buy List; no ejecuta órdenes ni crea posiciones.",
        "author": "idos:auto-authorization",
        "resolved_at": now,
    }
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    if decision_path.exists():
        return {"approved": False, "reason": "automatic_decision_record_already_exists"}
    decision_path.write_text(yaml.safe_dump(resolution, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (opportunity_dir / "decision_proposal.yml").write_text(
        yaml.safe_dump(saved_proposal, allow_unicode=True, sort_keys=False), encoding="utf-8",
    )
    (opportunity_dir / "board_resolution.yml").write_text(
        yaml.safe_dump(resolution, allow_unicode=True, sort_keys=False), encoding="utf-8",
    )
    saved_opportunity["approved_for_buylist"] = True
    saved_opportunity["automatic_buylist_decision_id"] = decision_id
    saved_opportunity["updated_at"] = now
    opportunity_path.write_text(yaml.safe_dump(saved_opportunity, allow_unicode=True, sort_keys=False), encoding="utf-8")
    buylist_path.parent.mkdir(parents=True, exist_ok=True)
    buylist_path.write_text(yaml.safe_dump({**buylist, "entries": remaining}, allow_unicode=True, sort_keys=False), encoding="utf-8")

    try:
        from idos.events.bus import get_event_bus
        from idos.events.types import Event
        get_event_bus().publish(Event(
            type="board:auto_approved",
            data={"ticker": ticker.upper(), "opp_id": opp_id, "decision_id": decision_id,
                  "proposal_hash": proposal_hash, "scope": "buy_list_only"},
            source="automatic_authorization",
        ))
    except Exception:
        # The persisted decision is authoritative; event notification is secondary.
        pass
    return {"approved": True, "decision_id": decision_id, "proposal_hash": proposal_hash}


def revoke_buylist_on_thesis_invalidation(
    base_path: str | Path,
    ticker: str,
    opp_id: str,
    *,
    invalidated_at: str,
    reason: str,
) -> bool:
    """Remove one invalidated opportunity from Buy List and append audit history."""
    root = Path(base_path)
    opportunity_dir = _opportunity_dir(root, ticker, opp_id)
    opportunity_path = opportunity_dir / "opportunity.yml"
    if not opportunity_path.is_file():
        return False
    try:
        datetime.fromisoformat(str(invalidated_at).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalidated_at must be an ISO timestamp") from exc
    opportunity = _read_mapping(opportunity_path)
    buylist_path = root / "idos-journal" / "portfolio" / "buylist.yml"
    buylist = _read_mapping(buylist_path) if buylist_path.exists() else {"entries": []}
    entries = buylist.get("entries", [])
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise ValueError("Existing Buy List is malformed; thesis invalidation was not persisted")
    matching = [entry for entry in entries if (
        str(entry.get("ticker", "")).upper() == ticker.upper()
        and str(entry.get("opp_id", "")) == opp_id
    )]
    proposal_path = opportunity_dir / "decision_proposal.yml"
    resolution_path = opportunity_dir / "board_resolution.yml"
    proposal = _read_mapping(proposal_path) if proposal_path.exists() else {}
    resolution = _read_mapping(resolution_path) if resolution_path.exists() else {}
    approved = (
        opportunity.get("approved_for_buylist") is True
        or bool(matching)
        or resolution.get("approved") is True
        or proposal.get("status") in {"AUTO_APPROVED", "MANAGER_APPROVED"}
    )
    if not approved:
        return False

    decision_hash = decision_proposal_fingerprint(proposal) if proposal else ""
    revocation_id = f"AUTO-REVOKE-{decision_hash[:12]}"
    record_path = opportunity_dir / "decisions" / f"{revocation_id}.yml"
    if record_path.exists():
        return False
    now = datetime.now(AR_TZ).isoformat()
    buylist["entries"] = [entry for entry in entries if entry not in matching]
    opportunity.update({
        "approved_for_buylist": False,
        "buylist_revoked_at": now,
        "buylist_revocation_reason": "thesis_invalidated",
    })
    if proposal:
        proposal["status_before_thesis_invalidation"] = proposal.get("status")
        proposal["status"] = "REVOKED_THESIS_INVALIDATED"
        proposal["buylist_revoked_at"] = now
        proposal["thesis_invalidated_reason"] = reason
    if resolution:
        resolution["approved"] = False
        resolution["status_before_thesis_invalidation"] = resolution.get("status")
        resolution["status"] = "REVOKED_THESIS_INVALIDATED"
        resolution["revoked_at"] = now
        resolution["thesis_invalidated_reason"] = reason
    record = {
        "approved": False,
        "status": "REVOKED_THESIS_INVALIDATED",
        "decision_id": revocation_id,
        "decision_type": "BUY_LIST_REMOVAL",
        "opportunity_id": opp_id,
        "proposal_hash": decision_hash,
        "reason": reason,
        "author": "idos:auto-thesis-monitor",
        "resolved_at": now,
        "scope": "buy_list_only; no_position_or_order_action",
    }
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(yaml.safe_dump(record, allow_unicode=True, sort_keys=False), encoding="utf-8")
    buylist_path.parent.mkdir(parents=True, exist_ok=True)
    buylist_path.write_text(yaml.safe_dump(buylist, allow_unicode=True, sort_keys=False), encoding="utf-8")
    opportunity_path.write_text(yaml.safe_dump(opportunity, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if proposal:
        proposal_path.write_text(yaml.safe_dump(proposal, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if resolution:
        resolution_path.write_text(yaml.safe_dump(resolution, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return True


def _opportunity_dir(root: Path, ticker: str, opp_id: str) -> Path:
    normalized_ticker = str(ticker).upper().strip()
    normalized_opp_id = str(opp_id).strip()
    if not normalized_ticker or not normalized_opp_id or any(part in normalized_opp_id for part in ("/", "\\", "..")):
        raise ValueError("Ticker or opportunity id is invalid")
    path = (root / "idos-journal" / "companies" / normalized_ticker
            / "case_file" / "opportunities" / normalized_opp_id).resolve()
    journal_root = (root / "idos-journal").resolve()
    if journal_root not in path.parents:
        raise ValueError("Opportunity path escapes the journal")
    return path


def _target_is_analyst_consensus(
    report: dict[str, Any], target: Any, opportunity: dict[str, Any],
) -> bool:
    """Reject legacy targets that are exactly the analyst consensus mean.

    Older assessments copied consensus into ``intrinsic_value``. Allow a value
    only when a future independent valuation explicitly identifies its basis.
    """
    conviction = opportunity.get("conviction")
    conviction = conviction if isinstance(conviction, dict) else {}
    basis = opportunity.get("intrinsic_value_basis") or conviction.get("intrinsic_value_basis")
    if isinstance(basis, str) and basis.strip().lower().replace("-", "_") in {
        "independent_dcf", "dcf_model", "discounted_cash_flow",
    }:
        return False
    snapshot = report.get("research_input_snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    market = snapshot.get("scenario_market_evidence")
    market = market if isinstance(market, dict) else {}
    consensus = market.get("analyst_target_consensus")
    consensus = consensus if isinstance(consensus, dict) else {}
    mean = consensus.get("mean")
    return (
        _positive_finite(target)
        and _positive_finite(mean)
        and math.isclose(float(target), float(mean), rel_tol=0.0, abs_tol=0.01)
    )


def _read_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML object in {path}")
    return data


def _positive_finite(value: Any) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value > 0)


def _max_position_pct(root: Path, opportunity: dict[str, Any], score: int) -> float:
    maximum = min(3.0, max(0.0, score / 100 * 5))
    strategy_path = root / "idos-config" / "strategies.yml"
    if strategy_path.exists():
        try:
            config = _read_mapping(strategy_path)
            profile = (config.get("strategies") or {}).get(opportunity.get("strategy_id"), {})
            limit = (profile.get("parameters") or {}).get("position_limit_pct")
            if isinstance(limit, (int, float)) and not isinstance(limit, bool) and math.isfinite(limit) and limit >= 0:
                maximum = min(maximum, float(limit))
        except (OSError, yaml.YAMLError, ValueError):
            return 0.0
    return round(maximum, 2)
