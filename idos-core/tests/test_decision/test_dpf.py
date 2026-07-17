from idos.decision.dpf import DualProbabilityFramework


def test_dpf_evaluation():
    dpf = DualProbabilityFramework()
    ctx = {
        "knowledge_base": {
            "static": {"moat_description": "Strong moat"},
            "dynamic": {
                "metrics": {
                    "roic": 25, "revenue_growth": 20, "operating_margin": 25,
                    "pe_ratio": 12, "pe_historical_avg": 20, "fcf_yield": 5,
                    "short_interest_pct": 10,
                }
            }
        },
        "margin_of_safety": 35,
        "catalysts": [{"impact": "high", "timeline": "short"}],
    }
    result = dpf.evaluate(ctx)
    assert "bsp" in result
    assert "mrp" in result
    assert "tsp" in result
    assert 0 <= result["bsp"] <= 1
    assert 0 <= result["mrp"] <= 1
    assert 0 <= result["tsp"] <= 1


def test_position_sizing():
    dpf = DualProbabilityFramework()
    size = dpf.calculate_position_size(0.7, 100000, 3.0)
    assert size > 0
    assert size <= 3000
    size_zero = dpf.calculate_position_size(0, 100000, 3.0)
    assert size_zero == 0
