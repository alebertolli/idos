from idos.discovery.scout import ScoutEngine


def test_scout_passes_good_company():
    scout = ScoutEngine(min_score=70)
    result = scout.scan("MELI", {
        "metrics": {
            "market_cap": 50e9,
            "avg_dollar_volume": 2e6,
            "relative_strength_3m": 80,
            "relative_strength_12m": 70,
            "price_volume_trend": 5,
            "roic": 0.18,
            "fcf_yield": 0.05,
            "debt_to_equity": 0.4,
        }
    })
    assert result.passed is True
    assert result.score >= 70
    assert result.ticker == "MELI"


def test_scout_rejects_poor_company():
    scout = ScoutEngine(min_score=70)
    result = scout.scan("POOR", {
        "metrics": {
            "market_cap": 50e6,
            "avg_dollar_volume": 10e3,
            "relative_strength_3m": -30,
            "relative_strength_12m": -50,
            "price_volume_trend": -5,
            "roic": 0.02,
            "fcf_yield": -0.01,
            "debt_to_equity": 3.0,
        }
    })
    assert result.passed is False
    assert result.score < 70


def test_scout_all_dimensions_scored():
    scout = ScoutEngine()
    result = scout.scan("TEST", {"metrics": {"market_cap": 10e9, "avg_dollar_volume": 1e6,
        "relative_strength_3m": 10, "relative_strength_12m": 20,
        "roic": 0.15, "fcf_yield": 0.03, "debt_to_equity": 0.5}})
    assert len(result.details) >= 3
    for dim, s in result.details.items():
        assert 0 <= s <= 100