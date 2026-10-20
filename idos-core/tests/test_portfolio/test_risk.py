import pytest
from idos.portfolio.risk import RiskEngine


class TestRiskEngine:
    def test_stop_loss(self):
        re = RiskEngine(max_drawdown=15, stop_loss=20)
        alert = re.evaluate_drawdown("AAPL", 22)
        assert alert is not None
        assert alert.alert_type == "STOP_LOSS"
        assert alert.severity == "HIGH"

    def test_max_drawdown(self):
        re = RiskEngine(max_drawdown=15, stop_loss=20)
        alert = re.evaluate_drawdown("AAPL", 16)
        assert alert is not None
        assert alert.alert_type == "MAX_DRAWDOWN"
        assert alert.severity == "MEDIUM"

    def test_no_drawdown_alert(self):
        re = RiskEngine(max_drawdown=15)
        alert = re.evaluate_drawdown("AAPL", 5)
        assert alert is None

    def test_volatility_alert(self):
        re = RiskEngine(max_volatility=30)
        alert = re.evaluate_volatility("AAPL", 45)
        assert alert is not None
        assert alert.alert_type == "HIGH_VOLATILITY"

    def test_leverage_alert(self):
        re = RiskEngine()
        alert = re.evaluate_leverage("AAPL", 3.5)
        assert alert is not None
        assert alert.alert_type == "HIGH_LEVERAGE"

    def test_concentration_alert(self):
        re = RiskEngine()
        alert = re.evaluate_concentration("AAPL", 5, max_weight=3)
        assert alert is not None

    def test_evaluate_all(self):
        re = RiskEngine()
        alerts = re.evaluate_all("AAPL", {"drawdown": 25, "volatility_90d": 40, "debt_to_equity": 3, "weight_pct": 4.5})
        assert len(alerts) == 4
