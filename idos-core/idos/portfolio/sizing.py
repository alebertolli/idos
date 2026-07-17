from dataclasses import dataclass


@dataclass
class SizingTranche:
    number: int
    pct_of_portfolio: float
    condition: str


class PositionSizer:
    TRANCHE_CONFIG = [
        SizingTranche(1, 1.0, "Initial entry"),
        SizingTranche(2, 1.0, "First quarterly results align with thesis"),
        SizingTranche(3, 1.0, "Catalyst confirmation or technical support"),
    ]

    def __init__(self, max_position_pct: float = 3.0, min_asymmetry: float = 3.0):
        self.max_position = max_position_pct
        self.min_asymmetry = min_asymmetry

    def kelly_size(self, tsp: float, payoff_ratio: float, bankroll: float) -> float:
        if tsp <= 0 or payoff_ratio <= 0:
            return 0.0
        q = (tsp * (payoff_ratio + 1) - 1) / payoff_ratio
        capped = min(q, self.max_position / 100.0)
        return max(0.0, capped) * bankroll

    def initial_tranche(self, tsp: float, payoff_ratio: float, bankroll: float) -> float:
        total = self.kelly_size(tsp, payoff_ratio, bankroll)
        return total * (self.TRANCHE_CONFIG[0].pct_portfolio / self.max_position) if self.max_position > 0 else 0

    def can_add_tranche(self, current_tranche: int, conditions_met: list[str]) -> bool:
        if current_tranche >= len(self.TRANCHE_CONFIG):
            return False
        next_tranch = self.TRANCHE_CONFIG[current_tranche]
        return True

    def calculate_max_size(self, conviction: int, bankroll: float,
                           current_weight: float) -> tuple[float, float]:
        max_additional = self.max_position - current_weight
        if max_additional <= 0:
            return 0.0, 0.0
        conviction_factor = conviction / 100.0
        suggested = max_additional * conviction_factor
        dollar_amount = (suggested / 100.0) * bankroll
        return round(suggested, 2), round(dollar_amount, 2)
