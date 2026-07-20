from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from idos.timezone import AR_TZ

class HypothesisStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    STRENGTHENING = "STRENGTHENING"
    CONFIRMED = "CONFIRMED"
    WEAKENING = "WEAKENING"
    AT_RISK = "AT_RISK"
    INVALIDATED = "INVALIDATED"
    CLOSED = "CLOSED"

class HypothesisPriority(StrEnum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    INFORMATIONAL = "informational"

class EvidenceCategory(StrEnum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"

@dataclass
class Prediction:
    metric: str = ""
    expected_value: float = 0.0
    unit: str = ""
    deadline: str = ""
    actual_value: float | None = None
    met: bool | None = None
    notes: str = ""

    def evaluate(self) -> bool | None:
        if self.actual_value is None:
            return None
        self.met = self.actual_value >= self.expected_value
        return self.met

@dataclass
class FalsificationCondition:
    condition: str = ""
    metric: str = ""
    threshold: float = 0.0
    triggered: bool = False
    triggered_at: str = ""

@dataclass
class EvidenceLink:
    claim: str = ""
    category: EvidenceCategory = EvidenceCategory.FACT
    source: str = ""
    date: str = ""

@dataclass
class Hypothesis:
    id: str
    opportunity_id: str
    ticker: str
    statement: str = ""
    status: HypothesisStatus = HypothesisStatus.DRAFT
    priority: HypothesisPriority = HypothesisPriority.IMPORTANT
    version: int = 1
    horizon: str = "24 months"
    author: str = "system"
    probability: float = 0.5
    confidence: float = 0.0
    parent_id: str = ""
    predictions: list[Prediction] = field(default_factory=list)
    falsification: list[FalsificationCondition] = field(default_factory=list)
    evidence: list[EvidenceLink] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = datetime.now(AR_TZ).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def promote(self, target: HypothesisStatus):
        order = list(HypothesisStatus)
        current_idx = order.index(self.status)
        target_idx = order.index(target)
        if target_idx >= current_idx:
            self.status = target
            self.updated_at = datetime.now(AR_TZ).isoformat()

    def check_falsification(self) -> list[str]:
        triggered = []
        for fc in self.falsification:
            if fc.triggered:
                triggered.append(fc.condition)
        if triggered:
            self.status = HypothesisStatus.INVALIDATED
        return triggered

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "opportunity_id": self.opportunity_id,
            "ticker": self.ticker,
            "statement": self.statement,
            "status": self.status.value,
            "priority": self.priority.value,
            "version": self.version,
            "probability": self.probability,
            "confidence": self.confidence,
            "predictions": [{"metric": p.metric, "expected": p.expected_value,
                             "unit": p.unit, "deadline": p.deadline,
                             "actual": p.actual_value, "met": p.met} for p in self.predictions],
            "falsification": [{"condition": f.condition, "metric": f.metric,
                               "threshold": f.threshold, "triggered": f.triggered}
                              for f in self.falsification],
        }

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
