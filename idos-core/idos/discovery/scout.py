from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from idos.timezone import AR_TZ

@dataclass
class ScoutResult:
    ticker: str
    score: int = 0
    passed: bool = False
    details: dict[str, int] = field(default_factory=dict)
    reason: str = ""
    discovery_type: str = ""
    flags: list[str] = field(default_factory=list)
    scanned_at: str = ""

    def __post_init__(self):
        if not self.scanned_at:
            self.scanned_at = datetime.now(AR_TZ).isoformat()

class ScoutEngine:
    def __init__(self, min_score: int = 50):
        self.min_score = min_score

    def scan(self, ticker: str, data: dict[str, Any]) -> ScoutResult:
        metrics = data.get("metrics", {})
        details = {}

        # --- INVESTABILITY (filter, not scored into total) ---
        cap = metrics.get("market_cap", 0)
        dolvol = metrics.get("avg_dollar_volume", 0)
        min_cap = metrics.get("min_market_cap", 2e9)
        min_dolvol = metrics.get("min_dollar_volume", 500e3)
        is_investable = cap >= min_cap and dolvol >= min_dolvol
        details["investability"] = 100 if is_investable else 0

        # --- TRANSITION SCORE (50% weight) ---
        rs_3m = metrics.get("relative_strength_3m", 0)
        rs_12m = metrics.get("relative_strength_12m", 0)
        price_vol_trend = metrics.get("price_volume_trend", 0)
        transition_score = self._score_momentum(rs_3m, rs_12m, price_vol_trend)
        details["transition"] = transition_score

        # --- QUALITY SCORE (25% weight) ---
        roic = metrics.get("roic", 0)
        fcf_yield = metrics.get("fcf_yield", 0)
        dte = metrics.get("debt_to_equity", 1.0)
        quality_score = self._score_quality(roic, fcf_yield, dte)
        details["quality"] = quality_score

        # --- MARKET CONFIRMATION (25% weight) ---
        market_score = self._score_market(rs_3m, rs_12m, price_vol_trend)
        details["market"] = market_score

        # --- WEIGHTED FINAL SCORE ---
        # Transition 50%, Quality 25%, Market 25%
        tw = transition_score * 0.50
        qw = quality_score * 0.25
        mw = market_score * 0.25
        total_weighted = tw + qw + mw  # max 100
        score = int(round(total_weighted)) if total_weighted > 0 else 0

        # --- DETERMINE DISCOVERY TYPE & FLAGS ---
        discovery_type, flags = self._determine_type_and_flags(details)

        passed = score >= self.min_score and is_investable

        return ScoutResult(
            ticker=ticker.upper(),
            score=score,
            passed=passed,
            details=details,
            reason=self._generate_reason(details, discovery_type),
            discovery_type=discovery_type,
            flags=flags,
            scanned_at=datetime.now(AR_TZ).isoformat(),
        )

    def _score_market_cap(self, cap: float) -> tuple[int, bool]:
        """Returns (score, is_investable). Investability = min market cap + min dollar volume."""
        min_cap = 2e9  # $2B minimum
        min_dolvol = 500e3  # $500K minimum average dollar volume
        is_investable = cap >= min_cap
        score = 90 if cap >= 10e9 else (70 if cap >= 2e9 else (50 if cap >= 300e6 else 20))
        return score, is_investable

    def _score_liquidity(self, volume: float) -> tuple[int, bool]:
        """Returns (score, is_liquid). Combined with market cap for investability gate."""
        min_vol = 1e6  # $1M minimum
        is_liquid = volume >= min_vol
        score = 90 if volume >= 1e6 else (70 if volume >= 500e3 else (50 if volume >= 100e3 else 20))
        return score, is_liquid

    def _score_momentum(self, rs_3m: float, rs_12m: float, price_vol_trend: float) -> int:
        """Transition score using relative strength vs sector/index.

        Weights: 3M RS 60%, 12M RS 40%, price/volume trend confirmation.
        """
        s = 50
        # 3M relative strength (60% weight)
        s += (rs_3m / 100.0) * 30  # normalize: ±100 RS → ±30 points
        # 12M relative strength (40% weight)
        s += (rs_12m / 100.0) * 20  # normalize: ±100 RS → ±20 points
        # Price/volume trend confirmation
        if price_vol_trend > 0: s += 10
        elif price_vol_trend < 0: s -= 10
        return max(0, min(100, s))

    def _score_quality(self, roic: float, fcf_yield: float, dte: float) -> int:
        """Quality score using current ROIC level + FCF conversion + balance sheet.

        Weights: ROIC 40%, FCF 30%, Balance sheet 30%.
        """
        s = 50
        # ROIC level (40% weight): >15 good, <5 poor
        s += (roic / 15.0) * 20  # ROIC 15 → +20, ROIC 0 → +0, ROIC -5 → -20 (capped)
        # FCF positive/conversion (30% weight)
        if fcf_yield and fcf_yield > 0: s += 10
        elif fcf_yield == 0: s += 0
        else: s -= 10  # negative FCF
        # Balance sheet (30% weight): debt/equity
        if dte < 0.5: s += 10
        elif dte > 2: s -= 10
        return max(0, min(100, s))

    def _score_market(self, rs_3m: float, rs_12m: float, price_vol_trend: float) -> int:
        """Market confirmation score using relative strength.

        Weights: 3M RS 60%, 12M RS 40%, similar to transition but standalone.
        This is separate from transition score so discovery types can differ.
        """
        s = 50
        # 3M relative strength (60% weight)
        s += (rs_3m / 100.0) * 30
        # 12M relative strength (40% weight)
        s += (rs_12m / 100.0) * 20
        # Price/volume trend confirmation
        if price_vol_trend > 0: s += 10
        elif price_vol_trend < 0: s -= 10
        return max(0, min(100, s))

    def _determine_type_and_flags(self, details: dict) -> tuple[str, list[str]]:
        """Classify discovery type and identify flags based on detail scores."""
        transition = details.get("transition", 0)
        quality = details.get("quality", 0)
        market = details.get("market", 0)
        investability = details.get("investability", 0)

        flags: list[str] = []
        discovery_type = "CONFIRMED_TRANSITION"  # default

        # 1. FUNDAMENTAL TRANSITION: strong transition + strong quality (70+)
        if transition >= 70 and quality >= 70:
            discovery_type = "FUNDAMENTAL_TRANSITION"
            flags.append("Strong fundamentals improving")
        # 2. CONTRARIAN TRANSITION: strong transition despite low quality
        elif transition >= 60 and quality < 50:
            discovery_type = "CONTRARIAN_TRANSITION"
            flags.append("Quality lagging price action - contrarian")
        # 3. CONFIRMED TRANSITION: strong transition + strong market
        elif transition >= 70 and market >= 70:
            discovery_type = "CONFIRMED_TRANSITION"
            flags.append("Price confirming fundamentals")
        # Default stays as CONFIRMED_TRANSITION

        # Add investability flag if needed
        if investability == 0:
            flags.append("Low investability - check dollar volume")

        return discovery_type, flags

    def _generate_reason(self, details: dict, discovery_type: str) -> str:
        """Generate human-readable reason based on details and discovery type."""
        transition = details.get("transition", 0)
        quality = details.get("quality", 0)
        market = details.get("market", 0)
        investability = details.get("investability", 0)

        reasons: list[str] = []

        if discovery_type == "FUNDAMENTAL_TRANSITION":
            reasons.append("Revenue and earnings acceleration with improving margins")
        elif discovery_type == "CONTRARIAN_TRANSITION":
            reasons.append("Price decline amid improving fundamentals - value opportunity")
        elif discovery_type == "CONFIRMED_TRANSITION":
            reasons.append("Fundamentals and price momentum both positive")
        else:
            # Generic reason based on highest scoring component
            if transition >= 70:
                reasons.append("Strong transition/acceleration detected")
            if quality >= 70:
                reasons.append("Strong current fundamentals")
            if market >= 70:
                reasons.append("Strong relative market strength")
            if not reasons:
                reasons.append("Passed initial screening criteria")

        # Add investability note
        if investability == 0:
            reasons.append("Note: Check minimum dollar volume requirement")

        return " | ".join(reasons)