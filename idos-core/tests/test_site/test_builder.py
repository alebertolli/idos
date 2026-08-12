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
