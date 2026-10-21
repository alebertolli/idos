"""Invalidate a Buy List approval when Research produces a newer thesis."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any

import yaml


def invalidate_manager_approval_after_research(
    base_path: str | Path,
    ticker: str,
    opp_id: str,
    *,
    invalidated_at: str,
) -> bool:
    """Remove only this opportunity's Buy List approval and stale its proposal.

    Immutable decision records under ``decisions/`` are preserved. Returns
    False when no manager-approved Buy List entry exists.
    """
    normalized_ticker = str(ticker).upper().strip()
    normalized_opp_id = str(opp_id).strip()
    if not re.fullmatch(r"[A-Z0-9.^=_-]{1,24}", normalized_ticker):
        raise ValueError("Ticker has invalid characters")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", normalized_opp_id):
        raise ValueError("Opportunity id has invalid characters")
    try:
        datetime.fromisoformat(str(invalidated_at).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalidated_at must be an ISO timestamp") from exc

    root = Path(base_path)
    opportunity_dir = (
        root / "idos-journal" / "companies" / normalized_ticker
        / "case_file" / "opportunities" / normalized_opp_id
    ).resolve()
    journal_root = (root / "idos-journal").resolve()
    if journal_root not in opportunity_dir.parents:
        raise ValueError("Opportunity path escapes the journal")

    opportunity_path = opportunity_dir / "opportunity.yml"
    if not opportunity_path.is_file():
        return False
    opportunity = _read_mapping(opportunity_path)

    buylist_path = root / "idos-journal" / "portfolio" / "buylist.yml"
    buylist = _read_mapping(buylist_path) if buylist_path.exists() else {"entries": []}
    entries = buylist.get("entries", [])
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise ValueError("Existing Buy List is malformed; approval was not changed")
    matching = [
        entry for entry in entries
        if str(entry.get("ticker", "")).upper() == normalized_ticker
        and str(entry.get("opp_id", "")) == normalized_opp_id
    ]

    proposal_path = opportunity_dir / "decision_proposal.yml"
    proposal = _read_mapping(proposal_path) if proposal_path.exists() else None
    resolution_path = opportunity_dir / "board_resolution.yml"
    resolution = _read_mapping(resolution_path) if resolution_path.exists() else None
    manager_approved = (
        opportunity.get("approved_for_buylist") is True
        or bool(matching)
        or (isinstance(resolution, dict) and resolution.get("approved") is True)
        or (
            isinstance(proposal, dict)
            and proposal.get("status") == "MANAGER_APPROVED"
        )
    )
    if not manager_approved:
        return False

    buylist["entries"] = [entry for entry in entries if entry not in matching]
    opportunity["approved_for_buylist"] = False
    opportunity["manager_approval_invalidated_at"] = invalidated_at
    opportunity["manager_approval_invalidation_reason"] = "new_research_version"
    if isinstance(proposal, dict):
        proposal["status"] = "INVALIDATED_BY_NEW_RESEARCH"
        proposal["approval_invalidated_at"] = invalidated_at
        proposal["approval_invalidation_reason"] = "new_research_version"
    if isinstance(resolution, dict):
        resolution["approved"] = False
        resolution["status"] = "invalidated_by_new_research"
        resolution["invalidated_at"] = invalidated_at
        resolution["invalidation_reason"] = "new_research_version"

    _write_yaml(buylist_path, buylist)
    _write_yaml(opportunity_path, opportunity)
    if isinstance(proposal, dict):
        _write_yaml(proposal_path, proposal)
    if isinstance(resolution, dict):
        _write_yaml(resolution_path, resolution)
    return True


def _read_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML object in {path}")
    return data


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
