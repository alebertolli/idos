from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from enum import StrEnum
from typing import Any


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 15
    cooldown_minutes: int = 30
    half_open_max_tests: int = 3

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    half_open_tests: int = 0
    last_failure: str = ""
    opened_at: str = ""

    def record_success(self):
        if self.state == CircuitState.HALF_OPEN:
            self.half_open_tests += 1
            if self.half_open_tests >= self.half_open_max_tests:
                self._reset()
        else:
            self._reset()

    def record_failure(self):
        self.failure_count += 1
        self.last_failure = datetime.now(UTC).isoformat()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = datetime.now(UTC).isoformat()

    def can_proceed(self) -> bool:
        now = datetime.now(UTC)
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if self.opened_at:
                opened = datetime.fromisoformat(self.opened_at)
                if (now - opened) >= timedelta(minutes=self.cooldown_minutes):
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_tests = 0
                    return True
            return False
        if self.state == CircuitState.HALF_OPEN:
            return self.half_open_tests < self.half_open_max_tests
        return True

    def _reset(self):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.half_open_tests = 0
        self.opened_at = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "cooldown_minutes": self.cooldown_minutes,
            "opened_at": self.opened_at,
        }


class CircuitBreakerRegistry:
    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_or_create(self, name: str, **kwargs) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name=name, **kwargs)
        return self._breakers[name]

    def all(self) -> list[CircuitBreaker]:
        return list(self._breakers.values())

    def open_breakers(self) -> list[CircuitBreaker]:
        return [b for b in self._breakers.values() if b.state == CircuitState.OPEN]
