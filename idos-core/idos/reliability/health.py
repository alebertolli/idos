from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import StrEnum
from typing import Any, Callable
from pathlib import Path


class HealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


@dataclass
class HealthCheck:
    name: str
    status: HealthStatus = HealthStatus.HEALTHY
    detail: str = ""
    checked_at: str = ""

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.now(UTC).isoformat()


@dataclass
class HealthReport:
    overall: HealthStatus = HealthStatus.HEALTHY
    checks: list[HealthCheck] = field(default_factory=list)
    generated_at: str = ""

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(UTC).isoformat()
        self._recalc()

    def _recalc(self):
        statuses = [c.status for c in self.checks]
        if HealthStatus.UNHEALTHY in statuses:
            self.overall = HealthStatus.UNHEALTHY
        elif HealthStatus.DEGRADED in statuses:
            self.overall = HealthStatus.DEGRADED
        else:
            self.overall = HealthStatus.HEALTHY


class HealthChecker:
    def __init__(self):
        self._checks: dict[str, Callable[[], HealthCheck]] = {}

    def register(self, name: str, check_fn: Callable[[], HealthCheck]):
        self._checks[name] = check_fn

    def run_all(self) -> HealthReport:
        checks = []
        for name, fn in self._checks.items():
            try:
                result = fn()
                checks.append(result)
            except Exception as e:
                checks.append(HealthCheck(name=name, status=HealthStatus.UNHEALTHY, detail=str(e)))
        return HealthReport(checks=checks)

    def run_one(self, name: str) -> HealthCheck | None:
        fn = self._checks.get(name)
        if not fn:
            return None
        try:
            return fn()
        except Exception as e:
            return HealthCheck(name=name, status=HealthStatus.UNHEALTHY, detail=str(e))

    @staticmethod
    def check_git_repo(path: str | Path = ".") -> HealthCheck:
        try:
            import subprocess
            result = subprocess.run(["git", "rev-parse", "--git-dir"], capture_output=True, text=True, cwd=path, timeout=10)
            if result.returncode == 0:
                return HealthCheck(name="git_repo", status=HealthStatus.HEALTHY, detail="Git repo accessible")
            return HealthCheck(name="git_repo", status=HealthStatus.UNHEALTHY, detail="Not a git repo")
        except Exception as e:
            return HealthCheck(name="git_repo", status=HealthStatus.UNHEALTHY, detail=str(e))

    @staticmethod
    def check_sqlite(path: str | Path = "idos.sqlite") -> HealthCheck:
        try:
            p = Path(path)
            if p.exists() and p.stat().st_size > 0:
                return HealthCheck(name="sqlite", status=HealthStatus.HEALTHY, detail="SQLite accessible")
            return HealthCheck(name="sqlite", status=HealthStatus.DEGRADED, detail="SQLite not found")
        except Exception as e:
            return HealthCheck(name="sqlite", status=HealthStatus.UNHEALTHY, detail=str(e))

    @staticmethod
    def check_disk_space(path: str | Path = ".", min_gb: float = 0.5) -> HealthCheck:
        try:
            import shutil
            usage = shutil.disk_usage(path)
            free_gb = usage.free / (1024 ** 3)
            if free_gb >= min_gb:
                return HealthCheck(name="disk_space", status=HealthStatus.HEALTHY, detail=f"{free_gb:.1f}GB free")
            return HealthCheck(name="disk_space", status=HealthStatus.DEGRADED, detail=f"Only {free_gb:.1f}GB free")
        except Exception as e:
            return HealthCheck(name="disk_space", status=HealthStatus.UNHEALTHY, detail=str(e))

    @staticmethod
    def check_env_var(name: str) -> HealthCheck:
        import os
        if os.environ.get(name):
            return HealthCheck(name=f"env_{name}", status=HealthStatus.HEALTHY, detail=f"{name} is set")
        return HealthCheck(name=f"env_{name}", status=HealthStatus.DEGRADED, detail=f"{name} not set")
