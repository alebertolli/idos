from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
from enum import StrEnum
from typing import Any


class TaskRequirement(StrEnum):
    REASONING = "reasoning"
    ANALYSIS = "analysis"
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    CODING = "coding"


@dataclass
class ProviderScore:
    trust: float = 1.0
    capability: float = 1.0
    cost: float = 0.5

    @property
    def composite(self) -> float:
        return self.trust * 0.5 + self.capability * 0.3 + (1.0 - self.cost) * 0.2


@dataclass
class ProviderRecord:
    name: str
    tasks: list[str] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: int = 0
    call_count: int = 0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 1.0

    @property
    def avg_latency_ms(self) -> int:
        return self.total_latency_ms // self.call_count if self.call_count > 0 else 0

    def score(self) -> ProviderScore:
        return ProviderScore(
            trust=self.success_rate,
            capability=min(1.0, self.call_count / 100),
            cost=max(0.0, 1.0 - self.avg_latency_ms / 5000),
        )


class AdaptiveRouter:
    def __init__(self):
        self._providers: dict[str, ProviderRecord] = {}

    def register(self, name: str, tasks: list[str] | None = None):
        self._providers[name] = ProviderRecord(name=name, tasks=tasks or [])

    def record_outcome(self, provider: str, success: bool, latency_ms: int = 0):
        record = self._providers.get(provider)
        if not record:
            return
        if success:
            record.success_count += 1
        else:
            record.failure_count += 1
        record.total_latency_ms += latency_ms
        record.call_count += 1

    def select(self, task_type: str) -> str | None:
        candidates = [
            p for p in self._providers.values()
            if not p.tasks or task_type in p.tasks
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.score().composite, reverse=True)
        return candidates[0].name

    def ranked(self) -> list[tuple[str, ProviderScore]]:
        return [
            (name, record.score())
            for name, record in sorted(
                self._providers.items(),
                key=lambda kv: kv[1].score().composite,
                reverse=True,
            )
        ]

    def get_provider(self, name: str) -> ProviderRecord | None:
        return self._providers.get(name)

    @property
    def provider_count(self) -> int:
        return len(self._providers)
