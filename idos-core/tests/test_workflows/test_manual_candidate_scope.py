from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.validate_manual_candidate_scope import main, requires_manual_selection


@pytest.mark.parametrize(
    ("event_name", "trigger_type", "expected"),
    [
        ("workflow_dispatch", "manual", True),
        ("workflow_dispatch", "monthly", False),
        ("workflow_dispatch", "", True),
        ("schedule", "monthly", False),
        ("repository_dispatch", "quarterly_results", False),
    ],
)
def test_manual_scope_is_required_only_for_direct_manual_invocations(
    event_name: str, trigger_type: str, expected: bool
):
    assert requires_manual_selection(event_name, trigger_type) is expected


def test_monthly_reusable_invocation_does_not_require_manual_tickers(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("IDOS_TRIGGER_TYPE", "monthly")
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    monkeypatch.delenv("IDOS_CANDIDATE_TICKERS", raising=False)

    assert main() == 0
    assert "Monthly orchestration" in capsys.readouterr().out


def test_direct_manual_invocation_still_requires_an_operable_ticker(tmp_path, monkeypatch, capsys):
    config = tmp_path / "idos-config" / "universe" / "operable.yml"
    config.parent.mkdir(parents=True)
    config.write_text("operable_tickers: []\n", encoding="utf-8")

    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("IDOS_TRIGGER_TYPE", "manual")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("IDOS_CANDIDATE_TICKERS", raising=False)

    assert main() == 1
    assert "at least one ticker" in capsys.readouterr().out
