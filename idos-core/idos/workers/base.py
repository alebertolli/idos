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
    PARTIAL_SUCCESS = "partial_success"
    CANCELLED = "cancelled"


@dataclass
class WorkerResult:
    status: WorkerStatus
    worker: str
    output: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metrics: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""

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
        from idos.resilience.checkpoint import RunManifest
        from idos.notifications.center import NotificationCenter, Notification, NotificationPriority
        from idos.telemetry.trace import get_tracer

        started = datetime.now(timezone.utc)
        tracer = get_tracer()
        run_id = tracer.start_run(self.name)

        manifest = RunManifest(run_id=run_id, worker=self.name)
        notif_center = NotificationCenter()

        try:
            result = self.run(context or {})
            if isinstance(result, WorkerResult):
                result.run_id = run_id
                result.started_at = started
                result.completed_at = datetime.now(timezone.utc)
                manifest.complete(result.status.value)
                status = result.status
            else:
                manifest.complete("SUCCESS")
                status = WorkerStatus.SUCCESS
                result = WorkerResult(
                    status=WorkerStatus.SUCCESS,
                    worker=self.name,
                    output=result,
                    started_at=started,
                    completed_at=datetime.now(timezone.utc),
                    run_id=run_id,
                )
        except Exception as e:
            status = WorkerStatus.FAILED
            manifest.complete("FAILED")
            manifest.errors.append({"error": str(e)})
            result = WorkerResult(
                status=WorkerStatus.FAILED,
                worker=self.name,
                error=str(e),
                started_at=started,
                completed_at=datetime.now(timezone.utc),
                run_id=run_id,
            )

        if status in (WorkerStatus.FAILED,):
            notif_center.notify(Notification(
                title=f"Worker {self.name} failed",
                body=str(result.error or "Unknown error"),
                priority=NotificationPriority.HIGH,
                source=self.name,
            ))
        elif status == WorkerStatus.PARTIAL_SUCCESS:
            notif_center.notify(Notification(
                title=f"Worker {self.name} partially completed",
                body=f"run_id={run_id}",
                priority=NotificationPriority.MEDIUM,
                source=self.name,
            ))

        return result

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
