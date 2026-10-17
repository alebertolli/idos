from pathlib import Path
from unittest.mock import MagicMock

import pytest

from idos.models.enums import OpportunityStatus
from idos.workers.ai.research_worker import ResearchWorker
from idos.workers.base import WorkerStatus
from idos.knowledge.wiki import AtomicWiki
from idos.research.wiki import WikiBuilder


@pytest.fixture
def seeded_opportunity(tmp_sqlite, tmp_journal):
    """Research starts after Discovery qualifies an opportunity."""
    ticker, opp_id = "TEST", "OPP-2026-TEST-001"
    opp = {
        "id": opp_id, "ticker": ticker,
        "status": OpportunityStatus.SCREENED.value,
        "conviction": {"overall": 70},
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }
    tmp_sqlite.save_opportunity(opp)
    tmp_journal.save_opportunity(ticker, opp)
    return ticker, opp_id


def _mock_research_registry() -> MagicMock:
    registry = MagicMock()

    def get_side_effect(prompt_name: str, category: str = "research"):
        if prompt_name == "wiki":
            return None
        if prompt_name == "multibaggers":
            return "MULTIBAGGERS {ticker} ({name}); Intake: {intake_package}; resumen: {financial_summary}"
        if prompt_name == "ddd":
            return "FASE 0 - clasificacion oportunidad for {ticker} ({name})"
        if prompt_name == "hypothesis":
            return "Genera hipotesis de inversion para {ticker}"
        if prompt_name == "aoif":
            return "AOIF 8-step protocol for {ticker} ({name})"
        return "template {ticker}"

    registry.get.side_effect = get_side_effect
    registry.get_system.return_value = "system"
    return registry


