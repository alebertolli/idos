"""Fail fast when a manually dispatched workflow has no bounded ticker scope."""

import os
from pathlib import Path

from idos.discovery.operability import OperabilityFilter


def main() -> int:
    if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
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
