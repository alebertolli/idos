from idos.research.hypothesis import HypothesisTreeManager
from idos.models.enums import HypothesisStatus


def test_create_hypothesis():
    mgr = HypothesisTreeManager()
    h = mgr.create("OPP-001", "MELI", "Market underestimates margin expansion",
                    secondary=["Logistics margins improving"],
                    falsification=["Margin drops below 10% for 2 quarters"])
    assert h.statement == "Market underestimates margin expansion"
    assert len(h.secondary_hypotheses) == 1
    assert len(h.falsification_conditions) == 1


def test_add_prediction():
    mgr = HypothesisTreeManager()
    h = mgr.create("OPP-001", "MELI", "Test thesis")
    pred = mgr.add_prediction(h.id, "Operating Margin", 18.0, "2026-12-31")
    assert pred is not None
    assert pred.variable == "Operating Margin"
    assert pred.status == "PENDING"


def test_evaluate_prediction():
    mgr = HypothesisTreeManager()
    h = mgr.create("OPP-001", "MELI", "Test")
    pred = mgr.add_prediction(h.id, "Revenue Growth", 20.0, "2026-12-31", tolerance=10.0)
    status = mgr.evaluate_prediction(pred.id, 21.0)
    assert status == "CONFIRMED"
    status = mgr.evaluate_prediction(pred.id, 5.0)
    assert status == "FAILED"


def test_get_opportunity_hypotheses():
    mgr = HypothesisTreeManager()
    mgr.create("OPP-001", "A", "Thesis A")
    mgr.create("OPP-001", "A", "Thesis B")
    mgr.create("OPP-002", "B", "Thesis C")
    opp_h = mgr.get_opportunity_hypotheses("OPP-001")
    assert len(opp_h) == 2
