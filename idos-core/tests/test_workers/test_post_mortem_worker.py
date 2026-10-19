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
        worker = PostMortemWorker({"llm_service": mock_llm_client})

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
        mock_llm_client.generate_structured.assert_not_called()
        report = list_reports(Path(base_path))[0]
        assert report["analysis"]["analysis_version"] == "deterministic_post_mortem_v1"
        assert report["recommendations"] == []

    def test_post_mortem_requires_human_approval(
        self,
        seeded_opportunity_exited: tuple[str, str],
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_sqlite,
        monkeypatch,
    ):
        ticker, opp_id = seeded_opportunity_exited
        worker = PostMortemWorker({"llm_service": mock_llm_client})

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
        assert report["recommendations"] == []
        assert "SINGLE_CASE_REPORT_ONLY" == report["analysis"]["strategy_recommendations_status"]
        monkeypatch.chdir(base_path)
        runner = CliRunner()
        listed = runner.invoke(app, ["learning-list"])
        assert listed.exit_code == 0
        assert report["id"] in listed.stdout
        shown = runner.invoke(app, ["learning-show", report["id"]])
        assert shown.exit_code == 0
        assert "No hay propuestas de cambio de estrategia" in shown.stdout
        approved = runner.invoke(app, ["learning-approve", report["id"], "family-manager"])
        assert approved.exit_code == 0
        assert tmp_sqlite.get_opportunity(opp_id)["status"] == OpportunityStatus.ARCHIVED.value
        assert list_reports(Path(base_path))[0]["review_status"] == "APPROVED"
        assert list_reports(Path(base_path))[0]["recommendations"] == []
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
        worker = PostMortemWorker({"llm_service": mock_llm_client})

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
        mock_llm_client.generate_structured.assert_not_called()

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

        worker = PostMortemWorker({"llm_service": mock_llm_client})

        result = worker.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "exit_reason": "thesis_broken",
            "base_path": base_path,
        })

        assert result.status == "success"
        assert result.output["status"] == "completed"

        report = list_reports(Path(base_path))[0]
        entry = report["analysis"]["evidence"]["entry"]
        assert entry["thesis"] == "THESIS-DE-ENTRADA-UNICA"
        assert entry["entry_price"] == 95.0
        assert entry["catalysts_count"] == 1
        assert entry["risks_count"] == 1
        assert entry["wyckoff_phase"] == "accumulation"
        assert entry["wyckoff_score"] == 74
        mock_llm_client.generate_structured.assert_not_called()

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

        worker = PostMortemWorker({"llm_service": mock_llm_client})

        result = worker.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "exit_reason": "thesis_broken",
            "base_path": base_path,
        })

        assert result.status == "success"
        assert result.output["status"] == "skipped"
        mock_llm_client.generate_structured.assert_not_called()

    def test_post_mortem_reports_prediction_evidence_without_strategy_recommendations(
        self,
        seeded_opportunity_exited: tuple[str, str],
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_journal,
    ):
        ticker, opp_id = seeded_opportunity_exited
        tmp_journal.save_hypothesis(ticker, opp_id, {
            "id": "H-PREDICTIONS",
            "status": "INVALIDATED",
            "predictions": [
                {"metric": "revenue_growth", "expected": ">10%", "actual": "4%", "met": False},
                {"metric": "gross_margin", "expected": ">40%", "actual": "44%", "met": True},
                {"metric": "debt", "expected": "stable", "actual": None, "met": None},
            ],
            "falsification": [{"condition": "moat erosion", "triggered": True}],
        })
        worker = PostMortemWorker({"llm_service": mock_llm_client})
        result = worker.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "exit_reason": "thesis_broken",
            "base_path": base_path,
        })

        report = list_reports(Path(base_path))[0]
        analysis = report["analysis"]
        assert result.output["hypotheses"]["predictions_evaluated"] == 2
        assert analysis["hypothesis_evaluation"]["predictions_met"] == 1
        assert len(analysis["what_went_right"]) == 1
        assert len(analysis["what_went_wrong"]) == 1
        assert analysis["hypothesis_evaluation"]["was_falsification_applied"] is True
        assert analysis["thesis_was_correct"] is None
        assert analysis["biases_assessment"] == "NOT_ASSESSED"
        assert analysis["portfolio_metrics"]["financial_pnl_usd"]["status"] == "NOT_ASSESSED"
        assert analysis["portfolio_metrics"]["purchasing_power_impact_ars"]["status"] == "NOT_ASSESSED"
        assert report["recommendations"] == []
        mock_llm_client.generate_structured.assert_not_called()
