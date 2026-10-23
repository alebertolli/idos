from pathlib import Path

from idos.discovery.configured_scout import configured_scout
from idos.discovery.configured_scout import ConfiguredScoutEngine
from idos.market.liquidity import MarketDataSettings


def _market(**values):
    return {
        "asset_type": "us_equity", "quote_currency": "USD", "size_metric_usd": 3_000_000_000, "market_cap_usd": 3_000_000_000,
        "avg_dollar_volume_usd": 100_000,
        "market_data_normalization": {"status": "complete"},
        "liquidity_provenance": {"basis": "UNDERLYING_USD_PROXY", "source": "test", "as_of": "2026-10-16", "currency": "USD"},
        "size_metric_provenance": {"source": "test", "as_of": "2026-10-16", "currency": "USD"},
        "market_cap_provenance": {"source": "test", "as_of": "2026-10-16", "currency": "USD"},
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


def test_compounder_accepts_country_neutral_equity_type_and_keeps_market_cap_gate():
    engine = configured_scout(Path(__file__).parents[3] / "idos-config")
    result = engine.scan_market_data("ASML", _market(
        asset_type="equity", operating_margin_pct=1, fcf=1, revenue_growth_pct=1,
    ))

    assert result.passed
    assert result.details["investability"] == 100


def test_compounder_rejects_etf_asset_class():
    engine = configured_scout(Path(__file__).parents[3] / "idos-config")
    result = engine.scan_market_data("ETF", _market(
        asset_type="etf", operating_margin_pct=1, fcf=1, revenue_growth_pct=1,
    ))

    assert result.status == "REJECTED"
    assert "Tipo de activo no habilitado" in result.reason


def test_compounder_universe_accepts_canonical_and_legacy_equity_labels(tmp_path):
    from idos.workers.data.pipeline_report import PipelineMetrics
    from idos.workers.data.universe_pipeline import UniversePipeline

    config = tmp_path / "config"
    universe = config / "universe"
    universe.mkdir(parents=True)
    (config / "strategies.yml").write_text(
        "strategies:\n"
        "  COMPOUNDER:\n"
        "    enabled: true\n"
        "    core: CORE_3_GROWTH\n"
        "    sleeve: HIGH_CONVICTION\n"
        "    thesis_type: STRATEGIC\n"
        "    discovery_profile: compounder\n"
        "    research_profile: strategic\n"
        "    entry_policy: VALUATION_ZONE\n"
        "    parameters:\n"
        "      supported_asset_types: [equity]\n",
        encoding="utf-8",
    )
    (universe / "operable.yml").write_text(
        "operable_tickers:\n"
        "  - {ticker: ASML, type: equity}\n"
        "  - {ticker: MELI, type: us_equity}\n"
        "  - {ticker: QQQ, type: etf}\n",
        encoding="utf-8",
    )
    pipeline = UniversePipeline({"config_path": str(config)})
    metrics = PipelineMetrics()

    pipeline._load_candidate_universe(metrics)

    assert metrics.candidate_tickers == ["ASML", "MELI"]


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


def test_material_source_conflict_blocks_promotion_even_when_both_values_pass_filter():
    engine = configured_scout(Path(__file__).parents[3] / "idos-config")
    result = engine.scan_market_data("TEST", _market(
        operating_margin_pct=44.356, fcf=10_374_124_544, revenue_growth_pct=55.2,
        data_provenance={"conflicts": [
            {"field": "fcf", "deviation_pct": 78.4},
            {"field": "revenue_growth_pct", "deviation_pct": 61.1},
        ]},
        financial_observations={
            "fcf": {"values": {"stockanalysis.com": 23_750_000_000, "yfinance": 10_374_124_544}},
            "revenue_growth_pct": {"values": {"stockanalysis.com": 29.38, "yfinance": 55.2}},
        },
    ))

    assert result.status == "PENDING_DATA"
    assert result.conflicting_metrics == ["fcf", "revenue_growth_pct"]
    assert set(result.missing_metrics) >= {"fcf", "revenue_growth_pct"}
    assert "Evidencia contradictoria" in result.reason
    assert not result.passed


def test_scout_uses_selected_value_and_ignores_non_comparable_peer():
    engine = configured_scout(Path(__file__).parents[3] / "idos-config")
    result = engine.scan_market_data("TEST", _market(
        operating_margin_pct=18.3, fcf=10, revenue_growth_pct=22.54,
        data_provenance={"conflicts": []},
        financial_observations={
            "revenue_growth_pct": {
                "selected_source": "stockanalysis.com",
                "values": {"stockanalysis.com": 22.54},
                "non_comparable_values": {"yfinance": -55.2},
                "period_status": "SINGLE_SOURCE",
                "non_comparable_reason": "different_period_unit_currency_or_cutoff",
            },
        },
    ))

    assert result.passed
    assert result.observed_metrics["revenue_growth_pct"] == 22.54


def test_scout_blocks_financial_filter_when_selected_period_is_unspecified():
    engine = configured_scout(Path(__file__).parents[3] / "idos-config")
    result = engine.scan_market_data("TEST", _market(
        operating_margin_pct=18.3, fcf=10, revenue_growth_pct=22.54,
        data_provenance={"conflicts": []},
        financial_observations={
            "revenue_growth_pct": {
                "selected_source": "yfinance",
                "values": {"yfinance": 22.54},
                "period_status": "PERIOD_UNSPECIFIED",
            },
        },
    ))

    assert not result.passed
    assert "revenue_growth_pct" in result.missing_metrics


def test_universe_pipeline_preserves_conflicting_metric_reason():
    from idos.workers.data.universe_pipeline import UniversePipeline

    config = Path(__file__).parents[3] / "idos-config"
    pipeline = UniversePipeline({"config_path": str(config)})
    result = pipeline._score_ticker(None, "TEST", _market(
        operating_margin_pct=44.356, fcf=10_374_124_544, revenue_growth_pct=55.2,
        data_provenance={"conflicts": [{"field": "fcf", "deviation_pct": 78.4}]},
        financial_observations={
            "fcf": {"values": {"stockanalysis.com": 23_750_000_000, "yfinance": 10_374_124_544}},
        },
    ))

    assert result["status"] == "PENDING_DATA"
    assert result["data_quality_valid"] is False
    assert result["conflicting_metrics"] == ["fcf"]
    assert "Evidencia contradictoria" in result["reason"]


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
