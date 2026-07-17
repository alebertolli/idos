from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional


class WorkerStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorkerResult:
    status: WorkerStatus
    worker: str
    output: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0.0


class BaseWorker:
    name: str = "base"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config if config is not None else {}

    def execute(self, context: dict[str, Any] | None = None) -> WorkerResult:
        started = datetime.now(timezone.utc)
        try:
            result = self.run(context or {})
            if isinstance(result, WorkerResult):
                result.started_at = started
                result.completed_at = datetime.now(timezone.utc)
                return result
            return WorkerResult(
                status=WorkerStatus.SUCCESS,
                worker=self.name,
                output=result,
                started_at=started,
                completed_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            return WorkerResult(
                status=WorkerStatus.FAILED,
                worker=self.name,
                error=str(e),
                started_at=started,
                completed_at=datetime.now(timezone.utc),
            )

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
