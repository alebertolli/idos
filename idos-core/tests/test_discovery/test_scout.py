from idos.discovery.scout import ScoutEngine


def test_scout_passes_good_company():
    scout = ScoutEngine(min_score=50)
    result = scout.scan("MELI", {
        "metrics": {
            "market_cap": 50e9,
            "avg_volume": 2e6,
            "price_change_3m": 15,
            "price_change_12m": 30,
            "pe_ratio": 25,
            "ev_ebitda": 12,
            "roic": 28,
            "operating_margin": 25,
            "debt_to_equity": 0.3,
            "revenue_growth": 20,
        }
    })
    assert result.passed is True
    assert result.score >= 50
    assert result.ticker == "MELI"


def test_scout_rejects_poor_company():
    scout = ScoutEngine(min_score=50)
    result = scout.scan("POOR", {
        "metrics": {
            "market_cap": 50e6,
            "avg_volume": 10e3,
            "price_change_3m": -30,
            "price_change_12m": -50,
            "pe_ratio": 50,
            "ev_ebitda": 30,
            "roic": 2,
            "operating_margin": 1,
            "debt_to_equity": 5.0,
            "revenue_growth": -5,
        }
    })
    assert result.passed is False
    assert result.score < 50


def test_scout_all_dimensions_scored():
    scout = ScoutEngine()
    result = scout.scan("TEST", {"metrics": {"market_cap": 10e9, "avg_volume": 1e6,
        "price_change_3m": 10, "price_change_12m": 20, "pe_ratio": 15,
        "ev_ebitda": 10, "roic": 15, "operating_margin": 15,
        "debt_to_equity": 0.5, "revenue_growth": 10}})
    assert len(result.details) == 5
    for dim, s in result.details.items():
        assert 0 <= s <= 100
