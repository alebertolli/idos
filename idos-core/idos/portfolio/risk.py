from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any


@dataclass
class RiskAlert:
    ticker: str
    alert_type: str
    severity: str
    message: str
    current_value: float = 0.0
    threshold: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


class RiskEngine:
    def __init__(self, max_drawdown: float = 15.0, stop_loss: float = 20.0,
                 max_volatility: float = 30.0):
        self.max_drawdown = max_drawdown
        self.stop_loss = stop_loss
        self.max_volatility = max_volatility

    def evaluate_drawdown(self, ticker: str, current_drawdown: float) -> RiskAlert | None:
        if current_drawdown >= self.stop_loss:
            return RiskAlert(ticker=ticker, alert_type="STOP_LOSS", severity="HIGH",
                            message=f"Stop loss triggered: {current_drawdown:.1f}%",
                            current_value=current_drawdown, threshold=self.stop_loss)
        if current_drawdown >= self.max_drawdown:
            return RiskAlert(ticker=ticker, alert_type="MAX_DRAWDOWN", severity="MEDIUM",
                            message=f"Max drawdown approached: {current_drawdown:.1f}%",
                            current_value=current_drawdown, threshold=self.max_drawdown)
        return None

    def evaluate_volatility(self, ticker: str, volatility: float) -> RiskAlert | None:
        if volatility > self.max_volatility:
            return RiskAlert(ticker=ticker, alert_type="HIGH_VOLATILITY", severity="MEDIUM",
                            message=f"High volatility: {volatility:.1f}%",
                            current_value=volatility, threshold=self.max_volatility)
        return None

    def evaluate_leverage(self, ticker: str, debt_equity: float) -> RiskAlert | None:
        if debt_equity > 2.0:
            return RiskAlert(ticker=ticker, alert_type="HIGH_LEVERAGE", severity="MEDIUM",
                            message=f"High leverage: {debt_equity:.1f}x debt/equity",
                            current_value=debt_equity, threshold=2.0)
        return None

    def evaluate_concentration(self, ticker: str, weight: float, max_weight: float = 3.0) -> RiskAlert | None:
        if weight > max_weight:
            return RiskAlert(ticker=ticker, alert_type="CONCENTRATION", severity="LOW",
                            message=f"Position weight {weight:.1f}% > {max_weight:.0f}% limit",
                            current_value=weight, threshold=max_weight)
        return None

    def evaluate_all(self, ticker: str, metrics: dict[str, Any]) -> list[RiskAlert]:
        alerts = []
        if "drawdown" in metrics:
            a = self.evaluate_drawdown(ticker, metrics["drawdown"])
            if a: alerts.append(a)
        if "volatility_90d" in metrics:
            a = self.evaluate_volatility(ticker, metrics["volatility_90d"])
            if a: alerts.append(a)
        if "debt_to_equity" in metrics:
            a = self.evaluate_leverage(ticker, metrics["debt_to_equity"])
            if a: alerts.append(a)
        if "weight_pct" in metrics:
            a = self.evaluate_concentration(ticker, metrics["weight_pct"])
            if a: alerts.append(a)
        return alerts
