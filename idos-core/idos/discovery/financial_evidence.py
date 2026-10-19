"""Strict normalization and reconciliation for strategy financial evidence."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any
from urllib.parse import urlparse


SOURCE_ALIASES = {
    "stockanalysis.com": "stockanalysis.com",
    "stockanalysis": "stockanalysis.com",
    "stock analysis": "stockanalysis.com",
    "yfinance": "yfinance",
    "yahoo_finance": "yfinance",
    "yahoo finance": "yfinance",
    "finance.yahoo.com": "yfinance",
    "sec_edgar": "sec_edgar",
    "sec edgar": "sec_edgar",
    "sec.gov": "sec_edgar",
    "finviz.com": "finviz.com",
    "finviz": "finviz.com",
}


def canonical_source_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return SOURCE_ALIASES.get(value.strip().casefold())


def reconcile_metric_observations(
    observations: Any,
    *,
    expected_unit: str,
    expected_currency: str | None,
    minimum_sources: int,
    conflict_tolerance_pct: float,
    stale_after_days: int,
    now: str,
) -> dict[str, Any]:
    """Return one canonical metric only when evidence is comparable and fresh.

    ``reported_at`` controls freshness. ``observed_at`` records retrieval time
    and is deliberately never used as a substitute for the financial period.
    """
    if not isinstance(observations, list) or not observations:
        return _empty_result("missing", "NO_SOURCE_OBSERVATIONS")

    accepted: dict[str, dict[str, Any]] = {}
    incomplete_evidence: list[dict[str, Any]] = []
    invalid_source = False
    stale_source = False
    incomplete = False
    periods: set[str] = set()
    currencies: set[str] = set()
    for observation in observations:
        if not isinstance(observation, dict):
            incomplete = True
            continue
        source = canonical_source_id(observation.get("source_id"))
        if source is None:
            invalid_source = True
            continue
        value = _finite_number(observation.get("value"))
        observed_at = _parse_date(observation.get("observed_at"))
        reported_at = _parse_date(observation.get("reported_at"))
        unit = _normalize_unit(value, observation.get("unit"), expected_unit)
        currency = str(observation.get("currency") or "").strip().upper()
        period = str(observation.get("period") or "").strip()
        source_url = str(observation.get("source_url") or "").strip()
        if value is None or observed_at is None or reported_at is None or unit is None or not period or not source_url:
            incomplete = True
            incomplete_evidence.append({
                "source_id": source,
                "raw_value": value,
                "unit": observation.get("unit"),
                "currency": currency or None,
                "period": period or None,
                "reported_at": reported_at.isoformat() if reported_at else None,
                "observed_at": observed_at.isoformat() if observed_at else None,
                "source_url": source_url or None,
                "status": "incomplete",
                "reason_code": "REQUIRED_EVIDENCE_FIELD_MISSING",
            })
            continue
        if not _source_url_matches(source, source_url):
            incomplete = True
            continue
        if expected_currency and currency != expected_currency.upper():
            currencies.add(currency or "UNKNOWN")
            incomplete = True
            continue
        if expected_currency is None and currency:
            currencies.add(currency)
        current = _parse_date(now)
        if current is None or reported_at > current or observed_at > current or observed_at < reported_at:
            incomplete = True
            continue
        if (current - reported_at).days > stale_after_days:
            stale_source = True
            continue
        periods.add(period)
        if expected_currency:
            currencies.add(currency)
        normalized = {
            "source_id": source,
            "status": "observed",
            "value": unit[0],
            "unit": unit[1],
            "currency": currency or None,
            "period": period,
            "reported_at": reported_at.isoformat(),
            "observed_at": observed_at.isoformat(),
            "source_url": source_url,
        }
        prior = accepted.get(source)
        if prior is not None and prior["value"] != normalized["value"]:
            return _empty_result("conflicted", "DUPLICATE_SOURCE_VALUES", list(accepted.values()) + [normalized])
        accepted[source] = normalized

    evidence = sorted(
        [*accepted.values(), *incomplete_evidence],
        key=lambda item: str(item.get("source_id") or ""),
    )
    sources = sorted(accepted)
    if stale_source:
        return _empty_result("stale", "STALE_SOURCE_OBSERVATION", evidence, sources)
    if periods and len(periods) > 1:
        return _empty_result("incompatible_period", "SOURCE_PERIOD_MISMATCH", evidence, sources)
    if expected_currency and currencies and currencies != {expected_currency.upper()}:
        return _empty_result("incompatible_currency", "SOURCE_CURRENCY_MISMATCH", evidence, sources)
    if len(currencies) > 1:
        return _empty_result("incompatible_currency", "SOURCE_CURRENCY_MISMATCH", evidence, sources)
    if incomplete or invalid_source:
        return _empty_result("incomplete", "SOURCE_EVIDENCE_INCOMPLETE", evidence, sources)
    if len(sources) < minimum_sources:
        return _empty_result("insufficient_sources", "INSUFFICIENT_INDEPENDENT_SOURCES", evidence, sources)

    values = [item["value"] for item in evidence]
    mean = sum(values) / len(values)
    spread = max(values) - min(values)
    deviation = spread / abs(mean) * 100 if mean else (100.0 if spread else 0.0)
    if deviation > conflict_tolerance_pct:
        return _empty_result("conflicted", "CRITICAL_SOURCE_CONFLICT", evidence, sources)

    return {
        "value": round(mean, 4),
        "unit": expected_unit,
        "currency": expected_currency.upper() if expected_currency else (sorted(currencies)[0] if currencies else None),
        "period": next(iter(periods), None),
        "source": sources,
        "source_values": {item["source_id"]: item["value"] for item in evidence},
        "source_evidence": evidence,
        "coverage": len(sources),
        "status": "observed",
        "reason_code": None,
        "deviation_pct": round(deviation, 4),
    }


def _empty_result(status: str, reason: str, evidence: list[dict[str, Any]] | None = None, sources: list[str] | None = None) -> dict[str, Any]:
    return {
        "value": None,
        "unit": None,
        "currency": None,
        "period": None,
        "source": sources or [],
        "source_values": {},
        "source_evidence": evidence or [],
        "coverage": len(sources or []),
        "status": status,
        "reason_code": reason,
        "deviation_pct": None,
    }


def _normalize_unit(value: float | None, raw_unit: Any, expected_unit: str) -> tuple[float, str] | None:
    if value is None or not isinstance(raw_unit, str):
        return None
    unit = raw_unit.strip().casefold()
    if expected_unit == "percent":
        if unit in {"percent", "%", "pct"}:
            return value, "percent"
        if unit in {"fraction", "decimal_fraction"}:
            return value * 100, "percent"
    elif expected_unit == "USD":
        scales = {"usd": 1.0, "usd_thousands": 1_000.0, "usd_millions": 1_000_000.0, "usd_billions": 1_000_000_000.0}
        scale = scales.get(unit)
        if scale is not None:
            return value * scale, "USD"
    elif expected_unit == "ratio" and unit in {"ratio", "x"}:
        return value, "ratio"
    elif expected_unit == "months" and unit in {"month", "months"}:
        return value, "months"
    return None


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _source_url_matches(source_id: str, value: str) -> bool:
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").casefold()
    except ValueError:
        return False
    if parsed.scheme != "https" or not host:
        return False
    domains = {
        "stockanalysis.com": ("stockanalysis.com",),
        "yfinance": ("yahoo.com",),
        "sec_edgar": ("sec.gov",),
        "finviz.com": ("finviz.com",),
    }
    return any(host == domain or host.endswith("." + domain) for domain in domains.get(source_id, ()))


def _parse_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)
