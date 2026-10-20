from dataclasses import dataclass
from typing import Any


@dataclass
class CompetitionResult:
    new_opportunity: str
    new_score: int
    worst_position: str
    worst_score: int
    should_replace: bool
    reason: str = ""


class CapitalCompetitionEngine:
    def __init__(self, replacement_threshold: float = 1.3):
        self.threshold = replacement_threshold

    def evaluate(self, new_opportunity: dict[str, Any],
                 active_positions: list[dict[str, Any]]) -> CompetitionResult:
        new_score = new_opportunity.get("conviction", 0)

        if not active_positions:
            return CompetitionResult(
                new_opportunity=new_opportunity.get("ticker", ""),
                new_score=new_score, worst_position="",
                worst_score=0, should_replace=False,
                reason="No active positions to compare",
            )

        worst = min(active_positions, key=lambda p: p.get("conviction", 0))
        worst_score = worst.get("conviction", 0)
        worst_ticker = worst.get("ticker", "")

        should_replace = new_score > worst_score * self.threshold

        return CompetitionResult(
            new_opportunity=new_opportunity.get("ticker", ""),
            new_score=new_score,
            worst_position=worst_ticker,
            worst_score=worst_score,
            should_replace=should_replace,
            reason=f"New ({new_score}) {'>' if should_replace else '<'} worst ({worst_score} × {self.threshold})" if should_replace
                   else f"New ({new_score}) not sufficiently above worst ({worst_score} × {self.threshold})",
        )
