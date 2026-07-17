import pytest
from idos.learning.patterns import PatternLearner


class TestPatternLearner:
    def test_register_and_observe(self):
        pl = PatternLearner(min_occurrences=3)
        pl.register_pattern("high_roe", "High ROE > 20%", {"roe": {"min": 20}}, ["value"])
        pl.observe("AAPL", {"roe": 25}, "success")
        assert len(pl.all_patterns()) == 1

    def test_high_performing(self):
        pl = PatternLearner(min_occurrences=2)
        pl.register_pattern("p1", "Pattern 1", {"roe": {"min": 20}}, ["value"])
        pl.register_pattern("p2", "Pattern 2", {"roe": {"max": 10}}, ["value"])
        pl.observe("A", {"roe": 25}, "success")
        pl.observe("B", {"roe": 30}, "success")
        pl.observe("C", {"roe": 5}, "failure")
        assert len(pl.get_high_performing(min_success_rate=70)) == 1

    def test_underperforming(self):
        pl = PatternLearner(min_occurrences=2)
        pl.register_pattern("p1", "Bad Pattern", {"debt": {"min": 5}}, ["risk"])
        pl.observe("X", {"debt": 10}, "failure")
        pl.observe("Y", {"debt": 8}, "failure")
        assert len(pl.get_underperforming(max_success_rate=40)) == 1

    def test_tag_filter(self):
        pl = PatternLearner()
        pl.register_pattern("p1", "Val", {"pe": {"max": 15}}, ["value"])
        pl.register_pattern("p2", "Mom", {"momentum": {"min": 10}}, ["momentum"])
        assert len(pl.get_patterns_by_tag("value")) == 1
        assert len(pl.get_patterns_by_tag("momentum")) == 1
