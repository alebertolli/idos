import pytest
from idos.learning.feedback import FeedbackCollector, FeedbackRecord
from idos.learning.weights import WeightAdjuster
from idos.learning.patterns import PatternLearner
from idos.learning.hitrate import HitRateTracker
from idos.learning.loop import ContinuousImprovementLoop


class TestContinuousImprovementLoop:
    def test_run_loop(self):
        fc = FeedbackCollector()
        wa = WeightAdjuster({"scout": 0.30})
        pl = PatternLearner()
        hr = HitRateTracker()

        pl.register_pattern("high_roe", "High ROE", {"roe": {"min": 20}}, ["value"])
        pl.observe("AAPL", {"roe": 25}, "success")

        for _ in range(10):
            fc.record(FeedbackRecord(ticker="A", prediction_id=str(_), predicted_direction="up",
                                     actual_direction="up", predicted_price=100, actual_price=105, engine="scout"))

        loop = ContinuousImprovementLoop(fc, wa, pl, hr)
        result = loop.run()

        assert result.feedback_processed == 10
        assert result.patterns_identified >= 0
        assert result.weights_adjusted >= 0

    def test_underperformers_detected(self):
        fc = FeedbackCollector()
        wa = WeightAdjuster({"scout": 0.30})
        pl = PatternLearner(min_occurrences=2)
        hr = HitRateTracker()

        pl.register_pattern("bad", "Bad pattern", {"debt": {"min": 5}}, ["risk"])
        pl.observe("X", {"debt": 10}, "failure")
        pl.observe("Y", {"debt": 8}, "failure")

        loop = ContinuousImprovementLoop(fc, wa, pl, hr)
        result = loop.run()

        assert "bad" in result.underperformers
