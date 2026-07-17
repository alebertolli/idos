import pytest
from idos.learning.feedback import FeedbackCollector, FeedbackRecord, FeedbackSummary, Outcome


class TestFeedbackCollector:
    def test_record_and_summary(self):
        fc = FeedbackCollector()
        fc.record(FeedbackRecord(ticker="AAPL", prediction_id="p1", predicted_direction="up",
                                 actual_direction="up", predicted_price=100, actual_price=105))
        fc.record(FeedbackRecord(ticker="AAPL", prediction_id="p2", predicted_direction="up",
                                 actual_direction="down", predicted_price=100, actual_price=130))
        fc.record(FeedbackRecord(ticker="MSFT", prediction_id="p3", predicted_direction="down",
                                 actual_direction="down", predicted_price=200, actual_price=195))
        s = fc.summary()
        assert s.total == 3
        assert s.failures == 1

    def test_summary_empty(self):
        fc = FeedbackCollector()
        s = fc.summary()
        assert s.total == 0

    def test_pending_outcome(self):
        fc = FeedbackCollector()
        fc.record(FeedbackRecord(ticker="AAPL", prediction_id="p1", predicted_direction="up",
                                 actual_direction="up"))
        assert fc.all()[0].outcome == Outcome.PENDING

    def test_filter_by_engine(self):
        fc = FeedbackCollector()
        fc.record(FeedbackRecord(ticker="A", prediction_id="1", predicted_direction="up",
                                 actual_direction="up", engine="scout"))
        fc.record(FeedbackRecord(ticker="B", prediction_id="2", predicted_direction="up",
                                 actual_direction="down", engine="scout"))
        fc.record(FeedbackRecord(ticker="C", prediction_id="3", predicted_direction="up",
                                 actual_direction="up", engine="ddd"))
        assert len(fc.get_by_engine("scout")) == 2
        assert len(fc.get_by_engine("ddd")) == 1
