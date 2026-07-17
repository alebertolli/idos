from typing import Any
from idos.decision.engines.base import AssessmentResult
from idos.models.conviction import Conviction
from idos.models.enums import ConfidenceLevel, ConvictionTrend


class ConvictionCalculator:
    WEIGHTS = {
        "BusinessAssessmentEngine": 0.30,
        "ValuationAssessmentEngine": 0.25,
        "RecoveryAssessmentEngine": 0.20,
        "RiskAssessmentEngine": 0.15,
        "PortfolioAssessmentEngine": 0.10,
    }

    def calculate(self, assessments: dict[str, AssessmentResult],
                  previous_conviction: Conviction | None = None) -> Conviction:
        scores = {}
        weighted_sum = 0.0
        total_weight = 0.0

        for engine_name, result in assessments.items():
            weight = self.WEIGHTS.get(engine_name, 0.10)
            scores[engine_name] = result.score
            weighted_sum += result.score * weight
            total_weight += weight

        overall = int(round(weighted_sum / total_weight)) if total_weight > 0 else 50

        confidences = [r.confidence for r in assessments.values()]
        if "HIGH" in confidences and confidences.count("HIGH") >= 3:
            confidence = ConfidenceLevel.HIGH
        elif "LOW" in confidences and confidences.count("LOW") >= 3:
            confidence = ConfidenceLevel.LOW
        else:
            confidence = ConfidenceLevel.MEDIUM

        if previous_conviction:
            diff = overall - previous_conviction.overall
            if diff > 5:
                trend = ConvictionTrend.IMPROVING
            elif diff < -5:
                trend = ConvictionTrend.DETERIORATING
            else:
                trend = ConvictionTrend.STABLE
        else:
            trend = ConvictionTrend.STABLE

        return Conviction(
            overall=overall,
            scores=scores,
            confidence=confidence,
            trend=trend,
        )
