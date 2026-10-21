"""Validated Bear/Bull scenario contracts used by financial authorization."""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import math
import re
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


SCENARIO_IDS = ("BEAR", "BASE", "BULL")
SCENARIO_SCHEMA_VERSION = "bear_bull_v2"


def scenario_source_urls_from_evidence(value: Any) -> set[str]:
    """Return source URLs supplied as structured research evidence."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return set()
    if not isinstance(value, dict):
        return set()

    urls: set[str] = set()
    for key in ("current_quote", "analyst_target_consensus"):
        evidence = value.get(key)
        sources = evidence.get("sources") if isinstance(evidence, dict) else None
        if isinstance(sources, list):
            urls.update(
                normalized for source in sources if isinstance(source, dict)
                if (normalized := _normalize_source_url(source.get("url")))
            )
    return urls


def scenario_source_urls_from_research_financial_evidence(value: Any) -> set[str]:
    """Return URLs attached to financial inputs admitted to Research."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return set()
    if not isinstance(value, dict):
        return set()

    urls: set[str] = set()
    observations = value.get("source_observations")
    if isinstance(observations, dict):
        for observation in observations.values():
            if isinstance(observation, dict):
                normalized = _normalize_source_url(observation.get("source_url"))
                if normalized:
                    urls.add(normalized)

    validated = value.get("validated_metric_observations")
    if isinstance(validated, dict):
        for metric_observations in validated.values():
            if not isinstance(metric_observations, list):
                continue
            for observation in metric_observations:
                if isinstance(observation, dict):
                    normalized = _normalize_source_url(observation.get("source_url"))
                    if normalized:
                        urls.add(normalized)
    return urls


def scenario_financial_evidence_snapshot(value: Any) -> dict[str, Any]:
    """Persist only source metadata needed to revalidate scenario citations."""
    if not isinstance(value, dict):
        return {}
    snapshot: dict[str, Any] = {
        "source_observations": {},
        "validated_metric_observations": {},
    }
    observations = value.get("source_observations")
    if isinstance(observations, dict):
        for metric, observation in observations.items():
            if not isinstance(observation, dict):
                continue
            source_url = _normalize_source_url(observation.get("source_url"))
            if not source_url:
                continue
            snapshot["source_observations"][str(metric)] = {
                "source_url": source_url,
                "unit": observation.get("unit"),
                "currency": observation.get("currency"),
                "period_type": observation.get("period_type"),
                "period_end": observation.get("period_end"),
                "sources": observation.get("sources", []),
            }
    validated = value.get("validated_metric_observations")
    if isinstance(validated, dict):
        for metric, metric_observations in validated.items():
            if not isinstance(metric_observations, list):
                continue
            rows = []
            for observation in metric_observations:
                if not isinstance(observation, dict):
                    continue
                source_url = _normalize_source_url(observation.get("source_url"))
                if not source_url:
                    continue
                rows.append({
                    "source_id": observation.get("source_id"),
                    "source_url": source_url,
                    "unit": observation.get("unit"),
                    "currency": observation.get("currency"),
                    "period": observation.get("period"),
                    "reported_at": observation.get("reported_at"),
                    "observed_at": observation.get("observed_at"),
                })
            if rows:
                snapshot["validated_metric_observations"][str(metric)] = rows
    return snapshot


def scenario_source_urls_from_report(report: Any) -> set[str]:
    """Extract the exact source URLs a DDD scenario may cite."""
    if not isinstance(report, dict):
        return set()
    snapshot = report.get("research_input_snapshot")
    if isinstance(snapshot, dict):
        urls = scenario_source_urls_from_evidence(snapshot.get("scenario_market_evidence"))
        urls.update(scenario_source_urls_from_research_financial_evidence(
            snapshot.get("scenario_financial_evidence")
        ))
        if urls:
            return urls

    consensus = report.get("target_consensus")
    sources = consensus.get("source_references") if isinstance(consensus, dict) else None
    if isinstance(sources, list):
        return {
            normalized for source in sources if isinstance(source, dict)
            if (normalized := _normalize_source_url(source.get("url")))
        }
    return set()


def _normalize_source_url(value: Any) -> str | None:
    parsed = urlparse(str(value or ""))
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        return None
    return f"https://{parsed.netloc.lower()}{parsed.path.rstrip('/')}{'?' + parsed.query if parsed.query else ''}"



