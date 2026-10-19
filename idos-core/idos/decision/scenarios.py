"""Validated Bear/Base/Bull scenario contracts used by financial authorization."""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import math
import re
from typing import Any
from urllib.parse import urlparse


SCENARIO_IDS = ("BEAR", "BASE", "BULL")
SCENARIO_SCHEMA_VERSION = "bear_base_bull_v1"


def validate_scenario_analysis(value: Any, *, today: date | None = None) -> list[str]:
    """Return contract errors without coercing or repairing model output."""
    if not isinstance(value, dict):
        return ["scenario_analysis debe ser un objeto"]
    errors: list[str] = []
    if value.get("schema_version") != SCENARIO_SCHEMA_VERSION:
        errors.append(f"schema_version debe ser {SCENARIO_SCHEMA_VERSION}")

    as_of = _parse_date(value.get("as_of_date"))
    horizon = _parse_date(value.get("horizon_date"))
    reference_date = today or date.today()
    if as_of is None:
        errors.append("as_of_date debe ser una fecha ISO válida")
    elif as_of > reference_date:
        errors.append("as_of_date no puede estar en el futuro")
    if horizon is None:
        errors.append("horizon_date debe ser una fecha ISO válida")
    elif as_of and horizon <= as_of:
        errors.append("horizon_date debe ser posterior a as_of_date")

    currency = value.get("currency")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        errors.append("currency debe ser un código ISO 4217 en mayúsculas")

    scenarios = value.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 3:
        return errors + ["scenarios debe contener exactamente Bear, Base y Bull"]

    by_id: dict[str, dict[str, Any]] = {}
    probabilities: list[float] = []
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict):
            errors.append(f"scenarios[{index}] debe ser un objeto")
            continue
        scenario_id = scenario.get("id")
        if scenario_id not in SCENARIO_IDS:
            errors.append(f"scenarios[{index}].id debe ser BEAR, BASE o BULL")
            continue
        if scenario_id in by_id:
            errors.append(f"id de escenario duplicado: {scenario_id}")
            continue
        by_id[scenario_id] = scenario

        probability = scenario.get("probability_pct")
        if not _finite_number(probability) or not 0 <= probability <= 100:
            errors.append(f"{scenario_id}: probability_pct debe estar entre 0 y 100")
        else:
            probabilities.append(float(probability))

        target = scenario.get("target_price")
        if not _finite_number(target) or target <= 0:
            errors.append(f"{scenario_id}: target_price debe ser positivo y finito")

        sources = scenario.get("sources")
        if not isinstance(sources, list) or not sources:
            errors.append(f"{scenario_id}: se requiere al menos una fuente")
            continue
        for source_index, source in enumerate(sources):
            prefix = f"{scenario_id}.sources[{source_index}]"
            if not isinstance(source, dict) or not str(source.get("name", "")).strip():
                errors.append(f"{prefix}: name es obligatorio")
                continue
            parsed_url = urlparse(str(source.get("url", "")))
            if parsed_url.scheme != "https" or not parsed_url.netloc:
                errors.append(f"{prefix}: url debe ser HTTPS")
            source_date = _parse_date(source.get("as_of_date"))
            if source_date is None:
                errors.append(f"{prefix}: as_of_date debe ser una fecha ISO válida")
            elif as_of and source_date > as_of:
                errors.append(f"{prefix}: la fecha de fuente no puede superar as_of_date")

    if set(by_id) != set(SCENARIO_IDS):
        errors.append("debe existir exactamente un escenario BEAR, BASE y BULL")
    if len(probabilities) == 3 and not math.isclose(sum(probabilities), 100.0, abs_tol=1e-6):
        errors.append("las probabilidades deben sumar exactamente 100%")
    if all(sid in by_id and _finite_number(by_id[sid].get("target_price")) for sid in SCENARIO_IDS):
        prices = [by_id[sid]["target_price"] for sid in SCENARIO_IDS]
        if prices != sorted(prices):
            errors.append("los precios objetivo deben cumplir Bear <= Base <= Bull")
    return errors


