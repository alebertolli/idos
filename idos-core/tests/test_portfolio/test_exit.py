import pytest
from idos.portfolio.exit import ExitEngine, ExitReason


class TestExitEngine:
    def test_thesis_exit(self):
        ee = ExitEngine()
        sig = ee.evaluate_thesis_exit("AAPL", thesis_active=False)
        assert sig is not None
        assert sig.should_exit is True
        assert sig.reason == ExitReason.THESIS_INVALIDATED
        assert sig.urgency == "high"
        assert sig.exit_pct == 100.0

    def test_thesis_not_invalidated(self):
        ee = ExitEngine()
        sig = ee.evaluate_thesis_exit("AAPL", thesis_active=True)
        assert sig is None

    def test_valuation_exit(self):
        ee = ExitEngine(max_pe_for_hold=25)
        sig = ee.evaluate_valuation_exit("AAPL", current_pe=50, intrinsic_pe=20)
        assert sig is not None
        assert sig.reason == ExitReason.VALUATION_EXCESSIVE
        assert sig.exit_pct > 0
        assert sig.exit_pct < 100

    def test_valuation_ok(self):
        ee = ExitEngine(max_pe_for_hold=35)
        sig = ee.evaluate_valuation_exit("AAPL", current_pe=22, intrinsic_pe=20)
        assert sig is None

    def test_valuation_margin_exit(self):
        ee = ExitEngine(valuation_overvaluation_pct=25, exit_pct_on_valuation=50)
        sig = ee.evaluate_valuation_margin_exit("AAPL", current_price=125, intrinsic_value=100)
        assert sig is not None
        assert sig.reason == ExitReason.VALUATION_EXCESSIVE
        assert sig.exit_pct == 50.0
        assert sig.exit_pct < 100

    def test_valuation_margin_not_overvalued(self):
        ee = ExitEngine(valuation_overvaluation_pct=25)
        sig = ee.evaluate_valuation_margin_exit("AAPL", current_price=110, intrinsic_value=100)
        assert sig is None

    def test_valuation_margin_never_full(self):
        ee = ExitEngine(valuation_overvaluation_pct=0, exit_pct_on_valuation=100)
        sig = ee.evaluate_valuation_margin_exit("AAPL", current_price=500, intrinsic_value=100)
        assert sig is not None
        assert sig.exit_pct < 100

    def test_portfolio_exit(self):
        ee = ExitEngine()
        sig = ee.evaluate_portfolio_exit("AAPL", replacement_score=80, current_conviction=50)
        assert sig is not None
        assert sig.reason == ExitReason.PORTFOLIO_REPLACEMENT

    def test_portfolio_no_exit(self):
        ee = ExitEngine()
        sig = ee.evaluate_portfolio_exit("AAPL", replacement_score=50, current_conviction=50)
        assert sig is None

    def test_risk_exit(self):
        ee = ExitEngine()
        sig = ee.evaluate_risk_exit("AAPL", thesis_intact=False)
        assert sig is not None
        assert sig.reason == ExitReason.RISK_CONTROL
        assert sig.exit_pct == 100.0

    def test_risk_no_exit(self):
        ee = ExitEngine()
        sig = ee.evaluate_risk_exit("AAPL", thesis_intact=True)
        assert sig is None

    def test_config_constructor(self):
        ee = ExitEngine(config={
            "min_conviction_for_hold": 50,
            "valuation_overvaluation_pct": 30,
        })
        assert ee.min_conviction == 50
        assert ee.valuation_overvaluation_pct == 30
