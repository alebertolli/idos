import pytest
from idos.learning.hitrate import HitRateTracker


class TestHitRateTracker:
    def test_hit_rate(self):
        hr = HitRateTracker()
        hr.record_hit("scout")
        hr.record_hit("scout")
        hr.record_miss("scout")
        s = hr.stats("scout")
        assert s.hits == 2
        assert s.misses == 1
        assert s.hit_rate_pct == 66.7
        assert s.total == 3

    def test_pending(self):
        hr = HitRateTracker()
        hr.record_pending("ddd")
        s = hr.stats("ddd")
        assert s.pending == 1
        assert s.hit_rate_pct == 0.0

    def test_empty_key(self):
        hr = HitRateTracker()
        s = hr.stats("nonexistent")
        assert s.total == 0

    def test_top_performers(self):
        hr = HitRateTracker()
        for _ in range(5):
            hr.record_hit("engine_a")
        for _ in range(3):
            hr.record_hit("engine_b")
        for _ in range(3):
            hr.record_miss("engine_b")
        for _ in range(2):
            hr.record_hit("engine_c")
        top = hr.top_performers(min_samples=3)
        assert len(top) == 2  # engine_a (100%, 5) and engine_b (50%, 6)
        assert top[0][0] == "engine_a"
        assert top[1][0] == "engine_b"

    def test_clear(self):
        hr = HitRateTracker()
        hr.record_hit("test")
        hr.clear()
        assert hr.stats("test").total == 0
