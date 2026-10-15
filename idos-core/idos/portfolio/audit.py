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

    argentina_direct = Decimal(0)
    argentina_indirect = Decimal(0)
    missing_indirect: list[str] = []
    for position, raw in zip(positions, raw_positions):
        if str(raw.get("country", "")).strip().upper() == "AR":
            argentina_direct += position["market_value_base"]
        else:
            if "argentina_indirect_exposure_pct" not in raw:
                missing_indirect.append(position["position_id"])
            else:
                exposure_pct = _decimal(raw["argentina_indirect_exposure_pct"],
                                        f"positions.{position['position_id']}.argentina_indirect_exposure_pct")
                if exposure_pct < 0 or exposure_pct > 100:
                    raise PortfolioAuditError("argentina_indirect_exposure_pct must be between 0 and 100")
                argentina_indirect += position["market_value_base"] * exposure_pct / Decimal(100)

    def pct(value: Decimal) -> float:
        return round(float(value / total_value * 100), 4)

    report = {
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
    report["risk_audit"] = _audit_risk_scenarios(snapshot, positions, total_value)
    argentina_total = argentina_direct + argentina_indirect
    report["risk_audit"]["argentina_exposure"] = {
        "direct_base": round(float(argentina_direct), 8),
        "indirect_base": round(float(argentina_indirect), 8),
        "total_base": round(float(argentina_total), 8),
        "direct_pct_invested": round(float(argentina_direct / total_value * 100), 6),
        "indirect_pct_invested": round(float(argentina_indirect / total_value * 100), 6),
        "total_pct_invested": round(float(argentina_total / total_value * 100), 6),
        "missing_indirect_classification_position_ids": missing_indirect,
        "status": "REVIEW" if missing_indirect else "COMPLETE",
        "limit_status": "UNKNOWN_POLICY_NOT_CONFIGURED",
    }
    report["risk_audit"]["financial_scenario_status"] = report["risk_audit"].pop("status")
    report["risk_audit"]["status"] = "REVIEW"
    report["risk_audit"]["completeness_gaps"] = [
        "illiquid assets, local income, businesses and total liabilities are not present in this snapshot",
        "family risk limits and risk budget are not configured",
    ]
    for field in ("snapshot_id", "source_version"):
        if field in snapshot:
            report[field] = _required_text(snapshot, field, "snapshot")
    if "cash" in snapshot or "obligations" in snapshot:
        report["liquidity"] = _audit_liquidity(snapshot, rates, as_of, total_value)
    return report


_ARGENTINA_SCENARIOS = {
    "sovereign_spread_100bps": {"driver": "sovereign_spread_bps", "sensitivity": "sovereign_spread_duration_years", "shock": 100},
    "sovereign_spread_300bps": {"driver": "sovereign_spread_bps", "sensitivity": "sovereign_spread_duration_years", "shock": 300},
    "sovereign_spread_500bps": {"driver": "sovereign_spread_bps", "sensitivity": "sovereign_spread_duration_years", "shock": 500},
    "fx_stress": {"driver": "fx_move_pct", "sensitivity": "fx_sensitivity_pct_per_100pct_move"},
    "extreme_inflation": {"driver": "inflation_shock_pct", "sensitivity": "inflation_sensitivity_pct_per_100pct_shock"},
    "ars_liquidity": {"driver": "ars_liquidity_haircut_pct", "sensitivity": "ars_liquidity_exposure_fraction"},
    "default_restructuring": {"driver": "default_loss_pct", "sensitivity": "default_loss_exposure_fraction"},
}


def _audit_risk_scenarios(snapshot: Mapping[str, Any], positions: list[dict[str, Any]],
                          total_value: Decimal) -> dict[str, Any]:
    """Apply configured Argentina stress shocks to explicitly supplied sensitivities.

    Sensitivities live on each source position under ``risk_sensitivities``;
    scenario shocks live in ``risk_scenarios``. Missing inputs are UNKNOWN.
    No asset-class or family-level risk is inferred from capital weights.
    """
    raw_scenarios = snapshot.get("risk_scenarios", {})
    if not isinstance(raw_scenarios, Mapping):
        raise PortfolioAuditError("snapshot.risk_scenarios must be an object")
    scenario_sources = snapshot.get("risk_scenario_sources", {})
    if not isinstance(scenario_sources, Mapping):
        raise PortfolioAuditError("snapshot.risk_scenario_sources must be an object")
    source_positions = {p["position_id"]: p for p in snapshot["positions"]}
    results: dict[str, Any] = {}
    unknown: list[dict[str, str]] = []

    for name, definition in _ARGENTINA_SCENARIOS.items():
        driver = definition["driver"]
        sensitivity_key = definition["sensitivity"]
        shock = definition.get("shock", raw_scenarios.get(name))
        if shock is None:
            results[name] = {"status": "UNKNOWN", "reason": f"missing shock: {name}"}
            unknown.append({"scenario": name, "field": f"risk_scenarios.{name}"})
            continue
        shock_value = _decimal(shock, f"risk_scenarios.{name}")
        if "shock" not in definition:
            source = scenario_sources.get(name)
            if not isinstance(source, str) or not source.strip():
                raise PortfolioAuditError(f"risk_scenario_sources.{name} is required")
        impact = Decimal(0)
        missing_positions: list[str] = []
        for position in positions:
            source = source_positions[position["position_id"]]
            sensitivity = source.get("risk_sensitivities", {})
            if not isinstance(sensitivity, Mapping) or sensitivity_key not in sensitivity:
                missing_positions.append(position["position_id"])
                continue
            coefficient = _decimal(sensitivity[sensitivity_key],
                                   f"positions.{position['position_id']}.risk_sensitivities.{sensitivity_key}")
            source_ref = source.get("risk_source_ref")
            if not isinstance(source_ref, str) or not source_ref.strip():
                raise PortfolioAuditError(
                    f"positions.{position['position_id']}.risk_source_ref is required"
                )
            value = position["market_value_base"]
            if driver == "sovereign_spread_bps":
                position_impact = -value * coefficient * shock_value / Decimal(10000)
            elif driver in ("fx_move_pct", "inflation_shock_pct"):
                position_impact = value * coefficient * shock_value / Decimal(10000)
            else:
                position_impact = -value * coefficient * shock_value / Decimal(100)
            impact += position_impact
        if missing_positions:
            results[name] = {"status": "UNKNOWN", "shock": float(shock_value),
                             "missing_position_ids": missing_positions}
            unknown.extend({"scenario": name, "position_id": pid} for pid in missing_positions)
        else:
            results[name] = {"status": "CALCULATED", "shock": float(shock_value),
                             "impact_base": round(float(impact), 8),
                             "impact_pct_invested": round(float(impact / total_value * 100), 6)}

    return {
        "status": "REVIEW" if unknown else "COMPLETE",
        "scenarios": results,
        "unknown_inputs": unknown,
        "allocation_authorized": False,
        "methodology": "configured_sensitivity_v1",
        "scope": "financial_positions_only; excludes illiquid_assets_income_and_unrecorded_liabilities",
    }


def _audit_liquidity(snapshot: Mapping[str, Any], rates: Mapping[str, Decimal],
                     as_of: str, invested_value: Decimal) -> dict[str, Any]:
    """Summarize cash and pending liabilities outside investment exposure weights."""
    cash_rows = snapshot.get("cash", [])
    obligations = snapshot.get("obligations", [])
    if not isinstance(cash_rows, list) or not isinstance(obligations, list):
        raise PortfolioAuditError("snapshot.cash and snapshot.obligations must be lists")
    cash_ids: set[str] = set()
    obligation_ids: set[str] = set()
    cash_total = Decimal(0)
    liability_total = Decimal(0)
    cash_by_currency: dict[str, Decimal] = defaultdict(Decimal)
    due_buckets = {"overdue": Decimal(0), "within_30_days": Decimal(0),
                   "31_to_90_days": Decimal(0), "over_90_days": Decimal(0)}
    cutoff = date.fromisoformat(as_of)
    for index, row in enumerate(cash_rows):
        label = f"cash[{index}]"
        if not isinstance(row, Mapping):
            raise PortfolioAuditError(f"{label} must be an object")
        identifier = _required_text(row, "cash_id", label)
        if identifier in cash_ids:
            raise PortfolioAuditError(f"duplicate cash_id: {identifier}")
        cash_ids.add(identifier)
        _required_text(row, "account_id", label)
        currency = _required_text(row, "currency", label).upper()
        if currency not in rates:
            raise PortfolioAuditError(f"missing FX rate for {currency}")
        _required_text(row, "source_ref", label)
        amount = _decimal(row.get("balance"), f"{label}.balance") * rates[currency]
        cash_total += amount
        cash_by_currency[currency] += amount

    for index, row in enumerate(obligations):
        label = f"obligations[{index}]"
        if not isinstance(row, Mapping):
            raise PortfolioAuditError(f"{label} must be an object")
        identifier = _required_text(row, "obligation_id", label)
        if identifier in obligation_ids:
            raise PortfolioAuditError(f"duplicate obligation_id: {identifier}")
        obligation_ids.add(identifier)
        _required_text(row, "account_id", label)
        currency = _required_text(row, "currency", label).upper()
        if currency not in rates:
            raise PortfolioAuditError(f"missing FX rate for {currency}")
        _required_text(row, "source_ref", label)
        if _required_text(row, "status", label).upper() != "PENDING":
            raise PortfolioAuditError(f"{label}.status must be PENDING")
        try:
            due_date = date.fromisoformat(_required_text(row, "due_date", label))
        except ValueError as exc:
            raise PortfolioAuditError(f"{label}.due_date must be YYYY-MM-DD") from exc
        amount = _decimal(row.get("amount"), f"{label}.amount", positive=True) * rates[currency]
        liability_total += amount
        days = (due_date - cutoff).days
        bucket = ("overdue" if days < 0 else "within_30_days" if days <= 30
                  else "31_to_90_days" if days <= 90 else "over_90_days")
        due_buckets[bucket] += amount

    def money(value: Decimal) -> float:
        return round(float(value), 8)

    return {
        "cash_total_base": money(cash_total),
        "cash_by_currency_base": {key: money(value) for key, value in sorted(cash_by_currency.items())},
        "pending_obligations_base": money(liability_total),
        "obligations_due_base": {key: money(value) for key, value in due_buckets.items()},
        "net_liquidity_base": money(cash_total - liability_total),
        "invested_assets_base": money(invested_value),
        "financial_assets_less_obligations_base": money(invested_value + cash_total - liability_total),
        "allocation_authorized": False,
        "scope": "cash_and_pending_obligations_context; excluded_from_investment_exposure_weights",
    }
