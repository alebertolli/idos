from pathlib import Path
from typing import Any
from idos.config import Settings, load_settings
from idos.decision.engines.base import AssessmentResult
from idos.models.conviction import Conviction
from idos.models.enums import ConfidenceLevel, ConvictionTrend


class ConvictionCalculator:
    def __init__(self, settings: Settings | None = None, config_dir: str | Path | None = None) -> None:
        if settings is None and config_dir is not None:
            settings = load_settings(config_dir)
        self.settings = settings
        self.WEIGHTS = (
            settings.conviction_weights()
            if settings is not None and settings.conviction_weights()
            else {
                "BusinessAssessmentEngine": 0.30,
                "ValuationAssessmentEngine": 0.25,
                "RecoveryAssessmentEngine": 0.20,
                "RiskAssessmentEngine": 0.15,
                "PortfolioAssessmentEngine": 0.10,
            }
        )

    def _thresholds(self):
        if self.settings is not None:
            c = self.settings.conviction
            return (
                int(c.get("high_confidence_count", 3)),
                int(c.get("track_event_diff", 5)),
            )
        return 3, 5

    def calculate(self, assessments: dict[str, AssessmentResult],
                  previous_conviction: Conviction | None = None) -> Conviction:
        high_confidence_count, track_event_diff = self._thresholds()
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
        if "HIGH" in confidences and confidences.count("HIGH") >= high_confidence_count:
            confidence = ConfidenceLevel.HIGH
        elif "LOW" in confidences and confidences.count("LOW") >= high_confidence_count:
            confidence = ConfidenceLevel.LOW
        else:
            confidence = ConfidenceLevel.MEDIUM

        if previous_conviction:
            diff = overall - previous_conviction.overall
            if diff > track_event_diff:
                trend = ConvictionTrend.IMPROVING
            elif diff < -track_event_diff:
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
