from pathlib import Path
from unittest.mock import MagicMock

import pytest

from idos.models.enums import OpportunityStatus
from idos.workers.ai.research_worker import ResearchWorker
from idos.workers.base import WorkerStatus
from idos.knowledge.wiki import AtomicWiki
from idos.research.wiki import WikiBuilder


def _mock_research_registry() -> MagicMock:
    registry = MagicMock()

    def get_side_effect(prompt_name: str, category: str = "research"):
        if prompt_name == "wiki":
            return None
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
