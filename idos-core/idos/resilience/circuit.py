from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
from enum import StrEnum
from typing import Any


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5
    recovery_timeout: int = 60
    _state: CircuitState = CircuitState.CLOSED
    _failure_count: int = 0
    _last_failure: str = ""
    _last_state_change: str = ""

    def __post_init__(self):
        if not self._last_state_change:
            self._last_state_change = datetime.now(UTC).isoformat()

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if self._last_failure:
                last = datetime.fromisoformat(self._last_failure)
                if datetime.now(UTC) - last > timedelta(seconds=self.recovery_timeout):
                    self._state = CircuitState.HALF_OPEN
                    self._last_state_change = datetime.now(UTC).isoformat()
        return self._state

    def record_success(self):
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._last_state_change = datetime.now(UTC).isoformat()
        self._failure_count = 0

    def record_failure(self):
        self._failure_count += 1
        self._last_failure = datetime.now(UTC).isoformat()
        if self._failure_count >= self.failure_threshold and self._state != CircuitState.OPEN:
            self._state = CircuitState.OPEN
            self._last_state_change = datetime.now(UTC).isoformat()

    def reset(self):
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_state_change = datetime.now(UTC).isoformat()

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def is_available(self) -> bool:
        return self.state != CircuitState.OPEN
