from pathlib import Path
import yaml

from idos.discovery.multibaggers import CRITICAL_METRICS, MultibaggersDiscoveryEngine
from idos.discovery.multibaggers_pipeline import MultibaggersPipeline
from idos.discovery.multibaggers_store import MultibaggersStore
from idos.workers.data.universe_pipeline import UniversePipeline


def valid_payload():
    metrics = {
        "revenue_cagr_3y_pct": 30, "eps_growth_pct": 28, "fcf_growth_pct": 25,
        "roic_pct": 20, "operating_margin_pct": 20, "fcf_conversion_pct": 80,
        "net_debt_ebitda": 1, "dilution_yoy_pct": 2, "market_cap_usd": 10_000_000_000,
        "avg_dollar_volume_usd": 5_000_000, "relative_strength_12m_pct": 25,
        "expectation_gap_pct": 5, "gross_margin_pct": 60, "revenue_growth_pct": 30,
        "rd_to_revenue_pct": 15, "capex_to_revenue_pct": 10, "drawdown_pct": 10,
        "volatility_90d_pct": 20, "current_ratio": 2.0, "interest_coverage": 8.0,
        "fcf_runway_months": 24, "share_count_cagr_3y_pct": 2,
    }
    sources = {key: ["stockanalysis.com", "yfinance"] for key in metrics}
    for key in list(metrics):
        metrics[f"{key}_as_of"] = "2026-10-15T12:00:00+00:00"
    return {"merged_data": metrics, "metric_sources": sources, "metric_values": {key: {"stockanalysis.com": value, "yfinance": value} for key, value in metrics.items()}, "conflicts": [], "as_of": "2026-10-15T12:00:00+00:00"}


def parameters():
    return {"discovery_threshold": 65, "market_cap_min_usd": 2_000_000_000, "avg_dollar_volume_min_usd": 1_000_000,
        "weights": {"economic_transition": .25, "quality": .20, "reinvestment": .20, "expectation_gap": .20, "market_confirmation": .15},
        "data_quality": {"critical_coverage_min": .8, "critical_sources_min": 2, "conflict_tolerance_pct": 20, "stale_after_days": 120},
        "hard_flags": {"current_ratio_below": .5, "interest_coverage_below": 2.0, "net_debt_ebitda_above": 4.0, "negative_fcf_runway_months_below": 12, "dilution_yoy_above_pct": 10, "share_count_cagr_3y_above_pct": 5},
        "position_limit_pct": 1.0}


def test_discovery_is_deterministic_and_keeps_scores_separate_from_conviction():
    engine = MultibaggersDiscoveryEngine(parameters(), "1.0")
    first = engine.evaluate("TEST", valid_payload())
    second = engine.evaluate("TEST", valid_payload())
    assert first.to_dict() == second.to_dict()
    assert first.passed is True
    assert first.discovery_score >= 65
    assert first.strategy_id == "MULTIBAGGERS"
    assert first.data_quality["critical_coverage"] == 1
    assert first.metrics_snapshot["roic_pct"]["coverage"] == 2
    assert "conviction" not in first.to_dict()


def test_missing_single_source_conflicted_and_stale_critical_data_fail_closed():
    engine = MultibaggersDiscoveryEngine(parameters())
    missing = valid_payload()
    for name in ("fcf_growth_pct", "revenue_cagr_3y_pct", "expectation_gap_pct"):
        del missing["merged_data"][name]
        missing["metric_sources"].pop(name)
    assert engine.evaluate("TEST", missing).discovery_type == "BLOCKED_DATA"
    single = valid_payload()
    single["metric_sources"]["roic_pct"] = ["stockanalysis.com"]
    assert "SINGLE_SOURCE_CRITICAL_METRIC" in {f["code"] for f in engine.evaluate("TEST", single).red_flags}
    conflict = valid_payload()
    conflict["conflicts"] = [{"field": "roic_pct", "deviation_pct": 25, "sources": {"yfinance": 10}}]
    result = engine.evaluate("TEST", conflict)
    assert result.metrics_snapshot["roic_pct"]["status"] == "conflicted"
    stale = valid_payload()
    stale["merged_data"]["roic_pct_as_of"] = "2025-01-01T00:00:00+00:00"
    result = engine.evaluate("TEST", stale)
    assert result.metrics_snapshot["roic_pct"]["status"] == "stale"


def test_hard_flags_and_metric_units_are_auditable():
    payload = valid_payload()
    payload["merged_data"]["current_ratio"] = .3
    result = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", payload)
    assert "LOW_CURRENT_RATIO" in {flag["code"] for flag in result.red_flags}
    assert result.metrics_snapshot["market_cap_usd"]["unit"] == "USD"
    assert result.metrics_snapshot["roic_pct"]["unit"] == "percent"
    assert result.passed is False


