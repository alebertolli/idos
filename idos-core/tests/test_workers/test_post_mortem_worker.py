from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from idos.cli.main import app
from idos.models.enums import OpportunityStatus
from idos.learning.review import approve_report, list_reports
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

    def test_post_mortem_requires_human_approval(
        self,
        seeded_opportunity_exited: tuple[str, str],
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_sqlite,
        monkeypatch,
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

        opp = tmp_sqlite.get_opportunity(opp_id)
        assert opp["status"] == OpportunityStatus.POST_MORTEM.value
        assert result.output["archived"] is False
        report = list_reports(Path(base_path))[0]
        assert report["strategy_id"] == "COMPOUNDER"
        assert report["review_status"] == "PENDING_REVIEW"
        assert report["recommendations"][0]["status"] == "PROPOSED"
        monkeypatch.chdir(base_path)
        runner = CliRunner()
        listed = runner.invoke(app, ["learning-list"])
        assert listed.exit_code == 0
        assert report["id"] in listed.stdout
        shown = runner.invoke(app, ["learning-show", report["id"]])
        assert shown.exit_code == 0
        assert "PROPOSED" in shown.stdout
        approved = runner.invoke(app, ["learning-approve", report["id"], "family-manager"])
        assert approved.exit_code == 0
        assert tmp_sqlite.get_opportunity(opp_id)["status"] == OpportunityStatus.ARCHIVED.value
        assert list_reports(Path(base_path))[0]["review_status"] == "APPROVED"
        assert list_reports(Path(base_path))[0]["recommendations"][0]["status"] == "PROPOSED"
        approve_report(Path(base_path), report["id"], "family-manager")
        transitions = list(tmp_sqlite.conn.execute(
            "SELECT id FROM state_transitions WHERE opportunity_id = ? AND to_status = 'ARCHIVED'",
            (opp_id,),
        ))
        assert len(transitions) == 1

    def test_private_review_rejects_invalid_id(self, base_path: str):
        with pytest.raises(ValueError, match="Invalid post-mortem ID"):
            approve_report(Path(base_path), "../public.yml", "family-manager")

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

        pm_dir = Path(base_path) / "private-data" / "learning" / "post_mortems"
        assert pm_dir.exists()
        yml_files = list(pm_dir.glob("*.yml"))
        assert len(yml_files) == 1
        assert not (tmp_journal.opportunity_path(ticker, opp_id) / "post_mortem").exists()

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
