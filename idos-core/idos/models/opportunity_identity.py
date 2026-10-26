"""Canonical opportunity identifiers and lifecycle cycle helpers."""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any


TERMINAL_OPPORTUNITY_STATUSES = {"EXITED", "POST_MORTEM", "ARCHIVED", "CLOSED", "REJECTED"}


def _normalize(value: Any) -> str:
    normalized = re.sub(r"[^A-Z0-9.-]+", "-", str(value or "").strip().upper()).strip("-.")
    if not normalized:
        raise ValueError("Opportunity strategy and ticker must be non-empty identifiers")
    return normalized


def is_active_opportunity(opportunity: dict[str, Any]) -> bool:
    """Unknown statuses stay active so discovery cannot silently duplicate cases."""
    return str(opportunity.get("status", "SCREENED")).strip().upper() not in TERMINAL_OPPORTUNITY_STATUSES


def next_opportunity_cycle(
    opportunities: Iterable[dict[str, Any]], strategy_id: str, ticker: str
) -> int:
    """Return the next per-strategy, per-ticker cycle, including legacy records."""
    strategy = str(strategy_id or "COMPOUNDER").strip().upper()
    symbol = str(ticker or "").strip().upper()
    cycles: list[int] = []
    for opportunity in opportunities:
        if str(opportunity.get("ticker", "")).strip().upper() != symbol:
            continue
        if str(opportunity.get("strategy_id", "COMPOUNDER")).strip().upper() != strategy:
            continue
        cycle = opportunity.get("opportunity_cycle")
        if isinstance(cycle, int) and not isinstance(cycle, bool) and cycle > 0:
            cycles.append(cycle)
        else:
            # Every pre-contract opportunity is a prior cycle, including OPP-MB-AAPL.
            cycles.append(1)
    return max(cycles, default=0) + 1


def build_opportunity_id(strategy_id: str, ticker: str, cycle: int) -> str:
    """Build OPP-{STRATEGY}-{TICKER}-{CYCLE}; cycle is stable across reruns."""
    if not isinstance(cycle, int) or isinstance(cycle, bool) or cycle < 1:
        raise ValueError("Opportunity cycle must be a positive integer")
    strategy = _normalize(strategy_id.replace("_", "-"))
    symbol = _normalize(ticker)
    return f"OPP-{strategy}-{symbol}-{cycle:04d}"
