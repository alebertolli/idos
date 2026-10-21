import json
import os
import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock


def test_monthly_script_skips_only_portfolio_and_records_reassessment(tmp_path, monkeypatch):
    workspace = tmp_path
    (workspace / "cache").mkdir()
    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
    monkeypatch.setenv("TICKER", "ASML")
    monkeypatch.setenv("SKIP_PORTFOLIO_REVIEW", "true")

    worker = MagicMock()
    worker.execute.return_value = SimpleNamespace(output={
        "total_active": 1,
        "thesis_reassessed": 1,
        "thesis_changed": 0,
        "conviction_recalibrated": 1,
        "portfolio_reviewed": 0,
        "portfolio_review_status": "skipped_for_run",
        "proposals": [],
        "exits_triggered": [],
    })
    worker_module = ModuleType("idos.workers.ai.monthly_reassessment_worker")
    worker_module.MonthlyReassessmentWorker = MagicMock(return_value=worker)
    service_module = ModuleType("idos.ai.service")
    service_module.LLMService = MagicMock()
    monkeypatch.setitem(sys.modules, "idos.workers.ai.monthly_reassessment_worker", worker_module)
    monkeypatch.setitem(sys.modules, "idos.ai.service", service_module)

    script = Path(__file__).parents[2] / "scripts" / "ddd_monthly.py"
    main = runpy.run_path(str(script), run_name="ddd_monthly_under_test")["main"]
    previous_cwd = Path.cwd()
    try:
        main()
    finally:
        os.chdir(previous_cwd)

    worker.execute.assert_called_once_with({
        "base_path": str(workspace),
        "tickers": ["ASML"],
        "skip_portfolio_review": True,
    })
    output = json.loads((workspace / "cache" / "monthly_reassessment.json").read_text(encoding="utf-8"))
    assert output["thesis_reassessed"] == 1
    assert output["conviction_recalibrated"] == 1
    assert output["portfolio_review_status"] == "skipped_for_run"
