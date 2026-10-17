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


@pytest.mark.parametrize(
    ("status", "expected_errors", "expected_skipped"),
    [
        ("completed", 0, 0),
        ("skipped", 0, 1),
        ("ddd_failed", 1, 0),
        ("unknown", 1, 0),
    ],
)
def test_worker_status_is_classified_before_downstream_assessment(
    status, expected_errors, expected_skipped
):
    processed, errors, skipped = [], [], []
    opportunity = {"opp_id": "OPP-1", "ticker": "VIST", "reason": "new candidate"}

    SCRIPT["_record_worker_result"](
        opportunity,
        {"status": status, "error": "invalid response"},
        processed,
        errors,
        skipped,
    )

    assert processed[0]["status"] == status
    assert len(errors) == expected_errors
    assert len(skipped) == expected_skipped
    if expected_errors:
        assert errors[0]["error"] == "invalid response"
