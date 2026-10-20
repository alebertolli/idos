from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from pathlib import Path
import json
from idos.timezone import AR_TZ

@dataclass
class Checkpoint:
    worker: str
    progress: int = 0
    total: int = 0
    last_item: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(AR_TZ).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker": self.worker,
            "progress": self.progress,
            "total": self.total,
            "last_item": self.last_item,
            "context": self.context,
            "timestamp": self.timestamp,
        }

@dataclass
class RunManifest:
    run_id: str
    worker: str
    status: str = "RUNNING"
    started_at: str = ""
    ended_at: str = ""
    provider_used: str = ""
    fallbacks: list[str] = field(default_factory=list)
    checkpoint: dict[str, Any] = field(default_factory=dict)
    files_modified: list[str] = field(default_factory=list)
    notifications: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    git_commit: str = ""

    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.now(AR_TZ).isoformat()

    def complete(self, status: str = "SUCCESS"):
        self.status = status
        self.ended_at = datetime.now(AR_TZ).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "worker": self.worker,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "provider_used": self.provider_used,
            "fallbacks": self.fallbacks,
            "checkpoint": self.checkpoint,
            "files_modified": self.files_modified,
            "notifications": self.notifications,
            "errors": self.errors,
            "git_commit": self.git_commit,
        }

class CheckpointManager:
    def __init__(self, base_path: str | Path = "cache/checkpoints"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def save(self, checkpoint: Checkpoint):
        path = self.base_path / f"{checkpoint.worker}.json"
        path.write_text(json.dumps(checkpoint.to_dict(), indent=2), encoding="utf-8")

    def load(self, worker: str) -> Checkpoint | None:
        path = self.base_path / f"{worker}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Checkpoint(**data)
        except (json.JSONDecodeError, KeyError):
            return None

    def remove(self, worker: str):
        path = self.base_path / f"{worker}.json"
        if path.exists():
            path.unlink()

    def exists(self, worker: str) -> bool:
        return (self.base_path / f"{worker}.json").exists()

    def update_progress(self, worker: str, progress: int, total: int, last_item: str = "",
                        context: dict[str, Any] | None = None):
        cp = self.load(worker) or Checkpoint(worker=worker)
        cp.progress = progress
        cp.total = total
        cp.last_item = last_item
        cp.timestamp = datetime.now(AR_TZ).isoformat()
        if context:
            cp.context.update(context)
        self.save(cp)
