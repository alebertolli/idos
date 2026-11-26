"""Persistent, deterministic state for the hourly DDD capacity ramp."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_BATCH_SIZE = 250
DEFAULT_BATCH_SIZE = 1
MAX_PROVIDER_BACKOFF_HOURS = 24
MAX_CANDIDATE_ATTEMPTS = 3


def initial_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "next_batch_size": DEFAULT_BATCH_SIZE,
        "last_successful_batch_size": 0,
        "paused": False,
        "pause_reason": "",
        "last_failure": None,
        "updated_at": None,
        "provider_retry_after": None,
        "provider_failure_count": 0,
    }


def load_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema_version") != SCHEMA_VERSION:
            return initial_state()
        next_size = value.get("next_batch_size")
        last_successful = value.get("last_successful_batch_size")
        if not isinstance(next_size, int) or not 1 <= next_size <= MAX_BATCH_SIZE:
            return initial_state()
        if not isinstance(last_successful, int) or not 0 <= last_successful <= MAX_BATCH_SIZE:
            return initial_state()
        return {**initial_state(), **value}
    except (OSError, ValueError, AttributeError, TypeError):
        return initial_state()


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def batch_limit(state: dict[str, Any], pending_count: int) -> int:
    if state.get("paused") or pending_count <= 0:
        return 0
    retry_after = state.get("provider_retry_after")
    if retry_after:
        try:
            if datetime.now(timezone.utc) < datetime.fromisoformat(retry_after):
                return 0
        except (TypeError, ValueError):
            pass
    return min(int(state.get("next_batch_size", DEFAULT_BATCH_SIZE)), pending_count, MAX_BATCH_SIZE)


def has_due_work(
    state: dict[str, Any], pending: list[dict[str, Any]], *, now: datetime | None = None,
) -> bool:
    """Return whether the durable queue can safely trigger another ramp run."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if state.get("paused") or not pending:
        return False
    retry_after = state.get("provider_retry_after")
    if retry_after:
        try:
            if current < datetime.fromisoformat(retry_after):
                return False
        except (TypeError, ValueError):
            pass
    today = current.date().isoformat()
    return any(item.get("next_attempt_date", "") <= today for item in pending)


def exclude_quarantined(
    pending: list[dict[str, Any]], quarantined: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return pending candidates that are not parked in the durable quarantine."""
    def candidate_key(item: dict[str, Any]) -> tuple[str, str] | None:
        ticker = str(item.get("ticker", "")).strip().upper()
        opp_id = str(item.get("opp_id", "")).strip()
        return (ticker, opp_id) if ticker and opp_id else None

    quarantined_keys = {
        key
        for item in quarantined
        if isinstance(item, dict)
        if (key := candidate_key(item)) is not None
    }
    return [
        item for item in pending
        if not isinstance(item, dict) or candidate_key(item) not in quarantined_keys
    ]


def defer_provider_retry(state: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Apply bounded exponential cooldown without requiring a manual resume."""
    updated = {**state}
    failures = int(updated.get("provider_failure_count", 0)) + 1
    delay_hours = min(2 ** (failures - 1), MAX_PROVIDER_BACKOFF_HOURS)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    updated.update({
        "provider_failure_count": failures,
        "provider_retry_after": (current + timedelta(hours=delay_hours)).isoformat(),
        "paused": False,
        "pause_reason": "",
        "updated_at": current.isoformat(),
    })
    return updated


def record_candidate_failure(
    item: dict[str, Any], error: str, *, now: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    """Schedule a bounded candidate retry; return (updated item, quarantined)."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    attempts = int(item.get("attempt_count", 0)) + 1
    updated = {
        **item,
        "attempt_count": attempts,
        "last_error": str(error)[:500],
        "force_reprocess": True,
    }
    quarantined = attempts >= MAX_CANDIDATE_ATTEMPTS
    if not quarantined:
        updated["next_attempt_date"] = (current.date() + timedelta(days=1)).isoformat()
    else:
        updated.pop("next_attempt_date", None)
    return updated, quarantined


def record_outcome(
    state: dict[str, Any],
    *,
    attempted: int,
    completed: int,
    failure_reason: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Advance by one only after a full clean batch; otherwise pause at the last safe size."""
    if attempted <= 0:
        return {**state}

    updated = {**state}
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    updated["updated_at"] = timestamp
    # A partial queue must not prove a larger batch size. Only advance after
    # exercising every slot in the current target batch successfully.
    expected_batch_size = int(state.get("next_batch_size", DEFAULT_BATCH_SIZE))
    full_success = (
        not failure_reason
        and completed == attempted
        and attempted >= expected_batch_size
    )
    if full_success:
        updated["last_successful_batch_size"] = expected_batch_size
        updated["next_batch_size"] = min(
            expected_batch_size + 1,
            MAX_BATCH_SIZE,
        )
        updated["paused"] = False
        updated["pause_reason"] = ""
        updated["provider_retry_after"] = None
        updated["provider_failure_count"] = 0
        return updated

    if not failure_reason and completed == attempted:
        updated["next_batch_size"] = expected_batch_size
        updated["paused"] = False
        updated["pause_reason"] = ""
        return updated

    safe_size = int(state.get("last_successful_batch_size", 0))
    updated["next_batch_size"] = min(max(safe_size, DEFAULT_BATCH_SIZE), MAX_BATCH_SIZE)
    updated["paused"] = True
    updated["pause_reason"] = (failure_reason or f"Only {completed} of {attempted} opportunities completed")[:500]
    updated["last_failure"] = {
        "at": timestamp,
        "attempted": attempted,
        "completed": completed,
        "safe_batch_size": safe_size,
        "reason": updated["pause_reason"],
    }
    return updated


def resume_state(state: dict[str, Any]) -> dict[str, Any]:
    """Explicitly resume from the last proven batch size after the failure was reviewed."""
    resumed = {**state}
    resumed["paused"] = False
    resumed["pause_reason"] = ""
    resumed["next_batch_size"] = max(
        DEFAULT_BATCH_SIZE, int(state.get("last_successful_batch_size", 0))
    )
    resumed["updated_at"] = datetime.now(timezone.utc).isoformat()
    return resumed
