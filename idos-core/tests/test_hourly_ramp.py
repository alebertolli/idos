from datetime import datetime, timezone
import json
from pathlib import Path

from idos.research.hourly_ramp import (
    batch_limit,
    initial_state,
    load_state,
    record_outcome,
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
