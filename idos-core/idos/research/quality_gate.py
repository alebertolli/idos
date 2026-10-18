"""Deterministic traceability and freshness checks for fundamental Research."""

from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse
from idos.timezone import AR_TZ


def _iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _has_citable_source(sources: Any, as_of: date, stale_after_days: int) -> bool:
    if not isinstance(sources, list) or not sources:
        return False
    for source in sources:
        if not isinstance(source, dict):
            return False
        parsed = urlparse(str(source.get("url", "")))
        source_date = _iso_date(source.get("source_date"))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or not source_date:
            return False
        if source_date > as_of or (as_of - source_date).days > stale_after_days:
            return False
    return True


def evaluate_research_quality(
    report: dict[str, Any] | None,
    as_of: date | None = None,
    stale_after_days: int = 365,
) -> dict[str, Any]:
    """Require claim-level source metadata and active, reviewable catalysts.

    This validates metadata shape and dates only. It does not assert that a URL
    supports a claim or that the cited source is authoritative.
    """
    current_date = as_of or datetime.now(AR_TZ).date()
    failures: list[str] = []
    report = report if isinstance(report, dict) else {}
    if report.get("research_status") != "COMPLETED":
        failures.append("research_not_completed")

    quality = report.get("calidad_evidencia") or {}
    facts = quality.get("hechos_reportados", quality.get("hechos_verificados", [])) if isinstance(quality, dict) else []
    if not isinstance(facts, list) or not facts:
        failures.append("reported_facts_missing")
    else:
        for index, fact in enumerate(facts):
            if not isinstance(fact, dict):
                failures.append(f"fact_{index + 1}_unstructured")
                continue
            if not str(fact.get("statement", "")).strip():
                failures.append(f"fact_{index + 1}_statement_missing")
            if not str(fact.get("period", "")).strip() or not str(fact.get("unit", "")).strip():
                failures.append(f"fact_{index + 1}_period_or_unit_missing")
            if not _has_citable_source(fact.get("sources"), current_date, stale_after_days):
                failures.append(f"fact_{index + 1}_source_metadata_missing_or_invalid")

    catalysts = report.get("dominio_catalizadores", [])
    if not isinstance(catalysts, list) or not catalysts:
        failures.append("catalysts_missing")
    else:
        active_count = 0
        for index, catalyst in enumerate(catalysts):
            if not isinstance(catalyst, dict):
                failures.append(f"catalyst_{index + 1}_unstructured")
                continue
            if catalyst.get("status", "active") != "active":
                continue
            active_count += 1
            review_by = _iso_date(catalyst.get("review_by"))
            if review_by is None:
                failures.append(f"catalyst_{index + 1}_review_date_missing_or_invalid")
            elif review_by < current_date:
                failures.append(f"catalyst_{index + 1}_expired")
            if not _has_citable_source(catalyst.get("sources"), current_date, stale_after_days):
                failures.append(f"catalyst_{index + 1}_source_metadata_missing_or_invalid")
        if not active_count:
            failures.append("active_catalyst_missing")

    return {
        "passed": not failures,
        "status": "PASS" if not failures else "BLOCKED",
        "as_of": current_date.isoformat(),
        "facts_count": len(facts) if isinstance(facts, list) else 0,
        "catalysts_count": len(catalysts) if isinstance(catalysts, list) else 0,
        "failures": failures,
        "scope": "metadata_and_freshness_only_not_source_relevance_or_truth",
    }
