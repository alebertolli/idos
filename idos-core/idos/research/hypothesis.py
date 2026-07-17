from datetime import datetime, UTC
from typing import Any
from idos.models.knowledge import Hypothesis, Prediction
from idos.models.enums import HypothesisStatus


class HypothesisTreeManager:
    def __init__(self):
        self._hypotheses: dict[str, Hypothesis] = {}

    def create(self, opportunity_id: str, ticker: str, statement: str,
               secondary: list[str] | None = None,
               falsification: list[str] | None = None) -> Hypothesis:
        hyp_id = f"HYP-{opportunity_id}-{len(self._hypotheses) + 1:03d}"
        hyp = Hypothesis(
            id=hyp_id,
            opportunity_id=opportunity_id,
            ticker=ticker.upper(),
            statement=statement,
            secondary_hypotheses=secondary or [],
            falsification_conditions=falsification or [],
        )
        self._hypotheses[hyp_id] = hyp
        return hyp

    def update_status(self, hyp_id: str, status: HypothesisStatus, reason: str = ""):
        hyp = self._hypotheses.get(hyp_id)
        if hyp:
            hyp.status = status

    def add_prediction(self, hyp_id: str, variable: str, expected_value: float,
                       measurement_date: str, tolerance: float = 5.0) -> Prediction | None:
        hyp = self._hypotheses.get(hyp_id)
        if not hyp:
            return None
        pred_id = f"PRED-{hyp_id}-{len(hyp.predictions) + 1:03d}"
        pred = Prediction(
            id=pred_id, variable=variable, expected_value=expected_value,
            measurement_date=measurement_date, tolerance_pct=tolerance,
        )
        hyp.predictions.append(pred)
        return pred

    def evaluate_prediction(self, pred_id: str, observed_value: float) -> str:
        for hyp in self._hypotheses.values():
            for pred in hyp.predictions:
                if pred.id == pred_id:
                    pred.observed_value = observed_value
                    tolerance = pred.expected_value * (pred.tolerance_pct / 100)
                    if abs(observed_value - pred.expected_value) <= tolerance:
                        pred.status = "CONFIRMED"
                    else:
                        pred.status = "FAILED"
                    return pred.status
        return "NOT_FOUND"

    def get_opportunity_hypotheses(self, opportunity_id: str) -> list[Hypothesis]:
        return [h for h in self._hypotheses.values() if h.opportunity_id == opportunity_id]

    def get(self, hyp_id: str) -> Hypothesis | None:
        return self._hypotheses.get(hyp_id)

    def all(self) -> list[Hypothesis]:
        return list(self._hypotheses.values())
