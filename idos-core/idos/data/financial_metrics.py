"""Normalize provider percentage units without guessing across mixed sources."""
from __future__ import annotations

from typing import Any


PERCENT_FIELDS = {
    "roic_pct", "roe_pct", "roa_pct", "revenue_growth_pct",
    "operating_margin_pct", "gross_margin_pct", "net_margin_pct",
    "fcf_yield_pct", "eps_growth", "fcf_growth",
}
YAHOO_FRACTION_FIELDS = {
    "roic_pct", "roe_pct", "roa_pct", "gross_margin_pct", "net_margin_pct",
}


def normalize_percentage_units(data: dict[str, Any]) -> dict[str, Any]:
    """Convert known Yahoo fractions to percentage points; preserve StockAnalysis points.

    Legacy cache entries without source provenance retain the historical average-based
    fallback. When field provenance exists, source-specific units take precedence and
    mixed-provider values are left unchanged for the data-quality gates to assess.
    """
    values = [
        data[key]
        for key in PERCENT_FIELDS
        if isinstance(data.get(key), (int, float)) and not isinstance(data.get(key), bool)
    ]
    legacy_fractional_format = (sum(abs(value) for value in values) / len(values)) < 5 if values else True
    provenance = data.get("data_provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    field_sources = provenance.get("field_sources")
    field_sources = field_sources if isinstance(field_sources, dict) else {}
    record_source = str(data.get("source") or "").casefold()

    for key in PERCENT_FIELDS:
        value = data.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        raw_sources = field_sources.get(key, [])
        if isinstance(raw_sources, list):
            sources = {str(source).casefold() for source in raw_sources if source}
        elif raw_sources:
            sources = {str(raw_sources).casefold()}
        else:
            sources = set()

        if "stockanalysis.com" in sources or (not sources and record_source == "stockanalysis.com"):
            continue
        if sources == {"yfinance"} or (not sources and record_source == "yfinance"):
            if key in YAHOO_FRACTION_FIELDS:
                data[key] = value * 100
            continue
        if not sources and not record_source and legacy_fractional_format:
            data[key] = value * 100

    return data

