from pathlib import Path
from unittest.mock import MagicMock

import pytest

from idos.models.enums import OpportunityStatus
from idos.portfolio.entry_snapshot import save_entry_snapshot
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

    def test_post_mortem_injects_entry_snapshot(
        self,
        seeded_opportunity_exited: tuple[str, str],
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_journal,
    ):
        ticker, opp_id = seeded_opportunity_exited

        snapshot = {
            "ticker": ticker,
            "opp_id": opp_id,
            "entry": {
                "entry_price": 95.0,
                "entry_date": "2026-01-02T10:30:00-03:00",
                "stop_loss": 80.0,
                "target_price": 130.0,
            },
            "thesis": {
                "tesis_inversion": "THESIS-DE-ENTRADA-UNICA",
                "opinion_valoracion": "infravalorado",
                "score_general": 82,
            },
            "catalysts": [{"descripcion": "Catalizador de prueba", "impacto": "alto"}],
            "risks": [{"riesgo": "Riesgo de prueba"}],
            "dominios": {"dominio_business_quality": {"rating": "excepcional"}},
            "technical": {
                "wyckoff_phase": "accumulation",
                "wyckoff_score": 74,
                "wyckoff_confidence": "alta",
                "wyckoff_entry_point": "lps",
                "wyckoff_price_target": 120.0,
                "llm_response": {"pruebas_compra": {"pruebas_pasan": 8, "total_pruebas": 9}},
            },
        }
        save_entry_snapshot(tmp_journal, ticker, opp_id, snapshot)

        worker = PostMortemWorker({"provider": "test"})
        worker.llm = mock_llm_client

        result = worker.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "exit_reason": "thesis_broken",
            "base_path": base_path,
        })

        assert result.status == "success"
        assert result.output["status"] == "completed"

        prompt = mock_llm_client.generate_structured.call_args.kwargs["prompt"]
        assert "THESIS-DE-ENTRADA-UNICA" in prompt
        assert "TESIS AL MOMENTO DE ENTRADA (snapshot)" in prompt
        assert "Catalizador de prueba" in prompt
        assert "Riesgo de prueba" in prompt
        assert "accumulation" in prompt
        assert "74" in prompt
        assert "8/9" in prompt

    def test_post_mortem_skips_wrong_state(        self,
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
