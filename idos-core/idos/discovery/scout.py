from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any


@dataclass
class ScoutResult:
    ticker: str
    score: int = 0
    passed: bool = False
    details: dict[str, int] = field(default_factory=dict)
    reason: str = ""
    scanned_at: str = ""

    def __post_init__(self):
        if not self.scanned_at:
            self.scanned_at = datetime.now(UTC).isoformat()


class ScoutEngine:
    def __init__(self, min_score: int = 50):
        self.min_score = min_score

    def scan(self, ticker: str, data: dict[str, Any]) -> ScoutResult:
        metrics = data.get("metrics", {})
        details = {}

        details["size_score"] = self._score_market_cap(metrics.get("market_cap", 0))
        details["liquidity_score"] = self._score_liquidity(metrics.get("avg_volume", 0))
        details["momentum_score"] = self._score_momentum(
            metrics.get("price_change_3m", 0), metrics.get("price_change_12m", 0))
        details["value_score"] = self._score_value(
            metrics.get("pe_ratio", 0), metrics.get("ev_ebitda", 0))
        details["quality_score"] = self._score_quality(
            metrics.get("roic", 0), metrics.get("operating_margin", 0),
            metrics.get("debt_to_equity", 0),
            metrics.get("revenue_growth", 0))

        total = sum(details.values())
        max_possible = len(details) * 100
        score = int(round(total / max_possible * 100)) if max_possible > 0 else 0

        return ScoutResult(
            ticker=ticker.upper(),
            score=score,
            passed=score >= self.min_score,
            details=details,
            reason="Passed initial screening" if score >= self.min_score else "Below minimum score threshold",
        )

    def _score_market_cap(self, cap: float) -> int:
        if cap >= 10e9: return 90
        if cap >= 2e9: return 70
        if cap >= 300e6: return 50
        return 20

    def _score_liquidity(self, volume: float) -> int:
        if volume >= 1e6: return 90
        if volume >= 500e3: return 70
        if volume >= 100e3: return 50
        return 20

    def _score_momentum(self, chg_3m: float, chg_12m: float) -> int:
        s = 50
        if chg_3m > 10: s += 15
        elif chg_3m < -20: s -= 15
        if chg_12m > 20: s += 15
        elif chg_12m < -30: s -= 10
        return max(0, min(100, s))

    def _score_value(self, pe: float, ev_ebitda: float) -> int:
        s = 50
        if 0 < pe <= 15: s += 20
        elif pe > 30: s -= 10
        if 0 < ev_ebitda <= 10: s += 15
        elif ev_ebitda > 20: s -= 10
        return max(0, min(100, s))

    def _score_quality(self, roic: float, margin: float, dte: float, growth: float) -> int:
        s = 50
        if roic > 15: s += 15
        elif roic < 5: s -= 15
        if margin > 15: s += 10
        elif margin < 5: s -= 10
        if dte < 0.5: s += 10
        elif dte > 2: s -= 10
        if growth > 10: s += 10
        return max(0, min(100, s))
