from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import StrEnum
from typing import Any


class ExitReason(StrEnum):
    THESIS_INVALIDATED = "THESIS_INVALIDATED"
    VALUATION_EXCESSIVE = "VALUATION_EXCESSIVE"
    PORTFOLIO_REPLACEMENT = "PORTFOLIO_REPLACEMENT"
    RISK_CONTROL = "RISK_CONTROL"


@dataclass
class ExitSignal:
    ticker: str
    should_exit: bool = False
    reason: ExitReason | None = None
    details: str = ""
    urgency: str = "medium"
    conviction_before: int = 0
    conviction_after: int = 0
    exit_pct: float = 100.0
    generated_at: str = ""

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(UTC).isoformat()


class ExitEngine:
    def __init__(self, min_conviction_for_hold: int = 40, max_pe_for_hold: float = 35):
        self.min_conviction = min_conviction_for_hold
        self.max_pe = max_pe_for_hold

    def evaluate_thesis_exit(self, ticker: str, thesis_active: bool,
                              falsification_triggered: bool = False) -> ExitSignal | None:
        if not thesis_active or falsification_triggered:
            return ExitSignal(
                ticker=ticker, should_exit=True,
                reason=ExitReason.THESIS_INVALIDATED,
                details="Investment thesis invalidated or falsified",
                urgency="high", exit_pct=100.0,
            )
        return None

    def evaluate_valuation_exit(self, ticker: str, current_pe: float,
                                 intrinsic_pe: float = 20) -> ExitSignal | None:
        if current_pe > self.max_pe and current_pe > intrinsic_pe * 1.5:
            exit_pct = min(100, (current_pe / self.max_pe - 1) * 50)
            return ExitSignal(
                ticker=ticker, should_exit=True,
                reason=ExitReason.VALUATION_EXCESSIVE,
                details=f"PER {current_pe:.1f}x exceeds max {self.max_pe}x and intrinsic {intrinsic_pe:.1f}x",
                urgency="medium", exit_pct=round(exit_pct, 1),
            )
        return None

    def evaluate_portfolio_exit(self, ticker: str, replacement_score: float,
                                 current_conviction: int) -> ExitSignal | None:
        if replacement_score > current_conviction * 1.3:
            return ExitSignal(
                ticker=ticker, should_exit=True,
                reason=ExitReason.PORTFOLIO_REPLACEMENT,
                details=f"Replacement opportunity ({replacement_score}) > current conviction ({current_conviction})",
                urgency="medium", exit_pct=100.0,
                conviction_before=current_conviction,
                conviction_after=replacement_score,
            )
        return None

    def evaluate_risk_exit(self, ticker: str, current_drawdown: float,
                            stop_loss: float = 20.0, max_drawdown: float = 15.0) -> ExitSignal | None:
        if current_drawdown > max_drawdown or current_drawdown > stop_loss:
            urgency = "high" if current_drawdown > stop_loss else "medium"
            return ExitSignal(
                ticker=ticker, should_exit=True,
                reason=ExitReason.RISK_CONTROL,
                details=f"Drawdown {current_drawdown:.1f}% exceeds limit {max_drawdown:.0f}%",
                urgency=urgency, exit_pct=100.0 if current_drawdown > stop_loss else 50.0,
            )
        return None
