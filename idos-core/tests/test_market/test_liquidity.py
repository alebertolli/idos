from datetime import date, datetime, timedelta, timezone

import pytest

from idos.market.liquidity import (
    FxObservation,
    LiquidityPolicy,
    MarketDataNormalizationError,
    MonedApiFxProvider,
    MarketDataSettings,
    expected_us_market_sessions,
    normalize_average_dollar_turnover,
    normalize_market_cap_usd,
)


def _days(count=20):
    result = []
    current = date(2026, 9, 1)
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def test_usd_turnover_uses_close_times_same_day_volume_and_20_session_window():
    rows = [
        {
            "date": day.isoformat(), "close": 10, "volume": 1000,
            "price_basis": "close_unadjusted", "source": "exchange-feed",
        }
        for day in _days(21)
    ]
    result = normalize_average_dollar_turnover(
        rows,
        expected_market_dates=_days(21)[1:],
        quote_currency="USD",
        source="exchange-feed",
        policy=LiquidityPolicy(),
    )

    assert result["avg_dollar_volume_usd"] == 10_000
    assert result["liquidity_provenance"]["valid_observations"] == 20
    assert result["liquidity_provenance"]["first_price_date"] == _days(21)[1].isoformat()


def test_turnover_accepts_exactly_80_percent_valid_observations():
    rows = [
        {"date": day.isoformat(), "close": 10 if index < 16 else None, "volume": 1000, "price_basis": "close_unadjusted"}
        for index, day in enumerate(_days())
    ]
    result = normalize_average_dollar_turnover(
        rows, expected_market_dates=_days(), quote_currency="USD", source="vendor"
    )
    assert result["avg_dollar_volume_usd"] == 10_000
    assert result["liquidity_provenance"]["coverage"] == 0.8


def test_turnover_fails_closed_below_80_percent_coverage():
    rows = [
        {"date": day.isoformat(), "close": 10 if index < 15 else None, "volume": 1000, "price_basis": "close_unadjusted"}
        for index, day in enumerate(_days())
    ]
    result = normalize_average_dollar_turnover(
        rows, expected_market_dates=_days(), quote_currency="USD", source="vendor"
    )
    assert result["avg_dollar_volume_usd"] is None


def test_turnover_counts_missing_expected_market_sessions_as_invalid():
    expected = _days()
    rows = [
        {"date": day.isoformat(), "close": 10, "volume": 1000, "price_basis": "close_unadjusted"}
        for day in expected[:-5]
    ]
    result = normalize_average_dollar_turnover(
        rows, expected_market_dates=expected, quote_currency="USD", source="vendor"
    )
    assert result["avg_dollar_volume_usd"] is None
    assert result["liquidity_provenance"]["valid_observations"] == 15
    assert len(result["liquidity_provenance"]["missing_market_dates"]) == 5


def test_turnover_requires_complete_expected_session_calendar():
    result = normalize_average_dollar_turnover(
        [], expected_market_dates=_days(19), quote_currency="USD", source="vendor"
    )
    assert result["avg_dollar_volume_usd"] is None
    assert result["liquidity_provenance"]["expected_observations"] == 20


def test_ars_turnover_converts_each_market_day_with_sell_rate_and_prior_fx():
    fx = [
        FxObservation(datetime.combine(day, datetime.min.time(), timezone.utc), sell=1000)
        for day in _days()
    ]
    rows = [
        {"date": day.isoformat(), "close": 100_000, "volume": 10, "price_basis": "close_unadjusted"}
        for day in _days()
    ]
    result = normalize_average_dollar_turnover(
        rows,
        expected_market_dates=_days(),
        quote_currency="ARS",
        source="local-market-feed",
        fx_reference="MEP",
        fx_observations=fx,
    )
    assert result["avg_dollar_volume_usd"] == 1000
    assert result["liquidity_provenance"]["fx_side"] == "sell"
    assert result["liquidity_provenance"]["fx_reference"] == "MEP"


def test_ars_turnover_rejects_missing_fx_reference_and_stale_fx():
    row = [{"date": day.isoformat(), "close": 100, "volume": 10, "price_basis": "close_unadjusted"} for day in _days()]
    with pytest.raises(MarketDataNormalizationError, match="explicit"):
        normalize_average_dollar_turnover(
            row, expected_market_dates=_days(), quote_currency="ARS", source="vendor"
        )
    stale = [FxObservation(datetime(2026, 8, 1, tzinfo=timezone.utc), sell=1000)]
    result = normalize_average_dollar_turnover(
        row, expected_market_dates=_days(), quote_currency="ARS", source="vendor",
        fx_reference="CCL", fx_observations=stale
    )
    assert result["avg_dollar_volume_usd"] is None


