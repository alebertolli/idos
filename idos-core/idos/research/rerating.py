from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReratingDimensions:
    business_momentum: int = 50
    valuation_gap: int = 50
    market_expectations: int = 50
    catalysts: int = 50
    technical_confirmation: int = 50
    risk_compression: int = 50


@dataclass
class RecoveryScore:
    overall: int = 0
    dimensions: ReratingDimensions = field(default_factory=ReratingDimensions)

    @property
    def rerating_probability(self) -> float:
        if self.overall >= 85:
            return 0.72
        if self.overall >= 70:
            return 0.55
        if self.overall >= 60:
            return 0.43
        return 0.31

    @property
    def probability_label(self) -> str:
        p = self.rerating_probability
        if p >= 0.70:
            return "HIGH"
        if p >= 0.50:
            return "MEDIUM"
        return "LOW"


@dataclass
class DualProbability:
    bsp: float  # Business Success Probability (0-1)
    mrp: float  # Market Recognition Probability (0-1)

    @property
    def tsp(self) -> float:
        return self.bsp * 0.6 + self.mrp * 0.4

    @property
    def opportunity_class(self) -> str:
        if self.bsp >= 0.80 and self.mrp >= 0.80:
            return "PRIME"
        if self.bsp >= 0.70:
            return "QUALITY_BUSINESS"
        if self.mrp >= 0.70:
            return "MOMENTUM"
        return "SPECULATIVE"


@dataclass
class ReratingResult:
    ticker: str
    recovery_score: RecoveryScore = field(default_factory=RecoveryScore)
    dual_prob: DualProbability | None = None
    recovery_index: float = 0.0
    expected_upside_pct: float = 0.0
    timeframe_months: int = 24


class ReratingProbabilityEngine:
    WEIGHTS = {
        "business_momentum": 0.25,
        "valuation_gap": 0.20,
        "market_expectations": 0.15,
        "catalysts": 0.20,
        "technical_confirmation": 0.10,
        "risk_compression": 0.10,
    }

    def calculate_recovery_score(self, dimensions: ReratingDimensions) -> RecoveryScore:
        weighted = sum(
            getattr(dimensions, k) * v
            for k, v in self.WEIGHTS.items()
        )
        return RecoveryScore(overall=round(weighted), dimensions=dimensions)

    def calculate_dual_probability(self, bsp_inputs: dict[str, Any],
                                   mrp_inputs: dict[str, Any]) -> DualProbability:
        bsp = self._score_bsp(bsp_inputs)
        mrp = self._score_mrp(mrp_inputs)
        return DualProbability(bsp=bsp, mrp=mrp)

    def calculate_recovery_index(self, recovery_score: RecoveryScore,
                                  dual_prob: DualProbability,
                                  expected_upside_pct: float = 50.0,
                                  expected_time_months: int = 24) -> float:
        prob = recovery_score.rerating_probability
        magnitude = expected_upside_pct / 100.0
        velocity = max(0.1, 1.0 - (expected_time_months - 12) / 48.0)
        confidence = dual_prob.tsp if dual_prob else 0.5
        return round(prob * magnitude * velocity * confidence, 4)

    def _score_bsp(self, inputs: dict[str, Any]) -> float:
        score = 50.0
        roic = inputs.get("roic", 0)
        if roic > 30:
            score += 20
        elif roic > 15:
            score += 10
        rev_growth = inputs.get("revenue_growth", 0)
        if rev_growth > 20:
            score += 15
        elif rev_growth > 10:
            score += 8
        margin = inputs.get("operating_margin", 0)
        if margin > 25:
            score += 10
        elif margin > 15:
            score += 5
        de = inputs.get("debt_to_equity", 1)
        if de < 0.3:
            score += 10
        elif de < 1:
            score += 5
        else:
            score -= 10
        return max(0, min(100, score)) / 100.0

    def _score_mrp(self, inputs: dict[str, Any]) -> float:
        score = 50.0
        pe_percentile = inputs.get("pe_percentile_5y", 50)
        if pe_percentile < 20:
            score += 20
        elif pe_percentile < 40:
            score += 10
        has_catalyst = inputs.get("has_catalyst", False)
        if has_catalyst:
            score += 15
        wyckoff = inputs.get("wyckoff_phase", "")
        if wyckoff.upper() in ("ACCUMULATION", "MARKUP"):
            score += 10
        short_interest = inputs.get("short_interest_pct", 0)
        if short_interest > 10:
            score += 10
        return max(0, min(100, score)) / 100.0
