from pathlib import Path

from idos.discovery.configured_scout import configured_scout
from idos.discovery.configured_scout import ConfiguredScoutEngine
from idos.market.liquidity import MarketDataSettings


def _market(**values):
    return {
        "asset_type": "us_equity", "size_metric_usd": 3_000_000_000, "market_cap_usd": 3_000_000_000,
        "avg_dollar_volume_usd": 100_000,
        "market_data_normalization": {"status": "complete"},
        "liquidity_provenance": {"basis": "UNDERLYING_USD_PROXY"},
        "size_metric_provenance": {"source": "test", "as_of": "2026-10-16"},
        "market_cap_provenance": {"source": "test", "as_of": "2026-10-16"},
        **values,
    }


def test_compounder_uses_configured_positive_filters_and_neutral_screening_result():
    engine = configured_scout(Path(__file__).parents[3] / "idos-config")
    result = engine.scan_market_data("TEST", _market(
        operating_margin_pct=0.01, fcf=1, revenue_growth_pct=0.01,
    ))
    assert result.passed
    assert result.status == "PASSED"
    assert result.score == 100  # Eligibility only; never copied to conviction.
    assert result.policy_version == "positive_fundamentals_v1"
    assert result.details == {
        "operating_margin_pct": 100, "fcf": 100,
        "revenue_growth_pct": 100, "investability": 100,
    }


def test_missing_metric_is_pending_and_does_not_pass():
    engine = configured_scout(Path(__file__).parents[3] / "idos-config")
    result = engine.scan_market_data("TEST", _market(
        operating_margin_pct=1, fcf=10,
    ))
    assert result.status == "PENDING_DATA"
    assert result.missing_metrics == ["revenue_growth_pct"]
    assert not result.passed


def test_negative_metric_rejects_without_technical_or_roic_inputs():
    engine = configured_scout(Path(__file__).parents[3] / "idos-config")
    result = engine.scan_market_data("TEST", _market(
        operating_margin_pct=-1, fcf=10, revenue_growth_pct=1,
    ))
    assert result.status == "REJECTED"
    assert result.details["operating_margin_pct"] == 0
    assert not result.passed


def test_conflicting_source_signs_block_promotion():
    engine = configured_scout(Path(__file__).parents[3] / "idos-config")
    result = engine.scan_market_data("TEST", _market(
        operating_margin_pct=2, fcf=10, revenue_growth_pct=1,
        financial_observations={"fcf": {"values": {"provider_a": 10, "provider_b": -2}}},
    ))
    assert result.status == "PENDING_DATA"
    assert "fcf" in result.missing_metrics


def test_etf_scout_needs_liquidity_but_not_market_cap_or_aum():
    config = Path(__file__).parents[3] / "idos-config"
    equity = configured_scout(config)
    engine = ConfiguredScoutEngine(equity.policy, MarketDataSettings.load(config), ["etf"])
    data = _market(operating_margin_pct=1, fcf=1, revenue_growth_pct=1, asset_type="etf")
    for key in ("size_metric_usd", "market_cap_usd", "size_metric_provenance", "market_cap_provenance"):
        data.pop(key, None)
    result = engine.scan_market_data("ETF", data)
    assert result.passed


def test_invalid_scout_policy_fails_at_construction():
    import pytest
    with pytest.raises(ValueError, match="versioned, nonempty"):
        ConfiguredScoutEngine({}, MarketDataSettings.load(Path(__file__).parents[3] / "idos-config"), ["us_equity"])
