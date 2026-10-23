from datetime import date, datetime, timedelta, timezone

import pytest

from idos.market.liquidity import (
    FxObservation,
    LiquidityPolicy,
    MarketDataNormalizationError,
    MonedApiFxProvider,
    normalize_average_dollar_turnover,
    normalize_market_cap_usd,
)


def _rows(days, *, price=10, volume=100, currency="USD"):
    return [
        {
            "date": day.isoformat(),
            "close": price,
            "volume": volume,
            "price_basis": "close_unadjusted",
            "source": "fixture",
        }
        for day in days
    ]


def test_usd_turnover_uses_available_observations_and_unadjusted_close():
    days = [date(2026, 9, 1) + timedelta(days=index) for index in range(20)]
    result = normalize_average_dollar_turnover(
        _rows(days[:16]),
        expected_market_dates=days,
        quote_currency="USD",
        source="fixture",
    )

    assert result["avg_dollar_volume_usd"] == 1_000
    assert result["liquidity_provenance"]["coverage"] == 0.8
    assert result["liquidity_provenance"]["valid_observations"] == 16
    assert result["liquidity_provenance"]["price_source"] == "fixture"

    with pytest.raises(MarketDataNormalizationError, match="unadjusted"):
        normalize_average_dollar_turnover(
            [{**_rows(days[:1])[0], "price_basis": "adjusted"}],
            expected_market_dates=days[:1],
            quote_currency="USD",
            source="fixture",
            policy=LiquidityPolicy(window_sessions=1, minimum_coverage=1),
        )


def test_ars_turnover_requires_usd_metric_while_legacy_cap_normalizer_remains_available():
    observed_at = datetime(2026, 9, 1, 18, tzinfo=timezone.utc)
    fx = [FxObservation(observed_at=observed_at, sell=1_000)]
    with pytest.raises(MarketDataNormalizationError, match="USD-denominated"):
        normalize_average_dollar_turnover(
            _rows([date(2026, 9, 1)], price=10, volume=100),
            expected_market_dates=[date(2026, 9, 1)],
            quote_currency="ARS", source="fixture",
            policy=LiquidityPolicy(window_sessions=1),
        )
    cap = normalize_market_cap_usd(
        2_000_000_000_000,
        currency="ARS",
        as_of=date(2026, 9, 1),
        source="fixture",
        fx_reference="MEP",
        fx_observations=fx,
    )

    assert cap["market_cap_usd"] == 2_000_000_000


def test_fx_provider_uses_documented_mep_pair_and_validates_payload():
    MonedApiFxProvider._cache.clear()
    calls = []

    class Response:
        status_code = 200
        headers = {}

        @staticmethod
        def json():
            return [{"buy": 999, "sell": 1_000, "createdAt": "2026-09-01T18:00:00-03:00"}]

    def fake_get(url, *, params, timeout):
        calls.append((url, params, timeout))
        return Response()

    provider = MonedApiFxProvider(get=fake_get)
    observations = provider.history("MEP", date(2026, 9, 1), date(2026, 9, 2))

    assert calls[0][0] == "https://monedapi.ar/api/v2/history/usd/bolsa"
    assert calls[0][1] == {"date_from": "2026-09-01", "date_to": "2026-09-02", "limit": 500}
    assert observations[0].sell == 1_000
    assert observations[0].observed_at.tzinfo is not None


def test_fx_provider_surfaces_retry_after_without_hot_loop():
    class RateLimitedResponse:
        status_code = 429
        headers = {"Retry-After": "10"}

    provider = MonedApiFxProvider(get=lambda *_args, **_kwargs: RateLimitedResponse())
    with pytest.raises(MarketDataNormalizationError, match="Retry-After: 10s"):
        provider.history("CCL", date(2026, 9, 1), date(2026, 9, 2))


def test_ars_turnover_does_not_attempt_fx_conversion():
    day = date(2026, 9, 10)
    with pytest.raises(MarketDataNormalizationError, match="USD-denominated"):
        normalize_average_dollar_turnover(
            _rows([day]), expected_market_dates=[day], quote_currency="ARS", source="fixture",
            policy=LiquidityPolicy(window_sessions=1, minimum_coverage=1),
        )

    with pytest.raises(MarketDataNormalizationError, match="stale"):
        normalize_market_cap_usd(
            1_000_000,
            currency="ARS",
            as_of=day,
            source="fixture",
            fx_reference="CCL",
            fx_observations=[FxObservation(datetime(2026, 9, 1, tzinfo=timezone.utc), 1_000)],
            max_fx_staleness_days=4,
        )
