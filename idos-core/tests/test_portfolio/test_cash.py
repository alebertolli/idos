import pytest
from idos.portfolio.cash import CashManager


class TestCashManager:
    def test_hold(self):
        cm = CashManager(target_cash_pct=5, min_cash_pct=5, emergency_cash_pct=10)
        pos = cm.evaluate(total_capital=100_000, cash_balance=7_000)
        assert pos.recommended_action == "HOLD"
        assert pos.cash_pct == 7.0

    def test_reduce_positions(self):
        cm = CashManager(min_cash_pct=5, emergency_cash_pct=10)
        pos = cm.evaluate(total_capital=100_000, cash_balance=2_000)
        assert pos.recommended_action == "REDUCE_POSITIONS"

    def test_deploy_capital(self):
        cm = CashManager(target_cash_pct=5, min_cash_pct=5, emergency_cash_pct=10)
        pos = cm.evaluate(total_capital=100_000, cash_balance=15_000)
        assert pos.recommended_action == "DEPLOY_CAPITAL"

    def test_deployable_capital(self):
        cm = CashManager(target_cash_pct=5)
        deployable = cm.deployable_capital(total_capital=100_000, cash_balance=15_000)
        assert round(deployable, 0) == 10_000

    def test_no_excess_cash(self):
        cm = CashManager(target_cash_pct=5)
        deployable = cm.deployable_capital(total_capital=100_000, cash_balance=3_000)
        assert deployable == 0
