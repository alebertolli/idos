#!/usr/bin/env python3
"""Dispatch the next bounded Research batch after results are persisted."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from idos.research.hourly_ramp import exclude_quarantined, has_due_work, load_state


def dispatch_if_due(
    state: dict[str, Any],
    pending: list[dict[str, Any]],
    *,
    repository: str,
    now: datetime | None = None,
    quarantined: list[dict[str, Any]] | None = None,
    run: Callable[..., Any] = subprocess.run,
) -> bool:
    """Dispatch one next batch only when the durable queue is due and unpaused."""
    eligible = exclude_quarantined(pending, quarantined or [])
    parked = len(pending) - len(eligible)
    if parked:
        print(f"[DDD] Ignoring {parked} quarantined candidate(s) in the continuation queue")
    if not has_due_work(state, eligible, now=now):
        print("[DDD] No due non-quarantined queue work; leaving continuation to the next scheduled run")
        return False
    command = [
        "gh", "workflow", "run", "ddd-pipeline.yml",
        "--repo", repository,
        "--ref", "main",
        "-f", "allow_production_e2e=true",
        "-f", "continue_hourly_ramp=true",
        "-f", "skip_portfolio_reevaluation=true",
    ]
    run(command, check=True)
    print("[DDD] Dispatched the next bounded hourly-ramp batch")
    return True


def _load_pending(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        pending = value.get("pending", []) if value.get("schema_version") == 1 else []
        return [item for item in pending if isinstance(item, dict)]
    except (OSError, ValueError, AttributeError, TypeError):
        return []

 
def _load_quarantine(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        items = value.get("items", []) if value.get("schema_version") == 1 else []
        return [item for item in items if isinstance(item, dict)]
    except (OSError, ValueError, AttributeError, TypeError):
        return []


def main() -> int:
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repository:
        raise RuntimeError("GITHUB_REPOSITORY is required to continue DDD Research")
    state = load_state(Path("cache/ddd_research_capacity.json"))
    pending = _load_pending(Path("cache/ddd_research_resume.json"))
    quarantined = _load_quarantine(Path("cache/ddd_research_quarantine.json"))
    dispatch_if_due(state, pending, repository=repository, quarantined=quarantined)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
