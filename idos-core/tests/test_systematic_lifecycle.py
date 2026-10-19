"""Monthly signal must pass the public research and decision gates."""

from pathlib import Path
from datetime import datetime, timedelta

import yaml

from idos.data.sqlite import SQLiteStore
from idos.decision.assessment_pipeline import run_full_pipeline
from idos.site.builder import SiteBuilder
from idos.workers.ai.research_worker import ResearchWorker
from idos.workers.data.strategy_pipeline import MonthlyStrategyWorker


class Prices:
    def get_history(self, ticker, period="2y", interval="1mo"):
        return [{"date": f"{(2024 * 12 + 10 + i) // 12}-{(10 + i) % 12 + 1:02d}-01", "close": 100 + 2 * i} for i in range(24)]


class MarketGate:
    def execute(self, context):
        from types import SimpleNamespace
        return SimpleNamespace(output={"data": {
            ticker: {"asset_type": "etf", "avg_dollar_volume_usd": 200_000,
                     "liquidity_provenance": {"price_source": "fixture"},
                     "market_data_normalization": {"status": "complete"}}
            for ticker in context["tickers"]
        }})


def test_momentum_discovery_research_assessment_wait(tmp_path: Path, monkeypatch, systematic_snapshot):
    config = tmp_path / "idos-config"
    config.mkdir()
    source = Path(__file__).resolve().parents[2] / "idos-config" / "strategies.yml"
    (config / "strategies.yml").write_bytes(source.read_bytes())
    (config / "universe").mkdir()
    (config / "universe" / "operable.yml").write_text(
        "operable_tickers:\n  - ticker: XLF\n    type: etf\n", encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    def no_corporate_context(*args):
        raise AssertionError("Systematic assessment must not fetch corporate consensus or portfolio context")

    monkeypatch.setattr("idos.decision.assessment_pipeline.build_context", no_corporate_context)

    output = MonthlyStrategyWorker({"config_path": str(config / "strategies.yml"),
                                   "price_provider": Prices(), "market_gate_worker": MarketGate()}).run({"base_path": tmp_path})
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

    report_file = proposal_file.parent / "ddd_report.yml"
    report = yaml.safe_load(report_file.read_text(encoding="utf-8"))
    mismatched = {**report, "strategy_context": {**report["strategy_context"], "signal": {**opp["signal"], "momentum": 2.5}}}
    report_file.write_text(yaml.safe_dump(mismatched), encoding="utf-8")
    mismatched_decision = run_full_pipeline(opp_id, opp["ticker"], tmp_path)
    assert mismatched_decision["status"] == "blocked"
    assert mismatched_decision["checks"]["current_selection"] is True
    assert mismatched_decision["checks"]["research_matches_signal"] is False
    report_file.write_text(yaml.safe_dump(report), encoding="utf-8")

    # A newer negative result invalidates an earlier research/decision case.
    signal = opp["signal"]
    newer = (datetime.fromisoformat(output["generated_at"]) + timedelta(seconds=1)).isoformat()
    systematic_snapshot(signal, output["signal_policy"], generated_at=newer, selected=[], action="CASH_FALLBACK")
    blocked = run_full_pipeline(opp_id, opp["ticker"], tmp_path)
    assert blocked["status"] == "blocked"
    assert blocked["checks"]["current_selection"] is False
    from scripts import ddd_research
    monkeypatch.setattr(ddd_research, "SKIP_TICKERS", set())
    should, _, reason = ddd_research._needs_research(store.get_opportunity(opp_id), True)
    assert should is False and "not_selected" in reason
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("FORCE", "true")
    monkeypatch.setenv("TICKER", "XLF")
    from unittest.mock import Mock
    service = Mock(side_effect=AssertionError("No eligible candidates must not initialize providers"))
    monkeypatch.setattr("idos.ai.service.LLMService", service)
    ddd_research.preview()
    import json
    preview = json.loads((tmp_path / "cache/ddd_preview.json").read_text(encoding="utf-8"))
    assert preview["selected"] == [] and "not_selected" in preview["skipped"][0]["reason"]
    assert ddd_research.main() == 0
    service.assert_not_called()

    # Re-research adopts a changed current signal while preserving the lifecycle.
    changed = {**signal, "momentum": signal["momentum"] + 0.1}
    newest = (datetime.fromisoformat(newer) + timedelta(seconds=1)).isoformat()
    systematic_snapshot(changed, output["signal_policy"], generated_at=newest)
    should, forced, _ = ddd_research._needs_research(store.get_opportunity(opp_id), False)
    assert should and forced
    result = worker.run({"ticker": opp["ticker"], "opp_id": opp_id, "base_path": tmp_path, "force_reprocess": True})
    assert result["status"] == "completed"
    assert store.get_opportunity(opp_id)["signal"] == changed
    assert run_full_pipeline(opp_id, opp["ticker"], tmp_path)["status"] == "decision_pending"
    assert not (tmp_path / "idos-journal" / "portfolio" / "buylist.yml").exists()
