from pathlib import Path
from unittest.mock import MagicMock

import pytest

from idos.models.enums import OpportunityStatus
from idos.workers.ai.research_worker import ResearchWorker


class TestResearchWorker:
    def test_research_completes(
        self,
        seeded_opportunity: tuple[str, str],
        tmp_sqlite,
        tmp_journal,
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_path: Path,
    ):
        ticker, opp_id = seeded_opportunity
        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})
        worker.llm = mock_llm_client
        worker.registry = MagicMock()
        worker.registry.get.return_value = "prompt template {ticker} {sector} ..."
        worker.registry.get_system.return_value = "system prompt"

        result = worker.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "base_path": base_path,
        })

        assert result.status == "success"
        output = result.output
        assert output["status"] == "completed"
        assert output["score"] > 0
        assert output["hypotheses_count"] >= 1
        assert output["classification"] == "compounder_castigado"
        assert output["market_error_conclusion"] == "SI"

    def test_research_transition(
        self,
        seeded_opportunity: tuple[str, str],
        tmp_sqlite,
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_path: Path,
    ):
        ticker, opp_id = seeded_opportunity
        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})
        worker.llm = mock_llm_client
        worker.registry = MagicMock()
        worker.registry.get.return_value = "template {ticker}"
        worker.registry.get_system.return_value = "system"

        worker.execute({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})

        opp = tmp_sqlite.get_opportunity(opp_id)
        assert opp is not None
        assert opp["status"] == OpportunityStatus.UNDER_DEEP_DD.value

    def test_research_saves_assessment(
        self,
        seeded_opportunity: tuple[str, str],
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_journal,
        tmp_path: Path,
    ):
        ticker, opp_id = seeded_opportunity
        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})
        worker.llm = mock_llm_client
        worker.registry = MagicMock()
        worker.registry.get.return_value = "template {ticker}"
        worker.registry.get_system.return_value = "system"

        worker.execute({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})

        ass_path = tmp_journal.opportunity_path(ticker, opp_id) / "assessments"
        assert ass_path.exists()
        yml_files = list(ass_path.glob("*.yml"))
        assert len(yml_files) >= 1

    def test_research_rejects_invalid_state(
        self,
        tmp_sqlite,
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_path: Path,
    ):
        ticker = "TEST"
        opp_id = "OPP-INVALID"
        opp = {
            "id": opp_id,
            "ticker": ticker,
            "status": OpportunityStatus.APPROVED.value,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        tmp_sqlite.save_opportunity(opp)

        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})
        worker.llm = mock_llm_client
        worker.registry = MagicMock()

        result = worker.execute({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})

        assert result.status == "success"
        assert result.output["status"] == "skipped"

    def test_research_requires_ticker_and_opp(
        self,
        base_path: str,
        tmp_path: Path,
    ):
        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})

        with pytest.raises(ValueError, match="Both ticker and opp_id"):
            worker.execute({"ticker": "", "opp_id": "", "base_path": base_path})
