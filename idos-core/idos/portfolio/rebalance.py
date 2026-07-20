from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from idos.timezone import AR_TZ

@dataclass
class RebalanceProposal:
    action: str
    ticker: str
    reason: str
    weight_change: float = 0.0
    priority: int = 0
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(AR_TZ).isoformat()

class PortfolioRebalancer:
    def __init__(self, max_position_pct: float = 3.0, max_sector_pct: float = 25.0,
                 conviction_drop_threshold: int = 10):
        self.max_position = max_position_pct
        self.max_sector = max_sector_pct
        self.conviction_drop = conviction_drop_threshold

    def evaluate(self, positions: list[dict[str, Any]],
                 conviction_changes: dict[str, int]) -> list[RebalanceProposal]:
        proposals = []

        for pos in positions:
            ticker = pos.get("ticker", "")
            weight = pos.get("weight_pct", 0)
            sector = pos.get("sector", "Unknown")

            if weight > self.max_position:
                excess = weight - self.max_position
                proposals.append(RebalanceProposal(
                    action="REDUCE", ticker=ticker,
                    reason=f"Position weight {weight}% exceeds {self.max_position}% limit",
                    weight_change=-round(excess, 1), priority=90,
                ))

            change = conviction_changes.get(ticker, 0)
            if change < -self.conviction_drop:
                proposals.append(RebalanceProposal(
                    action="REDUCE", ticker=ticker,
                    reason=f"Conviction dropped by {abs(change)} points",
                    priority=80,
                ))

        sector_weights: dict[str, float] = {}
        for pos in positions:
            sec = pos.get("sector", "Unknown")
            sector_weights[sec] = sector_weights.get(sec, 0) + pos.get("weight_pct", 0)

        for sector, total in sector_weights.items():
            if total > self.max_sector:
                proposals.append(RebalanceProposal(
                    action="ALERT", ticker=f"SECTOR:{sector}",
                    reason=f"Sector {sector} at {total}% exceeds {self.max_sector}% limit",
                    priority=70,
                ))

        proposals.sort(key=lambda p: p.priority, reverse=True)
        return proposals
