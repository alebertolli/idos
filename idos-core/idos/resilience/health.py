from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Callable
from idos.timezone import AR_TZ

class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"

@dataclass
class HealthCheck:
    name: str
    healthy: bool
    details: str = ""
    checked_at: str = ""

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.now(AR_TZ).isoformat()

class HealthMonitor:
    def __init__(self):
        self._checks: dict[str, Callable[[], HealthCheck]] = {}
        self._results: dict[str, HealthCheck] = {}
        self._status: HealthStatus = HealthStatus.HEALTHY

    def register(self, name: str, check_fn: Callable[[], HealthCheck]):
        self._checks[name] = check_fn

    def unregister(self, name: str):
        self._checks.pop(name, None)
        self._results.pop(name, None)

    def run_all(self) -> list[HealthCheck]:
        self._results.clear()
        results = []
        for name, fn in self._checks.items():
            try:
                check = fn()
            except Exception as e:
                check = HealthCheck(name=name, healthy=False, details=str(e))
            self._results[name] = check
            results.append(check)

        healthy_count = sum(1 for r in results if r.healthy)
        total = len(results)
        if total == 0:
            self._status = HealthStatus.HEALTHY
        elif healthy_count == total:
            self._status = HealthStatus.HEALTHY
        elif healthy_count >= total / 2:
            self._status = HealthStatus.DEGRADED
        else:
            self._status = HealthStatus.UNHEALTHY

        return results

    def get_result(self, name: str) -> HealthCheck | None:
        return self._results.get(name)

    @property
    def status(self) -> HealthStatus:
        return self._status

    @property
    def registered_count(self) -> int:
        return len(self._checks)