def canonicalize_scenario_ticker_url_case(
    value: Any,
    *,
    ticker: str,
    trusted_source_urls: set[str],
) -> Any:
    """Repair only ticker path casing to the exact URL supplied as evidence."""
    if not isinstance(value, dict):
        return value

    import copy
    from urllib.parse import unquote

    result = copy.deepcopy(value)
    ticker_key = unquote(str(ticker)).casefold()
    scenarios = result.get("scenarios")
    if not isinstance(scenarios, list):
        return result

    trusted = sorted(url for url in trusted_source_urls if isinstance(url, str))
    for scenario in scenarios:
        sources = scenario.get("sources") if isinstance(scenario, dict) else None
        if not isinstance(sources, list):
            continue
        for source in sources:
            if not isinstance(source, dict):
                continue
            candidate = urlparse(str(source.get("url", "")))
            candidate_path = [unquote(part) for part in candidate.path.rstrip("/").split("/")]
            for trusted_url in trusted:
                supplied = urlparse(trusted_url)
                supplied_path = [unquote(part) for part in supplied.path.rstrip("/").split("/")]
                if (
                    candidate.scheme.lower() != "https"
                    or supplied.scheme.lower() != "https"
                    or candidate.netloc.lower() != supplied.netloc.lower()
                    or candidate.query != supplied.query
                    or candidate.fragment != supplied.fragment
                    or len(candidate_path) != len(supplied_path)
                ):
                    continue
                mismatches = [
                    index for index, (left, right) in enumerate(zip(candidate_path, supplied_path))
                    if left != right
                ]
                if (
                    len(mismatches) == 1
                    and candidate_path[mismatches[0]].casefold() == ticker_key
                    and supplied_path[mismatches[0]].casefold() == ticker_key
                ):
                    source["url"] = trusted_url
                    break
    return result


def validate_scenario_analysis(
    value: Any,
    *,
    today: date | None = None,
    trusted_source_urls: set[str] | None = None,
) -> list[str]:
    """Return contract errors without coercing or repairing model output."""
    if not isinstance(value, dict):
        return ["scenario_analysis debe ser un objeto"]
    errors: list[str] = []
    if value.get("schema_version") != SCENARIO_SCHEMA_VERSION:
        errors.append(f"schema_version debe ser {SCENARIO_SCHEMA_VERSION}")

    as_of = _parse_date(value.get("as_of_date"))
    horizon = _parse_date(value.get("horizon_date"))
    reference_date = today or datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date()
    if as_of is None:
        errors.append("as_of_date debe ser una fecha ISO válida")
    elif as_of > reference_date:
        errors.append("as_of_date no puede estar en el futuro")
    elif as_of < reference_date:
        errors.append("as_of_date debe coincidir con la fecha actual del análisis")
    if horizon is None:
        errors.append("horizon_date debe ser una fecha ISO válida")
    elif horizon <= reference_date:
        errors.append("horizon_date debe ser posterior a la fecha actual")
    elif as_of and horizon <= as_of:
        errors.append("horizon_date debe ser posterior a as_of_date")

    currency = value.get("currency")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        errors.append("currency debe ser un código ISO 4217 en mayúsculas")

    quantification_status = value.get("quantification_status", "validated")
    if quantification_status not in {"validated", "not_calibrated"}:
        errors.append("quantification_status debe ser validated o not_calibrated")

    scenarios = value.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) not in {2, 3}:
        return errors + ["scenarios debe contener Bear y Bull, con Base opcional"]

    by_id: dict[str, dict[str, Any]] = {}
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

        if "probability_pct" in scenario:
            errors.append(
                f"{scenario_id}: probability_pct no está permitido sin una calibración validada"
            )

        target = scenario.get("target_price")
        if quantification_status == "validated":
            if not _finite_number(target) or target <= 0:
                errors.append(f"{scenario_id}: target_price debe ser positivo y finito")
        elif target is not None:
            errors.append(f"{scenario_id}: target_price debe ser null cuando no está calibrado")
        if not isinstance(scenario.get("rationale"), str) or not scenario["rationale"].strip():
            errors.append(f"{scenario_id}: rationale es obligatorio")
        for field in ("key_assumptions", "falsifiers"):
            values = scenario.get(field)
            if (
                not isinstance(values, list)
                or not values
                or any(not isinstance(item, str) or not item.strip() for item in values)
            ):
                errors.append(f"{scenario_id}: {field} debe contener texto no vacío")

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
            elif re.search(r"0{6,}", f"{parsed_url.netloc}{parsed_url.path}"):
                errors.append(f"{prefix}: url contiene un identificador de relleno")
            elif trusted_source_urls is not None:
                normalized = _normalize_source_url(source.get("url"))
                if not normalized or normalized not in trusted_source_urls:
                    errors.append(f"{prefix}: URL no está respaldada por evidencia de entrada verificable")
            source_date = _parse_date(source.get("as_of_date"))
            if source_date is None:
                errors.append(f"{prefix}: as_of_date debe ser una fecha ISO válida")
            elif as_of and source_date > as_of:
                errors.append(f"{prefix}: la fecha de fuente no puede superar as_of_date")

    scenario_ids = set(by_id)
    if not {"BEAR", "BULL"}.issubset(scenario_ids) or scenario_ids - set(SCENARIO_IDS):
        errors.append("debe existir exactamente un escenario BEAR y BULL, con BASE opcional")
    if quantification_status == "validated" and all(
        sid in by_id and _finite_number(by_id[sid].get("target_price"))
        for sid in ("BEAR", "BULL")
    ):
        bear_price = by_id["BEAR"]["target_price"]
        bull_price = by_id["BULL"]["target_price"]
        base_price = by_id.get("BASE", {}).get("target_price")
        if bear_price > bull_price:
            errors.append("el precio objetivo Bear debe ser menor o igual al precio Bull")
        if base_price is not None and _finite_number(base_price) and not bear_price <= base_price <= bull_price:
            errors.append("el precio objetivo Base debe quedar entre Bear y Bull")
    return errors


