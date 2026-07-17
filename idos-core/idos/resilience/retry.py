from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any, Callable
import time


@dataclass
class RetryPolicy:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    backoff_multiplier: float = 2.0
    retryable_exceptions: tuple = (Exception,)


class RetryMechanism:
    def __init__(self, policy: RetryPolicy | None = None):
        self.policy = policy or RetryPolicy()
        self._attempts: list[dict[str, Any]] = []

    def execute(self, fn: Callable, *args, **kwargs) -> Any:
        last_exception = None
        for attempt in range(self.policy.max_retries + 1):
            try:
                result = fn(*args, **kwargs)
                self._attempts.append({
                    "attempt": attempt + 1,
                    "success": True,
                    "timestamp": datetime.now(UTC).isoformat(),
                })
                return result
            except self.policy.retryable_exceptions as e:
                last_exception = e
                self._attempts.append({
                    "attempt": attempt + 1,
                    "success": False,
                    "error": str(e),
                    "timestamp": datetime.now(UTC).isoformat(),
                })
                if attempt < self.policy.max_retries:
                    delay = min(
                        self.policy.base_delay * (self.policy.backoff_multiplier ** attempt),
                        self.policy.max_delay,
                    )
                    time.sleep(delay)
        raise last_exception

    @property
    def attempts(self) -> list[dict[str, Any]]:
        return list(self._attempts)

    def success_count(self) -> int:
        return sum(1 for a in self._attempts if a["success"])

    def failure_count(self) -> int:
        return sum(1 for a in self._attempts if not a["success"])
