"""Evidence-driven calculations for Risk Audit v2.1.

Risk evidence is supplied by a private portfolio snapshot. This module never
fills missing risk inputs with defaults and never authorizes an allocation.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


RATE_SHOCKS_BPS = (100, 300, 500)
CREDIT_SPREAD_SHOCKS_BPS = (100, 300, 500)
GLOBAL_EQUITY_SHOCK_PCT = -20
_SIZING_LIMITS = (
    "risk_capacity_limit_pct",
    "opportunity_limit_pct",
    "portfolio_limit_pct",
    "liquidity_limit_pct",
    "architecture_limit_pct",
)
_FIXED_INCOME = {"SOVEREIGN_DEBT", "CORPORATE_DEBT", "FIXED_INCOME"}
_EQUITY = {"EQUITY", "ETF"}
_SUPPORTED_INSTRUMENT_TYPES = _FIXED_INCOME | _EQUITY | {"CASH"}
_RISK_PROFILE_SCHEMA_VERSION = "1.0"


def assess_risk_v21(
    snapshot: Mapping[str, Any],
    positions: list[Mapping[str, Any]],
    *,
    total_market_value: Decimal,
    gross_assets: Decimal,
    as_of: date,
) -> dict[str, Any]:
    """Calculate only risk values supported by dated, sourced snapshot data."""
    position_reports: list[dict[str, Any]] = []
    missing_domains: set[str] = set()
    scenario_rows: dict[str, list[dict[str, Any]]] = {}
    credit_expected_loss = Decimal(0)
    credit_expected_loss_complete = True
    risk_scores: list[tuple[str, Decimal]] = []
    risk_score_complete = True
    sizing: list[dict[str, Any]] = []

    for position in positions:
        profile = position.get("risk_profile")
        if not isinstance(profile, Mapping):
            profile = {}
        profile_version = profile.get("schema_version")
        profile_supported = profile_version == _RISK_PROFILE_SCHEMA_VERSION
        risk_profile = profile if profile_supported else {}
        if profile_supported:
            kind = str(risk_profile.get("instrument_type", "UNKNOWN")).strip().upper()
            metrics = risk_profile.get("metrics")
            metrics = metrics if isinstance(metrics, Mapping) else {}
        else:
            kind = "UNKNOWN"
            metrics = {}
        position_id = str(position.get("position_id", "UNKNOWN"))
        value = _as_decimal(position.get("market_value_base")) or Decimal(0)
        if kind not in _SUPPORTED_INSTRUMENT_TYPES:
            kind = "UNKNOWN"

        metric_report: dict[str, Any] = {}
        for name, raw in metrics.items():
            metric_report[str(name)] = _read_evidence(raw, as_of)

        market = _market_risk(kind, metrics, as_of)
        if market["status"] != "ASSESSED":
            missing_domains.add("market_risk_duration_convexity_volatility_beta")

        credit = _credit_risk(kind, metrics, as_of, value, risk_profile)
        if credit["applicable"]:
            if credit["status"] == "ASSESSED":
                credit_expected_loss += Decimal(str(credit["expected_loss_base"]))
            else:
                credit_expected_loss_complete = False
                missing_domains.add("credit_default_recovery_risk")

        liquidity = _liquidity_risk(metrics, as_of)
        if liquidity["status"] != "ASSESSED":
            missing_domains.add("liquidity_under_normal_and_stress")

        currency = _currency_risk(position, risk_profile, value, as_of)
        if currency["status"] != "ASSESSED":
            missing_domains.add("nominal_and_economic_currency_risk")

        inflation = _evidence_domain(
            metrics,
            ("inflation_sensitivity_pct", "real_purchasing_power_delta_pct"),
            as_of,
        )
        if inflation["status"] != "ASSESSED":
            missing_domains.add("inflation_and_real_purchasing_power")

        permanent_loss = _permanent_loss(risk_profile, as_of)
        if permanent_loss["status"] != "ASSESSED":
            missing_domains.add("permanent_loss_risk")

        risk_score = _risk_contribution(position_id, value, total_market_value, metrics, as_of)
        if risk_score is None:
            risk_score_complete = False
            missing_domains.add("asset_specific_risk_contribution")
        else:
            risk_scores.append((position_id, risk_score))

        sizing.append(_position_sizing(position_id, risk_profile, as_of))
        profile_scenarios = risk_profile.get("scenario_returns_pct")
        profile_scenarios = profile_scenarios if isinstance(profile_scenarios, Mapping) else {}
        for scenario_id, evidence in profile_scenarios.items():
            parsed = _read_evidence(evidence, as_of, expected_unit="percent")
            scenario_rows.setdefault(str(scenario_id), []).append({
                "position_id": position_id,
                "market_value_base": float(value),
                "return_pct": parsed["value"],
                "status": parsed["status"],
                "source_ref": parsed.get("source_ref"),
                "as_of": parsed.get("as_of"),
            })

        position_reports.append({
            "position_id": position_id,
            "risk_profile_schema_version": profile_version,
            "risk_profile_schema_status": "SUPPORTED" if profile_supported else "UNKNOWN",
            "instrument_type": kind,
            "market_risk": market,
            "credit_risk": credit,
            "liquidity_risk": liquidity,
            "currency_risk": currency,
            "inflation_risk": inflation,
            "permanent_loss_risk": permanent_loss,
            "risk_metrics_evidence": metric_report,
        })

    scenarios = _scenario_analysis(positions, scenario_rows, gross_assets, as_of)
    for scenario in scenarios:
        if scenario["status"] != "ASSESSED":
            missing_domains.add("interest_rate_credit_argentina_equity_and_combined_scenarios")

    correlation = _correlation_report(snapshot, positions, as_of)
    if correlation["status"] != "ASSESSED":
        missing_domains.add("factor_correlation_and_return_stream_overlap")

    contributions = _normalize_risk_contributions(risk_scores, risk_score_complete)
    risk_budget = _risk_budget(snapshot, as_of)
    sizing_complete = bool(sizing) and all(row["status"] == "ASSESSED" for row in sizing)
    if not risk_budget["status"] == "ASSESSED":
        missing_domains.add("risk_capacity_budget_and_position_sizing_limits")
    elif not sizing_complete:
        missing_domains.add("risk_capacity_budget_and_position_sizing_limits")

    any_input = any(isinstance(pos.get("risk_profile"), Mapping) for pos in positions)
    status = "ASSESSED" if any_input and not missing_domains else "PARTIAL" if any_input else "NOT_ASSESSED"
    return {
        "risk_audit_status": status,
        "risk_dimensions_not_assessed": sorted(missing_domains) if status != "ASSESSED" else [],
        "risk_audit_methodology": "risk_audit_v2_1_evidence_driven_v1",
        "risk_positions": position_reports,
        "credit_expected_loss_base": float(credit_expected_loss) if credit_expected_loss_complete else None,
        "credit_expected_loss_status": "ASSESSED" if credit_expected_loss_complete else "PARTIAL",
        "correlation_and_return_streams": correlation,
        "scenarios": scenarios,
        "risk_contributions": contributions,
        "risk_budget": risk_budget,
        "position_sizing": sizing,
        "allocation_authorized": False,
    }


def _as_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _valid_source_date(value: Mapping[str, Any], as_of: date) -> bool:
    source_ref = value.get("source_ref")
    try:
        evidence_date = date.fromisoformat(str(value.get("as_of", "")))
    except ValueError:
        return False
    return isinstance(source_ref, str) and bool(source_ref.strip()) and evidence_date <= as_of


def _read_evidence(
    evidence: Any,
    as_of: date,
    *,
    expected_unit: str | None = None,
) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        return {"value": None, "status": "UNKNOWN", "reason": "EVIDENCE_MISSING"}
    value = _as_decimal(evidence.get("value"))
    unit = str(evidence.get("unit", "")).strip()
    source_ref = evidence.get("source_ref")
    date_text = evidence.get("as_of")
    try:
        evidence_date = date.fromisoformat(str(date_text))
    except (TypeError, ValueError):
        evidence_date = None
    if value is None or not unit or not isinstance(source_ref, str) or not source_ref.strip() or evidence_date is None:
        return {"value": None, "status": "UNKNOWN", "reason": "EVIDENCE_INCOMPLETE"}
    if evidence_date > as_of:
        return {"value": None, "status": "UNKNOWN", "reason": "EVIDENCE_AFTER_SNAPSHOT"}
    if expected_unit and unit != expected_unit:
        return {"value": None, "status": "UNKNOWN", "reason": "UNIT_MISMATCH"}
    return {
        "value": float(value),
        "unit": unit,
        "as_of": evidence_date.isoformat(),
        "source_ref": source_ref.strip(),
        "status": "ASSESSED",
    }


def _metric(metrics: Mapping[str, Any], key: str, as_of: date, unit: str) -> Decimal | None:
    item = _read_evidence(metrics.get(key), as_of, expected_unit=unit)
    return _as_decimal(item.get("value")) if item["status"] == "ASSESSED" else None


def _market_risk(kind: str, metrics: Mapping[str, Any], as_of: date) -> dict[str, Any]:
    if kind in _FIXED_INCOME:
        duration_key = "effective_duration_years" if metrics.get("effective_duration_years") else "modified_duration_years"
        duration = _metric(metrics, duration_key, as_of, "years")
        convexity = _metric(metrics, "convexity", as_of, "years_squared")
        volatility = _metric(metrics, "annualized_volatility_pct", as_of, "percent")
        if duration is None or duration < 0:
            return {"status": "UNKNOWN", "duration_years": None, "convexity": None}
        return {
            "status": "ASSESSED" if convexity is not None and volatility is not None else "PARTIAL",
            "duration_method": duration_key,
            "duration_years": float(duration),
            "convexity": float(convexity) if convexity is not None else None,
            "volatility_pct": float(volatility) if volatility is not None else None,
            "beta_global_equity": None,
        }
    if kind in _EQUITY:
        beta = _metric(metrics, "beta_global_equity", as_of, "ratio")
        volatility = _metric(metrics, "annualized_volatility_pct", as_of, "percent")
        return {
            "status": "ASSESSED" if beta is not None and volatility is not None else "PARTIAL",
            "duration_years": None,
            "convexity": None,
            "volatility_pct": float(volatility) if volatility is not None else None,
            "beta_global_equity": float(beta) if beta is not None else None,
        }
    return {"status": "UNKNOWN", "duration_years": None, "convexity": None, "volatility_pct": None, "beta_global_equity": None}


def _metric_float(metrics: Mapping[str, Any], key: str, as_of: date, unit: str) -> float | None:
    value = _metric(metrics, key, as_of, unit)
    return float(value) if value is not None else None


def _credit_risk(kind: str, metrics: Mapping[str, Any], as_of: date, value: Decimal, profile: Mapping[str, Any]) -> dict[str, Any]:
    if kind == "UNKNOWN":
        return {"applicable": True, "status": "UNKNOWN", "expected_loss_base": None}
    if kind not in _FIXED_INCOME:
        return {"applicable": False, "status": "NOT_APPLICABLE", "expected_loss_base": None}
    pd_pct = _metric(metrics, "pd_1y_pct", as_of, "percent")
    lgd_pct = _metric(metrics, "lgd_pct", as_of, "percent")
    if pd_pct is None or lgd_pct is None or not (0 <= pd_pct <= 100 and 0 <= lgd_pct <= 100):
        return {"applicable": True, "status": "UNKNOWN", "pd_1y_pct": None, "lgd_pct": None, "expected_loss_base": None}
    classification = profile.get("credit_classification")
    classification_valid = (
        isinstance(classification, Mapping)
        and bool(str(classification.get("issuer_type", "")).strip())
        and bool(str(classification.get("seniority", "")).strip())
        and bool(str(classification.get("rating", "")).strip())
        and _valid_source_date(classification, as_of)
    )
    distressed_assessment = profile.get("distressed_assessment")
    distressed: bool | None = None
    if isinstance(distressed_assessment, Mapping) and _valid_source_date(distressed_assessment, as_of):
        if isinstance(distressed_assessment.get("value"), bool):
            distressed = distressed_assessment["value"]
    recovery_status = "UNKNOWN"
    recovery_report: dict[str, Any] | None = None
    if distressed is False:
        recovery_status = "NOT_APPLICABLE"
    elif distressed is True:
        recovery = profile.get("recovery_analysis")
        required = (
            "enterprise_value_base", "senior_debt_base", "secured_debt_base",
            "unsecured_debt_base", "priority_obligations_base", "assets_available_base",
            "recovery_min_pct", "recovery_base_pct", "recovery_optimistic_pct",
        )
        recovery_values: dict[str, float] = {}
        for field in required:
            unit = "percent" if field.endswith("_pct") else "base_currency"
            item = _read_evidence(recovery.get(field) if isinstance(recovery, Mapping) else None, as_of, expected_unit=unit)
            if item["status"] == "ASSESSED":
                recovery_values[field] = float(item["value"])
        if (
            len(recovery_values) != len(required)
            or not 0 <= recovery_values.get("recovery_min_pct", -1)
            <= recovery_values.get("recovery_base_pct", -1)
            <= recovery_values.get("recovery_optimistic_pct", -1) <= 100
        ):
            recovery_status = "UNKNOWN"
        else:
            recovery_status = "ASSESSED"
            recovery_report = {
                "status": "ASSESSED",
                "waterfall_base": {
                    field: recovery_values[field]
                    for field in required
                    if not field.endswith("_pct")
                },
                "recovery_scenarios_pct": {
                    "minimum": recovery_values["recovery_min_pct"],
                    "base": recovery_values["recovery_base_pct"],
                    "optimistic": recovery_values["recovery_optimistic_pct"],
                },
                "unit": "base_currency_and_percent",
            }
    expected = value * pd_pct / Decimal(100) * lgd_pct / Decimal(100)
    return {
        "applicable": True,
        "status": "ASSESSED" if classification_valid and recovery_status in {"NOT_APPLICABLE", "ASSESSED"} else "PARTIAL",
        "pd_1y_pct": float(pd_pct),
        "lgd_pct": float(lgd_pct),
        "expected_loss_base": float(expected),
        "classification_status": "ASSESSED" if classification_valid else "UNKNOWN",
        "recovery_analysis_status": recovery_status,
        "recovery_analysis": recovery_report,
        "methodology": "pd_times_lgd_v1",
    }


def _liquidity_risk(metrics: Mapping[str, Any], as_of: date) -> dict[str, Any]:
    keys = {
        "avg_daily_dollar_volume": "USD",
        "bid_ask_spread_bps": "basis_points",
        "market_depth_base": "USD",
        "liquidity_under_stress_pct": "percent",
    }
    values = {key: _metric_float(metrics, key, as_of, unit) for key, unit in keys.items()}
    available = sum(value is not None for value in values.values())
    values["measurements_status"] = "ASSESSED" if available == len(keys) else "PARTIAL" if available else "UNKNOWN"
    values["status"] = "PARTIAL" if available else "UNKNOWN"
    # No High/Medium/Low classification is created without an approved limit.
    values["classification"] = "UNKNOWN"
    return values


def _currency_risk(position: Mapping[str, Any], profile: Mapping[str, Any], value: Decimal, as_of: date) -> dict[str, Any]:
    nominal = str(position.get("currency", "")).strip().upper()
    economic = profile.get("economic_currency_exposures")
    if not nominal or not isinstance(economic, list) or not economic:
        return {"status": "PARTIAL", "nominal_currency": nominal or "UNKNOWN", "economic_exposures": []}
    rows = []
    total = Decimal(0)
    for item in economic:
        if not isinstance(item, Mapping):
            continue
        currency = str(item.get("currency", "")).strip().upper()
        exposure = _read_evidence(item.get("exposure_pct"), as_of, expected_unit="percent")
        exposure_value = _as_decimal(exposure.get("value")) if exposure["status"] == "ASSESSED" else None
        if not currency or exposure_value is None or exposure_value < 0:
            continue
        total += exposure_value
        rows.append({"currency": currency, "exposure_pct": float(exposure_value), "source_ref": exposure["source_ref"], "as_of": exposure["as_of"]})
    if not rows or total != Decimal(100):
        return {"status": "PARTIAL", "nominal_currency": nominal, "market_value_base": float(value), "economic_exposures": rows, "reason": "ECONOMIC_EXPOSURES_MUST_SUM_TO_100_PERCENT"}
    return {"status": "ASSESSED", "nominal_currency": nominal, "market_value_base": float(value), "economic_exposures": rows}


def _evidence_domain(metrics: Mapping[str, Any], keys: tuple[str, ...], as_of: date) -> dict[str, Any]:
    values = {key: _read_evidence(metrics.get(key), as_of, expected_unit="percent") for key in keys}
    complete = all(value["status"] == "ASSESSED" for value in values.values())
    return {"status": "ASSESSED" if complete else "UNKNOWN", "evidence": values}


def _permanent_loss(profile: Mapping[str, Any], as_of: date) -> dict[str, Any]:
    assessment = profile.get("permanent_loss_assessment")
    if not isinstance(assessment, Mapping):
        return {"status": "UNKNOWN", "level": "UNKNOWN", "reason": "MANAGER_ASSESSMENT_MISSING"}
    level = str(assessment.get("level", "")).upper()
    if level not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        return {"status": "UNKNOWN", "level": "UNKNOWN", "reason": "INVALID_LEVEL"}
    evidence = _read_evidence({**assessment, "value": 1, "unit": "categorical"}, as_of)
    reviewer = assessment.get("reviewer")
    if evidence["status"] != "ASSESSED" or not isinstance(reviewer, str) or not reviewer.strip() or not str(assessment.get("rationale", "")).strip():
        return {"status": "UNKNOWN", "level": "UNKNOWN", "reason": "REVIEWER_RATIONALE_OR_PROVENANCE_MISSING"}
    return {"status": "ASSESSED", "level": level, "reviewer": reviewer.strip(), "rationale": str(assessment["rationale"]).strip(), "source_ref": evidence["source_ref"], "as_of": evidence["as_of"]}


def _scenario_analysis(
    positions: list[Mapping[str, Any]],
    direct_rows: Mapping[str, list[dict[str, Any]]],
    gross_assets: Decimal,
    as_of: date,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    definitions = [*(('INTEREST_RATE_UP', shock) for shock in RATE_SHOCKS_BPS), *(('CREDIT_SPREAD_UP', shock) for shock in CREDIT_SPREAD_SHOCKS_BPS), ('GLOBAL_EQUITY_CRASH', GLOBAL_EQUITY_SHOCK_PCT)]
    by_id = {str(position.get("position_id", "UNKNOWN")): position for position in positions}
    for family, shock in definitions:
        impacts: list[dict[str, Any]] = []
        complete = True
        for position_id, position in by_id.items():
            profile = position.get("risk_profile") if isinstance(position.get("risk_profile"), Mapping) else {}
            if profile.get("schema_version") != _RISK_PROFILE_SCHEMA_VERSION:
                complete = False
                impacts.append({"position_id": position_id, "status": "UNKNOWN", "return_pct": None, "pnl_base": None})
                continue
            kind = str(profile.get("instrument_type", "UNKNOWN")).upper()
            market_value = _as_decimal(position.get("market_value_base")) or Decimal(0)
            metrics = profile.get("metrics") if isinstance(profile.get("metrics"), Mapping) else {}
            return_pct: Decimal | None = None
            if family == "INTEREST_RATE_UP" and kind in _FIXED_INCOME:
                duration_key = "effective_duration_years" if metrics.get("effective_duration_years") else "modified_duration_years"
                duration = _metric(metrics, duration_key, as_of, "years")
                convexity = _metric(metrics, "convexity", as_of, "years_squared")
                if duration is not None and convexity is not None and duration >= 0 and convexity >= 0:
                    dy = Decimal(shock) / Decimal(10000)
                    return_pct = (-duration * dy + Decimal("0.5") * convexity * dy * dy) * 100
            elif family == "CREDIT_SPREAD_UP" and kind in _FIXED_INCOME:
                duration = _metric(metrics, "spread_duration_years", as_of, "years")
                if duration is not None:
                    return_pct = -duration * Decimal(shock) / Decimal(100)
            elif family == "GLOBAL_EQUITY_CRASH" and kind in _EQUITY:
                beta = _metric(metrics, "beta_global_equity", as_of, "ratio")
                if beta is not None:
                    return_pct = beta * Decimal(shock)
            else:
                direct = profile.get("scenario_returns_pct")
                direct = direct if isinstance(direct, Mapping) else {}
                direct_key = f"{family}_{shock}"
                direct_value = _metric(direct, direct_key, as_of, "percent")
                if direct_value is not None:
                    return_pct = direct_value
            if return_pct is None:
                complete = False
                impacts.append({"position_id": position_id, "status": "UNKNOWN", "return_pct": None, "pnl_base": None})
            else:
                pnl = market_value * return_pct / Decimal(100)
                impacts.append({"position_id": position_id, "status": "ASSESSED", "return_pct": round(float(return_pct), 6), "pnl_base": round(float(pnl), 4)})
        total_pnl = sum((_as_decimal(item.get("pnl_base")) or Decimal(0) for item in impacts), Decimal(0))
        output.append({
            "scenario_id": f"{family}_{shock}",
            "shock": shock,
            "shock_unit": "basis_points" if family != "GLOBAL_EQUITY_CRASH" else "percent",
            "status": "ASSESSED" if complete else "PARTIAL",
            "total_pnl_base": round(float(total_pnl), 4) if complete else None,
            "nav_impact_pct": round(float(total_pnl / gross_assets * 100), 6) if complete and gross_assets > 0 else None,
            "positions": impacts,
            "interpretation": "Sensitivity only; not a forecast.",
        })
    for scenario_id in ("ARGENTINA_STRESS", "SEVERE_COMBINED_STRESS"):
        rows = direct_rows.get(scenario_id, [])
        by_position = {row["position_id"]: row for row in rows}
        impacts = []
        complete = True
        for position_id, position in by_id.items():
            row = by_position.get(position_id)
            if not row or row["status"] != "ASSESSED":
                complete = False
                impacts.append({"position_id": position_id, "status": "UNKNOWN", "return_pct": None, "pnl_base": None})
                continue
            value = _as_decimal(position.get("market_value_base")) or Decimal(0)
            ret = Decimal(str(row["return_pct"]))
            pnl = value * ret / Decimal(100)
            impacts.append({"position_id": position_id, "status": "ASSESSED", "return_pct": ret, "pnl_base": round(float(pnl), 4)})
        total_pnl = sum((_as_decimal(item.get("pnl_base")) or Decimal(0) for item in impacts), Decimal(0))
        output.append({"scenario_id": scenario_id, "status": "ASSESSED" if complete else "PARTIAL", "total_pnl_base": round(float(total_pnl), 4) if complete else None, "nav_impact_pct": round(float(total_pnl / gross_assets * 100), 6) if complete and gross_assets > 0 else None, "positions": impacts, "interpretation": "Sensitivity only; not a forecast."})
    return output


def _correlation_report(snapshot: Mapping[str, Any], positions: list[Mapping[str, Any]], as_of: date) -> dict[str, Any]:
    rows = snapshot.get("correlations")
    if not isinstance(rows, list) or not rows:
        profile = positions[0].get("risk_profile") if len(positions) == 1 else None
        if isinstance(profile, Mapping) and profile.get("schema_version") == _RISK_PROFILE_SCHEMA_VERSION and profile.get("return_stream_id"):
            return {"status": "ASSESSED", "return_stream_count": 1, "correlations": [], "reason": "SINGLE_RETURN_STREAM"}
        return {"status": "UNKNOWN", "return_stream_count": None, "correlations": [], "reason": "CORRELATION_MATRIX_MISSING"}
    known = {str(pos.get("position_id")) for pos in positions}
    results = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        left, right = str(row.get("position_id_a", "")), str(row.get("position_id_b", ""))
        evidence = _read_evidence({"value": row.get("value"), "unit": "ratio", "as_of": row.get("as_of"), "source_ref": row.get("source_ref")}, as_of, expected_unit="ratio")
        value = _as_decimal(evidence.get("value")) if evidence["status"] == "ASSESSED" else None
        if left not in known or right not in known or left == right or value is None or abs(value) > 1:
            continue
        results.append({"position_id_a": left, "position_id_b": right, "correlation": float(value), "as_of": evidence["as_of"], "source_ref": evidence["source_ref"]})
    streams = {
        str(profile.get("return_stream_id"))
        for pos in positions
        if isinstance((profile := pos.get("risk_profile")), Mapping)
        and profile.get("schema_version") == _RISK_PROFILE_SCHEMA_VERSION
        and profile.get("return_stream_id")
    }
    has_single_stream = len(positions) == 1 and bool(streams)
    status = "ASSESSED" if has_single_stream or (results and len(results) == len(rows)) else "PARTIAL" if results else "UNKNOWN"
    return {"status": status, "return_stream_count": len(streams) if streams else None, "correlations": results}


def _risk_contribution(position_id: str, value: Decimal, total: Decimal, metrics: Mapping[str, Any], as_of: date) -> Decimal | None:
    intensity = _metric(metrics, "risk_intensity", as_of, "ratio")
    adjustment = _metric(metrics, "correlation_adjustment", as_of, "ratio")
    if total <= 0 or intensity is None or adjustment is None or intensity < 0 or adjustment < 0:
        return None
    return value / total * intensity * adjustment


def _normalize_risk_contributions(rows: list[tuple[str, Decimal]], complete: bool) -> dict[str, Any]:
    total = sum((score for _, score in rows), Decimal(0))
    if not complete or not rows or total <= 0:
        return {"status": "UNKNOWN", "methodology": "capital_weight_times_risk_intensity_times_correlation_adjustment_v1", "positions": []}
    return {
        "status": "ASSESSED",
        "methodology": "capital_weight_times_risk_intensity_times_correlation_adjustment_v1",
        "positions": [{"position_id": position_id, "contribution_pct": round(float(score / total * 100), 6)} for position_id, score in rows],
    }


def _risk_budget(snapshot: Mapping[str, Any], as_of: date) -> dict[str, Any]:
    raw = snapshot.get("risk_budget")
    if not isinstance(raw, Mapping):
        return {"status": "UNKNOWN", "available_base": None, "reason": "RISK_CAPACITY_BUDGET_MISSING"}
    capacity = _read_evidence(raw.get("capacity_base"), as_of, expected_unit="base_currency")
    used = _read_evidence(raw.get("used_base"), as_of, expected_unit="base_currency")
    capacity_value = _as_decimal(capacity.get("value")) if capacity["status"] == "ASSESSED" else None
    used_value = _as_decimal(used.get("value")) if used["status"] == "ASSESSED" else None
    if capacity_value is None or used_value is None or capacity_value < 0 or used_value < 0:
        return {"status": "UNKNOWN", "available_base": None, "reason": "RISK_BUDGET_EVIDENCE_INCOMPLETE"}
    return {"status": "ASSESSED", "capacity_base": float(capacity_value), "used_base": float(used_value), "available_base": float(capacity_value - used_value), "unit": "base_currency"}


def _position_sizing(position_id: str, profile: Mapping[str, Any], as_of: date) -> dict[str, Any]:
    limits = profile.get("allocation_limits")
    limits = limits if isinstance(limits, Mapping) else {}
    parsed = {name: _read_evidence(limits.get(name), as_of, expected_unit="percent") for name in _SIZING_LIMITS}
    complete = all(item["status"] == "ASSESSED" and 0 <= float(item["value"]) <= 100 for item in parsed.values())
    final = min(float(item["value"]) for item in parsed.values()) if complete else None
    return {"position_id": position_id, "status": "ASSESSED" if complete else "BLOCKED", "limits_pct": {name: item["value"] for name, item in parsed.items()}, "final_weight_limit_pct": final, "methodology": "minimum_of_five_limits_v1"}
