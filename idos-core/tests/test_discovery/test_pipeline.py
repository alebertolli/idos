from idos.discovery.pipeline import ScreeningPipeline
from idos.discovery.scout import ScoutEngine
from idos.discovery.watchlist import WatchlistManager
from idos.events.bus import get_event_bus


def test_pipeline_good_company_adds_to_watchlist():
    pipeline = ScreeningPipeline(min_watchlist_score=60)
    data = {
        "metrics": {
            "market_cap": 50e9, "avg_dollar_volume": 2e6,
            "relative_strength_3m": 80, "relative_strength_12m": 70,
            "price_volume_trend": 5, "roic": 0.18,
            "fcf_yield": 0.05, "debt_to_equity": 0.4,
        }
    }
    result = pipeline.process("MELI", data)
    assert result.passed is True
    assert pipeline.watchlist.count() == 1


def test_pipeline_rejects_poor_company():
    pipeline = ScreeningPipeline()
    data = {"metrics": {
        "market_cap": 50e6, "avg_dollar_volume": 10e3,
        "relative_strength_3m": -30, "relative_strength_12m": -50,
        "price_volume_trend": -5, "roic": 0.02,
        "fcf_yield": -0.01, "debt_to_equity": 3.0,
    }}
    result = pipeline.process("POOR", data)
    assert result.passed is False
    assert pipeline.watchlist.count() == 0


def test_pipeline_events():
    bus = get_event_bus()
    bus.clear()
    pipeline = ScreeningPipeline(min_watchlist_score=50)
    data = {"metrics": {
        "market_cap": 10e9, "avg_dollar_volume": 1e6,
        "relative_strength_3m": 5, "relative_strength_12m": 10,
        "price_volume_trend": 0, "roic": 0.2,
        "fcf_yield": 0.03, "debt_to_equity": 0.4,
    }}
    pipeline.process("EVENT_TEST", data)
    events = bus.get_history()
    scout_events = [e for e in events if e.type.startswith("scout:")]
    assert len(scout_events) > 0