"""Monthly signal must pass the public research and decision gates."""

from pathlib import Path

import yaml

from idos.data.sqlite import SQLiteStore
from idos.decision.assessment_pipeline import run_full_pipeline
from idos.site.builder import SiteBuilder
from idos.workers.ai.research_worker import ResearchWorker
from idos.workers.data.strategy_pipeline import MonthlyStrategyWorker


class Prices:
    def get_history(self, ticker, period="2y", interval="1mo"):
        return [{"date": f"2026-{i % 12 + 1:02d}-01", "close": 100 + 2 * i} for i in range(24)]


def test_momentum_discovery_research_assessment_wait(tmp_path: Path, monkeypatch):
    config = tmp_path / "idos-config"
    config.mkdir()
    source = Path(__file__).resolve().parents[2] / "idos-config" / "strategies.yml"
    (config / "strategies.yml").write_bytes(source.read_bytes())

    MonthlyStrategyWorker({"price_provider": Prices()}).run({"base_path": tmp_path})
    store = SQLiteStore(tmp_path / "idos.db")
    opp_id = store.conn.execute("SELECT id FROM opportunities").fetchone()[0]
    opp = store.get_opportunity(opp_id)
    assert opp["status"] == "SCREENED"
    assert run_full_pipeline(opp_id, opp["ticker"], tmp_path)["status"] == "blocked"

    worker = ResearchWorker({})
    monkeypatch.setattr(worker, "_load_financial_data", lambda *args: {})
    monkeypatch.setattr(worker, "_enrich_company_info", lambda ticker, company, knowledge: {"name": ticker, "sector": "ETF"})
    monkeypatch.setattr(worker, "_fetch_target_consensus", lambda *args: {})
    result = worker.run({"ticker": opp["ticker"], "opp_id": opp_id, "base_path": tmp_path})
    assert result["status"] == "completed"
    assert store.get_opportunity(opp_id)["status"] == "UNDER_RESEARCH"

    decision = run_full_pipeline(opp_id, opp["ticker"], tmp_path)
    assert decision["status"] == "decision_pending"
    assert decision["recommendation"] == "WAIT"
    assert decision["board_approved"] is False
    proposal_file = tmp_path / "idos-journal" / "companies" / opp["ticker"] / "case_file" / "opportunities" / opp_id / "decision_proposal.yml"
    proposal = yaml.safe_load(proposal_file.read_text(encoding="utf-8"))
    assert proposal["status"] == "PENDING_HUMAN_REVIEW"
    assert all(proposal["checks"].values())
    assert store.get_opportunity(opp_id)["status"] == "UNDER_RESEARCH"
    assert not (tmp_path / "idos-journal" / "portfolio" / "buylist.yml").exists()

    public = SiteBuilder(tmp_path).build()
    assert any("revisión humana" in alert["message"] for alert in public.dashboard["alerts"])
    assert public.positions == []
