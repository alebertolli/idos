import pytest
from idos.resilience.retry import RetryMechanism, RetryPolicy


class TestRetryMechanism:
    def test_success_on_first_try(self):
        rm = RetryMechanism()
        result = rm.execute(lambda: "ok")
        assert result == "ok"
        assert rm.success_count() == 1
        assert rm.failure_count() == 0

    def test_retry_on_failure_then_success(self):
        attempts = 0

        def flaky():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ValueError("not yet")
            return "success"

        rm = RetryMechanism(policy=RetryPolicy(max_retries=3, base_delay=0))
        result = rm.execute(flaky)
        assert result == "success"
        assert attempts == 3

    def test_exhausts_retries(self):
        attempts = 0

        def always_fails():
            nonlocal attempts
            attempts += 1
            raise ValueError("always")

        rm = RetryMechanism(policy=RetryPolicy(max_retries=2, base_delay=0))
        with pytest.raises(ValueError):
            rm.execute(always_fails)
        assert attempts == 3  # initial + 2 retries

    def test_tracks_attempts(self):
        rm = RetryMechanism(policy=RetryPolicy(max_retries=1, base_delay=0))
        with pytest.raises(ValueError):
            rm.execute(lambda: (_ for _ in ()).throw(ValueError("fail")))
        assert len(rm.attempts) == 2
