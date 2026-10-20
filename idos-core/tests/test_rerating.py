import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from idos.research.rerating import (
    ReratingProbabilityEngine, ReratingDimensions, RecoveryScore, DualProbability
)


def test_recovery_score_calculation():
    engine = ReratingProbabilityEngine()
    dims = ReratingDimensions(
        business_momentum=85, valuation_gap=75, market_expectations=70,
        catalysts=80, technical_confirmation=65, risk_compression=70,
    )
    score = engine.calculate_recovery_score(dims)
    assert 0 <= score.overall <= 100
    assert score.overall > 70


def test_low_recovery_score():
    engine = ReratingProbabilityEngine()
    dims = ReratingDimensions(
        business_momentum=30, valuation_gap=40, market_expectations=35,
        catalysts=20, technical_confirmation=30, risk_compression=40,
    )
    score = engine.calculate_recovery_score(dims)
    assert score.overall < 60
    assert score.rerating_probability == 0.31


def test_high_recovery_probability():
    score = RecoveryScore(overall=90)
    assert score.rerating_probability == 0.72
    assert score.probability_label == "HIGH"


def test_medium_recovery_probability():
    score = RecoveryScore(overall=75)
    assert score.rerating_probability == 0.55
    assert score.probability_label == "MEDIUM"


def test_low_recovery_probability():
    score = RecoveryScore(overall=50)
    assert score.rerating_probability == 0.31
    assert score.probability_label == "LOW"


def test_dual_probability_high():
    dp = DualProbability(bsp=0.90, mrp=0.85)
    assert dp.opportunity_class == "PRIME"
    assert dp.tsp > 0.80


def test_dual_probability_business_focus():
    dp = DualProbability(bsp=0.85, mrp=0.30)
    assert dp.opportunity_class == "QUALITY_BUSINESS"


def test_dual_probability_momentum():
    dp = DualProbability(bsp=0.40, mrp=0.85)
    assert dp.opportunity_class == "MOMENTUM"


def test_dual_probability_speculative():
    dp = DualProbability(bsp=0.40, mrp=0.40)
    assert dp.opportunity_class == "SPECULATIVE"


def test_calculate_dual_probability():
    engine = ReratingProbabilityEngine()
    dp = engine.calculate_dual_probability(
        bsp_inputs={"roic": 28, "revenue_growth": 15, "operating_margin": 30, "debt_to_equity": 0.1},
        mrp_inputs={"pe_percentile_5y": 15, "has_catalyst": True, "wyckoff_phase": "ACCUMULATION"},
    )
    assert 0 < dp.bsp < 1
    assert 0 < dp.mrp < 1
    assert dp.tsp > 0


def test_recovery_index():
    engine = ReratingProbabilityEngine()
    score = RecoveryScore(overall=85)
    dp = DualProbability(bsp=0.88, mrp=0.82)
    ri = engine.calculate_recovery_index(score, dp, expected_upside_pct=60, expected_time_months=24)
    assert ri > 0
    assert ri < 1


if __name__ == "__main__":
    test_recovery_score_calculation()
    test_low_recovery_score()
    test_high_recovery_probability()
    test_medium_recovery_probability()
    test_low_recovery_probability()
    test_dual_probability_high()
    test_dual_probability_business_focus()
    test_dual_probability_momentum()
    test_dual_probability_speculative()
    test_calculate_dual_probability()
    test_recovery_index()
    print("ALL RERATING TESTS PASSED")
