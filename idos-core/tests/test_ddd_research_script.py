import json
import runpy
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = runpy.run_path(str(REPO_ROOT / "scripts" / "ddd_research.py"))


def test_research_failure_is_persisted_before_nonzero_exit(tmp_path):
    results_path = tmp_path / "cache" / "ddd_results.json"
    results = {
        "processed": [{"ticker": "VIST", "opp_id": "OPP-1", "status": "ddd_failed"}],
        "errors": [{"ticker": "VIST", "opp_id": "OPP-1", "error": "invalid JSON"}],
        "status": "failed",
    }

    with pytest.raises(SystemExit) as exc_info:
        SCRIPT["_persist_results_or_fail"](results, results_path)

    assert exc_info.value.code == 1
    assert json.loads(results_path.read_text(encoding="utf-8")) == results


def test_successful_research_results_are_persisted_without_error(tmp_path):
    results_path = tmp_path / "cache" / "ddd_results.json"
    results = {"processed": [{"status": "completed"}], "errors": []}

    SCRIPT["_persist_results_or_fail"](results, results_path)

    assert json.loads(results_path.read_text(encoding="utf-8")) == results
