from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any


@dataclass
class PredictionResult:
    pred_id: str
    variable: str
    expected: float
    observed: float | None
    tolerance_pct: float
    status: str
    deviation_pct: float = 0.0


class PredictionTracker:
    def __init__(self):
        self._results: dict[str, PredictionResult] = {}

    def track(self, pred_id: str, variable: str, expected: float,
              measurement_date: str, tolerance_pct: float = 5.0):
        self._results[pred_id] = PredictionResult(
            pred_id=pred_id, variable=variable, expected=expected,
            observed=None, tolerance_pct=tolerance_pct, status="PENDING",
        )

    def record(self, pred_id: str, observed: float) -> PredictionResult:
        result = self._results.get(pred_id)
        if not result:
            raise ValueError(f"Prediction {pred_id} not found")
        result.observed = observed
        if result.expected != 0:
            result.deviation_pct = abs((observed - result.expected) / result.expected) * 100
        if result.deviation_pct <= result.tolerance_pct:
            result.status = "CONFIRMED"
        else:
            result.status = "FAILED"
        return result

    def get_pending(self, as_of: str = "") -> list[PredictionResult]:
        return [r for r in self._results.values() if r.status == "PENDING"]

    def get_confirmed(self) -> list[PredictionResult]:
        return [r for r in self._results.values() if r.status == "CONFIRMED"]

    def get_failed(self) -> list[PredictionResult]:
        return [r for r in self._results.values() if r.status == "FAILED"]

    def hit_rate(self) -> float:
        confirmed = len(self.get_confirmed())
        failed = len(self.get_failed())
        total = confirmed + failed
        return confirmed / total if total > 0 else 0.0

    def all(self) -> list[PredictionResult]:
        return list(self._results.values())