class TestResearchWorker:
    def test_project_factory_uses_central_model_and_fallback_configuration(self):
        from pathlib import Path

        from idos.ai.service import LLMService

        project_root = Path(__file__).resolve().parents[3]
        worker = ResearchWorker.from_project_config(project_root)

        assert isinstance(worker.llm, LLMService)
        assert worker.llm.default_provider == "gemini"
        assert worker.llm.clients["gemini"].model == "gemini-3.8-flash"
        assert worker.llm._rank_providers("analysis")[0] == "gemini"

    def test_multibaggers_research_routes_by_persisted_profile_and_intake(
        self, tmp_sqlite, tmp_journal, mock_llm_client: MagicMock,
        base_path: str, tmp_path: Path, monkeypatch,
    ):
        import yaml
        ticker, opp_id = "TEST", "OPP-MB-TEST"
        opp = {
            "id": opp_id, "ticker": ticker, "status": OpportunityStatus.SCREENED.value,
            "strategy_id": "MULTIBAGGERS", "strategy_version": "1.0",
            "research_profile": "multibaggers", "entry_policy": "MANUAL_REVIEW",
            "conviction": {}, "created_at": "2026-10-15T12:00:00+00:00",
            "updated_at": "2026-10-15T12:00:00+00:00",
        }
        tmp_sqlite.save_opportunity(opp)
        tmp_journal.save_opportunity(ticker, opp)
        intake = {"ticker": ticker, "strategy_id": "MULTIBAGGERS", "strategy_version": "1.0",
                  "research_profile": "multibaggers", "snapshot_hash": "fixture-hash",
                  "constraints": ["PACKAGE_TOKEN"]}
        intake_path = tmp_journal.opportunity_path(ticker, opp_id) / "research_intake.yml"
        intake_path.write_text(yaml.safe_dump(intake), encoding="utf-8")
        snapshot_path = tmp_journal.opportunity_path(ticker, opp_id) / "discovery_snapshot.yml"
        snapshot_path.write_text(yaml.safe_dump({"ticker": ticker, "snapshot_hash": "fixture-hash"}), encoding="utf-8")
        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})
        worker.llm = mock_llm_client
        worker.registry = _mock_research_registry()
        monkeypatch.setattr(worker, "_load_financial_data", lambda *args: {})
        monkeypatch.setattr(worker, "_enrich_company_info", lambda ticker, company, knowledge: {"name": ticker, "sector": "Technology"})
        monkeypatch.setattr(worker, "_fetch_target_consensus", lambda *args: {})

        result = worker.run({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})

        assert result["status"] == "completed"
        first_prompt = mock_llm_client.generate_structured.call_args_list[0].kwargs["prompt"]
        assert "MULTIBAGGERS" in first_prompt
        assert "PACKAGE_TOKEN" in first_prompt
        assert tmp_sqlite.get_opportunity(opp_id)["status"] == OpportunityStatus.UNDER_RESEARCH.value

    def test_systematic_ddd_is_signal_specific(self):
        report = ResearchWorker._build_systematic_ddd(
            "XLE",
            {"strategy_id": "MOMENTUM_ETF", "signal": {"momentum": 1.8, "as_of_date": "2026-09-01"}},
            {"volatility_90d": 30},
        )
        assert report["clasificacion_oportunidad"]["categoria"] == "systematic_momentum"
        assert report["score_general"] == 67
        assert report["strategy_context"]["signal"]["momentum"] == 1.8
        assert report["calidad_evidencia"]["inferencias_llm"] == []

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
        worker.registry = _mock_research_registry()

        result = worker.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "base_path": base_path,
        })

        assert result.status == WorkerStatus.SUCCESS
        output = result.output
        assert output["status"] == "completed"
        assert output["score"] > 0
        assert output["hypotheses_count"] >= 1
        assert output["classification"] == "compounder_castigado"
        assert output["market_error_conclusion"] == "SI"

    def test_empty_ddd_fails_closed_without_advancing_lifecycle(
        self,
        seeded_opportunity: tuple[str, str],
        tmp_sqlite,
        tmp_journal,
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_path: Path,
        monkeypatch,
    ):
        ticker, opp_id = seeded_opportunity
        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})
        worker.llm = mock_llm_client
        worker.registry = _mock_research_registry()
        monkeypatch.setattr("idos.workers.ai.research_worker.time.sleep", lambda *_: None)
        monkeypatch.setattr(
            worker,
            "_run_prompt",
            lambda prompt_name, _ticker, _kwargs: {} if prompt_name == "ddd" else {"hipotesis": []},
        )

        result = worker.run({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})

        assert result["status"] == "ddd_failed"
        assert result["ddd_empty"] is True
        assert result["error"] == "DDD output empty or incomplete"
        assert tmp_sqlite.get_opportunity(opp_id)["status"] == OpportunityStatus.SCREENED.value
        assert not (tmp_journal.opportunity_path(ticker, opp_id) / "assessments").exists()

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
        worker.registry = _mock_research_registry()

        result = worker.execute({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})
        assert result.status == WorkerStatus.SUCCESS

        opp = tmp_sqlite.get_opportunity(opp_id)
        assert opp is not None
        assert opp["status"] == OpportunityStatus.UNDER_RESEARCH.value

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
        worker.registry = _mock_research_registry()

        result = worker.execute({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})
        assert result.status == WorkerStatus.SUCCESS

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
        worker.registry = _mock_research_registry()

        result = worker.execute({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})

        assert result.status == WorkerStatus.SUCCESS
        assert result.output["status"] == "skipped"

    def test_research_creates_wiki_with_all_sections(
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
        worker.registry = _mock_research_registry()

        result = worker.execute({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})
        assert result.status == WorkerStatus.SUCCESS

        bp = Path(base_path)
        atomic = AtomicWiki(bp / "idos-knowledge")
        sections = atomic.all_sections(ticker)

        section_names = {s.name for s in sections}
        print(f"[DEBUG] Secciones encontradas: {section_names}")

        expected = {"business", "products", "moat", "management", "competition",
                     "financial_highlights", "catalysts", "investment_thesis"}
        missing = expected - section_names
        extra = section_names - expected
        assert not missing, f"Faltan secciones wiki: {missing}"
        if extra:
            print(f"[TEST] Secciones extra: {extra}")

        md_path = bp / "idos-knowledge" / "companies" / ticker / "knowledge_base" / "static" / "wiki.md"
        assert md_path.exists(), "wiki.md no encontrado"
        content = md_path.read_text(encoding="utf-8")
        assert "## Business Model" in content
        assert "## Products & Services" in content
        assert "## Competitive Moat" in content
        assert "## Investment Thesis" in content
        assert "## Financial Highlights" in content
        assert "## Catalysts" in content

    def test_research_creates_claims_and_lifecycle(
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
        worker.registry = _mock_research_registry()

        result = worker.execute({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})
        assert result.status == WorkerStatus.SUCCESS

        bp = Path(base_path)
        claim_store = type("obj", (object,), {"_claims_dir": bp / "idos-knowledge" / ".claims"})()
        claims_dir = bp / "idos-knowledge" / ".claims"
        assert claims_dir.exists(), ".claims directory no creado"
        claim_files = list(claims_dir.glob("CLAIM-TEST-DDD-*.json"))
        assert len(claim_files) >= 1, "No se crearon claims desde DDD"

        from idos.knowledge.claims import ClaimStore as CS
        store = CS(str(bp / "idos-knowledge"))
        claims = store.search(tag=ticker)
        assert len(claims) >= 1
        assert any("ROIC" in c.statement for c in claims), "Claim de ROIC no encontrado"

    def test_research_requires_ticker_and_opp(
        self,
        base_path: str,
        tmp_path: Path,
    ):
        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})

        with pytest.raises(ValueError, match="Both ticker and opp_id"):
            worker.run({"ticker": "", "opp_id": "", "base_path": base_path})

    def test_persist_hypotheses_ids_unicos_entre_opps(self, tmp_sqlite, tmp_journal):
        worker = ResearchWorker({"provider": "test"})
        worker._persist_hypotheses(
            "AAA", "OPP-AAA-1", "tesis",
            [{"id": "H1", "enunciado": "h1"},
             {"id": "H2", "enunciado": "h2", "parent_id": "H1"}],
            tmp_journal, tmp_sqlite,
        )
        worker._persist_hypotheses(
            "BBB", "OPP-BBB-1", "tesis",
            [{"id": "H1", "enunciado": "h1"}],
            tmp_journal, tmp_sqlite,
        )

        rows = list(tmp_sqlite.conn.execute(
            "SELECT id, parent_id FROM hypotheses ORDER BY opportunity_id"))
        assert len(rows) == 3
        ids = [dict(r)["id"] for r in rows]
        assert len(ids) == len(set(ids)), "los IDs colisionan entre oportunidades"
        parents = {dict(r)["id"]: dict(r)["parent_id"] for r in rows}
        assert parents["H1-OPP-AAA-1"] == ""
        assert parents["H2-OPP-AAA-1"] == "H1-OPP-AAA-1"
        assert parents["H1-OPP-BBB-1"] == ""

    def test_persist_hypotheses_reproceso_no_duplica(self, tmp_sqlite, tmp_journal):
        worker = ResearchWorker({"provider": "test"})
        raw = [{"id": "H1", "enunciado": "h1"}]
        worker._persist_hypotheses("AAA", "OPP-AAA-1", "tesis", raw, tmp_journal, tmp_sqlite)
        worker._persist_hypotheses("AAA", "OPP-AAA-1", "tesis", raw, tmp_journal, tmp_sqlite)

        rows = list(tmp_sqlite.conn.execute("SELECT id FROM hypotheses"))
        assert len(rows) == 1
