"""Normalize annual financial facts from SEC CompanyFacts XBRL responses.

This module is intentionally network-free. Callers own SEC access policy,
User-Agent configuration, caching, and request pacing.
"""

from __future__ import annotations

from datetime import date
import math
from typing import Any


SOURCE_NAME = "sec_edgar"
SOURCE_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}

REVENUE_CONCEPTS = (
    ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    ("us-gaap", "SalesRevenueNet"),
    ("us-gaap", "Revenues"),
    ("ifrs-full", "Revenue"),
)
OPERATING_INCOME_CONCEPTS = (
    ("us-gaap", "OperatingIncomeLoss"),
    ("ifrs-full", "ProfitLossFromOperatingActivities"),
)
OPERATING_CASH_FLOW_CONCEPTS = (
    ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
    ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
    ("ifrs-full", "CashFlowsFromUsedInOperatingActivities"),
)
CAPEX_CONCEPTS = (
    ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
    ("us-gaap", "PaymentsToAcquireProductiveAssets"),
    ("ifrs-full", "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"),
)


def normalize_company_facts(ticker: str, cik: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a small, provenance-carrying annual metrics record.

    Facts are paired only when fiscal-period start/end and currency match.
    Missing or custom-taxonomy-only facts remain absent for downstream gates.
    """
    normalized_ticker = str(ticker).strip().upper()
    normalized_cik = str(cik).strip().lstrip("0") or "0"
    if not normalized_ticker or not normalized_cik.isdigit():
        raise ValueError("A valid ticker and SEC CIK are required")
    if not isinstance(payload, dict) or not isinstance(payload.get("facts"), dict):
        raise ValueError("SEC CompanyFacts payload is malformed")

    revenue = _latest_revenue_series(payload["facts"])
    if not revenue:
        return _empty_result(normalized_ticker, normalized_cik, "annual_revenue_not_available")

    taxonomy, revenue_tag, currency, annual_revenue = revenue
    current = annual_revenue[-1]
    previous = _previous_fiscal_year(annual_revenue)
    result: dict[str, Any] = {
        "ticker": normalized_ticker,
        "cik": normalized_cik.zfill(10),
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL.format(cik=normalized_cik.zfill(10)),
        "financial_currency": currency,
        "financial_period_type": "FY",
        "period_end_date": current["end"],
        "financial_metric_metadata": {},
        "data_quality_warnings": [],
    }

    evidence = [current]
    if previous is not None and previous["val"] > 0 and current["val"] >= 0:
        revenue_growth = (current["val"] / previous["val"] - 1.0) * 100.0
        result["revenue_growth_pct"] = round(revenue_growth, 6)
        evidence = [previous, current]
        result["financial_metric_metadata"]["revenue_growth_pct"] = _metadata(
            taxonomy, revenue_tag, "percentage_points", currency, current,
            result["source_url"], evidence,
        )
    elif previous is None:
        result["data_quality_warnings"].append("sec_prior_fiscal_year_revenue_missing")
    else:
        result["data_quality_warnings"].append("sec_revenue_not_positive_for_growth")

    period_key = (current.get("start"), current.get("end"))
    operating = _find_period_fact(
        payload["facts"], OPERATING_INCOME_CONCEPTS, currency, period_key
    )
    if operating and current["val"] > 0:
        result["operating_margin_pct"] = round(operating["fact"]["val"] / current["val"] * 100.0, 6)
        result["financial_metric_metadata"]["operating_margin_pct"] = _metadata(
            operating["taxonomy"], operating["tag"], "percentage_points", currency,
            operating["fact"], result["source_url"], [operating["fact"]],
        )
    else:
        result["data_quality_warnings"].append("sec_operating_income_not_comparable_to_revenue")

    cash_flow = _find_period_fact(payload["facts"], OPERATING_CASH_FLOW_CONCEPTS, currency, period_key)
    capex = _find_period_fact(payload["facts"], CAPEX_CONCEPTS, currency, period_key)
    if cash_flow and capex:
        result["fcf"] = round(cash_flow["fact"]["val"] - abs(capex["fact"]["val"]), 6)
        result["financial_metric_metadata"]["fcf"] = _metadata(
            cash_flow["taxonomy"], cash_flow["tag"], currency, currency,
            cash_flow["fact"], result["source_url"],
            [cash_flow["fact"], capex["fact"]],
            components={"operating_cash_flow": cash_flow["tag"], "capital_expenditures": capex["tag"]},
        )
    else:
        result["data_quality_warnings"].append("sec_cash_flow_or_capex_not_comparable")

    field_sources = {
        field: [SOURCE_NAME]
        for field in ("revenue_growth_pct", "operating_margin_pct", "fcf")
        if field in result
    }
    result["data_provenance"] = {
        "source_count": 1,
        "sources_used": [SOURCE_NAME],
        "source_urls": [result["source_url"]],
        "field_sources": field_sources,
        "field_urls": {field: [result["source_url"]] for field in field_sources},
        "conflicts": [],
    }
    if not field_sources:
        result["data_quality_warnings"].append("sec_no_supported_annual_metrics")
    return result


def _latest_revenue_series(facts: dict[str, Any]) -> tuple[str, str, str, list[dict[str, Any]]] | None:
    candidates = []
    for taxonomy, tag in REVENUE_CONCEPTS:
        units = _concept_units(facts, taxonomy, tag)
        for unit, entries in units.items():
            annual = _annual_facts(entries)
            if len(annual) >= 1 and _is_currency_unit(unit):
                candidates.append((taxonomy, tag, unit, annual))
    if not candidates:
        return None
    # Prefer known canonical tags, complete annual histories, and USD when the
    # issuer files both a reporting currency and a translated USD fact.
    candidates.sort(key=lambda item: (-len(item[3]), item[2] != "USD", REVENUE_CONCEPTS.index((item[0], item[1])), item[2]))
    taxonomy, tag, unit, annual = candidates[0]
    return taxonomy, tag, unit, annual


def _find_period_fact(
    facts: dict[str, Any], concepts: tuple[tuple[str, str], ...], currency: str,
    period_key: tuple[str, str],
) -> dict[str, Any] | None:
    for taxonomy, tag in concepts:
        entries = _concept_units(facts, taxonomy, tag).get(currency, [])
        matches = [fact for fact in _annual_facts(entries) if (fact.get("start"), fact.get("end")) == period_key]
        if matches:
            fact = matches[-1]
            return {"taxonomy": taxonomy, "tag": tag, "fact": fact}
    return None


def _concept_units(facts: dict[str, Any], taxonomy: str, tag: str) -> dict[str, list[dict[str, Any]]]:
    units = (((facts.get(taxonomy) or {}).get(tag) or {}).get("units") or {})
    return {unit: entries for unit, entries in units.items() if isinstance(entries, list)}


def _annual_facts(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_end: dict[str, dict[str, Any]] = {}
    for fact in entries:
        if not isinstance(fact, dict) or fact.get("form") not in ANNUAL_FORMS:
            continue
        start, end, filed, value = fact.get("start"), fact.get("end"), fact.get("filed"), fact.get("val")
        if not isinstance(start, str) or not isinstance(end, str) or not isinstance(filed, str):
            continue
        try:
            duration = (date.fromisoformat(end) - date.fromisoformat(start)).days
        except ValueError:
            continue
        if not 330 <= duration <= 400 or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        prior = by_end.get(end)
        if prior is None or (filed, str(fact.get("accn") or "")) > (prior["filed"], str(prior.get("accn") or "")):
            by_end[end] = fact
    return sorted(by_end.values(), key=lambda fact: (fact["end"], fact["filed"]))


def _previous_fiscal_year(annual: list[dict[str, Any]]) -> dict[str, Any] | None:
    current = annual[-1]
    current_end = date.fromisoformat(current["end"])
    prior = [
        item for item in annual[:-1]
        if 330 <= (current_end - date.fromisoformat(item["end"])).days <= 400
    ]
    return prior[-1] if prior else None


def _is_currency_unit(unit: Any) -> bool:
    return isinstance(unit, str) and len(unit) == 3 and unit.isalpha() and unit.isupper()


def _metadata(
    taxonomy: str, tag: str, metric_unit: str, currency: str, fact: dict[str, Any], source_url: str,
    evidence: list[dict[str, Any]], components: dict[str, str] | None = None,
) -> dict[str, Any]:
    metadata = {
        "period_type": "FY",
        "period_start_date": fact.get("start"),
        "period_end_date": fact.get("end"),
        "unit": metric_unit,
        "currency": currency,
        "filed_at": fact.get("filed"),
        "form": fact.get("form"),
        "accession_number": fact.get("accn"),
        "taxonomy": taxonomy,
        "concept": tag,
        "source_url": source_url,
        "evidence": [
            {"start": item.get("start"), "end": item.get("end"), "filed_at": item.get("filed"),
             "form": item.get("form"), "accession_number": item.get("accn"), "value": item.get("val")}
            for item in evidence
        ],
    }
    if components:
        metadata["components"] = components
    return metadata


def _empty_result(ticker: str, cik: str, reason: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "cik": cik.zfill(10),
        "source": SOURCE_NAME,
        "financial_metric_metadata": {},
        "data_quality_warnings": [reason],
        "data_provenance": {
            "source_count": 1, "sources_used": [SOURCE_NAME],
            "field_sources": {}, "field_urls": {}, "conflicts": [],
        },
    }

