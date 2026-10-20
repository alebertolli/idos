import os
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "validate_production_dispatch.py"
REPOSITORY_ROOT = SCRIPT.parent.parent


@pytest.mark.parametrize(
    ("event_name", "ref_name", "allowed", "expected_code"),
    [
        ("schedule", "main", "false", 0),
        ("workflow_dispatch", "main", "false", 1),
        ("workflow_dispatch", "main", "true", 0),
        ("workflow_dispatch", "codex/e2e", "false", 0),
    ],
)
def test_production_dispatch_requires_explicit_opt_in(
    event_name: str, ref_name: str, allowed: str, expected_code: int
):
    env = os.environ.copy()
    env.update(
        {
            "GITHUB_EVENT_NAME": event_name,
            "GITHUB_REF_NAME": ref_name,
            "IDOS_ALLOW_PRODUCTION_E2E": allowed,
        }
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPOSITORY_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == expected_code
    if expected_code:
        assert "allow_production_e2e=true" in result.stderr
