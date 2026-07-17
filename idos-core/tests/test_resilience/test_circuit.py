import time
import pytest
from idos.resilience.circuit import CircuitBreaker, CircuitState


class TestCircuitBreaker:
    def test_closed_by_default(self):
        cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout=5)
        assert cb.state == CircuitState.CLOSED
        assert cb.is_available is True

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.is_available is False

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(1.1)
        assert cb.state == CircuitState.HALF_OPEN

    def test_reset(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=60)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_success_closes_half_open(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0)
        cb.record_failure()
        time.sleep(0.1)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
