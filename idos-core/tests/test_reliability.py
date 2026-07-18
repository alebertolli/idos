import sys, os, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from idos.reliability.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitState
from idos.reliability.retry import retry_with_backoff, execute_with_retry
from idos.reliability.self_healing import SelfHealer
from idos.reliability.checkpoint import CheckpointManager, Checkpoint, RunManifest
from idos.reliability.health import HealthChecker, HealthStatus


def test_circuit_breaker_closed():
    cb = CircuitBreaker(name="test", failure_threshold=3)
    assert cb.state == CircuitState.CLOSED
    assert cb.can_proceed() is True


def test_circuit_breaker_opens():
    cb = CircuitBreaker(name="test", failure_threshold=3)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.can_proceed() is False


def test_circuit_breaker_recovers():
    cb = CircuitBreaker(name="test", failure_threshold=3, cooldown_minutes=0)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.can_proceed() is True
    assert cb.state == CircuitState.HALF_OPEN


def test_circuit_breaker_success_resets():
    cb = CircuitBreaker(name="test", failure_threshold=3)
    cb.failure_count = 2
    cb.record_success()
    assert cb.failure_count == 0
    assert cb.state == CircuitState.CLOSED


def test_circuit_breaker_registry():
    reg = CircuitBreakerRegistry()
    cb1 = reg.get_or_create("provider_a", failure_threshold=5)
    cb2 = reg.get_or_create("provider_a")
    assert cb1 is cb2
    cb3 = reg.get_or_create("provider_b")
    assert len(reg.all()) == 2


def test_retry_success():
    counter = {"n": 0}

    def fails_twice():
        counter["n"] += 1
        if counter["n"] < 3:
            raise ConnectionError("transient")
        return "ok"

    ok, result, log = execute_with_retry(fails_twice, max_attempts=5, initial_delay=0.01)
    assert ok is True
    assert result == "ok"
    assert len(log) == 3


def test_retry_fails():
    def always_fails():
        raise ValueError("permanent")

    ok, result, log = execute_with_retry(always_fails, max_attempts=3, initial_delay=0.01)
    assert ok is False
    assert len(log) == 3


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


def test_health_checker():
    hc = HealthChecker()
    report = hc.run_all()
    assert report.overall == HealthStatus.HEALTHY


def test_health_env_var():
    check = HealthChecker.check_env_var("PATH")
    assert check.status == HealthStatus.HEALTHY


def test_health_disk():
    check = HealthChecker.check_disk_space(min_gb=0.001)
    assert check.status == HealthStatus.HEALTHY


if __name__ == "__main__":
    test_circuit_breaker_closed()
    test_circuit_breaker_opens()
    test_circuit_breaker_recovers()
    test_circuit_breaker_success_resets()
    test_circuit_breaker_registry()
    test_retry_success()
    test_retry_fails()
    test_self_healing_repair_json()
    test_self_healing_repair_boolean()
    test_self_healing_extract_from_markdown()
    test_self_healing_invalid()
    test_checkpoint_save_load(Path("cache/test_checkpoints"))
    test_checkpoint_update(Path("cache/test_checkpoints"))
    test_checkpoint_not_found(Path("cache/test_checkpoints"))
    test_run_manifest()
    test_health_checker()
    test_health_env_var()
    test_health_disk()
    print("ALL RELIABILITY TESTS PASSED")
