"""Auditable normalization of traded turnover and asset size to USD."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import math
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any, Callable, Iterable

import requests
import yaml


class MarketDataNormalizationError(ValueError):
    """Raised when required market or FX evidence is unavailable or invalid."""


EQUITY_ASSET_TYPES = frozenset({"equity", "us_equity"})


def is_equity_asset_type(asset_type: str | None) -> bool:
    """Return whether a registry type represents an individual equity share.

    ``us_equity`` remains supported as a legacy registry value. ``equity`` is
    the country-neutral canonical value for new and international listings.
    """
    return str(asset_type or "").strip().lower() in EQUITY_ASSET_TYPES


def supports_asset_type(asset_type: str | None, supported_types: Iterable[str]) -> bool:
    """Match canonical and legacy equity labels while keeping ETFs distinct."""
    actual = str(asset_type or "").strip().lower()
    supported = {str(value).strip().lower() for value in supported_types if value}
    if is_equity_asset_type(actual):
        return bool(supported & EQUITY_ASSET_TYPES)
    return actual in supported


@dataclass(frozen=True)
class LiquidityPolicy:
    window_sessions: int = 20
    minimum_coverage: float = 0.8
    max_fx_staleness_days: int = 4
    fx_side: str = "sell"

    def __post_init__(self) -> None:
        if self.window_sessions <= 0:
            raise ValueError("window_sessions must be positive")
        if not 0 < self.minimum_coverage <= 1:
            raise ValueError("minimum_coverage must be in (0, 1]")
        if self.max_fx_staleness_days < 0:
            raise ValueError("max_fx_staleness_days cannot be negative")
        if self.fx_side != "sell":
            raise ValueError("ARS-to-USD conversion policy requires FX sell")


@dataclass(frozen=True)
class MarketDataSettings:
    market_cap_min_usd: float = 2_000_000_000
    avg_dollar_volume_min_usd: float = 100_000
    liquidity: LiquidityPolicy = LiquidityPolicy()

    def __post_init__(self) -> None:
        if not math.isfinite(self.market_cap_min_usd) or self.market_cap_min_usd <= 0:
            raise ValueError("market_cap_min_usd must be positive and finite")
        if not math.isfinite(self.avg_dollar_volume_min_usd) or self.avg_dollar_volume_min_usd <= 0:
            raise ValueError("avg_dollar_volume_min_usd must be positive and finite")

    @classmethod
    def load(cls, config_root: str | None = None) -> "MarketDataSettings":
        path = Path(config_root or "idos-config") / "market_data.yml"
        if not path.exists():
            return cls()
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(document, dict):
                raise TypeError("root must be a mapping")
            gates = document.get("eligibility", {})
            liquidity_values = document.get("liquidity", {})
            if not isinstance(gates, dict) or not isinstance(liquidity_values, dict):
                raise TypeError("eligibility and liquidity must be mappings")
            return cls(
                market_cap_min_usd=float(gates.get("market_cap_min_usd", 2_000_000_000)),
                avg_dollar_volume_min_usd=float(gates.get("avg_dollar_volume_min_usd", 100_000)),
                liquidity=LiquidityPolicy(
                    window_sessions=int(liquidity_values.get("window_sessions", 20)),
                    minimum_coverage=float(liquidity_values.get("minimum_coverage", 0.8)),
                    max_fx_staleness_days=int(liquidity_values.get("max_fx_staleness_days", 4)),
                    fx_side=str(liquidity_values.get("fx_side", "sell")).lower(),
                ),
            )
        except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
            raise MarketDataNormalizationError(f"Invalid market data configuration: {path}") from exc


def evaluate_global_market_eligibility(
    merged_data: dict[str, Any],
    *,
    asset_type: str | None,
    settings: MarketDataSettings,
) -> dict[str, Any]:
    """Apply USD-denominated size and liquidity thresholds, independent of domicile."""
    reasons: list[str] = []
    # Issuer country and listing country are deliberately not eligibility rules.
    is_equity = is_equity_asset_type(asset_type)
    if asset_type != "etf" and not is_equity:
        reasons.append("UNSUPPORTED_OR_MISSING_ASSET_TYPE")

    normalization = merged_data.get("market_data_normalization")
    liquidity = merged_data.get("avg_dollar_volume_usd")
    liquidity_provenance = merged_data.get("liquidity_provenance")
    valid_liquidity = (
        isinstance(liquidity, (int, float))
        and not isinstance(liquidity, bool)
        and math.isfinite(float(liquidity))
        and float(liquidity) > 0
        and isinstance(liquidity_provenance, dict)
        and liquidity_provenance.get("basis") in {"USD_PROVIDER_METRIC", "UNDERLYING_USD_PROXY"}
        and bool(str(liquidity_provenance.get("source", "")).strip())
        and liquidity_provenance.get("currency") == "USD"
        and bool(str(liquidity_provenance.get("as_of", "")).strip())
    )
    if not isinstance(normalization, dict) or normalization.get("status") != "complete":
        reasons.append("MARKET_DATA_NORMALIZATION_INCOMPLETE")
    if not valid_liquidity:
        reasons.append("GLOBAL_LIQUIDITY_EVIDENCE_INCOMPLETE")
    elif float(liquidity) < settings.avg_dollar_volume_min_usd:
        reasons.append("GLOBAL_LIQUIDITY_BELOW_MINIMUM")

    size = merged_data.get("size_metric_usd")
    size_provenance = merged_data.get("size_metric_provenance")
    if is_equity:
        market_cap_provenance = merged_data.get("market_cap_provenance")
        valid_size = (
            isinstance(size, (int, float))
            and not isinstance(size, bool)
            and math.isfinite(float(size))
            and float(size) > 0
            and isinstance(size_provenance, dict)
            and size_provenance.get("source")
            and size_provenance.get("as_of")
            and isinstance(market_cap_provenance, dict)
            and market_cap_provenance.get("currency") == "USD"
            and market_cap_provenance.get("source") == size_provenance.get("source")
            and market_cap_provenance.get("as_of") == size_provenance.get("as_of")
        )
        if not valid_size:
            reasons.append("GLOBAL_MARKET_CAP_EVIDENCE_INCOMPLETE")
        elif float(size) < settings.market_cap_min_usd:
            reasons.append("GLOBAL_MARKET_CAP_BELOW_MINIMUM")

    return {
        "passed": not reasons,
        "asset_type": asset_type,
        "size_metric_usd": size if is_equity else None,
        "market_cap_min_usd": settings.market_cap_min_usd if is_equity else None,
        "avg_dollar_volume_usd": liquidity,
        "avg_dollar_volume_min_usd": settings.avg_dollar_volume_min_usd,
        "liquidity_basis": "UNDERLYING_USD_PROXY",
        "reason_codes": reasons,
        "normalization": normalization,
        "size_provenance": size_provenance,
        "liquidity_provenance": liquidity_provenance,
    }


@dataclass(frozen=True)
class FxObservation:
    observed_at: datetime
    sell: float


YAHOO_US_EXCHANGES = {
    "NMS": "XNYS", "NGM": "XNYS", "NCM": "XNYS", "NYQ": "XNYS",
    "ASE": "XNYS", "PCX": "XNYS", "BTS": "XNYS",
}


def expected_us_market_sessions(start: date, end: date, yahoo_exchange: str) -> list[date]:
    """Use the exchange calendar; unknown Yahoo exchange codes fail closed."""
    calendar_name = YAHOO_US_EXCHANGES.get(str(yahoo_exchange or "").upper())
    if not calendar_name:
        raise MarketDataNormalizationError(f"Unsupported Yahoo exchange calendar: {yahoo_exchange}")
    try:
        import exchange_calendars

        calendar = exchange_calendars.get_calendar(calendar_name)
        return [session.date() for session in calendar.sessions_in_range(start.isoformat(), end.isoformat())]
    except Exception as exc:
        raise MarketDataNormalizationError("Could not resolve expected market sessions") from exc


class MonedApiFxProvider:
    """Bounded MonedAPI history adapter with in-process request coalescing/cache."""

    BASE_URL = "https://monedapi.ar/api/v2/history/usd"
    ORIGINS = {"MEP": "bolsa", "CCL": "ccl"}
    _cache: dict[tuple[str, str, str], tuple[float, list[FxObservation]]] = {}
    _lock = Lock()

    def __init__(self, timeout_seconds: float = 10, get: Callable[..., Any] | None = None):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self._get = get or requests.get

    def history(self, reference: str, date_from: date, date_to: date) -> list[FxObservation]:
        key_name = reference.strip().upper()
        origin = self.ORIGINS.get(key_name)
        if not origin:
            raise MarketDataNormalizationError(f"Unsupported FX reference: {reference}")
        if date_from > date_to:
            raise MarketDataNormalizationError("FX history start date is after end date")
        key = (key_name, date_from.isoformat(), date_to.isoformat())
        now = monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > now:
                return list(cached[1])
            try:
                response = self._get(
                    f"{self.BASE_URL}/{origin}",
                    params={"date_from": key[1], "date_to": key[2], "limit": 500},
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                raise MarketDataNormalizationError("MonedAPI history request failed") from exc
            if response.status_code != 200:
                retry_after = response.headers.get("Retry-After")
                suffix = f" (Retry-After: {retry_after}s)" if retry_after else ""
                raise MarketDataNormalizationError(
                    f"MonedAPI returned HTTP {response.status_code}{suffix}"
                )
            try:
                payload = response.json()
            except (ValueError, TypeError) as exc:
                raise MarketDataNormalizationError("MonedAPI returned invalid JSON") from exc
            if not isinstance(payload, list):
                raise MarketDataNormalizationError("MonedAPI history schema must be a list")
            observations = []
            for item in payload:
                if not isinstance(item, dict) or not isinstance(item.get("createdAt"), str):
                    raise MarketDataNormalizationError("MonedAPI history point has an invalid schema")
                try:
                    observed_at = datetime.fromisoformat(item["createdAt"].replace("Z", "+00:00"))
                    sell = _positive_finite(item.get("sell"))
                except (TypeError, ValueError) as exc:
                    raise MarketDataNormalizationError("MonedAPI history point is invalid") from exc
                if observed_at.tzinfo is None or sell is None:
                    raise MarketDataNormalizationError("MonedAPI history point lacks timezone or valid sell")
                observations.append(FxObservation(observed_at=observed_at, sell=sell))
            observations.sort(key=lambda point: point.observed_at)
            # Historical ranges ending more than a day ago are immutable; recent ranges
            # use a short TTL to avoid bursts when ticker refresh runs concurrently.
            ttl = 86400 if date_to < date.today() - timedelta(days=1) else 60
            self._cache[key] = (now + ttl, observations)
            return list(observations)


def normalize_average_dollar_turnover(
    rows: Iterable[dict[str, Any]],
    *,
    expected_market_dates: Iterable[date],
    quote_currency: str,
    source: str,
    fx_reference: str | None = None,
    fx_observations: Iterable[FxObservation] = (),
    policy: LiquidityPolicy = LiquidityPolicy(),
) -> dict[str, Any]:
    """Return average USD turnover from available observations, without a coverage gate."""
    currency = quote_currency.strip().upper()
    if currency != "USD":
        raise MarketDataNormalizationError(
            "USD-denominated volume metric is required; local-currency FX conversion is not an eligibility input"
        )

    expected_dates = sorted(set(expected_market_dates))[-policy.window_sessions :]
    if not expected_dates:
        return _turnover_result(
            None, currency, source, fx_reference, policy, 0,
            0, None, None, [],
        )
    history = {}
    for row in rows:
        normalized = _normalize_row(row)
        history[normalized[0]] = normalized
    window = [history.get(day, (day, None, None, None)) for day in expected_dates]

    valid: list[float] = []
    source_dates: list[str] = []
    for day, close, volume, row_source in window:
        if close is None or volume is None or close <= 0 or volume < 0:
            continue
        turnover = close * volume
        if not math.isfinite(turnover) or turnover < 0:
            continue
        valid.append(turnover)
        source_dates.append(day.isoformat())

    coverage = len(valid) / len(expected_dates)
    average = sum(valid) / len(valid) if valid else None
    metadata = {
        "quote_currency": currency,
        "currency": "USD",
        "fx_reference": None,
        "fx_side": None,
        "window_sessions": policy.window_sessions,
        "expected_observations": len(expected_dates),
        "valid_observations": len(valid),
        "coverage": round(coverage, 6),
        "minimum_coverage": None,
        "first_price_date": expected_dates[0].isoformat(),
        "last_price_date": expected_dates[-1].isoformat(),
        "as_of": expected_dates[-1].isoformat(),
        "price_source": source,
        "fx_source": None,
        "fx_observations": [],
        "valid_price_dates": source_dates,
        "missing_market_dates": [day.isoformat() for day in expected_dates if day not in history],
    }
    return {"avg_dollar_volume_usd": average, "liquidity_provenance": metadata}


def normalize_market_cap_usd(
    value: Any,
    *,
    currency: str,
    as_of: date,
    source: str,
    fx_reference: str | None = None,
    fx_observations: Iterable[FxObservation] = (),
    max_fx_staleness_days: int = 4,
) -> dict[str, Any]:
    amount = _positive_finite(value)
    code = currency.strip().upper()
    if amount is None:
        raise MarketDataNormalizationError("Market cap must be a positive finite number")
    if code == "USD":
        usd = amount
        fx_meta = None
    elif code == "ARS":
        if not fx_reference or fx_reference.upper() not in {"MEP", "CCL"}:
            raise MarketDataNormalizationError("ARS market cap requires an explicit MEP or CCL reference")
        observations = list(fx_observations)
        if any(
            not isinstance(item, FxObservation)
            or item.observed_at.tzinfo is None
            or _positive_finite(item.sell) is None
            for item in observations
        ):
            raise MarketDataNormalizationError("FX observation is invalid")
        points = [item for item in observations if item.observed_at.date() <= as_of]
        if not points:
            raise MarketDataNormalizationError("No FX observation on or before market cap date")
        point = max(points, key=lambda item: item.observed_at)
        age = (as_of - point.observed_at.date()).days
        if age > max_fx_staleness_days:
            raise MarketDataNormalizationError("FX observation is stale for market cap normalization")
        usd = amount / point.sell
        fx_meta = {"reference": fx_reference.upper(), "side": "sell", "observed_at": point.observed_at.isoformat(), "staleness_days": age}
    else:
        raise MarketDataNormalizationError(f"Unsupported market cap currency: {currency}")
    return {"market_cap_usd": usd, "market_cap_provenance": {"source": source, "as_of": as_of.isoformat(), "source_currency": code, "fx": fx_meta}}


def _normalize_row(row: dict[str, Any]) -> tuple[date, float | None, float | None, str | None]:
    if not isinstance(row, dict):
        raise MarketDataNormalizationError("Market history rows must be objects")
    try:
        day = date.fromisoformat(str(row.get("date", ""))[:10])
    except ValueError as exc:
        raise MarketDataNormalizationError("Market history row has invalid date") from exc
    if row.get("price_basis") != "close_unadjusted":
        raise MarketDataNormalizationError("Market history must declare unadjusted closing prices")
    return day, _positive_finite(row.get("close")), _finite_non_negative(row.get("volume")), row.get("source")


def _positive_finite(value: Any) -> float | None:
    parsed = _finite(value)
    return parsed if parsed is not None and parsed > 0 else None


def _finite_non_negative(value: Any) -> float | None:
    parsed = _finite(value)
    return parsed if parsed is not None and parsed >= 0 else None


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _turnover_result(value, currency, source, fx_reference, policy, valid, expected, first, last, fx):
    return {
        "avg_dollar_volume_usd": value,
        "liquidity_provenance": {
            "quote_currency": currency, "fx_reference": fx_reference,
            "fx_side": policy.fx_side if currency == "ARS" else None,
            "window_sessions": policy.window_sessions, "expected_observations": expected,
            "valid_observations": valid, "coverage": 0.0,
            "minimum_coverage": policy.minimum_coverage,
            "first_price_date": first.isoformat() if first else None,
            "last_price_date": last.isoformat() if last else None,
            "price_source": source, "fx_source": "monedapi.ar" if fx else None,
            "fx_observations": fx, "valid_price_dates": [], "missing_market_dates": [],
        },
    }
