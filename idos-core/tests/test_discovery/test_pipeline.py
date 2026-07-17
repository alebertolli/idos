from idos.discovery.pipeline import ScreeningPipeline
from idos.discovery.scout import ScoutEngine
from idos.discovery.watchlist import WatchlistManager
from idos.events.bus import get_event_bus


def test_pipeline_good_company_adds_to_watchlist():
    pipeline = ScreeningPipeline(min_watchlist_score=60)
    data = {
        "metrics": {
            "market_cap": 50e9, "avg_volume": 2e6, "price_change_3m": 15,
            "price_change_12m": 30, "pe_ratio": 20, "ev_ebitda": 10,
            "roic": 25, "operating_margin": 20, "debt_to_equity": 0.3,
            "revenue_growth": 18,
        }
    }
    result = pipeline.process("MELI", data)
    assert result.passed is True
    assert pipeline.watchlist.count() == 1


def test_pipeline_rejects_poor_company():
    pipeline = ScreeningPipeline()
    data = {"metrics": {
        "market_cap": 50e6, "avg_volume": 10e3, "price_change_3m": -40,
        "price_change_12m": -60, "pe_ratio": 100, "ev_ebitda": 50,
        "roic": 1, "operating_margin": 0, "debt_to_equity": 10,
        "revenue_growth": -10,
    }}
    result = pipeline.process("POOR", data)
    assert result.passed is False
    assert pipeline.watchlist.count() == 0


def test_pipeline_events():
    bus = get_event_bus()
    bus.clear()
    pipeline = ScreeningPipeline(min_watchlist_score=50)
    data = {"metrics": {
        "market_cap": 10e9, "avg_volume": 1e6, "price_change_3m": 5,
        "price_change_12m": 10, "pe_ratio": 15, "ev_ebitda": 8,
        "roic": 20, "operating_margin": 18, "debt_to_equity": 0.4,
        "revenue_growth": 12,
    }}
    pipeline.process("EVENT_TEST", data)
    events = bus.get_history()
    scout_events = [e for e in events if e.type.startswith("scout:")]
    assert len(scout_events) > 0
