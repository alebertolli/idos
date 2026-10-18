from dataclasses import dataclass, field
from datetime import datetime
import math
from typing import Any
from idos.timezone import AR_TZ


@dataclass
class ScoutResult:
    ticker: str
    score: int = 0
    passed: bool = False
    details: dict[str, int] = field(default_factory=dict)
    reason: str = ''
    discovery_type: str = ''
    flags: list[str] = field(default_factory=list)
    scanned_at: str = ''

    def __post_init__(self):
        if not self.scanned_at:
            self.scanned_at = datetime.now(AR_TZ).isoformat()


class ScoutEngine:
    def __init__(
        self,
        min_score: int = 70,
        market_cap_min_usd: float = 2e9,
        avg_dollar_volume_min_usd: float = 100e3,
        aum_min_usd: float = 2e9,
    ):
        self.min_score = min_score
        self.market_cap_min_usd = market_cap_min_usd
        self.avg_dollar_volume_min_usd = avg_dollar_volume_min_usd
        self.aum_min_usd = aum_min_usd

    def scan(self, ticker: str, data: dict[str, Any]) -> ScoutResult:
        metrics = data.get('metrics', {})
        details = {}

        # --- INVESTABILITY (filter, not scored into total) ---
        # Eligibility requires normalized USD values. Share-volume aliases are
        # deliberately rejected until the market-data pipeline provides the
        # canonical, provenance-bearing fields.
        # Populated only after the typed global gate validates market cap
        # (equities) or AUM (ETFs), with provenance.
        cap = self._positive_number(
            metrics.get('size_metric_usd', metrics.get('market_cap_usd'))
        )
        cap_label = metrics.get('size_metric_label', 'market cap')
        dolvol_raw = self._positive_number(metrics.get('avg_dollar_volume_usd'))
        min_cap = self.aum_min_usd if metrics.get('asset_type') == 'etf' else self.market_cap_min_usd
        min_dolvol = self.avg_dollar_volume_min_usd
        is_investable = cap is not None and dolvol_raw is not None and cap >= min_cap and dolvol_raw >= min_dolvol
        details['investability'] = 100 if is_investable else 0

        # --- TRANSITION SCORE (50% weight) ---
        rs_3m = metrics.get('relative_strength_3m', 0)
        rs_12m = metrics.get('relative_strength_12m', 0)
        price_vol_trend = metrics.get('price_volume_trend', 0)
        transition_score = self._score_momentum(rs_3m, rs_12m, price_vol_trend)
        details['transition'] = transition_score

        # --- QUALITY SCORE (25% weight) ---
        roic = metrics.get('roic', 0)
        fcf_yield = metrics.get('fcf_yield', 0)
        dte = metrics.get('debt_to_equity', 1.0)
        quality_score = self._score_quality(roic, fcf_yield, dte)
        details['quality'] = quality_score

        # --- MARKET CONFIRMATION (25% weight) ---
        market_score = self._score_market(rs_3m, rs_12m, price_vol_trend)
        details['market'] = market_score

        # --- WEIGHTED FINAL SCORE ---
        # Transition 50%, Quality 25%, Market 25%
        tw = transition_score * 0.50
        qw = quality_score * 0.25
        mw = market_score * 0.25
        total_weighted = tw + qw + mw  # max 100
        score = int(round(total_weighted)) if total_weighted > 0 else 0

        # --- DETERMINE DISCOVERY TYPE & FLAGS ---
        discover_type, flags = self._determine_type_and_flags(details)

        # --- DIAGNOSTIC BREAKDOWN ---
        reasons: list[str] = []
        if not is_investable:
            cap = cap or 0
            dolvol_raw = dolvol_raw or 0
            if cap < min_cap:
                reasons.append(f'{cap_label} ${cap:,.0f} < minimum ${min_cap:,.0f}')
            if dolvol_raw < min_dolvol:
                reasons.append(f'Dollar volume ${dolvol_raw:,.0f} < minimum ${min_dolvol:,.0f} or unavailable')
        elif score < self.min_score:
            reasons.append(f'Score {score} < threshold {self.min_score}')
        else:
            reasons.append('Passed all filters')

        passed = score >= self.min_score and is_investable

        # Add diagnostic flags
        if not is_investable:
            flags.append('Low investability')
        if not is_investable and score < self.min_score:
            flags.append('Below threshold')
        if is_investable and score >= self.min_score:
            flags.append('Above threshold')

        return ScoutResult(
            ticker=ticker.upper(),
            score=score,
            passed=passed,
            details=details,
            reason=self._generate_reason(details, discover_type),
            discovery_type=discover_type,
            flags=flags,
            scanned_at=datetime.now(AR_TZ).isoformat(),
        )

    @staticmethod
    def _positive_number(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None

    @staticmethod
    def _score_momentum(rs_3m: float, rs_12m: float, price_vol_trend: float) -> int:
        s = 50
        # 3M relative strength (60% weight)
        s += (rs_3m / 100.0) * 30  # normalize: ±100 RS → ±30 points
        # 12M relative strength (40% weight)
        s += (rs_12m / 100.0) * 20  # normalize: ±100 RS → ±20 points
        # Price/volume trend confirmation
        if price_vol_trend > 0: s += 10
        elif price_vol_trend < 0: s -= 10
        return max(0, min(100, s))

    @staticmethod
    def _score_quality(roic: float, fcf_yield: float, dte: float) -> int:
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

    @staticmethod
    def _score_market(rs_3m: float, rs_12m: float, price_vol_trend: float) -> int:
        s = 50
        # 3M relative strength (60% weight)
        s += (rs_3m / 100.0) * 30
        # 12M relative strength (40% weight)
        s += (rs_12m / 100.0) * 20
        # Price/volume trend confirmation
        if price_vol_trend > 0: s += 10
        elif price_vol_trend < 0: s -= 10
        return max(0, min(100, s))

    @staticmethod
    def _determine_type_and_flags(details: dict) -> tuple[str, list[str]]:
        transition = details.get('transition', 0)
        quality = details.get('quality', 0)
        market = details.get('market', 0)
        investability = details.get('investability', 0)

        flags: list[str] = []
        discover_type = 'CONFIRMED_TRANSITION'  # default

        # 1. FUNDAMENTAL TRANSITION: strong transition + strong quality (70+)
        if transition >= 70 and quality >= 70:
            discover_type = 'FUNDAMENTAL_TRANSITION'
            flags.append('Strong fundamentals improving')
        # 2. CONTRARIAN TRANSITION: strong transition despite low quality
        elif transition >= 60 and quality < 50:
            discover_type = 'CONTRARIAN_TRANSITION'
            flags.append('Quality lagging price action - contrarian')
        # 3. CONFIRMED TRANSITION: strong transition + strong market
        elif transition >= 70 and market >= 70:
            discover_type = 'CONFIRMED_TRANSITION'
            flags.append('Price confirming fundamentals')
        # Default stays as CONFIRMED_TRANSITION

        # Add investability flag if needed
        if investability == 0:
            flags.append('Low investability - check dollar volume')

        return discover_type, flags

    @staticmethod
    def _generate_reason(details: dict, discover_type: str) -> str:
        transition = details.get('transition', 0)
        quality = details.get('quality', 0)
        market = details.get('market', 0)
        investability = details.get('investability', 0)

        reasons: list[str] = []

        if discover_type == 'FUNDAMENTAL_TRANSITION':
            reasons.append('Revenue and earnings acceleration with improving margins')
        elif discover_type == 'CONTRARIAN_TRANSITION':
            reasons.append('Price decline amid improving fundamentals - value opportunity')
        elif discover_type == 'CONFIRMED_TRANSITION':
            reasons.append('Fundamentals and price momentum both positive')
        else:
            # Generic reason based on highest scoring component
            if transition >= 70:
                reasons.append('Strong transition/acceleration detected')
            if quality >= 70:
                reasons.append('Strong current fundamentals')
            if market >= 70:
                reasons.append('Strong relative market strength')
            if not reasons:
                reasons.append('Passed initial screening criteria')

        # Add investability note
        if investability == 0:
            reasons.append('Note: Check minimum dollar volume requirement')

        return ' | '.join(reasons)