def test_unknown_currency_and_non_finite_values_do_not_normalize():
    with pytest.raises(MarketDataNormalizationError, match="Unsupported quote currency"):
        normalize_average_dollar_turnover(
            [], expected_market_dates=_days(), quote_currency="EUR", source="vendor"
        )
    rows = [{"date": day.isoformat(), "close": float("nan"), "volume": 1000, "price_basis": "close_unadjusted"} for day in _days()]
    result = normalize_average_dollar_turnover(
        rows, expected_market_dates=_days(), quote_currency="USD", source="vendor"
    )
    assert result["avg_dollar_volume_usd"] is None


def test_market_cap_requires_currency_and_as_of_fx():
    usd = normalize_market_cap_usd(2_000_000_000, currency="USD", as_of=date(2026, 9, 10), source="vendor")
    assert usd["market_cap_usd"] == 2_000_000_000
    fx = [FxObservation(datetime(2026, 9, 9, 18, tzinfo=timezone.utc), sell=1000)]
    ars = normalize_market_cap_usd(
        2_000_000_000_000, currency="ARS", as_of=date(2026, 9, 10), source="vendor",
        fx_reference="MEP", fx_observations=fx,
    )
    assert ars["market_cap_usd"] == 2_000_000_000
    with pytest.raises(MarketDataNormalizationError, match="currency"):
        normalize_market_cap_usd(2_000_000_000, currency="EUR", as_of=date(2026, 9, 10), source="vendor")


def test_monedapi_adapter_validates_schema_uses_bounded_request_and_caches():
    MonedApiFxProvider._cache.clear()
    calls = []

    class Response:
        status_code = 200
        headers = {}

        @staticmethod
        def json():
            return [{"buy": 990, "sell": 1000, "createdAt": "2026-09-10T18:00:00-03:00"}]

    def get(url, *, params, timeout):
        calls.append((url, params, timeout))
        return Response()

    provider = MonedApiFxProvider(timeout_seconds=5, get=get)
    first = provider.history("MEP", date(2026, 9, 1), date(2026, 9, 10))
    second = provider.history("mep", date(2026, 9, 1), date(2026, 9, 10))
    assert first == second
    assert len(calls) == 1
    assert calls[0][0].endswith("/bolsa")
    assert calls[0][1]["limit"] == 500
    assert calls[0][2] == 5


def test_monedapi_adapter_rejects_bad_status_and_history_shape():
    class Response:
        status_code = 429
        headers = {"Retry-After": "10"}

    provider = MonedApiFxProvider(get=lambda *args, **kwargs: Response())
    with pytest.raises(MarketDataNormalizationError, match="429.*10"):
        provider.history("CCL", date(2026, 9, 1), date(2026, 9, 10))

    class BadJsonResponse(Response):
        status_code = 200

        @staticmethod
        def json():
            return {"history": []}

    provider = MonedApiFxProvider(get=lambda *args, **kwargs: BadJsonResponse())
    with pytest.raises(MarketDataNormalizationError, match="schema"):
        provider.history("CCL", date(2026, 9, 1), date(2026, 9, 10))


def test_market_data_settings_load_shared_thresholds_and_liquidity_window(tmp_path):
    (tmp_path / "market_data.yml").write_text(
        "eligibility:\n  market_cap_min_usd: 3000000000\n"
        "  avg_dollar_volume_min_usd: 250000\n"
        "liquidity:\n  window_sessions: 20\n  minimum_coverage: 0.8\n"
        "  max_fx_staleness_days: 4\n  fx_side: sell\n",
        encoding="utf-8",
    )
    settings = MarketDataSettings.load(str(tmp_path))
    assert settings.market_cap_min_usd == 3_000_000_000
    assert settings.avg_dollar_volume_min_usd == 250_000
    assert settings.liquidity.window_sessions == 20


def test_market_data_settings_rejects_non_mapping_configuration(tmp_path):
    (tmp_path / "market_data.yml").write_text("- invalid-root\n", encoding="utf-8")
    with pytest.raises(MarketDataNormalizationError, match="Invalid market data configuration"):
        MarketDataSettings.load(str(tmp_path))


def test_exchange_calendar_excludes_us_market_holiday_and_unknown_exchange():
    sessions = expected_us_market_sessions(date(2026, 9, 4), date(2026, 9, 8), "NMS")
    assert date(2026, 9, 7) not in sessions  # Labor Day
    assert date(2026, 9, 8) in sessions
    with pytest.raises(MarketDataNormalizationError, match="Unsupported Yahoo exchange"):
        expected_us_market_sessions(date(2026, 9, 1), date(2026, 9, 10), "UNKNOWN")
