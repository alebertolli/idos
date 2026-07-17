from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any


@dataclass
class AOIFProtocol:
    opportunity_id: str
    ticker: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)

    def add_step(self, name: str, result: dict[str, Any]):
        self.steps.append({
            "step": name,
            "result": result,
            "timestamp": datetime.now(datetime.UTC).isoformat(),
        })

    def complete(self):
        self.completed_at = datetime.now(datetime.UTC)
