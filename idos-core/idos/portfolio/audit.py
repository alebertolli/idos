"""Deterministic capital exposure audit for an explicitly supplied snapshot.

This module does not value assets, infer missing classifications, or authorize trades.
Amounts are converted using rates supplied with the snapshot, never live quotes.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


class PortfolioAuditError(ValueError):
    """The snapshot cannot be audited reliably."""


_DIMENSIONS = (
    "instrument_id", "issuer", "economic_cluster", "strategy_id",
    "sleeve", "sector", "country", "argentina_risk_bucket",
)


def _decimal(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise PortfolioAuditError(f"{label} must be a finite number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PortfolioAuditError(f"{label} must be a finite number") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise PortfolioAuditError(f"{label} must be a finite positive number")
    return result


def _required_text(row: Mapping[str, Any], key: str, label: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PortfolioAuditError(f"{label}.{key} is required")
    return value.strip()


def audit_portfolio(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Audit capital weights and known data gaps without inventing risk scores.

    ``fx_to_base`` expresses one unit of each currency in ``base_currency``.
    A missing rate, duplicate position ID, invalid amount or empty portfolio
    fails the audit. Unknown optional classifications are reported as UNKNOWN.
    """
    if not isinstance(snapshot, Mapping):
        raise PortfolioAuditError("snapshot must be an object")
    as_of = _required_text(snapshot, "as_of", "snapshot")
    try:
        date.fromisoformat(as_of)
    except ValueError as exc:
        raise PortfolioAuditError("snapshot.as_of must be YYYY-MM-DD") from exc
    base = _required_text(snapshot, "base_currency", "snapshot").upper()
    rates_raw = snapshot.get("fx_to_base", {})
    if not isinstance(rates_raw, Mapping):
        raise PortfolioAuditError("snapshot.fx_to_base must be an object")
    rates = {base: Decimal(1)}
    for currency, value in rates_raw.items():
        if not isinstance(currency, str) or not currency.strip():
            raise PortfolioAuditError("FX currency code is required")
        key = currency.strip().upper()
        rate = _decimal(value, f"fx_to_base.{key}", positive=True)
        if key == base and rate != 1:
            raise PortfolioAuditError("base currency FX rate must equal 1")
        rates[key] = rate

    raw_positions = snapshot.get("positions")
    if not isinstance(raw_positions, list) or not raw_positions:
        raise PortfolioAuditError("snapshot.positions must be a non-empty list")

    positions: list[dict[str, Any]] = []
    seen: set[str] = set()
    totals: dict[str, dict[str, Decimal]] = {key: defaultdict(Decimal) for key in _DIMENSIONS}
    missing: list[dict[str, str]] = []
    total_value = Decimal(0)
    for index, raw in enumerate(raw_positions):
        label = f"positions[{index}]"
        if not isinstance(raw, Mapping):
            raise PortfolioAuditError(f"{label} must be an object")
        position_id = _required_text(raw, "position_id", label)
        if position_id in seen:
            raise PortfolioAuditError(f"duplicate position_id: {position_id}")
        seen.add(position_id)
        currency = _required_text(raw, "currency", label).upper()
        if currency not in rates:
            raise PortfolioAuditError(f"missing FX rate for {currency}")
        amount = _decimal(raw.get("market_value"), f"{label}.market_value", positive=True)
        value = amount * rates[currency]
        total_value += value
        groups: dict[str, str] = {}
        for key in _DIMENSIONS:
            raw_value = raw.get(key)
            value_text = raw_value.strip() if isinstance(raw_value, str) else ""
            groups[key] = value_text or "UNKNOWN"
            if not value_text:
                missing.append({"position_id": position_id, "field": key})
            totals[key][groups[key]] += value
        positions.append({
            "position_id": position_id,
            "currency": currency,
            "market_value_base": value,
            "classifications": groups,
        })

    def pct(value: Decimal) -> float:
        return round(float(value / total_value * 100), 4)

    return {
        "as_of": as_of,
        "base_currency": base,
        "total_market_value": float(total_value),
        "positions": [
            {**position,
             "market_value_base": float(position["market_value_base"]),
             "capital_weight_pct": pct(position["market_value_base"])}
            for position in positions
        ],
        "exposures_pct": {
            dimension: {name: pct(value) for name, value in sorted(groups.items())}
            for dimension, groups in totals.items()
        },
        "missing_classifications": missing,
        "status": "REVIEW" if missing else "COMPLETE",
        "allocation_authorized": False,
        "methodology": "capital_exposure_v1",
    }
