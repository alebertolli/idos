from pathlib import Path

from idos.site.builder import SiteBuilder


def _builder() -> SiteBuilder:
    return SiteBuilder.__new__(SiteBuilder)


def _opp(opp_id: str, ticker: str, intrinsic: float | None) -> dict:
    return {
        "opp_id": opp_id,
        "ticker": ticker,
        "status": "FULL_POSITION",
        "intrinsic_value": intrinsic,
    }


def _position(ticker: str, opp_id: str, current_price: float | None) -> dict:
    return {"ticker": ticker, "opp_id": opp_id, "current_price": current_price}


def _alerts(opps: list[dict], positions: list[dict]) -> list[dict]:
    return _builder()._build_dashboard(opps, positions, [], [], [])["alerts"]


def _sections(opps: list[dict], watchlist: list[dict], universe_stats: dict = None) -> list[dict]:
    return _builder()._build_dashboard(opps, [], [], watchlist, [], universe_stats)["sections"]


def test_no_alert_when_price_below_intrinsic():
    alerts = _alerts(
        [_opp("OPP-1", "AAA", 120.0)],
        [_position("AAA", "OPP-1", 100.0)],
    )
    assert alerts == []


def test_alert_when_price_above_intrinsic_by_opp_id():
    alerts = _alerts(
        [_opp("OPP-1", "AAA", 100.0)],
        [_position("AAA", "OPP-1", 130.0)],
    )
    assert len(alerts) == 1
    a = alerts[0]
    assert a["severity"] == "warn"
    assert a["ticker"] == "AAA"
    assert "30.0% sobre el valor intrínseco (100.00)" in a["message"]


def test_falls_back_to_ticker_when_opp_id_missing():
    alerts = _alerts(
        [_opp("OPP-1", "AAA", 50.0)],
        [_position("AAA", "OPP-NONE", 60.0)],
    )
    assert len(alerts) == 1
    assert alerts[0]["ticker"] == "AAA"


def test_no_alert_without_intrinsic_value():
    alerts = _alerts(
        [_opp("OPP-1", "AAA", None)],
        [_position("AAA", "OPP-1", 130.0)],
    )
    assert alerts == []


def test_no_alert_without_price():
    alerts = _alerts(
        [_opp("OPP-1", "AAA", 100.0)],
        [_position("AAA", "OPP-1", None)],
    )
    assert alerts == []


def test_discovery_shows_operable_count_from_universe_stats():
    universe_stats = {
        "operable_count": 267,
        "scout_passed": 57,
        "scout_rejected": 210,
        "finviz_count": 1874,
        "opportunities_created": 0,
    }
    sections = _sections([], [], universe_stats)
    discovery = next(s for s in sections if s["key"] == "discovery")
    assert discovery["count"] == 267


def test_research_shows_under_research_count_from_opps():
    universe_stats = {
        "operable_count": 267,
        "scout_passed": 57,
    }
    opps = [{"ticker": f"T{i}", "status": "UNDER_RESEARCH"} for i in range(57)]
    sections = _sections(opps, [], universe_stats)
    research = next(s for s in sections if s["key"] == "research")
    assert research["count"] == 57


def test_research_does_not_count_watchlist():
    universe_stats = {
        "operable_count": 267,
        "scout_passed": 57,
    }
    opps = [{"ticker": f"T{i}", "status": "WATCHLIST"} for i in range(57)]
    sections = _sections(opps, [], universe_stats)
    research = next(s for s in sections if s["key"] == "research")
    assert research["count"] == 0


def test_discovery_falls_back_to_zero_without_universe_stats():
    sections = _sections([], [], None)
    discovery = next(s for s in sections if s["key"] == "discovery")
    assert discovery["count"] == 0


def test_research_falls_back_to_funnel_count_without_universe_stats():
    opp = _opp("OPP-1", "AAA", 100.0)
    opp["status"] = "UNDER_RESEARCH"
    sections = _sections([opp], [], None)
    research = next(s for s in sections if s["key"] == "research")
    assert research["count"] == 1


def test_universe_stats_included_in_dashboard_return():
    universe_stats = {"operable_count": 267, "scout_passed": 57}
    result = _builder()._build_dashboard([], [], [], [], [], universe_stats)
    assert result["universe_stats"] == universe_stats


def test_universe_stats_empty_without_stats():
    result = _builder()._build_dashboard([], [], [], [], [], None)
    assert result["universe_stats"] == {}
