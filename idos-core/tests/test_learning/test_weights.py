import pytest
from idos.learning.weights import WeightAdjuster


class TestWeightAdjuster:
    def test_adjust_up(self):
        wa = WeightAdjuster({"quality": 0.30})
        adj = wa.adjust("quality", hit_rate=80, sample_size=10)
        assert adj is not None
        assert wa.get_weight("quality") > 0.30

    def test_adjust_down(self):
        wa = WeightAdjuster({"quality": 0.30})
        adj = wa.adjust("quality", hit_rate=20, sample_size=10)
        assert adj is not None
        assert wa.get_weight("quality") < 0.30

    def test_no_adjust_insufficient_data(self):
        wa = WeightAdjuster({"quality": 0.30})
        adj = wa.adjust("quality", hit_rate=80, sample_size=3)
        assert adj is None

    def test_unknown_dimension(self):
        wa = WeightAdjuster({"quality": 0.30})
        adj = wa.adjust("unknown", hit_rate=80, sample_size=10)
        assert adj is None

    def test_clamped_to_bounds(self):
        wa = WeightAdjuster({"quality": 0.01}, min_weight=0.05, max_weight=0.50)
        adj = wa.adjust("quality", hit_rate=10, sample_size=10)
        assert wa.get_weight("quality") >= 0.05

    def test_get_all_weights(self):
        wa = WeightAdjuster({"a": 0.2, "b": 0.3})
        assert wa.get_all_weights() == {"a": 0.2, "b": 0.3}

    def test_history(self):
        wa = WeightAdjuster({"quality": 0.30})
        wa.adjust("quality", hit_rate=80, sample_size=10)
        assert len(wa.get_history()) == 1
