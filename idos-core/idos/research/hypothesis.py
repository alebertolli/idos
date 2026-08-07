from dataclasses import dataclass, field
from idos.models.knowledge import (
    Hypothesis, Prediction, FalsificationCondition, EvidenceLink,
)
from idos.models.enums import (
    HypothesisStatus, HypothesisPriority, EvidenceCategory,
)

__all__ = [
    "HypothesisStatus", "HypothesisPriority", "EvidenceCategory",
    "Prediction", "FalsificationCondition", "EvidenceLink", "Hypothesis",
    "FiveQuestions", "HypothesisManager",
]


@dataclass
class FiveQuestions:
    what_we_believe: str = ""
    why_we_believe: str = ""
    what_should_happen: str = ""
    what_proves_us_wrong: str = ""
    when_we_stop_believing: str = ""

    def is_complete(self) -> bool:
        return all([self.what_we_believe, self.why_we_believe,
                    self.what_should_happen, self.what_proves_us_wrong,
                    self.when_we_stop_believing])


class HypothesisManager:
    def __init__(self):
        self._hypotheses: dict[str, Hypothesis] = {}

    def create(self, hypothesis: Hypothesis):
        self._hypotheses[hypothesis.id] = hypothesis

    def get(self, hypothesis_id: str) -> Hypothesis | None:
        return self._hypotheses.get(hypothesis_id)

    def by_opportunity(self, opportunity_id: str) -> list[Hypothesis]:
        return [h for h in self._hypotheses.values()
                if h.opportunity_id == opportunity_id]

    def by_ticker(self, ticker: str) -> list[Hypothesis]:
        return [h for h in self._hypotheses.values()
                if h.ticker.upper() == ticker.upper()]

    def by_status(self, status: HypothesisStatus) -> list[Hypothesis]:
        return [h for h in self._hypotheses.values() if h.status == status]

    def active(self) -> list[Hypothesis]:
        active_statuses = {HypothesisStatus.ACTIVE, HypothesisStatus.STRENGTHENING,
                           HypothesisStatus.CONFIRMED}
        return [h for h in self._hypotheses.values() if h.status in active_statuses]

    def count(self) -> int:
        return len(self._hypotheses)