from pathlib import Path
import yaml

from idos.discovery.multibaggers import CRITICAL_METRICS, MultibaggersDiscoveryEngine
from idos.discovery.financial_evidence import reconcile_metric_observations
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
    observations = {}
    for key, value in metrics.items():
        if key.endswith(("_as_of", "_period", "_currency")):
            continue
        unit = "USD" if key.endswith("_usd") else "percent" if key.endswith("_pct") else "months" if key.endswith("_months") else "ratio"
        stockanalysis_value = value
        yahoo_value = .20 if key == "roic_pct" else value
        yahoo_unit = "fraction" if key == "roic_pct" else unit
        observations[key] = [
            {"source_id": "stockanalysis.com", "value": stockanalysis_value, "unit": unit,
             "currency": "USD" if unit == "USD" else None, "period": "FY2025",
             "reported_at": "2026-09-30T00:00:00+00:00", "observed_at": "2026-10-15T12:00:00+00:00",
             "source_url": f"https://stockanalysis.com/stocks/test/statistics/{key}"},
            {"source_id": "yfinance", "value": yahoo_value, "unit": yahoo_unit,
             "currency": "USD" if unit == "USD" else None, "period": "FY2025",
             "reported_at": "2026-09-30T00:00:00+00:00", "observed_at": "2026-10-15T12:00:00+00:00",
             "source_url": f"https://finance.yahoo.com/quote/TEST/{key}"},
        ]
    return {"merged_data": metrics, "metric_sources": sources, "metric_values": {key: {"stockanalysis.com": value, "yfinance": value} for key, value in metrics.items()}, "metric_observations": observations, "conflicts": [], "as_of": "2026-10-15T12:00:00+00:00"}


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
        missing["metric_observations"].pop(name)
    assert engine.evaluate("TEST", missing).discovery_type == "BLOCKED_DATA"
    single = valid_payload()
    single["metric_sources"]["roic_pct"] = ["stockanalysis.com"]
    single["metric_observations"]["roic_pct"] = single["metric_observations"]["roic_pct"][:1]
    assert "SINGLE_SOURCE_CRITICAL_METRIC" in {f["code"] for f in engine.evaluate("TEST", single).red_flags}
    conflict = valid_payload()
    conflict["metric_observations"]["roic_pct"][1]["value"] = .10
    result = engine.evaluate("TEST", conflict)
    assert result.metrics_snapshot["roic_pct"]["status"] == "conflicted"
    stale = valid_payload()
    for observation in stale["metric_observations"]["roic_pct"]:
        observation["reported_at"] = "2025-01-01T00:00:00+00:00"
    result = engine.evaluate("TEST", stale)
    assert result.metrics_snapshot["roic_pct"]["status"] == "stale"


def test_missing_critical_metric_fails_source_gate_even_when_total_coverage_exceeds_minimum():
    payload = valid_payload()
    del payload["merged_data"]["expectation_gap_pct"]
    payload["metric_sources"].pop("expectation_gap_pct")
    payload["metric_observations"].pop("expectation_gap_pct")

    result = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", payload)

    assert result.data_quality["critical_coverage"] >= .8
    assert result.data_quality["critical_source_failures"] == 1
    assert result.passed is False
    assert "CRITICAL_METRIC_SOURCE_COVERAGE_FAILED" in result.reason_codes
    assert "MISSING_CRITICAL_METRIC" in {flag["code"] for flag in result.red_flags}


def test_duplicate_source_labels_do_not_satisfy_independent_source_gate():
    payload = valid_payload()
    payload["metric_sources"]["roic_pct"] = ["yfinance", " YFINANCE "]
    duplicate = payload["metric_observations"]["roic_pct"][1].copy()
    duplicate["source_id"] = " YAHOO_FINANCE "
    payload["metric_observations"]["roic_pct"] = [payload["metric_observations"]["roic_pct"][1], duplicate]

    result = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", payload)

    assert result.metrics_snapshot["roic_pct"]["source"] == ["yfinance"]
    assert result.metrics_snapshot["roic_pct"]["coverage"] == 1
    assert "SINGLE_SOURCE_CRITICAL_METRIC" in {flag["code"] for flag in result.red_flags}
    assert result.passed is False


