from enum import StrEnum
from typing import Any


class WyckoffPhase(StrEnum):
    ACCUMULATION = "accumulation"
    MARKUP = "markup"
    DISTRIBUTION = "distribution"
    MARKDOWN = "markdown"
    ABSORPTION = "absorption"
    UNKNOWN = "unknown"


class WyckoffAnalyzer:
    def analyze(self, price_data: list[dict[str, Any]]) -> WyckoffPhase:
        if not price_data or len(price_data) < 20:
            return WyckoffPhase.UNKNOWN

        closes = [p.get("close", 0) for p in price_data]
        volumes = [p.get("volume", 0) for p in price_data]

        n = len(closes)
        third = n // 3

        early = closes[:third]
        mid = closes[third:2*third]
        late = closes[2*third:]

        avg_early = sum(early) / len(early)
        avg_mid = sum(mid) / len(mid)
        avg_late = sum(late) / len(late)

        early_vol = sum(volumes[:third]) / len(early)
        mid_vol = sum(volumes[third:2*third]) / len(mid)
        late_vol = sum(volumes[2*third:]) / len(late)

        late_trend = (late[-1] - late[0]) / late[0] * 100 if late[0] else 0

        if avg_late > avg_mid * 1.1 and avg_late > avg_early * 1.05:
            if late_vol > mid_vol * 1.3 and late_vol > early_vol * 1.3:
                return WyckoffPhase.DISTRIBUTION
            return WyckoffPhase.MARKUP

        if avg_late < avg_mid * 0.9 and avg_late < avg_early * 0.9:
            if late_trend > -10 and late_vol < mid_vol * 0.7 and mid_vol:
                return WyckoffPhase.ACCUMULATION
            return WyckoffPhase.MARKDOWN

        if avg_late < avg_early * 0.9 and -5 <= late_trend <= 5:
            if late_vol < mid_vol * 0.7 and mid_vol:
                return WyckoffPhase.ACCUMULATION

        if -5 <= late_trend <= 5 and late_vol < mid_vol * 0.6:
            return WyckoffPhase.ABSORPTION

        return WyckoffPhase.UNKNOWN

    def is_entry_confirmed(self, phase: WyckoffPhase) -> bool:
        return phase in (WyckoffPhase.ACCUMULATION, WyckoffPhase.ABSORPTION)
