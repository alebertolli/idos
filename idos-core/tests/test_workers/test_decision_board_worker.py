from pathlib import Path
from unittest.mock import MagicMock

import pytest

from idos.models.enums import OpportunityStatus
from idos.workers.ai.decision_board_worker import DecisionBoardWorker


class TestDecisionBoardWorker:
    def test_approves_good_opportunity(
        self,
        seeded_opportunity_under_dd: tuple[str, str],
        mock_llm_client: MagicMock,
        base_path: str,
    ):
        ticker, opp_id = seeded_opportunity_under_dd
        worker = DecisionBoardWorker({"provider": "test"})
        worker.llm = mock_llm_client

        result = worker.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "base_path": base_path,
        })

        assert result.status == "success"
        output = result.output
        assert output["decision"] == "APPROVED"
        assert output["all_rules_pass"] is True
        assert output["rules_evaluated"] >= 3

    def test_rejects_poor_opportunity(
        self,
        mock_llm_reject_client: MagicMock,
        base_path: str,
        tmp_sqlite,
        tmp_journal,
    ):
        ticker = "POOR"
        opp_id = "OPP-2026-POOR-001"
        opp = {
            "id": opp_id,
            "ticker": ticker,
            "status": OpportunityStatus.UNDER_DEEP_DD.value,
            "conviction": {"overall": 40, "business": 35},
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        tmp_sqlite.save_opportunity(opp)
        tmp_journal.save_opportunity(ticker, opp)
        ass = {"id": "ass-poor", "engine": "ResearchWorker", "score": 35,
               "confidence": "LOW", "findings": ["Low quality"],
               "status": "COMPLETED", "generated_at": "2026-01-01T00:00:00"}
        tmp_journal.save_assessment(ticker, opp_id, ass)

        worker = DecisionBoardWorker({"provider": "test"})
        worker.llm = mock_llm_reject_client

        result = worker.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "base_path": base_path,
        })

        assert result.status == "success"
        output = result.output
        assert output["decision"] == "WATCHLIST"

    def test_saves_decision_record(
        self,
        seeded_opportunity_under_dd: tuple[str, str],
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_journal,
    ):
        ticker, opp_id = seeded_opportunity_under_dd
        worker = DecisionBoardWorker({"provider": "test"})
        worker.llm = mock_llm_client

        worker.execute({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})

        dec_path = tmp_journal.opportunity_path(ticker, opp_id) / "decisions"
        assert dec_path.exists()
        yml_files = list(dec_path.glob("*.yml"))
        assert len(yml_files) >= 1

    def test_skips_invalid_state(
        self,
        tmp_sqlite,
        mock_llm_client: MagicMock,
        base_path: str,
    ):
        ticker = "TEST"
        opp_id = "OPP-INVALID"
        opp = {
            "id": opp_id,
            "ticker": ticker,
            "status": OpportunityStatus.WATCHLIST.value,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        tmp_sqlite.save_opportunity(opp)

        worker = DecisionBoardWorker({"provider": "test"})
        worker.llm = mock_llm_client

        result = worker.execute({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})

        assert result.status == "success"
        assert result.output["status"] == "skipped"
