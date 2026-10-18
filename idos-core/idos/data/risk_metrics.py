"""Deterministic risk inputs; prices and units must be auditable before scoring."""
import math
from datetime import date, datetime
from statistics import stdev
from typing import Any

from idos.timezone import AR_TZ


def normalize_debt_equity(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize Yahoo's percent field once; other providers report a ratio."""
    units = dict(data.get("metric_units") or {})
    value = data.get("debt_equity_ratio")
    unit = units.get("debt_equity_ratio")
    if unit is None and data.get("source") in {"yahoo_finance", "yfinance"}:
        unit = "percent"
    try:
        if isinstance(value, bool) or unit not in {None, "ratio", "percent"}:
            raise ValueError("invalid_debt_equity")
        value = float(value)
        if not math.isfinite(value) or value < 0:
            raise ValueError("invalid_debt_equity")
        data["debt_equity_ratio"] = value / 100 if unit == "percent" else value
    except (TypeError, ValueError, OverflowError):
        data["debt_equity_ratio"] = None
        availability = dict(data.get("_risk_metric_availability") or {})
        availability["debt_to_equity"] = False
        data["_risk_metric_availability"] = availability
    units["debt_equity_ratio"] = "ratio"
    data["metric_units"] = units
    return data


def enrich_price_risk(data: dict[str, Any], *, as_of: date | None = None) -> dict[str, Any]:
    """90 daily log returns, sample sigma, annualized percent (252 sessions).

    Require 91 finite positive adjusted closes, ordered unique dates, a daily
    window <=150 calendar days, no gap >7 days, and last close <=7 days old.
    Missing/invalid input remains UNKNOWN; never impute or remove bad observations.
    """
    today = as_of or datetime.now(AR_TZ).date()
    prices = data.get("price_history") or []
    dates = data.get("price_history_dates") or []
    evidence = {
        "status": "UNKNOWN", "method": "sample_stdev_daily_log_returns",
        "lookback_returns": 90, "annualization_sessions": 252, "unit": "percent",
        "evaluated_as_of": today.isoformat(), "max_age_days": 7,
        "source": data.get("price_history_source", "unspecified"),
        "adjustment": data.get("price_history_adjustment", "unspecified"),
    }
    value = None
    reason = None
    if evidence["adjustment"] != "split_and_dividend_adjusted":
        reason = "unconfirmed_price_adjustment"
    elif not isinstance(prices, list) or not isinstance(dates, list) or len(prices) != len(dates) or len(prices) < 91:
        reason = "insufficient_or_unaligned_history"
    else:
        try:
            window = prices[-91:]
            if any(isinstance(x, bool) for x in window):
                raise ValueError("boolean_price")
            closes = [float(x) for x in window]
            observations = [date.fromisoformat(str(x)) for x in dates[-91:]]
            if any(not math.isfinite(x) or x <= 0 for x in closes):
                raise ValueError("invalid_price")
            gaps = [(b - a).days for a, b in zip(observations, observations[1:])]
            if any(gap <= 0 or gap > 7 for gap in gaps) or (observations[-1] - observations[0]).days > 150:
                raise ValueError("invalid_daily_dates")
            age = (today - observations[-1]).days
            if age < 0 or age > 7:
                raise ValueError("stale_or_future_history")
            returns = [math.log(b) - math.log(a) for a, b in zip(closes, closes[1:])]
            value = stdev(returns) * math.sqrt(252) * 100
            if not math.isfinite(value):
                raise ValueError("invalid_volatility")
            evidence.update(status="OBSERVED", start_date=observations[0].isoformat(),
                            end_date=observations[-1].isoformat(), observations=91)
        except (TypeError, ValueError, OverflowError) as exc:
            reason = str(exc)
    if reason:
        evidence["reason"] = reason
    data["volatility_90d"] = value
    provenance = dict(data.get("risk_metric_provenance") or {})
    provenance["volatility_90d"] = evidence
    data["risk_metric_provenance"] = provenance
    availability = dict(data.get("_risk_metric_availability") or {})
    availability["volatility_90d"] = value is not None
    data["_risk_metric_availability"] = availability
    return data