def scenario_fingerprint(value: dict[str, Any]) -> str:
    """Hash the exact reviewed scenario assumptions, excluding derived metadata."""
    canonical = {
        "schema_version": value.get("schema_version"),
        "as_of_date": value.get("as_of_date"),
        "horizon_date": value.get("horizon_date"),
        "currency": value.get("currency"),
        "quantification_status": value.get("quantification_status", "validated"),
        "scenarios": sorted(value.get("scenarios", []), key=lambda item: str(item.get("id", ""))),
    }
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_board_scenario_confirmation(
    analysis: Any,
    review: Any,
    *,
    today: date | None = None,
    trusted_source_urls: set[str] | None = None,
) -> tuple[bool, str]:
    """Validate the scenario confirmation captured as part of Decision Board review."""
    errors = validate_scenario_analysis(
        analysis, today=today, trusted_source_urls=trusted_source_urls,
    )
    if errors:
        return False, "; ".join(errors)
    if not isinstance(review, dict):
        return False, "Decision Board no confirmó escenarios y fuentes"
    if review.get("status") != "approved":
        return False, "Decision Board no aprobó el conjunto de escenarios"
    if review.get("sources_verified") is not True:
        return False, "Decision Board no confirmó las fuentes y sus fechas"
    if review.get("scenario_hash") != scenario_fingerprint(analysis):
        return False, "la confirmación no corresponde a la versión actual de escenarios"
    if not str(review.get("reviewed_by", "")).strip():
        return False, "falta la identidad autenticada del gestor"
    try:
        reviewed_timestamp = datetime.fromisoformat(str(review.get("reviewed_at", "")).replace("Z", "+00:00"))
    except ValueError:
        reviewed_timestamp = None
    reviewed_at = reviewed_timestamp.date() if reviewed_timestamp and reviewed_timestamp.tzinfo else None
    reference_date = today or datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date()
    if reviewed_at is None or reviewed_at > reference_date:
        return False, "la fecha de confirmación es inválida"
    if len(str(review.get("note", "")).strip()) < 10:
        return False, "la decisión requiere una justificación de al menos 10 caracteres"
    return True, "escenarios y fuentes confirmados en Decision Board"


def calculate_scenario_asymmetry(
    analysis: dict[str, Any],
    *,
    current_price: Any,
    quote_currency: str | None,
    trusted_source_urls: set[str] | None = None,
) -> dict[str, Any]:
    """Calculate unweighted Bear downside and Bull upside for RULE-008."""
    errors = validate_scenario_analysis(analysis, trusted_source_urls=trusted_source_urls)
    if errors:
        return _blocked_asymmetry("; ".join(errors))
    if analysis.get("quantification_status", "validated") != "validated":
        return _blocked_asymmetry("los escenarios cualitativos no tienen rangos de precio calibrados")
    if not _finite_number(current_price) or current_price <= 0:
        return _blocked_asymmetry("precio actual ausente o inválido")
    if not quote_currency or quote_currency != analysis.get("currency"):
        return _blocked_asymmetry("la moneda del escenario no coincide con la cotización actual")

    rows = []
    returns: dict[str, float] = {}
    for scenario in analysis["scenarios"]:
        target = float(scenario["target_price"])
        return_pct = (target / float(current_price) - 1) * 100
        if not math.isfinite(return_pct):
            return _blocked_asymmetry("los retornos calculados exceden el rango numérico")
        returns[scenario["id"]] = return_pct
        rows.append({
            "scenario": scenario["id"],
            "target_price": target,
            "return_pct": round(return_pct, 2),
            "sources": scenario["sources"],
        })

    bear_return = returns["BEAR"]
    bull_return = returns["BULL"]
    if bull_return <= 0 or bear_return >= 0:
        return _blocked_asymmetry("Bear debe mostrar downside y Bull upside frente al precio actual")
    ratio = round(bull_return / abs(bear_return), 2)
    return {
        "rows": rows,
        "upside_pct": round(bull_return, 2),
        "downside_pct": round(bear_return, 2),
        "benefit_risk_ratio": ratio,
        "scenario_hash": scenario_fingerprint(analysis),
        "validation_status": "validated",
        "board_review_eligible": True,
        "validation_reason": "casos Bear/Bull validados automáticamente; listos para Decision Board",
    }


def _blocked_asymmetry(reason: str) -> dict[str, Any]:
    return {
        "rows": [],
        "benefit_risk_ratio": None,
        "validation_status": "invalid",
        "board_review_eligible": False,
        "validation_reason": reason,
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
