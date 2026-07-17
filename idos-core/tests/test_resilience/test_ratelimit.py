import pytest
from idos.resilience.ratelimit import RateLimiter


class TestRateLimiter:
    def test_allow_under_limit(self):
        rl = RateLimiter(max_calls=3, window_seconds=60)
        assert rl.allow("api") is True
        assert rl.remaining("api") == 3

    def test_block_over_limit(self):
        rl = RateLimiter(max_calls=2, window_seconds=60)
        assert rl.call("api") is True
        assert rl.call("api") is True
        assert rl.call("api") is False

    def test_reset(self):
        rl = RateLimiter(max_calls=1, window_seconds=60)
        rl.call("api")
        assert rl.remaining("api") == 0
        rl.reset("api")
        assert rl.remaining("api") == 1

    def test_reset_all(self):
        rl = RateLimiter(max_calls=1, window_seconds=60)
        rl.call("a")
        rl.call("b")
        rl.reset()
        assert rl.remaining("a") == 1
        assert rl.remaining("b") == 1