def test_hard_flags_and_metric_units_are_auditable():
    payload = valid_payload()
    for observation in payload["metric_observations"]["current_ratio"]:
        observation["value"] = .3
    result = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", payload)
    assert "LOW_CURRENT_RATIO" in {flag["code"] for flag in result.red_flags}
    assert result.metrics_snapshot["market_cap_usd"]["unit"] == "USD"
    assert result.metrics_snapshot["roic_pct"]["unit"] == "percent"
    assert result.passed is False


def test_source_observations_normalize_units_and_reject_incompatible_periods():
    observations = [
        {"source_id": "stockanalysis.com", "value": 20, "unit": "percent", "period": "FY2025",
         "reported_at": "2026-09-30", "observed_at": "2026-10-15", "source_url": "https://stockanalysis.com/example"},
        {"source_id": "YAHOO_FINANCE", "value": .2, "unit": "fraction", "period": "FY2025",
         "reported_at": "2026-09-30", "observed_at": "2026-10-15", "source_url": "https://finance.yahoo.com/example"},
    ]
    result = reconcile_metric_observations(observations, expected_unit="percent", expected_currency=None,
        minimum_sources=2, conflict_tolerance_pct=20, stale_after_days=120, now="2026-10-16T00:00:00+00:00")
    assert result["status"] == "observed"
    assert result["value"] == 20
    assert result["source"] == ["stockanalysis.com", "yfinance"]

    observations[1]["period"] = "FY2024"
    mismatch = reconcile_metric_observations(observations, expected_unit="percent", expected_currency=None,
        minimum_sources=2, conflict_tolerance_pct=20, stale_after_days=120, now="2026-10-16T00:00:00+00:00")
    assert mismatch["status"] == "incompatible_period"
    assert mismatch["value"] is None

    observations[1]["period"] = "FY2025"
    observations[1]["source_url"] = "https://example.com/not-yahoo"
    bad_provenance = reconcile_metric_observations(observations, expected_unit="percent", expected_currency=None,
        minimum_sources=2, conflict_tolerance_pct=20, stale_after_days=120, now="2026-10-16T00:00:00+00:00")
    assert bad_provenance["status"] == "incomplete"

    observations[1]["source_url"] = "https://finance.yahoo.com/example"
    observations[1]["reported_at"] = "2026-10-16"
    bad_date_order = reconcile_metric_observations(observations, expected_unit="percent", expected_currency=None,
        minimum_sources=2, conflict_tolerance_pct=20, stale_after_days=120, now="2026-10-16T00:00:00+00:00")
    assert bad_date_order["status"] == "incomplete"


def test_legacy_merged_metrics_cannot_pass_without_source_evidence():
    payload = valid_payload()
    payload.pop("metric_observations")

    result = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", payload)

    assert result.passed is False
    assert result.data_quality["critical_coverage"] == 0
    assert "MISSING_CRITICAL_METRIC" in {flag["code"] for flag in result.red_flags}


def test_legacy_raw_conflict_does_not_override_reconciled_source_evidence():
    payload = valid_payload()
    payload["conflicts"] = [{"field": "roic_pct", "deviation_pct": 190, "sources": {"yfinance": .2, "stockanalysis.com": 20}}]

    result = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", payload)

    assert result.passed is True
    assert result.metrics_snapshot["roic_pct"]["value"] == 20
    assert "roic_pct" not in result.data_quality["critical_conflicts"]


def test_missing_report_date_blocks_otherwise_complete_source_evidence():
    payload = valid_payload()
    payload["metric_observations"]["roic_pct"][0]["reported_at"] = None

    result = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", payload)

    assert result.metrics_snapshot["roic_pct"]["status"] == "incomplete"
    assert result.metrics_snapshot["roic_pct"]["value"] is None
    assert result.metrics_snapshot["roic_pct"]["source_evidence"][0]["raw_value"] == 20
    assert result.metrics_snapshot["roic_pct"]["source_evidence"][0]["reason_code"] == "REQUIRED_EVIDENCE_FIELD_MISSING"
    assert result.passed is False


def test_incomplete_evidence_is_preserved_without_crashing_as_of_selection():
    payload = valid_payload()
    observations = payload["metric_observations"]["roic_pct"]
    observations[0]["reported_at"] = None

    result = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", payload)

    snapshot = result.metrics_snapshot["roic_pct"]
    assert snapshot["status"] == "incomplete"
    assert snapshot["as_of"] == "2026-09-30T00:00:00+00:00"
    assert [item["status"] for item in snapshot["source_evidence"]] == ["incomplete", "observed"]
    assert snapshot["source_evidence"][0]["raw_value"] == 20


