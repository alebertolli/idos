from idos.decision.rpf import ReratingProbabilityEngine


def test_rpf_high_score():
    rpf = ReratingProbabilityEngine()
    ctx = {
        "knowledge_base": {
            "dynamic": {
                "metrics": {
                    "revenue_growth": 25, "eps_growth": 20, "fcf_growth": 18,
                    "roic": 28, "operating_margin": 30,
                    "pe_ratio": 12, "pe_historical_avg": 22, "fcf_yield": 6,
                    "short_interest_pct": 15,
                    "intrinsic_value": 200, "current_price": 100,
                }
            }
        },
        "margin_of_safety": 50,
        "catalysts": [
            {"impact": "high", "timeline": "short"},
            {"impact": "high", "timeline": "short"},
        ],
    }
    index = rpf.evaluate(ctx)
    assert index.probability > 0.5
    assert index.magnitude >= 1.0
    assert index.index_value > 0


def test_rpf_calibration():
    rpf = ReratingProbabilityEngine()
    rpf.calibrate("high", 0.80)
    assert rpf.get_calibration()["high"] == 0.80
