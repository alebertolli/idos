from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any


@dataclass
class CostBudget:
    max_tokens_per_worker: int = 100000
    max_daily_per_provider: int = 500000
    max_monthly_total: int = 10000000
    max_execution_seconds: int = 600
    max_context_size: int = 128000


@dataclass
class UsageRecord:
    worker: str = ""
    provider: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    estimated_cost: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out


class CostController:
    def __init__(self, budget: CostBudget | None = None):
        self.budget = budget or CostBudget()
        self._records: list[UsageRecord] = []

    def record(self, worker: str, provider: str, tokens_in: int, tokens_out: int):
        self._records.append(UsageRecord(
            worker=worker,
            provider=provider,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        ))

    def allow_call(self, worker: str, provider: str, estimated_tokens: int) -> tuple[bool, str]:
        if estimated_tokens > self.budget.max_context_size:
            return False, f"Context too large: {estimated_tokens} > {self.budget.max_context_size}"

        worker_tokens = sum(r.total_tokens for r in self._records if r.worker == worker)
        if worker_tokens + estimated_tokens > self.budget.max_tokens_per_worker:
            return False, f"Worker token budget exceeded for {worker}"

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        provider_daily = sum(
            r.total_tokens for r in self._records
            if r.provider == provider and r.timestamp.startswith(today)
        )
        if provider_daily + estimated_tokens > self.budget.max_daily_per_provider:
            return False, f"Daily provider budget exceeded for {provider}"

        this_month = datetime.now(UTC).strftime("%Y-%m")
        monthly_total = sum(
            r.total_tokens for r in self._records
            if r.timestamp.startswith(this_month)
        )
        if monthly_total + estimated_tokens > self.budget.max_monthly_total:
            return False, "Monthly total budget exceeded"

        return True, ""

    def worker_usage(self, worker: str) -> int:
        return sum(r.total_tokens for r in self._records if r.worker == worker)

    def provider_usage(self, provider: str) -> int:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        return sum(r.total_tokens for r in self._records if r.provider == provider and r.timestamp.startswith(today))

    def total_usage(self) -> int:
        return sum(r.total_tokens for r in self._records)

    def clear(self):
        self._records.clear()

    @property
    def record_count(self) -> int:
        return len(self._records)
