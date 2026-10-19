from idos.workers.data.digest_worker import DigestWorker


def test_digest_empty():
    w = DigestWorker()
    result = w.run({})
    assert result["line_count"] >= 5
    assert result["summary"]["opportunities"] == 0


def test_digest_with_scout_results():
    w = DigestWorker()
    result = w.run({
        "scout_results": [
            {"ticker": "MELI", "passed": True, "score": 85, "reason": "Good quality"},
            {"ticker": "V", "passed": True, "score": 72, "reason": "Fair value"},
            {"ticker": "TSLA", "passed": False, "score": 30, "reason": "Too volatile"},
        ],
    })
    assert result["summary"]["opportunities"] == 2
    assert "MELI" in result["digest"]
    assert "V" in result["digest"]
    assert "TSLA" not in result["digest"]


def test_digest_with_risk_alerts():
    w = DigestWorker()
    result = w.run({
        "risk_alerts": [
            {"ticker": "XYZ", "message": "Drawdown > 15%"},
        ],
    })
    assert "XYZ" in result["digest"]
    assert "Drawdown" in result["digest"]


def test_digest_with_opportunities():
    w = DigestWorker()
    result = w.run({
        "opportunities": [
            {"id": "OPP-001", "ticker": "MELI", "status": "WATCHLIST", "conviction": 75},
        ],
    })
    assert "OPP-001" in result["digest"]
    assert "WATCHLIST" in result["digest"]


def test_digest_generated_at():
    w = DigestWorker()
    result = w.run({})
    assert "generated_at" in result
    assert "T" in result["generated_at"]
