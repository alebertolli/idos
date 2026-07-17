from datetime import datetime
from idos.models.knowledge import Company, Hypothesis, Evidence, Rule, Prediction
from idos.models.journal import Opportunity, Assessment, Decision, PortfolioPosition, CaseFile, Review
from idos.models.conviction import Conviction
from idos.models.enums import (
    OpportunityStatus, HypothesisStatus, AssessmentStatus,
    DecisionType, ConfidenceLevel, ConvictionTrend,
)


def test_company_creation():
    c = Company(ticker="MELI", name="MercadoLibre", sector="Technology")
    assert c.ticker == "MELI"
    assert c.currency == "USD"


def test_opportunity_creation():
    opp = Opportunity(id="OPP-2026-001", ticker="MELI")
    assert opp.status == OpportunityStatus.DISCOVERED
    assert opp.conviction.overall == 0


def test_hypothesis_creation():
    h = Hypothesis(
        id="HYP-001",
        opportunity_id="OPP-2026-001",
        ticker="MELI",
        statement="Market underestimates margin expansion",
        falsification_conditions=["Margin drops below 10%"],
    )
    assert h.status == HypothesisStatus.DRAFT
    assert len(h.falsification_conditions) == 1


def test_assessment_creation():
    a = Assessment(id="ASM-001", engine="BusinessAssessmentEngine", score=85)
    assert a.status == AssessmentStatus.PENDING
    assert a.score == 85


def test_decision_creation():
    d = Decision(id="DEC-001", type=DecisionType.BUY, opportunity_id="OPP-2026-001", justification="Strong thesis")
    assert d.type == DecisionType.BUY


def test_conviction_creation():
    c = Conviction(overall=84, confidence=ConfidenceLevel.HIGH, trend=ConvictionTrend.IMPROVING)
    assert c.overall == 84
    assert c.confidence == ConfidenceLevel.HIGH


def test_prediction_creation():
    p = Prediction(id="PRED-001", variable="EBIT Margin", expected_value=15.0, measurement_date="2026-12-31")
    assert p.status == "PENDING"


def test_evidence_creation():
    e = Evidence(id="EVI-001", description="ROIC improved to 31%", source="Annual Report 2025", event_date="2025-12-31")
    assert e.reliability == ConfidenceLevel.MEDIUM


def test_rule_creation():
    r = Rule(id="RULE-001", description="Min business score", condition="score >= 70", action="PASS", priority=100)
    assert r.active is True


def test_portfolio_position():
    p = PortfolioPosition(ticker="MELI", opportunity_id="OPP-2026-001", avg_entry_price=85.0, shares=100, weight_pct=2.5)
    assert p.weight_pct == 2.5
    assert p.status == "ACTIVE"


def test_case_file():
    cf = CaseFile(ticker="MELI")
    assert cf.opportunity_ids == []


def test_review():
    r = Review(id="REV-001", type="POST_MORTEM", opportunity_id="OPP-2026-001", content="Analysis completed")
    assert r.author == "system"
