from idos.research.hypothesis import HypothesisManager, Hypothesis, FalsificationCondition, Prediction
from idos.models.enums import HypothesisStatus


def test_create_hypothesis():
    mgr = HypothesisManager()
    h = Hypothesis(
        id="H-T1", opportunity_id="OPP-001", ticker="MELI",
        statement="Market underestimates margin expansion",
        falsification=[FalsificationCondition(condition="Margin drops below 10% for 2 quarters", metric="margin", threshold=0.1)],
    )
    mgr.create(h)
    assert h.statement == "Market underestimates margin expansion"
    assert len(h.falsification) == 1
    assert mgr.get(h.id) is h


def test_add_prediction():
    mgr = HypothesisManager()
    h = Hypothesis(id="H-T2", opportunity_id="OPP-001", ticker="MELI", statement="Test thesis")
    mgr.create(h)
    h.predictions.append(Prediction(metric="Operating Margin", expected_value=18.0, deadline="2026-12-31"))
    assert h.predictions[0].metric == "Operating Margin"


def test_evaluate_prediction():
    mgr = HypothesisManager()
    h = Hypothesis(id="H-T3", opportunity_id="OPP-001", ticker="MELI", statement="Test")
    mgr.create(h)
    p = Prediction(metric="Revenue Growth", expected_value=20.0, deadline="2026-12-31")
    h.predictions.append(p)
    p.actual_value = 21.0
    assert p.evaluate() is True
    p.actual_value = 5.0
    assert p.evaluate() is False


def test_get_opportunity_hypotheses():
    mgr = HypothesisManager()
    mgr.create(Hypothesis(id="H-T4", opportunity_id="OPP-001", ticker="A", statement="Thesis A"))
    mgr.create(Hypothesis(id="H-T5", opportunity_id="OPP-001", ticker="A", statement="Thesis B"))
    mgr.create(Hypothesis(id="H-T6", opportunity_id="OPP-002", ticker="B", statement="Thesis C"))
    opp_h = mgr.by_opportunity("OPP-001")
    assert len(opp_h) == 2
