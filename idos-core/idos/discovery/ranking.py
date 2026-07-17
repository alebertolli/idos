from dataclasses import dataclass
from typing import Any
from idos.discovery.scout import ScoutResult


@dataclass
class RankedEntry:
    ticker: str
    scout_score: int
    conviction_score: int
    combined_score: int
    rank: int = 0
    reason: str = ""


class RankingSystem:
    def __init__(self, scout_weight: float = 0.4, conviction_weight: float = 0.6):
        self.scout_weight = scout_weight
        self.conviction_weight = conviction_weight

    def rank(self, entries: list[dict[str, Any]]) -> list[RankedEntry]:
        ranked = []
        for e in entries:
            combined = int(round(
                e.get("scout_score", 0) * self.scout_weight +
                e.get("conviction_score", 0) * self.conviction_weight
            ))
            ranked.append(RankedEntry(
                ticker=e.get("ticker", ""),
                scout_score=e.get("scout_score", 0),
                conviction_score=e.get("conviction_score", 0),
                combined_score=combined,
            ))

        ranked.sort(key=lambda r: r.combined_score, reverse=True)
        for i, r in enumerate(ranked, 1):
            r.rank = i
            r.reason = f"Rank {i}: Scout {r.scout_score}, Conviction {r.conviction_score}"

        return ranked

    def top_n(self, entries: list[dict[str, Any]], n: int = 10) -> list[RankedEntry]:
        return self.rank(entries)[:n]
