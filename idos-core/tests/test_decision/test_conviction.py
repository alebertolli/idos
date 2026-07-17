from idos.decision.conviction import ConvictionCalculator
from idos.decision.engines.base import AssessmentResult
from idos.models.conviction import Conviction


def test_conviction_calculation():
    calc = ConvictionCalculator()
    assessments = {
        "BusinessAssessmentEngine": AssessmentResult(
            engine="BusinessAssessmentEngine", score=90, confidence="HIGH"),
        "ValuationAssessmentEngine": AssessmentResult(
            engine="ValuationAssessmentEngine", score=75, confidence="HIGH"),
        "RecoveryAssessmentEngine": AssessmentResult(
            engine="RecoveryAssessmentEngine", score=80, confidence="MEDIUM"),
        "RiskAssessmentEngine": AssessmentResult(
            engine="RiskAssessmentEngine", score=70, confidence="MEDIUM"),
        "PortfolioAssessmentEngine": AssessmentResult(
            engine="PortfolioAssessmentEngine", score=85, confidence="HIGH"),
    }
    conv = calc.calculate(assessments)
    assert 0 <= conv.overall <= 100
    assert conv.confidence.value == "HIGH"
    assert conv.trend.value == "STABLE"


def test_conviction_with_previous():
    calc = ConvictionCalculator()
    prev = Conviction(overall=70)
    assessments = {
        "BusinessAssessmentEngine": AssessmentResult(
            engine="BusinessAssessmentEngine", score=95, confidence="HIGH"),
    }
    conv = calc.calculate(assessments, prev)
    assert conv.trend.value == "IMPROVING"
    assert conv.overall > 70


def test_conviction_with_low_confidence():
    calc = ConvictionCalculator()
    assessments = {
        "BusinessAssessmentEngine": AssessmentResult(
            engine="BusinessAssessmentEngine", score=50, confidence="LOW"),
        "ValuationAssessmentEngine": AssessmentResult(
            engine="ValuationAssessmentEngine", score=45, confidence="LOW"),
        "RecoveryAssessmentEngine": AssessmentResult(
            engine="RecoveryAssessmentEngine", score=55, confidence="LOW"),
    }
    conv = calc.calculate(assessments)
    assert conv.confidence.value == "LOW"
