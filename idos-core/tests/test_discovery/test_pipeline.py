from idos.discovery.pipeline import ScreeningPipeline
from idos.discovery.scout import ScoutEngine
from idos.discovery.watchlist import WatchlistManager
from idos.events.bus import get_event_bus


def test_pipeline_good_company_adds_to_watchlist():
    pipeline = ScreeningPipeline(min_watchlist_score=60)
    data = {
        "metrics": {
            "asset_type": "us_equity", "market_cap_usd": 50e9, "size_metric_usd": 50e9,
            "avg_dollar_volume_usd": 2e6, "market_data_normalization": {"status": "complete"},
            "liquidity_provenance": {"basis": "UNDERLYING_USD_PROXY"},
            "size_metric_provenance": {"source": "test", "as_of": "2026-10-16"},
            "market_cap_provenance": {"source": "test", "as_of": "2026-10-16"},
            "operating_margin_pct": 12, "fcf": 1_000_000_000, "revenue_growth_pct": 15,
        }
    }
    result = pipeline.process("MELI", data)
    assert result.passed is True
    assert pipeline.watchlist.count() == 1


def test_pipeline_rejects_poor_company():
    pipeline = ScreeningPipeline()
    data = {"metrics": {
        "asset_type": "us_equity", "market_cap_usd": 50e6, "size_metric_usd": 50e6,
        "avg_dollar_volume_usd": 10e3, "market_data_normalization": {"status": "complete"},
        "liquidity_provenance": {"basis": "UNDERLYING_USD_PROXY"},
        "size_metric_provenance": {"source": "test", "as_of": "2026-10-16"},
        "market_cap_provenance": {"source": "test", "as_of": "2026-10-16"},
        "operating_margin_pct": -1, "fcf": -1, "revenue_growth_pct": -1,
    }}
    result = pipeline.process("POOR", data)
    assert result.passed is False
    assert pipeline.watchlist.count() == 0


def test_pipeline_events():
    bus = get_event_bus()
    bus.clear()
    pipeline = ScreeningPipeline(min_watchlist_score=50)
    data = {"metrics": {
        "asset_type": "us_equity", "market_cap_usd": 10e9, "size_metric_usd": 10e9,
        "avg_dollar_volume_usd": 1e6, "market_data_normalization": {"status": "complete"},
        "liquidity_provenance": {"basis": "UNDERLYING_USD_PROXY"},
        "size_metric_provenance": {"source": "test", "as_of": "2026-10-16"},
        "market_cap_provenance": {"source": "test", "as_of": "2026-10-16"},
        "operating_margin_pct": 10, "fcf": 1, "revenue_growth_pct": 1,
    }}
    pipeline.process("EVENT_TEST", data)
    events = bus.get_history()
    scout_events = [e for e in events if e.type.startswith("scout:")]
    assert len(scout_events) > 0
