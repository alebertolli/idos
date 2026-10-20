from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from idos.timezone import AR_TZ

class BiasType(StrEnum):
    CONFIRMATION = "confirmation_bias"
    OVERCONFIDENCE = "overconfidence"
    ANCHORING = "anchoring"
    HERDING = "herding"
    LOSS_AVERSION = "loss_aversion"
    RECENCY = "recency_bias"
    SUNK_COST = "sunk_cost_fallacy"
    HINDSIGHT = "hindsight_bias"
    OTHER = "other"

@dataclass
class BiasEntry:
    ticker: str
    bias_type: BiasType
    description: str
    severity: str = "low"
    impact: str = ""
    decision_id: str = ""
    identified_at: str = ""

    def __post_init__(self):
        if not self.identified_at:
            self.identified_at = datetime.now(AR_TZ).isoformat()

class BehavioralJournal:
    def __init__(self):
        self._entries: list[BiasEntry] = []

    def log(self, entry: BiasEntry):
        self._entries.append(entry)

    def get_by_ticker(self, ticker: str) -> list[BiasEntry]:
        return [e for e in self._entries if e.ticker.upper() == ticker.upper()]

    def get_by_bias(self, bias_type: BiasType) -> list[BiasEntry]:
        return [e for e in self._entries if e.bias_type == bias_type]

    def get_by_severity(self, severity: str) -> list[BiasEntry]:
        return [e for e in self._entries if e.severity == severity]

    def bias_frequencies(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self._entries:
            counts[e.bias_type.value] = counts.get(e.bias_type.value, 0) + 1
        return counts

    def recent(self, n: int = 10) -> list[BiasEntry]:
        return self._entries[-n:]

    def count(self) -> int:
        return len(self._entries)

    def clear(self):
        self._entries.clear()
