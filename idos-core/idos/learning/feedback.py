from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from idos.timezone import AR_TZ

class Outcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"

@dataclass
class FeedbackRecord:
    ticker: str
    prediction_id: str
    predicted_direction: str
    actual_direction: str
    predicted_price: float = 0.0
    actual_price: float = 0.0
    accuracy: float = 0.0
    outcome: Outcome = Outcome.PENDING
    analyst: str = ""
    engine: str = ""
    notes: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(AR_TZ).isoformat()

@dataclass
class FeedbackSummary:
    total: int = 0
    successes: int = 0
    failures: int = 0
    pending: int = 0
    hit_rate: float = 0.0
    avg_accuracy: float = 0.0

class FeedbackCollector:
    def __init__(self):
        self._records: list[FeedbackRecord] = []

    def record(self, record: FeedbackRecord):
        if record.actual_price > 0 and record.predicted_price > 0:
            diff = abs(record.actual_price - record.predicted_price) / record.predicted_price
            record.accuracy = max(0, 1 - diff)
            record.outcome = Outcome.SUCCESS if record.accuracy >= 0.8 else Outcome.FAILURE
        self._records.append(record)

    def get_by_ticker(self, ticker: str) -> list[FeedbackRecord]:
        return [r for r in self._records if r.ticker.upper() == ticker.upper()]

    def get_by_engine(self, engine: str) -> list[FeedbackRecord]:
        return [r for r in self._records if r.engine == engine]

    def get_by_analyst(self, analyst: str) -> list[FeedbackRecord]:
        return [r for r in self._records if r.analyst == analyst]

    def summary(self, records: list[FeedbackRecord] | None = None) -> FeedbackSummary:
        recs = records or self._records
        if not recs:
            return FeedbackSummary()
        successes = sum(1 for r in recs if r.outcome == Outcome.SUCCESS)
        failures = sum(1 for r in recs if r.outcome == Outcome.FAILURE)
        pending = sum(1 for r in recs if r.outcome == Outcome.PENDING)
        closed = successes + failures
        return FeedbackSummary(
            total=len(recs), successes=successes, failures=failures,
            pending=pending,
            hit_rate=round(successes / closed * 100, 1) if closed else 0.0,
            avg_accuracy=round(sum(r.accuracy for r in recs if r.accuracy) / closed, 2) if closed else 0.0,
        )

    def all(self) -> list[FeedbackRecord]:
        return list(self._records)

    def count(self) -> int:
        return len(self._records)
