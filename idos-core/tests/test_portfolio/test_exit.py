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

    def test_valuation_ok(self):
        ee = ExitEngine(max_pe_for_hold=35)
        sig = ee.evaluate_valuation_exit("AAPL", current_pe=22, intrinsic_pe=20)
        assert sig is None

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
        sig = ee.evaluate_risk_exit("AAPL", current_drawdown=25, max_drawdown=15)
        assert sig is not None
        assert sig.reason == ExitReason.RISK_CONTROL

    def test_risk_no_exit(self):
        ee = ExitEngine()
        sig = ee.evaluate_risk_exit("AAPL", current_drawdown=5, max_drawdown=15)
        assert sig is None
