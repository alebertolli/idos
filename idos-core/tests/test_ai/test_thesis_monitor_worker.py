from pathlib import Path
from unittest.mock import MagicMock

from idos.workers.ai.research_worker import ResearchWorker
from idos.workers.ai.thesis_monitor_worker import ThesisMonitorWorker


def test_thesis_review_is_delegated_to_research_worker():
    research = MagicMock()
    expected = {"thesis_active": False, "reason": "evidencia contradictoria"}
    research.reassess_thesis.return_value = expected
    sqlite = MagicMock()
    journal = MagicMock()
    base_path = Path("/tmp/idos")

    worker = ThesisMonitorWorker({"research_worker": research})
    result = worker.evaluate("AAPL", "OPP-1", sqlite, journal, base_path, "monthly")

    assert result == expected
    research.reassess_thesis.assert_called_once_with(
        "AAPL", "OPP-1", sqlite, journal, base_path, "monthly",
    )


def test_research_worker_owns_thesis_review_prompt():
    worker = ResearchWorker({"llm_service": MagicMock()})
    worker._load_thesis_review_financial_data = MagicMock(return_value={"revenue_growth_pct": 8.0})
    worker._load_financial_data = MagicMock(side_effect=AssertionError("no live provider fetch"))
    worker._run_prompt = MagicMock(return_value={"thesis_active": True})
    sqlite = MagicMock()
    sqlite.get_opportunity.return_value = {"conviction": {"overall": 72}}
    journal = MagicMock()
    journal.opportunity_path.return_value = Path("missing-opportunity")
    journal.load_case_file.return_value = None

    result = worker.reassess_thesis(
        "AAPL", "OPP-1", sqlite, journal, Path("."), "monthly",
    )

    assert result == {"thesis_active": True}
    prompt_name, ticker, inputs = worker._run_prompt.call_args.args
    assert (prompt_name, ticker) == ("thesis_monitor", "AAPL")
    assert inputs["financial_summary"] == "revenue_growth_pct=8.0"
    assert inputs["conviction"] == 72
    assert inputs["trigger_source"] == "monthly"
