from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from idos.timezone import AR_TZ

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
            self.generated_at = datetime.now(AR_TZ).isoformat()


class ExitEngine:
    """Exit Decision Engine.

    Spec v2:
    - Total liquidation (100%) ONLY by Thesis Exit, Risk Exit (thesis changed
      after reassessment) or explicit Capital Allocation Engine decision.
    - Valuation Exit is always partial (never 100%).
    - Technical signals (stop loss / trailing stop) NEVER liquidate a position;
      they are not used for exits.
    """

    def __init__(self, config: dict[str, Any] | None = None, **kwargs):
        cfg = dict(config or {})
        cfg.update(kwargs)
        self.min_conviction = float(cfg.get("min_conviction_for_hold", 40))
        self.max_pe = float(cfg.get("max_pe_for_hold", 35))
        self.valuation_overvaluation_pct = float(cfg.get("valuation_overvaluation_pct", 25))
        self.exit_pct_on_valuation = float(cfg.get("exit_pct_on_valuation", 50))

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

    def evaluate_risk_exit(self, ticker: str, thesis_intact: bool = True,
                           details: str = "") -> ExitSignal | None:
        """Risk Exit: si la tesis cambió tras el re-assessment, vender todo."""
        if not thesis_intact:
            return ExitSignal(
                ticker=ticker, should_exit=True,
                reason=ExitReason.RISK_CONTROL,
                details=details or "Tesis cambiada tras re-assessment por triggers de riesgo",
                urgency="high", exit_pct=100.0,
            )
        return None

    def evaluate_valuation_margin_exit(self, ticker: str, current_price: float,
                                        intrinsic_value: float) -> ExitSignal | None:
        """Valuation Exit cuantitativo: overvaluation = price / intrinsic - 1.

        Venta SIEMPRE parcial (exit_pct_on_valuation), nunca 100%.
        """
        if intrinsic_value <= 0 or current_price <= 0:
            return None
        overvaluation = (current_price / intrinsic_value - 1) * 100
        if overvaluation >= self.valuation_overvaluation_pct:
            exit_pct = min(self.exit_pct_on_valuation, 50.0)
            return ExitSignal(
                ticker=ticker, should_exit=True,
                reason=ExitReason.VALUATION_EXCESSIVE,
                details=f"Overvaluation {overvaluation:.1f}% >= {self.valuation_overvaluation_pct:.0f}% (price {current_price:.2f} vs intrinsic {intrinsic_value:.2f})",
                urgency="medium", exit_pct=exit_pct,
            )
        return None

    def evaluate_valuation_exit(self, ticker: str, current_pe: float,
                                 intrinsic_pe: float = 20) -> ExitSignal | None:
        """Valuation Exit por PER (compatibilidad). Venta SIEMPRE parcial."""
        if current_pe > self.max_pe and current_pe > intrinsic_pe * 1.5:
            exit_pct = min(self.exit_pct_on_valuation, 50.0)
            return ExitSignal(
                ticker=ticker, should_exit=True,
                reason=ExitReason.VALUATION_EXCESSIVE,
                details=f"PER {current_pe:.1f}x exceeds max {self.max_pe:.0f}x and intrinsic {intrinsic_pe:.1f}x",
                urgency="medium", exit_pct=exit_pct,
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