def scenario_fingerprint(value: dict[str, Any]) -> str:
    """Hash the exact reviewed scenario assumptions, excluding derived metadata."""
    canonical = {
        "schema_version": value.get("schema_version"),
        "as_of_date": value.get("as_of_date"),
        "horizon_date": value.get("horizon_date"),
        "currency": value.get("currency"),
        "scenarios": sorted(value.get("scenarios", []), key=lambda item: str(item.get("id", ""))),
    }
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_scenario_review(
    analysis: Any,
    review: Any,
    *,
    today: date | None = None,
) -> tuple[bool, str]:
    errors = validate_scenario_analysis(analysis, today=today)
    if errors:
        return False, "; ".join(errors)
    if not isinstance(review, dict):
        return False, "el gestor aún no revisó los escenarios"
    if review.get("status") != "approved":
        return False, "los escenarios no están aprobados por el gestor"
    if review.get("scenario_hash") != scenario_fingerprint(analysis):
        return False, "la aprobación no corresponde a la versión actual de escenarios"
    if not str(review.get("reviewed_by", "")).strip():
        return False, "falta la identidad del gestor revisor"
    try:
        reviewed_timestamp = datetime.fromisoformat(str(review.get("reviewed_at", "")).replace("Z", "+00:00"))
    except ValueError:
        reviewed_timestamp = None
    reviewed_at = reviewed_timestamp.date() if reviewed_timestamp and reviewed_timestamp.tzinfo else None
    if reviewed_at is None or reviewed_at > (today or date.today()):
        return False, "la fecha de revisión es inválida"
    if len(str(review.get("note", "")).strip()) < 10:
        return False, "la revisión requiere una justificación de al menos 10 caracteres"
    return True, "escenarios vigentes aprobados por el gestor"


def calculate_scenario_asymmetry(
    analysis: dict[str, Any],
    *,
    current_price: Any,
    quote_currency: str | None,
) -> dict[str, Any]:
    """Calculate weighted upside/downside only for a validated scenario set."""
    errors = validate_scenario_analysis(analysis)
    if errors:
        return _blocked_asymmetry("; ".join(errors))
    if not _finite_number(current_price) or current_price <= 0:
        return _blocked_asymmetry("precio actual ausente o inválido")
    if not quote_currency or quote_currency != analysis.get("currency"):
        return _blocked_asymmetry("la moneda del escenario no coincide con la cotización actual")

    rows = []
    upside = 0.0
    downside = 0.0
    for scenario in analysis["scenarios"]:
        probability = float(scenario["probability_pct"]) / 100
        target = float(scenario["target_price"])
        return_pct = (target / float(current_price) - 1) * 100
        contribution = probability * return_pct
        if not math.isfinite(return_pct) or not math.isfinite(contribution):
            return _blocked_asymmetry("los retornos calculados exceden el rango numérico")
        if return_pct > 0:
            upside += contribution
        elif return_pct < 0:
            downside += contribution
        rows.append({
            "scenario": scenario["id"],
            "probability_pct": float(scenario["probability_pct"]),
            "target_price": target,
            "return_pct": round(return_pct, 2),
            "weighted_return_pct": round(contribution, 2),
            "sources": scenario["sources"],
        })

    if upside <= 0 or downside >= 0:
        return _blocked_asymmetry("se requieren resultados con upside y downside para calcular B/R")
    ratio = round(upside / abs(downside), 2)
    expected_return = round(sum(row["weighted_return_pct"] for row in rows), 2)
    return {
        "rows": rows,
        "valor_esperado": round(float(current_price) * (1 + expected_return / 100), 4),
        "retorno_esperado_pct": expected_return,
        "upside_esperado_pct": round(upside, 2),
        "downside_esperado_pct": round(downside, 2),
        "benefit_risk_ratio": ratio,
        "scenario_hash": scenario_fingerprint(analysis),
        "validation_status": "validated",
        "authorization_eligible": False,
        "validation_reason": "pendiente de aprobación del gestor",
        "passes_threshold": False,
    }


def _blocked_asymmetry(reason: str) -> dict[str, Any]:
    return {
        "rows": [],
        "benefit_risk_ratio": None,
        "validation_status": "invalid",
        "authorization_eligible": False,
        "validation_reason": reason,
        "passes_threshold": False,
    }


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
