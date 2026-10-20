from typing import Any
from idos.decision.engines.business import BusinessAssessmentEngine
from idos.decision.engines.recovery import RecoveryAssessmentEngine


class DualProbabilityFramework:
    def __init__(self):
        self.business_engine = BusinessAssessmentEngine()
        self.recovery_engine = RecoveryAssessmentEngine()
        self.bsp_weight = 0.6
        self.mrp_weight = 0.4

    def evaluate(self, context: dict[str, Any]) -> dict[str, float]:
        bsp_assessment = self.business_engine.evaluate(context)
        mrp_assessment = self.recovery_engine.evaluate(context)

        bsp = bsp_assessment.score / 100.0
        mrp = mrp_assessment.score / 100.0

        tsp = self._combine(bsp, mrp)

        return {
            "bsp": round(bsp, 4),
            "mrp": round(mrp, 4),
            "tsp": round(tsp, 4),
        }

    def _combine(self, bsp: float, mrp: float) -> float:
        total = self.bsp_weight + self.mrp_weight
        if total <= 0:
            return 0.0
        return (bsp * self.bsp_weight + mrp * self.mrp_weight) / total

    def set_weights(self, bsp_weight: float, mrp_weight: float):
        self.bsp_weight = bsp_weight
        self.mrp_weight = mrp_weight

    def calibrate_from_hitrates(self, bsp_hit_rate: float, mrp_hit_rate: float):
        total = bsp_hit_rate + mrp_hit_rate
        if total > 0:
            self.bsp_weight = bsp_hit_rate / total
            self.mrp_weight = mrp_hit_rate / total

    def calculate_position_size(self, tsp: float, bankroll: float, payoff_ratio: float = 3.0) -> float:
        if tsp <= 0 or payoff_ratio <= 0:
            return 0.0
        q = (tsp * (payoff_ratio + 1) - 1) / payoff_ratio
        return max(0.0, min(q, 0.03)) * bankroll
