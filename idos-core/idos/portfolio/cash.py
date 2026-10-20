from dataclasses import dataclass


@dataclass
class CashPosition:
    total_capital: float
    cash_balance: float
    cash_pct: float
    target_cash_pct: float = 5.0
    recommended_action: str = "HOLD"

    @property
    def invested_pct(self) -> float:
        return 100.0 - self.cash_pct


class CashManager:
    def __init__(self, target_cash_pct: float = 5.0, min_cash_pct: float = 5.0,
                 emergency_cash_pct: float = 10.0):
        self.target = target_cash_pct
        self.min_cash = min_cash_pct
        self.emergency = emergency_cash_pct

    def evaluate(self, total_capital: float, cash_balance: float) -> CashPosition:
        cash_pct = (cash_balance / total_capital * 100) if total_capital > 0 else 0

        if cash_pct < self.min_cash:
            action = "REDUCE_POSITIONS"
        elif cash_pct > self.emergency:
            action = "DEPLOY_CAPITAL"
        else:
            action = "HOLD"

        return CashPosition(
            total_capital=total_capital,
            cash_balance=cash_balance,
            cash_pct=round(cash_pct, 1),
            target_cash_pct=self.target,
            recommended_action=action,
        )

    def deployable_capital(self, total_capital: float, cash_balance: float) -> float:
        cash_pct = (cash_balance / total_capital * 100) if total_capital > 0 else 0
        if cash_pct > self.target:
            excess_pct = cash_pct - self.target
            return total_capital * (excess_pct / 100)
        return 0.0
