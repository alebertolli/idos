import sys, os, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from idos.resilience.circuit import CircuitBreaker, CircuitState
from idos.resilience.retry import RetryMechanism, RetryPolicy
from idos.resilience.self_healing import SelfHealer
from idos.resilience.checkpoint import CheckpointManager, Checkpoint, RunManifest
from idos.resilience.health import HealthMonitor, HealthStatus, HealthCheck


def test_circuit_breaker_closed():
    cb = CircuitBreaker(name="test", failure_threshold=3)
    assert cb.state == CircuitState.CLOSED
    assert cb.is_available is True


def test_circuit_breaker_opens():
    cb = CircuitBreaker(name="test", failure_threshold=3)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.is_available is False


def test_circuit_breaker_recovers():
    cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout=0)
    for _ in range(3):
        cb.record_failure()
    assert cb.failure_count == 3
    assert cb.is_available is True
    assert cb.state == CircuitState.HALF_OPEN


def test_circuit_breaker_success_resets():
    cb = CircuitBreaker(name="test", failure_threshold=3)
    for _ in range(2):
        cb.record_failure()
    assert cb.failure_count == 2
    cb.record_success()
    assert cb.failure_count == 0
    assert cb.state == CircuitState.CLOSED


def test_retry_success():
    counter = {"n": 0}

    def fails_twice():
        counter["n"] += 1
        if counter["n"] < 3:
            raise ConnectionError("transient")
        return "ok"

    policy = RetryPolicy(max_retries=5, base_delay=0.01, max_delay=0.1)
    mech = RetryMechanism(policy)
    result = mech.execute(fails_twice)
    assert result == "ok"
    assert mech.success_count() == 1
    assert mech.failure_count() == 2


def test_retry_fails():
    def always_fails():
        raise ValueError("permanent")

    policy = RetryPolicy(max_retries=3, base_delay=0.01, max_delay=0.1,
                         retryable_exceptions=(Exception,))
    mech = RetryMechanism(policy)
    try:
        mech.execute(always_fails)
        assert False, "Should have raised"
    except ValueError:
        pass
    assert mech.failure_count() == 4


def test_self_healing_repair_json():
    healer = SelfHealer()
    broken = '{name: "MELI", value: 100,}'
    fixed = healer.repair_json(broken)
    assert fixed is not None
    parsed = json.loads(fixed)
    assert parsed["name"] == "MELI"


def test_self_healing_repair_boolean():
    healer = SelfHealer()
    broken = '{"active": True, "score": None}'
    fixed = healer.repair_json(broken)
    assert fixed is not None
    parsed = json.loads(fixed)
    assert parsed["active"] is True
    assert parsed["score"] is None


def test_self_healing_extract_from_markdown():
    healer = SelfHealer()
    text = "Some text before\n```json\n{\"key\": \"value\"}\n```\nafter"
    result = healer.parse_with_healing(text)
    assert result is not None
    assert result["key"] == "value"


def test_self_healing_invalid():
    healer = SelfHealer()
    result = healer.repair_json("not json at all")
    assert result is None


def test_checkpoint_save_load(tmp_path):
    cm = CheckpointManager(tmp_path)
    cp = Checkpoint(worker="scout", progress=50, total=100, last_item="MELI")
    cm.save(cp)
    loaded = cm.load("scout")
    assert loaded is not None
    assert loaded.worker == "scout"
    assert loaded.progress == 50
    assert loaded.last_item == "MELI"


def test_checkpoint_update(tmp_path):
    cm = CheckpointManager(tmp_path)
    cm.update_progress("scout", 75, 100, "GOOGL")
    loaded = cm.load("scout")
    assert loaded.progress == 75
    assert loaded.last_item == "GOOGL"


def test_checkpoint_not_found(tmp_path):
    cm = CheckpointManager(tmp_path)
    loaded = cm.load("nonexistent")
    assert loaded is None


def test_run_manifest():
    m = RunManifest(run_id="RUN-001", worker="Scout")
    assert m.status == "RUNNING"
    m.complete("SUCCESS")
    assert m.status == "SUCCESS"
    assert m.ended_at != ""


def test_health_monitor():
    hm = HealthMonitor()
    results = hm.run_all()
    assert len(results) == 0
    assert hm.status == HealthStatus.HEALTHY


def test_health_register_check():
    hm = HealthMonitor()
    hm.register("always_healthy", lambda: HealthCheck(
        name="always_healthy", healthy=True, details="OK"
    ))
    results = hm.run_all()
    assert len(results) == 1
    assert results[0].healthy is True
    assert hm.status == HealthStatus.HEALTHY


if __name__ == "__main__":
    test_circuit_breaker_closed()
    test_circuit_breaker_opens()
    test_circuit_breaker_recovers()
    test_circuit_breaker_success_resets()
    test_retry_success()
    test_retry_fails()
    test_self_healing_repair_json()
    test_self_healing_repair_boolean()
    test_self_healing_extract_from_markdown()
    test_self_healing_invalid()
    test_checkpoint_not_found(Path("cache/test_checkpoints"))
    test_run_manifest()
    test_health_monitor()
    test_health_register_check()
    print("ALL RELIABILITY TESTS PASSED")
