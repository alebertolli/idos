from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from idos.research.hourly_ramp import (
    batch_limit,
    defer_provider_retry,
    initial_state,
    load_state,
    record_outcome,
    record_candidate_failure,
    resume_state,
    save_state,
)


def test_hourly_ramp_increases_after_full_batches_and_pauses_at_last_safe_size(tmp_path):
    now = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    state = initial_state()
    assert batch_limit(state, 10) == 1

    state = record_outcome(state, attempted=1, completed=1, now=now)
    assert state["next_batch_size"] == 2
    assert state["last_successful_batch_size"] == 1
    assert not state["paused"]

    state = record_outcome(state, attempted=2, completed=2, now=now)
    assert state["next_batch_size"] == 3
    assert state["last_successful_batch_size"] == 2

    state = record_outcome(
        state,
        attempted=3,
        completed=1,
        failure_reason="GROQ HTTP 429",
        now=now,
    )
    assert state["paused"]
    assert state["next_batch_size"] == 2
    assert state["last_failure"]["safe_batch_size"] == 2
    assert batch_limit(state, 10) == 0

    resumed = resume_state(state)
    assert not resumed["paused"]
    assert resumed["next_batch_size"] == 2
    assert resumed["last_failure"] == state["last_failure"]


def test_hourly_ramp_state_is_atomic_and_invalid_versions_reset(tmp_path):
    path = tmp_path / "cache" / "ddd_research_capacity.json"
    state = record_outcome(initial_state(), attempted=1, completed=1)

    save_state(path, state)

    assert load_state(path) == state
    assert not path.with_suffix(path.suffix + ".tmp").exists()
    path.write_text(json.dumps({"schema_version": 99, "next_batch_size": 8}), encoding="utf-8")
    assert load_state(path) == initial_state()


def test_hourly_ramp_does_not_claim_an_unfilled_batch_size_as_proven():
    state = record_outcome(initial_state(), attempted=1, completed=1)
    assert state["next_batch_size"] == 2

    underfilled = record_outcome(state, attempted=1, completed=1)

    assert underfilled["next_batch_size"] == 2
    assert underfilled["last_successful_batch_size"] == 1
    assert underfilled["paused"] is False


def test_provider_backoff_is_automatic_bounded_and_blocks_calls_until_due():
    now = datetime.now(timezone.utc) + timedelta(days=1)
    state = defer_provider_retry(initial_state(), now=now)
    assert state["provider_failure_count"] == 1
    assert datetime.fromisoformat(state["provider_retry_after"]) == now + timedelta(hours=1)
    assert not state["paused"]
    assert batch_limit(state, 5) == 0

    for _ in range(10):
        state = defer_provider_retry(state, now=now)
    assert state["provider_failure_count"] == 11
    assert datetime.fromisoformat(state["provider_retry_after"]) == now + timedelta(hours=24)


def test_candidate_failure_is_retried_twice_then_quarantined():
    now = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
    item = {"ticker": "TEST", "opp_id": "OPP-TEST", "attempt_count": 0}
    item, quarantined = record_candidate_failure(item, "temporary parse error", now=now)
    assert not quarantined
    assert item["attempt_count"] == 1
    assert item["force_reprocess"] is True
    assert item["next_attempt_date"] == "2026-11-20"

    item, quarantined = record_candidate_failure(item, "still failing", now=now)
    assert not quarantined
    item, quarantined = record_candidate_failure(item, "persistent error", now=now)
    assert quarantined
    assert item["attempt_count"] == 3
    assert "next_attempt_date" not in item
