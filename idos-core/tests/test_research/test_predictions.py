from idos.research.predictions import PredictionTracker


def test_track_and_record():
    tracker = PredictionTracker()
    tracker.track("PRED-001", "Revenue", 1000.0, "2026-12-31", tolerance_pct=5.0)
    result = tracker.record("PRED-001", 1020.0)
    assert result.status == "CONFIRMED"
    assert result.deviation_pct == 2.0


def test_failed_prediction():
    tracker = PredictionTracker()
    tracker.track("PRED-002", "EPS", 5.0, "2026-12-31", tolerance_pct=5.0)
    result = tracker.record("PRED-002", 3.0)
    assert result.status == "FAILED"
    assert result.deviation_pct == 40.0


def test_hit_rate():
    tracker = PredictionTracker()
    tracker.track("P1", "A", 100, "2026-01-01", tolerance_pct=10)
    tracker.track("P2", "B", 100, "2026-01-01", tolerance_pct=10)
    tracker.record("P1", 105)
    tracker.record("P2", 50)
    assert tracker.hit_rate() == 0.5


def test_get_pending():
    tracker = PredictionTracker()
    tracker.track("P1", "A", 100, "2026-12-31")
    assert len(tracker.get_pending()) == 1
    tracker.record("P1", 100)
    assert len(tracker.get_pending()) == 0
