"""Fail fast when a manually dispatched workflow has no bounded ticker scope."""

import os
from pathlib import Path

from idos.discovery.operability import OperabilityFilter


def requires_manual_selection(event_name: str, trigger_type: str) -> bool:
    """Apply the ticker selector only to direct manual runs, not monthly orchestration."""
    return event_name == "workflow_dispatch" and trigger_type.strip().lower() != "monthly"


def main() -> int:
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    trigger_type = os.environ.get("IDOS_TRIGGER_TYPE", "manual")
    if not requires_manual_selection(event_name, trigger_type):
        if event_name == "workflow_dispatch" and trigger_type.strip().lower() == "monthly":
            print("[SCOPE] Monthly orchestration uses the deterministic DDD selector.")
        return 0

    root = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    os.chdir(root)
    try:
        limit = int(os.environ.get("IDOS_MANUAL_SELECTION_LIMIT", "5"))
        selected = OperabilityFilter(
            "idos-config/universe/operable.yml"
        ).validate_manual_selection(
            os.environ.get("IDOS_CANDIDATE_TICKERS", ""),
            limit=limit,
        )
    except (OSError, ValueError) as exc:
        print(f"::error::Invalid manual candidate scope: {exc}")
        return 1

    print(f"[SCOPE] Manual run bounded to {len(selected)} operable ticker(s): {', '.join(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
