from dataclasses import dataclass, field
from typing import Any
from idos.decision.engines.recovery import RecoveryAssessmentEngine


@dataclass
class RecoveryIndex:
    probability: float
    magnitude: float
    velocity: float
    confidence: float
    index_value: float = 0.0

    def __post_init__(self):
        self.index_value = self.probability * self.magnitude * self.velocity * self.confidence


class ReratingProbabilityEngine:
    def __init__(self):
        self.recovery_engine = RecoveryAssessmentEngine()
        self._calibration: dict[str, float] = {
            "high": 0.72,
            "medium": 0.55,
            "low": 0.31,
        }

    def evaluate(self, context: dict[str, Any]) -> RecoveryIndex:
        assessment = self.recovery_engine.evaluate(context)
        score = assessment.score

        if score > 85:
            prob = self._calibration["high"]
        elif score >= 70:
            prob = self._calibration["medium"]
        else:
            prob = self._calibration["low"]

        magnitude = self._estimate_magnitude(context)
        velocity = self._estimate_velocity(context)
        conf = 0.9 if assessment.confidence == "HIGH" else 0.7 if assessment.confidence == "MEDIUM" else 0.4

        return RecoveryIndex(
            probability=prob,
            magnitude=magnitude,
            velocity=velocity,
            confidence=conf,
        )

    def _estimate_magnitude(self, ctx: dict[str, Any]) -> float:
        m = ctx.get("knowledge_base", {}).get("dynamic", {}).get("metrics", {})
        intrinsic = m.get("intrinsic_value", 0)
        price = m.get("current_price", 1)
        if intrinsic and price:
            return max(1.0, (intrinsic / price) - 1.0)
        return 1.5

    def _estimate_velocity(self, ctx: dict[str, Any]) -> float:
        cat = ctx.get("catalysts", [])
        if not cat:
            return 0.5
        short_term = sum(1 for c in cat if c.get("timeline") == "short")
        return min(1.0, 0.3 + short_term * 0.15)

    def calibrate(self, band: str, new_probability: float):
        if band in self._calibration:
            self._calibration[band] = new_probability

    def get_calibration(self) -> dict[str, float]:
        return dict(self._calibration)
