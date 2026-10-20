from dataclasses import dataclass
from typing import Any


@dataclass
class DCFResult:
    intrinsic_value: float
    current_price: float
    margin_of_safety_pct: float
    growth_assumption_pct: float
    terminal_growth_pct: float
    discount_rate_pct: float
    projection_years: int


class DCFModel:
    """Discounted Cash Flow model for intrinsic value estimation.

    Uses a two-stage DCF: explicit projection period + terminal value.
    """

    def __init__(self, discount_rate: float = 0.10, terminal_growth: float = 0.03,
                 projection_years: int = 5):
        self.discount_rate = discount_rate
        self.terminal_growth = terminal_growth
        self.projection_years = projection_years

    def calculate(self, free_cash_flow: float, growth_rate: float,
                  shares_outstanding: float, current_price: float,
                  net_debt: float = 0.0) -> DCFResult:
        if free_cash_flow <= 0 or shares_outstanding <= 0:
            return DCFResult(0.0, current_price, 0.0, growth_rate * 100,
                           self.terminal_growth * 100, self.discount_rate * 100,
                           self.projection_years)

        fcf = float(free_cash_flow)
        g = float(growth_rate)
        r = self.discount_rate
        tg = self.terminal_growth
        n = self.projection_years

        pv_fcf = 0.0
        for year in range(1, n + 1):
            fcf_year = fcf * (1 + g) ** year
            pv_fcf += fcf_year / (1 + r) ** year

        terminal_fcf = fcf * (1 + g) ** n * (1 + tg)
        terminal_value = terminal_fcf / (r - tg)
        pv_terminal = terminal_value / (1 + r) ** n

        enterprise_value = pv_fcf + pv_terminal
        equity_value = enterprise_value - net_debt
        intrinsic_per_share = equity_value / shares_outstanding

        margin = ((intrinsic_per_share - current_price) / current_price * 100) if current_price > 0 else 0.0

        return DCFResult(
            intrinsic_value=round(intrinsic_per_share, 2),
            current_price=current_price,
            margin_of_safety_pct=round(margin, 1),
            growth_assumption_pct=round(g * 100, 1),
            terminal_growth_pct=round(tg * 100, 1),
            discount_rate_pct=round(r * 100, 1),
            projection_years=n,
        )

    def calculate_from_context(self, context: dict[str, Any]) -> DCFResult:
        kb = context.get("knowledge_base", {})
        dynamic = kb.get("dynamic", {})
        metrics = dynamic.get("metrics", {})
        price_data = dynamic.get("price", {})

        fcf = metrics.get("free_cash_flow", 0)
        growth = metrics.get("fcf_growth_rate", metrics.get("revenue_growth", 5)) / 100.0
        shares = metrics.get("shares_outstanding", 1)
        price = price_data.get("current", context.get("current_price", 0))
        net_debt = metrics.get("net_debt", 0)

        return self.calculate(fcf, growth, shares, price, net_debt)