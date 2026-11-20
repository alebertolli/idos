from pathlib import Path
from unittest.mock import MagicMock

import yaml

from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.models.enums import OpportunityStatus
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


def test_invalidated_thesis_revokes_buylist_without_touching_positions(tmp_path: Path):
    db = SQLiteStore(tmp_path / "idos.db")
    journal = JournalRepository(tmp_path / "idos-journal")
    opportunity = {
        "id": "OPP-NVDA", "ticker": "NVDA",
        "status": OpportunityStatus.UNDER_DEEP_DD.value,
        "approved_for_buylist": True, "thesis_active": True,
    }
    db.save_opportunity(opportunity)
    journal.save_opportunity("NVDA", opportunity)
    opp_dir = journal.opportunity_path("NVDA", "OPP-NVDA")
    (opp_dir / "decision_proposal.yml").write_text(yaml.safe_dump({"status": "AUTO_APPROVED"}), encoding="utf-8")
    (opp_dir / "board_resolution.yml").write_text(yaml.safe_dump({
        "approved": True, "status": "AUTO_APPROVED", "author": "idos:auto-authorization",
    }), encoding="utf-8")
    buylist_path = journal.base / "portfolio" / "buylist.yml"
    buylist_path.parent.mkdir(parents=True, exist_ok=True)
    buylist_path.write_text(yaml.safe_dump({"entries": [
        {"ticker": "NVDA", "opp_id": "OPP-NVDA"},
        {"ticker": "MSFT", "opp_id": "OPP-MSFT"},
    ]}), encoding="utf-8")
    position_path = journal.base / "portfolio" / "positions" / "NVDA.yml"
    position_path.parent.mkdir(parents=True, exist_ok=True)
    position_path.write_text("ticker: NVDA\nshares: 1\n", encoding="utf-8")
    research = MagicMock()
    research.reassess_thesis.return_value = {
        "thesis_active": False, "reason": "La hipótesis quedó falsada.", "confidence": 0.95,
    }

    result = ThesisMonitorWorker({"research_worker": research}).run({
        "ticker": "NVDA", "opp_id": "OPP-NVDA", "base_path": str(tmp_path),
        "trigger_source": "monthly",
    })

    assert result["thesis_active"] is False
    assert result["buylist_removed"] is True
    assert yaml.safe_load(buylist_path.read_text(encoding="utf-8"))["entries"] == [
        {"ticker": "MSFT", "opp_id": "OPP-MSFT"},
    ]
    assert position_path.exists()
    assert journal.load_opportunity("NVDA", "OPP-NVDA")["approved_for_buylist"] is False
