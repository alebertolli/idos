"""Require an explicit opt-in for manually dispatched production workflows."""

from __future__ import annotations

import os
import sys


def production_dispatch_error(event_name: str, ref_name: str, allow_production_e2e: str) -> str | None:
    """Return a validation message when a manual run targets main without opt-in."""
    is_manual_production = event_name == "workflow_dispatch" and ref_name == "main"
    explicitly_allowed = allow_production_e2e.strip().lower() == "true"
    if is_manual_production and not explicitly_allowed:
        return (
            "Manual execution on main requires allow_production_e2e=true; "
            "keep candidate scope bounded and portfolio runtime disabled."
        )
    return None


def main() -> int:
    error = production_dispatch_error(
        os.environ.get("GITHUB_EVENT_NAME", ""),
        os.environ.get("GITHUB_REF_NAME", ""),
        os.environ.get("IDOS_ALLOW_PRODUCTION_E2E", "false"),
    )
    if error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    print("[WORKFLOW-SCOPE] dispatch allowed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
