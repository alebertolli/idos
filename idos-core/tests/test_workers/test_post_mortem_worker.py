from pathlib import Path
from unittest.mock import MagicMock

import pytest

from idos.models.enums import OpportunityStatus
from idos.workers.learning.post_mortem_worker import PostMortemWorker


class TestPostMortemWorker:
    def test_post_mortem_generates(
        self,
        seeded_opportunity_exited: tuple[str, str],
        mock_llm_client: MagicMock,
        base_path: str,
    ):
        ticker, opp_id = seeded_opportunity_exited
        worker = PostMortemWorker({"provider": "test"})
        worker.llm = mock_llm_client

        result = worker.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "exit_reason": "thesis_broken",
            "base_path": base_path,
        })

        assert result.status == "success"
        output = result.output
        assert output["status"] == "completed"
        assert output["pm_id"] is not None
        assert output["exit_reason"] == "thesis_broken"

    def test_post_mortem_archives(
        self,
        seeded_opportunity_exited: tuple[str, str],
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_sqlite,
    ):
        ticker, opp_id = seeded_opportunity_exited
        worker = PostMortemWorker({"provider": "test"})
        worker.llm = mock_llm_client

        worker.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "exit_reason": "thesis_broken",
            "base_path": base_path,
        })

        opp = tmp_sqlite.get_opportunity(opp_id)
        assert opp["status"] == OpportunityStatus.ARCHIVED.value

    def test_post_mortem_persists(
        self,
        seeded_opportunity_exited: tuple[str, str],
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_journal,
    ):
        ticker, opp_id = seeded_opportunity_exited
        worker = PostMortemWorker({"provider": "test"})
        worker.llm = mock_llm_client

        worker.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "exit_reason": "thesis_broken",
            "base_path": base_path,
        })

        pm_dir = tmp_journal.opportunity_path(ticker, opp_id) / "post_mortem"
        assert pm_dir.exists()
        yml_files = list(pm_dir.glob("*.yml"))
        assert len(yml_files) >= 1

    def test_post_mortem_skips_wrong_state(
        self,
        tmp_sqlite,
        mock_llm_client: MagicMock,
        base_path: str,
    ):
        ticker = "TEST"
        opp_id = "OPP-SKIP"
        opp = {
            "id": opp_id,
            "ticker": ticker,
            "status": OpportunityStatus.APPROVED.value,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        tmp_sqlite.save_opportunity(opp)

        worker = PostMortemWorker({"provider": "test"})
        worker.llm = mock_llm_client

        result = worker.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "exit_reason": "thesis_broken",
            "base_path": base_path,
        })

        assert result.status == "success"
        assert result.output["status"] == "skipped"
