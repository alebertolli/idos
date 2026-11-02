#!/usr/bin/env python3
"""Resume the persistent DDD results branch on current main safely.

The results branch carries resumable data across runs. The append-only SDD audit
log is owned by main, so a conflict in that single file is resolved in favor of
main. Any conflict in persisted results or other files remains a hard failure.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath


RESULTS_BRANCH = "codex/ddd-research-results"
MAIN_REF = "refs/remotes/origin/main"
AUDIT_LOG = PurePosixPath("SDD/25.PLAN-E2E-EN-RAMA-DE-PRUEBA.md")


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if check and result.returncode:
        details = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {details}")
    return result


def _sync_results_branch() -> None:
    _git("fetch", "origin", f"refs/heads/main:{MAIN_REF}")

    branch_ref = f"refs/heads/{RESULTS_BRANCH}"
    remote_branch_ref = f"refs/remotes/origin/{RESULTS_BRANCH}"
    branch_exists = _git("ls-remote", "--exit-code", "--heads", "origin", branch_ref, check=False)
    if branch_exists.returncode == 0:
        _git("fetch", "origin", f"{branch_ref}:{remote_branch_ref}")
        _git("switch", "-C", RESULTS_BRANCH, remote_branch_ref)
    else:
        _git("switch", "-C", RESULTS_BRANCH, MAIN_REF)

    merge = _git(
        "-c",
        "user.name=idos-bot",
        "-c",
        "user.email=bot@idos.local",
        "merge",
        "--no-edit",
        MAIN_REF,
        check=False,
    )
    if merge.returncode == 0:
        print(f"[DDD-SYNC] Results branch is synchronized with {MAIN_REF}")
        return

    conflicts = _git("diff", "--name-only", "--diff-filter=U").stdout.splitlines()
    expected_conflicts = {AUDIT_LOG.as_posix()}
    if set(conflicts) != expected_conflicts:
        _git("merge", "--abort", check=False)
        raise RuntimeError(
            "Refusing to resolve unexpected results-branch merge conflicts: "
            + (", ".join(conflicts) if conflicts else "merge failed without a file conflict")
        )

    # The current merge direction is results branch <- main. Keep main's canonical
    # audit log; the results branch persists state and generated reports, not SDD.
    _git("checkout", "--theirs", "--", AUDIT_LOG.as_posix())
    _git("add", "--", AUDIT_LOG.as_posix())
    commit = _git(
        "-c",
        "user.name=idos-bot",
        "-c",
        "user.email=bot@idos.local",
        "commit",
        "--no-edit",
        check=False,
    )
    if commit.returncode:
        _git("merge", "--abort", check=False)
        details = commit.stderr.strip() or commit.stdout.strip()
        raise RuntimeError(f"Could not finish the documented audit-log resolution: {details}")

    print(f"[DDD-SYNC] Resolved {AUDIT_LOG.as_posix()} using canonical main content")


if __name__ == "__main__":
    try:
        _sync_results_branch()
    except RuntimeError as exc:
        print(f"[DDD-SYNC] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