def test_multibaggers_pipeline_and_journal_are_idempotent_and_gated(tmp_path: Path):
    config_dir = tmp_path / "idos-config"
    universe_path = config_dir / "universe" / "multibaggers.yml"
    universe_path.parent.mkdir(parents=True)
    profile = {"enabled": True, "core": "CORE_4_ALPHA_ASYMMETRY", "sleeve": "ALPHA_ASYMMETRY", "thesis_type": "STRATEGIC",
        "discovery_profile": "multibaggers", "research_profile": "multibaggers", "entry_policy": "MANUAL_REVIEW", "strategy_version": "1.0",
        "parameters": {**parameters(), "universe_path": str(universe_path)}}
    (config_dir / "strategies.yml").write_text(yaml.safe_dump({"default_strategy": "COMPOUNDER", "strategies": {"MULTIBAGGERS": profile}}), encoding="utf-8")
    universe_path.write_text(yaml.safe_dump({"strategy_id": "MULTIBAGGERS", "enabled": True, "tickers": ["TEST"]}), encoding="utf-8")
    class FakeCache:
        def get(self, key):
            return valid_payload() if key == "merged:TEST" else None
    config = {"base_path": str(tmp_path), "config_path": str(config_dir), "journal_path": str(tmp_path / "idos-journal"), "data_cache": FakeCache(), "refresh_missing": False}
    first = MultibaggersPipeline(config).run()
    second = UniversePipeline({**config, "strategy_id": "MULTIBAGGERS"}).execute({})
    assert first["created"] == 1
    assert second.status.value == "success"
    assert second.output["existing"] == 1
    opp_dir = tmp_path / "idos-journal" / "companies" / "TEST" / "case_file" / "opportunities" / "OPP-MB-TEST"
    assert (opp_dir / "discovery_snapshot.yml").exists()
    intake = yaml.safe_load((opp_dir / "research_intake.yml").read_text(encoding="utf-8"))
    assert intake["research_profile"] == "multibaggers"
    assert intake["strategy_version"] == "1.0"
    assert len(MultibaggersStore(tmp_path / "idos.db").list("TEST")) == 1
    from idos.site.builder import SiteBuilder
    site = SiteBuilder(tmp_path).build()
    public_opp = next(item for item in site.opportunities if item["strategy_id"] == "MULTIBAGGERS")
    assert public_opp["discovery_score"] >= 65
    assert public_opp["research_priority"] is not None


def test_manual_review_stops_assessment_before_buy_list(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import yaml
    from idos.data.sqlite import SQLiteStore
    from idos.models.enums import DecisionType
    import idos.decision.assessment_pipeline as assessment

    config_dir = tmp_path / "idos-config"
    config_dir.mkdir()
    (config_dir / "strategies.yml").write_text(yaml.safe_dump({"default_strategy": "COMPOUNDER", "strategies": {"MULTIBAGGERS": {
        "enabled": False, "core": "CORE_4_ALPHA_ASYMMETRY", "sleeve": "ALPHA_ASYMMETRY",
        "thesis_type": "STRATEGIC", "discovery_profile": "multibaggers", "research_profile": "multibaggers",
        "entry_policy": "MANUAL_REVIEW", "strategy_version": "1.0", "parameters": {"position_limit_pct": 1.0}}}}), encoding="utf-8")
    journal = tmp_path / "idos-journal" / "companies" / "TEST" / "case_file" / "opportunities" / "OPP-MB-TEST"
    journal.mkdir(parents=True)
    opp = {"id": "OPP-MB-TEST", "ticker": "TEST", "status": "UNDER_RESEARCH", "strategy_id": "MULTIBAGGERS",
           "strategy_version": "1.0", "research_profile": "multibaggers", "entry_policy": "MANUAL_REVIEW",
           "conviction": {}, "created_at": "2026-10-15T00:00:00+00:00", "updated_at": "2026-10-15T00:00:00+00:00"}
    (journal / "opportunity.yml").write_text(yaml.safe_dump(opp), encoding="utf-8")
    SQLiteStore(tmp_path / "idos.db").save_opportunity(opp)

    class FakeOrchestrator:
        def __init__(self, **kwargs): pass
        def register_engine(self, engine): pass
        def run_pipeline(self, event_type, context):
            return SimpleNamespace(type=event_type, opportunity_id=opp["id"], assessments={}, rules_passed=["all"],
                rules_failed=[], conviction_score=90, recommendation="APPROVE", rules_details={}, reasoning="approved by algorithm", created_at="2026-10-15T00:00:00+00:00")
    class FakeBoard:
        def __init__(self, **kwargs): pass
        def submit(self, proposal): pass
        def review(self):
            return SimpleNamespace(approved=True, decision_id="DEC-1", decision_type=DecisionType.BUY,
                justification="algorithmic approval", author="system", resolved_at="2026-10-15T00:00:00+00:00")
    monkeypatch.setattr(assessment, "DecisionOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(assessment, "DecisionBoard", FakeBoard)
    monkeypatch.setattr(assessment, "_register_authorization_rules", lambda *args: None)
    monkeypatch.setattr(assessment, "build_context", lambda *args: {"strategy_id": "MULTIBAGGERS", "research_profile": "multibaggers",
        "entry_policy": "MANUAL_REVIEW", "proposed_weight": 3.0, "asymmetry": 4.0, "knowledge_base": {"dynamic": {"metrics": {}}}})

    result = assessment.run_full_pipeline("OPP-MB-TEST", "TEST", tmp_path)

    assert result["status"] == "decision_pending"
    assert result["recommendation"] == "WAIT"
    assert result["board_approved"] is False
    assert not (tmp_path / "idos-journal" / "portfolio" / "buylist.yml").exists()
    proposal = yaml.safe_load((journal / "decision_proposal.yml").read_text(encoding="utf-8"))
    resolution = yaml.safe_load((journal / "board_resolution.yml").read_text(encoding="utf-8"))
    assert proposal["status"] == "PENDING_HUMAN_REVIEW"
    assert resolution["approved"] is False
    assert resolution["algorithmic_approved"] is True
