"""Deterministic capital, balance-sheet, and sourced risk audit for a snapshot.

This module does not value assets, infer missing evidence, or authorize trades.
Amounts are converted using rates supplied with the snapshot, never live quotes.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from idos.portfolio.risk_audit_v21 import assess_risk_v21


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
    """Audit capital, balance-sheet, and evidence-backed portfolio risk.

    ``fx_to_base`` expresses one unit of each currency in ``base_currency``.
    A missing rate, duplicate position ID, invalid amount or empty portfolio
    fails the audit. Cash and pending obligations are optional. Unknown
    optional classifications are reported as UNKNOWN.
    """
    if not isinstance(snapshot, Mapping):
        raise PortfolioAuditError("snapshot must be an object")
    as_of = _required_text(snapshot, "as_of", "snapshot")
    try:
        as_of_date = date.fromisoformat(as_of)
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

    raw_fx_provenance = snapshot.get("fx_provenance", {})
    if not isinstance(raw_fx_provenance, Mapping):
        raise PortfolioAuditError("snapshot.fx_provenance must be an object")
    fx_provenance: dict[str, dict[str, str]] = {base: {"as_of": as_of, "source_ref": "IDENTITY"}}
    for currency in sorted(key for key in rates if key != base):
        raw_provenance = raw_fx_provenance.get(currency)
        if not isinstance(raw_provenance, Mapping):
            raise PortfolioAuditError(f"missing FX provenance for {currency}")
        fx_as_of = _required_text(raw_provenance, "as_of", f"fx_provenance.{currency}")
        try:
            fx_as_of_date = date.fromisoformat(fx_as_of)
        except ValueError as exc:
            raise PortfolioAuditError(f"fx_provenance.{currency}.as_of must be YYYY-MM-DD") from exc
        if fx_as_of_date > as_of_date:
            raise PortfolioAuditError(f"fx_provenance.{currency}.as_of cannot be after snapshot.as_of")
        fx_source_ref = _required_text(raw_provenance, "source_ref", f"fx_provenance.{currency}")
        fx_provenance[currency] = {"as_of": fx_as_of, "source_ref": fx_source_ref}

    raw_positions = snapshot.get("positions")
    if not isinstance(raw_positions, list) or not raw_positions:
        raise PortfolioAuditError("snapshot.positions must be a non-empty list")

    raw_cash = snapshot.get("cash", [])
    raw_obligations = snapshot.get("obligations", [])
    if not isinstance(raw_cash, list):
        raise PortfolioAuditError("snapshot.cash must be a list")
    if not isinstance(raw_obligations, list):
        raise PortfolioAuditError("snapshot.obligations must be a list")

    positions: list[dict[str, Any]] = []
    risk_positions: list[dict[str, Any]] = []
    seen: set[str] = set()
    totals: dict[str, dict[str, Decimal]] = {key: defaultdict(Decimal) for key in _DIMENSIONS}
    missing: list[dict[str, str]] = []
    total_value = Decimal(0)
    converted_cash: list[dict[str, Any]] = []
    cash_ids: set[str] = set()
    cash_total = Decimal(0)
    cash_by_currency: dict[str, Decimal] = defaultdict(Decimal)
    cash_by_account: dict[str, Decimal] = defaultdict(Decimal)
    for index, raw in enumerate(raw_cash):
        label = f"cash[{index}]"
        if not isinstance(raw, Mapping):
            raise PortfolioAuditError(f"{label} must be an object")
        cash_id = _required_text(raw, "cash_id", label)
        if cash_id in cash_ids:
            raise PortfolioAuditError(f"duplicate cash_id: {cash_id}")
        cash_ids.add(cash_id)
        account_id = _required_text(raw, "account_id", label)
        source_ref = _required_text(raw, "source_ref", label)
        currency = _required_text(raw, "currency", label).upper()
        if currency not in rates:
            raise PortfolioAuditError(f"missing FX rate for {currency}")
        balance = _decimal(raw.get("balance"), f"{label}.balance")
        if balance < 0:
            raise PortfolioAuditError(f"{label}.balance must be finite and non-negative")
        value = balance * rates[currency]
        cash_total += value
        cash_by_currency[currency] += value
        cash_by_account[account_id] += value
        converted_cash.append({
            "cash_id": cash_id,
            "account_id": account_id,
            "source_ref": source_ref,
            "currency": currency,
            "balance_base": float(value),
        })

    converted_obligations: list[dict[str, Any]] = []
    obligation_ids: set[str] = set()
    liabilities_total = Decimal(0)
    liabilities_by_currency: dict[str, Decimal] = defaultdict(Decimal)
    for index, raw in enumerate(raw_obligations):
        label = f"obligations[{index}]"
        if not isinstance(raw, Mapping):
            raise PortfolioAuditError(f"{label} must be an object")
        obligation_id = _required_text(raw, "obligation_id", label)
        if obligation_id in obligation_ids:
            raise PortfolioAuditError(f"duplicate obligation_id: {obligation_id}")
        obligation_ids.add(obligation_id)
        account_id = _required_text(raw, "account_id", label)
        source_ref = _required_text(raw, "source_ref", label)
        due_date = _required_text(raw, "due_date", label)
        try:
            date.fromisoformat(due_date)
        except ValueError as exc:
            raise PortfolioAuditError(f"{label}.due_date must be YYYY-MM-DD") from exc
        status = _required_text(raw, "status", label).upper()
        if status != "PENDING":
            raise PortfolioAuditError(f"{label}.status must be PENDING for an auditable obligation")
        currency = _required_text(raw, "currency", label).upper()
        if currency not in rates:
            raise PortfolioAuditError(f"missing FX rate for {currency}")
        amount = _decimal(raw.get("amount"), f"{label}.amount", positive=True)
        value = amount * rates[currency]
        liabilities_total += value
        liabilities_by_currency[currency] += value
        converted_obligations.append({
            "obligation_id": obligation_id,
            "account_id": account_id,
            "source_ref": source_ref,
            "due_date": due_date,
            "currency": currency,
            "status": status,
            "amount_base": float(value),
        })
    for index, raw in enumerate(raw_positions):
        label = f"positions[{index}]"
        if not isinstance(raw, Mapping):
            raise PortfolioAuditError(f"{label} must be an object")
        position_id = _required_text(raw, "position_id", label)
        if position_id in seen:
            raise PortfolioAuditError(f"duplicate position_id: {position_id}")
        seen.add(position_id)
        source_ref = _required_text(raw, "source_ref", label)
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
            "source_ref": source_ref,
            "currency": currency,
            "market_value_base": value,
            "classifications": groups,
        })
        risk_positions.append({
            "position_id": position_id,
            "currency": currency,
            "market_value_base": value,
            "risk_profile": raw.get("risk_profile"),
        })

    def pct(value: Decimal, denominator: Decimal) -> float:
        if denominator <= 0:
            return 0.0
        return round(float(value / denominator * 100), 4)

    def share(value: Decimal, denominator: Decimal) -> float:
        if denominator <= 0:
            return 0.0
        return round(float(value / denominator * 100), 4)

    gross_assets = total_value + cash_total
    net_asset_value = gross_assets - liabilities_total
    risk_report = assess_risk_v21(
        snapshot,
        risk_positions,
        total_market_value=total_value,
        gross_assets=gross_assets,
        as_of=as_of_date,
    )

    return {
        "as_of": as_of,
        "base_currency": base,
        "fx_to_base": {currency: str(rate) for currency, rate in sorted(rates.items())},
        "fx_provenance": fx_provenance,
        "audit_scope": (
            "CAPITAL_AND_BALANCE_SHEET_EXPOSURE"
            if "cash" in snapshot or "obligations" in snapshot
            else "CAPITAL_EXPOSURE_ONLY"
        ),
        "balance_sheet_status": (
            "COMPLETE" if "cash" in snapshot and "obligations" in snapshot
            else "PARTIAL" if "cash" in snapshot or "obligations" in snapshot
            else "NOT_PROVIDED"
        ),
        "total_market_value": float(total_value),
        "cash_total_base": float(cash_total),
        "pending_obligations_total_base": float(liabilities_total),
        "gross_assets_base": float(gross_assets),
        "net_asset_value_base": float(net_asset_value),
        "cash_after_all_pending_obligations_base": float(cash_total - liabilities_total),
        "positions": [
            {**position,
             "market_value_base": float(position["market_value_base"]),
                "capital_weight_pct": pct(position["market_value_base"], total_value),
             "weight_of_gross_assets_pct": pct(position["market_value_base"], gross_assets)}
            for position in positions
        ],
        "exposures_pct": {
            dimension: {name: pct(value, total_value) for name, value in sorted(groups.items())}
            for dimension, groups in totals.items()
        },
        "cash": converted_cash,
        "cash_exposure_pct": {
            "currency": {name: share(value, gross_assets) for name, value in sorted(cash_by_currency.items())},
            "account_id": {name: share(value, gross_assets) for name, value in sorted(cash_by_account.items())},
        },
        "pending_obligations": converted_obligations,
        "pending_obligations_pct_of_gross_assets": share(liabilities_total, gross_assets),
        "missing_classifications": missing,
        "status": "REVIEW" if missing else "COMPLETE",
        "allocation_authorized": False,
        "liabilities_exposure_pct": {
            "currency": {name: share(value, gross_assets) for name, value in sorted(liabilities_by_currency.items())},
        },
        "methodology": "capital_balance_sheet_exposure_v1",
        **risk_report,
    }
