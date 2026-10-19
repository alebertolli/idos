import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from idos.research.hypothesis import (
    HypothesisManager, Hypothesis, HypothesisStatus, HypothesisPriority,
    Prediction, FalsificationCondition, FiveQuestions
)


def test_create_hypothesis():
    h = Hypothesis(id="H-001", opportunity_id="OPP-001", ticker="MELI",
                   statement="MELI will expand margins via fintech")
    assert h.status == HypothesisStatus.DRAFT
    assert h.priority == HypothesisPriority.IMPORTANT


def test_promote_hypothesis():
    h = Hypothesis(id="H-001", opportunity_id="OPP-001", ticker="MELI")
    h.promote(HypothesisStatus.ACTIVE)
    assert h.status == HypothesisStatus.ACTIVE
    h.promote(HypothesisStatus.STRENGTHENING)
    assert h.status == HypothesisStatus.STRENGTHENING


def test_cannot_demote():
    h = Hypothesis(id="H-001", opportunity_id="OPP-001", ticker="MELI",
                   status=HypothesisStatus.CONFIRMED)
    h.promote(HypothesisStatus.ACTIVE)
    assert h.status == HypothesisStatus.CONFIRMED


def test_falsification_triggers():
    h = Hypothesis(id="H-001", opportunity_id="OPP-001", ticker="MELI",
                   status=HypothesisStatus.ACTIVE,
                   falsification=[FalsificationCondition(condition="Revenue decline", metric="revenue", threshold=0)])
    assert h.status == HypothesisStatus.ACTIVE
    h.falsification[0].triggered = True
    triggered = h.check_falsification()
    assert len(triggered) == 1
    assert h.status == HypothesisStatus.INVALIDATED


def test_prediction_evaluate():
    p = Prediction(metric="ROIC", expected_value=25, unit="%", deadline="2026-12-31")
    assert p.evaluate() is None
    p.actual_value = 28
    assert p.evaluate() is True
    p.actual_value = 20
    assert p.evaluate() is False


def test_hypothesis_manager():
    mgr = HypothesisManager()
    mgr.create(Hypothesis(id="H-001", opportunity_id="OPP-001", ticker="MELI"))
    mgr.create(Hypothesis(id="H-002", opportunity_id="OPP-001", ticker="MELI",
                          status=HypothesisStatus.ACTIVE))
    mgr.create(Hypothesis(id="H-003", opportunity_id="OPP-002", ticker="GOOGL"))
    assert mgr.count() == 3
    assert len(mgr.by_opportunity("OPP-001")) == 2
    assert len(mgr.by_ticker("GOOGL")) == 1


def test_intrusive_parameters():
    q = FiveQuestions(
        what_we_believe="Market underestimates growth",
        why_we_believe="ROIC improving, margins expanding",
        what_should_happen="EPS grows 20%+",
        what_proves_us_wrong="Revenue declines 2 quarters",
        when_we_stop_believing="Q4 2026"
    )
    assert q.is_complete() is True
    q2 = FiveQuestions()
    assert q2.is_complete() is False


if __name__ == "__main__":
    test_create_hypothesis()
    test_promote_hypothesis()
    test_cannot_demote()
    test_falsification_triggers()
    test_prediction_evaluate()
    test_hypothesis_manager()
    test_intrusive_parameters()
    print("ALL HYPOTHESIS TESTS PASSED")