def test_multibaggers_pipeline_and_journal_are_idempotent_and_gated(tmp_path: Path):
    config_dir = tmp_path / "idos-config"
    universe_path = config_dir / "universe" / "multibaggers.yml"
    universe_path.parent.mkdir(parents=True)
    (config_dir / "universe" / "operable.yml").write_text(yaml.safe_dump({"operable_tickers": [{"ticker": "TEST"}]}), encoding="utf-8")
    profile = {"enabled": True, "core": "CORE_4_ALPHA_ASYMMETRY", "sleeve": "ALPHA_ASYMMETRY", "thesis_type": "STRATEGIC",
        "discovery_profile": "multibaggers", "research_profile": "multibaggers", "entry_policy": "MANUAL_REVIEW", "strategy_version": "1.0",
        "parameters": {**parameters(), "universe_path": str(universe_path)}}
    (config_dir / "strategies.yml").write_text(yaml.safe_dump({"default_strategy": "COMPOUNDER", "strategies": {"MULTIBAGGERS": profile}}), encoding="utf-8")
    universe_path.write_text(yaml.safe_dump({"strategy_id": "MULTIBAGGERS", "enabled": True, "tickers": ["TEST"]}), encoding="utf-8")
    class FakeCache:
        payload = valid_payload()

        def get(self, key):
            return self.payload if key == "merged:TEST" else None
    cache = FakeCache()
    config = {"base_path": str(tmp_path), "config_path": str(config_dir), "journal_path": str(tmp_path / "idos-journal"), "data_cache": cache, "refresh_missing": False}
    legacy_payload = valid_payload()
    legacy_payload.pop("metric_observations")
    cache.payload = legacy_payload
    blocked = MultibaggersPipeline(config).run()
    assert blocked["blocked"] == 1
    assert blocked["created"] == 0
    assert not (tmp_path / "idos-journal" / "companies" / "TEST" / "case_file" / "opportunities" / "OPP-MB-TEST").exists()
    cache.payload = valid_payload()
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
    snapshots = MultibaggersStore(tmp_path / "idos.db").list("TEST")
    assert len(snapshots) == 2
    assert {snapshot["result"]["passed"] for snapshot in snapshots} == {False, True}
    assert sum(snapshot["result"]["passed"] for snapshot in snapshots) == 1
    from idos.site.builder import SiteBuilder
    site = SiteBuilder(tmp_path).build()
    public_opp = next(item for item in site.opportunities if item["strategy_id"] == "MULTIBAGGERS")
    assert public_opp["discovery_score"] >= 65
    assert public_opp["research_priority"] is not None


def test_multibaggers_excludes_tickers_missing_from_shared_operable_allowlist(tmp_path: Path):
    config_dir = tmp_path / "idos-config"
    universe_path = config_dir / "universe" / "multibaggers.yml"
    universe_path.parent.mkdir(parents=True)
    profile = {"enabled": True, "core": "CORE_4_ALPHA_ASYMMETRY", "sleeve": "ALPHA_ASYMMETRY", "thesis_type": "STRATEGIC",
        "discovery_profile": "multibaggers", "research_profile": "multibaggers", "entry_policy": "MANUAL_REVIEW", "strategy_version": "1.0",
        "parameters": {**parameters(), "universe_path": str(universe_path)}}
    (config_dir / "strategies.yml").write_text(yaml.safe_dump({"default_strategy": "COMPOUNDER", "strategies": {"MULTIBAGGERS": profile}}), encoding="utf-8")
    universe_path.write_text(yaml.safe_dump({"strategy_id": "MULTIBAGGERS", "enabled": True, "tickers": ["OUT"]}), encoding="utf-8")
    (config_dir / "universe" / "operable.yml").write_text(yaml.safe_dump({"operable_tickers": [{"ticker": "IN"}]}), encoding="utf-8")

    class CacheMustNotBeRead:
        def get(self, _key):
            raise AssertionError("discovery must not read data for an inoperable ticker")

    result = MultibaggersPipeline({"base_path": str(tmp_path), "config_path": str(config_dir), "data_cache": CacheMustNotBeRead()}).run()

    assert result["status"] == "no_eligible_tickers"
    assert result["excluded_tickers"] == ["OUT"]
    assert result["processed"] == 0
    assert not (tmp_path / "idos.db").exists()


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
