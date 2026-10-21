from datetime import date, timedelta
from math import isclose
from pathlib import Path
import yaml

from idos.discovery.multibaggers import CRITICAL_METRICS, MultibaggersDiscoveryEngine, build_research_intake
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
    merged_data = {
        **metrics,
        "asset_type": "us_equity",
        "size_metric_usd": metrics["market_cap_usd"],
        "size_metric_provenance": {"source": "yfinance", "as_of": "2026-10-15"},
        "market_cap_provenance": {"source": "yfinance", "as_of": "2026-10-15"},
        "avg_dollar_volume_usd": metrics["avg_dollar_volume_usd"],
        "liquidity_provenance": {"basis": "UNDERLYING_USD_PROXY", "window_sessions": 20, "coverage": 0.8},
        "market_data_normalization": {"status": "complete", "liquidity_basis": "UNDERLYING_USD_PROXY"},
    }
    price_dates = []
    cursor = date(2025, 10, 15)
    while cursor <= date(2026, 10, 15):
        if cursor.weekday() < 5:
            price_dates.append(cursor.isoformat())
        cursor += timedelta(days=1)
    merged_data.update({
        "price_history": [100 + 45 * i / (len(price_dates) - 1) for i in range(len(price_dates))],
        "price_history_dates": price_dates,
        "price_history_basis": "close_unadjusted",
    })
    return {"merged_data": merged_data, "metric_sources": sources, "metric_values": {key: {"stockanalysis.com": value, "yfinance": value} for key, value in metrics.items()}, "metric_observations": observations, "conflicts": [], "as_of": "2026-10-15T12:00:00+00:00"}


def parameters():
    return {
        "discovery_threshold": 65,
        "weights": {"market_confirmation": 1.0},
        "scoring": {"method": "absolute_linear_clamped", "version": "absolute-ranges-v1", "components": {
            "market_confirmation": {"inputs": [
                {"metric": "price_momentum_12m_pct", "min": -50, "max": 50, "direction": "higher"},
                {"metric": "drawdown_pct", "min": 0, "max": 60, "direction": "lower"},
                {"metric": "volatility_90d_pct", "min": 0, "max": 80, "direction": "lower"}]}}},
        "data_quality": {"critical_metrics": list(CRITICAL_METRICS), "critical_coverage_min": .8, "critical_sources_min": 1, "conflict_tolerance_pct": 20, "stale_after_days": 120},
        "research": {
            "required_analysis": ["fundamental_ratio_review", "bear_bull_scenarios", "source_cited_expectation_gap", "validated_asymmetry"],
            "ratios_to_review": ["revenue_cagr_3y_pct", "fcf_growth_pct", "fcf_conversion_pct", "net_debt_ebitda", "dilution_yoy_pct", "share_count_cagr_3y_pct", "current_ratio", "interest_coverage", "fcf_runway_months", "gross_margin_pct"],
            "ratio_definitions": {"fcf_conversion_pct": "FCF / net_income * 100"},
            "ratio_units": {"current_ratio": "x"},
            "risk_review_thresholds": {"current_ratio_below": .5, "interest_coverage_below": 2.0},
        },
        "position_limit_pct": 1.0,
    }


def test_discovery_is_deterministic_and_scores_only_market_confirmation():
    engine = MultibaggersDiscoveryEngine(parameters(), "1.5")
    first = engine.evaluate("TEST", valid_payload())
    second = engine.evaluate("TEST", valid_payload())
    assert first.to_dict() == second.to_dict()
    assert first.passed is True
    assert first.discovery_score >= 65
    assert first.strategy_id == "MULTIBAGGERS"
    assert first.data_quality["critical_coverage"] == 1
    assert set(first.component_scores) == {"market_confirmation"}
    assert set(first.metrics_snapshot) == set(CRITICAL_METRICS)
    assert first.discovery_type == "RESEARCH_REQUIRED"
    assert "conviction" not in first.to_dict()


def test_financial_metrics_are_deferred_to_research():
    payload = valid_payload()
    payload["metric_observations"].clear()
    payload["merged_data"]["operating_margin_pct"] = -100
    payload["merged_data"]["revenue_growth_pct"] = -100
    result = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", payload)
    assert result.passed is True
    assert "operating_margin_pct" not in result.metrics_snapshot
    assert "revenue_growth_pct" not in result.metrics_snapshot


def test_absolute_scoring_configuration_rejects_invalid_ranges():
    config = parameters()
    config["scoring"]["components"]["market_confirmation"]["inputs"][0]["max"] = -50
    try:
        MultibaggersDiscoveryEngine(config).evaluate("TEST", valid_payload())
    except ValueError as exc:
        assert "Invalid absolute scoring range" in str(exc)
    else:
        raise AssertionError("Invalid scoring range was accepted")


def test_market_confirmation_scoring_clamps_inputs():
    payload = valid_payload()
    payload["merged_data"].pop("price_history")
    payload["merged_data"].pop("price_history_dates")
    for metric, value in {"price_momentum_12m_pct": 100, "drawdown_pct": 60, "volatility_90d_pct": 80}.items():
        payload["metric_observations"][metric] = [{
            "source_id": "yfinance", "value": value, "unit": "percent", "currency": None,
            "period": "range", "reported_at": "2026-10-15", "observed_at": "2026-10-15",
            "source_url": "https://finance.yahoo.com/quote/TEST/history/",
        }]
    result = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", payload)
    assert result.component_scores["market_confirmation"] == 33.33


def test_repository_profile_uses_market_only_discovery_and_stays_disabled():
    repository_root = Path(__file__).resolve().parents[3]
    config = yaml.safe_load((repository_root / "idos-config" / "strategies.yml").read_text(encoding="utf-8"))
    profile = config["strategies"]["MULTIBAGGERS"]
    policy = profile["parameters"]
    assert config["default_strategy"] == "COMPOUNDER"
    assert profile["enabled"] is False
    assert profile["strategy_version"] == "1.5"
    assert policy["supported_asset_types"] == ["us_equity"]
    assert "universe_path" not in policy
    market_data = yaml.safe_load((repository_root / "idos-config" / "market_data.yml").read_text(encoding="utf-8"))
    assert market_data["eligibility"]["market_cap_min_usd"] == 2_000_000_000
    assert market_data["eligibility"]["avg_dollar_volume_min_usd"] == 100_000
    assert set(policy["data_quality"]["critical_metrics"]) == set(CRITICAL_METRICS)
    assert set(policy["scoring"]["components"]) == {"market_confirmation"}
    assert policy["data_quality"]["critical_sources_min"] == 1
    assert isclose(sum(policy["weights"].values()), 1.0, abs_tol=1e-9)


def test_research_intake_routes_fundamental_analysis_to_llm_stage():
    result = MultibaggersDiscoveryEngine(parameters(), "1.5").evaluate("TEST", valid_payload())
    intake = build_research_intake(result.to_dict(), {"parameters": parameters()})
    assert "expectation_gap_pct" not in intake["metrics_snapshot"]
    assert "fundamental_ratio_review" in intake["research_requirements"]["required_analysis"]
    assert "net_debt_ebitda" in intake["research_requirements"]["ratios_to_review"]
    assert intake["research_requirements"]["ratio_units"]["current_ratio"] == "x"
    assert intake["research_requirements"]["scenario_schema_version"] == "bear_bull_v2"


def test_shared_market_gate_fails_closed_and_does_not_require_etf_aum():
    from idos.market.liquidity import MarketDataSettings, evaluate_global_market_eligibility

    settings = MarketDataSettings()
    complete_etf = {
        "market_data_normalization": {"status": "complete"},
        "avg_dollar_volume_usd": 150_000,
        "liquidity_provenance": {"basis": "UNDERLYING_USD_PROXY", "window_sessions": 20, "coverage": 0.8},
    }
    assert evaluate_global_market_eligibility(complete_etf, asset_type="etf", settings=settings)["passed"]

    incomplete_equity = evaluate_global_market_eligibility({}, asset_type="us_equity", settings=settings)
    assert incomplete_equity["passed"] is False
    assert "GLOBAL_MARKET_CAP_EVIDENCE_INCOMPLETE" in incomplete_equity["reason_codes"]
    assert "GLOBAL_LIQUIDITY_EVIDENCE_INCOMPLETE" in incomplete_equity["reason_codes"]


def test_multibaggers_engine_does_not_duplicate_global_market_thresholds():
    payload = valid_payload()
    for observation in payload["metric_observations"]["avg_dollar_volume_usd"]:
        observation["value"] = 100_000

    result = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", payload)

    assert "DOLLAR_VOLUME_BELOW_MINIMUM" not in {flag["code"] for flag in result.red_flags}


def test_market_history_derivations_override_legacy_metric_observations():
    payload = valid_payload()
    payload["metric_observations"]["price_momentum_12m_pct"] = [{
        "source_id": "yfinance", "value": -99, "unit": "percent", "currency": None,
        "period": "wrong", "reported_at": "2026-10-15", "observed_at": "2026-10-15",
        "source_url": "https://finance.yahoo.com/quote/TEST/history/",
    }]
    result = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", payload)
    assert result.metrics_snapshot["price_momentum_12m_pct"]["value"] > 40
    assert result.metrics_snapshot["price_momentum_12m_pct"]["source"] == ["yfinance"]
    assert result.metrics_snapshot["price_momentum_12m_pct"]["status"] == "observed"


def test_missing_or_short_market_history_fails_closed():
    payload = valid_payload()
    payload["merged_data"].pop("price_history")
    payload["merged_data"].pop("price_history_dates")
    for metric in CRITICAL_METRICS:
        payload["metric_observations"].pop(metric, None)
    missing = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", payload)
    assert missing.discovery_type == "BLOCKED_DATA"
    assert missing.data_quality["critical_coverage"] == 0
    assert "MISSING_CRITICAL_METRIC" in {flag["code"] for flag in missing.red_flags}

    short = valid_payload()
    short["merged_data"]["price_history"] = short["merged_data"]["price_history"][-60:]
    short["merged_data"]["price_history_dates"] = short["merged_data"]["price_history_dates"][-60:]
    short_result = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", short)
    assert short_result.discovery_type == "BLOCKED_DATA"
    assert short_result.metrics_snapshot["price_momentum_12m_pct"]["status"] == "missing"

    unsupported = valid_payload()
    unsupported["merged_data"]["price_history_basis"] = "adjusted_close"
    unsupported_result = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", unsupported)
    assert unsupported_result.discovery_type == "BLOCKED_DATA"
    assert unsupported_result.metrics_snapshot["price_momentum_12m_pct"]["status"] == "missing"


def test_research_ratios_do_not_gate_discovery():
    payload = valid_payload()
    payload["metric_observations"]["current_ratio"] = []
    payload["merged_data"]["current_ratio"] = .1
    result = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", payload)
    assert "current_ratio" not in result.metrics_snapshot
    assert result.passed is True


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


def test_financial_source_evidence_is_not_required_until_research():
    payload = valid_payload()
    payload.pop("metric_observations")
    result = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", payload)
    assert result.passed is True
    assert set(result.metrics_snapshot) == set(CRITICAL_METRICS)


def test_missing_market_history_blocks_even_with_financial_ratios():
    payload = valid_payload()
    payload["merged_data"].pop("price_history")
    payload["merged_data"].pop("price_history_dates")
    result = MultibaggersDiscoveryEngine(parameters()).evaluate("TEST", payload)
    assert result.passed is False
    assert result.data_quality["critical_coverage"] < .8
    assert "MISSING_CRITICAL_METRIC" in {flag["code"] for flag in result.red_flags}


def test_multibaggers_pipeline_and_journal_are_idempotent_and_gated(tmp_path: Path):
    config_dir = tmp_path / "idos-config"
    (config_dir / "universe").mkdir(parents=True)
    (config_dir / "universe" / "operable.yml").write_text(yaml.safe_dump({"operable_tickers": [{"ticker": "TEST", "type": "us_equity"}]}), encoding="utf-8")
    profile = {"enabled": True, "core": "CORE_4_ALPHA_ASYMMETRY", "sleeve": "ALPHA_ASYMMETRY", "thesis_type": "STRATEGIC",
        "discovery_profile": "multibaggers", "research_profile": "multibaggers", "entry_policy": "MANUAL_REVIEW", "strategy_version": "1.0",
        "parameters": {**parameters(), "supported_asset_types": ["us_equity"]}}
    (config_dir / "strategies.yml").write_text(yaml.safe_dump({"default_strategy": "COMPOUNDER", "strategies": {"MULTIBAGGERS": profile}}), encoding="utf-8")
    class FakeCache:
        payload = valid_payload()

        def get(self, key):
            return self.payload if key == "merged:TEST" else None
    cache = FakeCache()
    config = {"base_path": str(tmp_path), "config_path": str(config_dir), "journal_path": str(tmp_path / "idos-journal"), "data_cache": cache, "refresh_missing": False}
    legacy_payload = valid_payload()
    legacy_payload["merged_data"].pop("price_history")
    legacy_payload["merged_data"].pop("price_history_dates")
    cache.payload = legacy_payload
    blocked = MultibaggersPipeline(config).run()
    assert blocked["blocked"] == 1
    assert blocked["created"] == 0
    assert not (tmp_path / "idos-journal" / "companies" / "TEST" / "case_file" / "opportunities" / "OPP-MB-TEST").exists()
    cache.payload = valid_payload()
    cache.payload["merged_data"]["quote_currency"] = "USD"
    cache.payload["field_sources"] = {"price_history": ["yfinance"]}
    first = MultibaggersPipeline(config).run()
    first_opp_path = tmp_path / "idos-journal" / "companies" / "TEST" / "case_file" / "opportunities" / "OPP-MB-TEST" / "opportunity.yml"
    first_opp = yaml.safe_load(first_opp_path.read_text(encoding="utf-8"))
    expected_quote = {
        "price": 145.0,
        "as_of_date": "2026-10-15",
        "currency": "USD",
        "source": "yfinance",
        "url": "https://finance.yahoo.com/quote/TEST/history/",
    }
    assert first_opp["discovery_evidence"]["market_quote"] == expected_quote
    assert first_opp["latest_discovery_evidence"]["market_quote"] == expected_quote
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

    cache.payload = valid_payload()
    cache.payload["merged_data"]["quote_currency"] = "USD"
    cache.payload["field_sources"] = {"price_history": ["yfinance"]}
    cache.payload["merged_data"]["price_history"][-1] = 200.0
    rerun = MultibaggersPipeline(config).run()
    assert rerun["existing"] == 1
    updated_opp = yaml.safe_load(first_opp_path.read_text(encoding="utf-8"))
    assert updated_opp["discovery_evidence"]["market_quote"] == expected_quote
    assert updated_opp["latest_discovery_evidence"]["market_quote"]["price"] == 200.0


def test_multibaggers_pipeline_blocks_market_ineligible_tickers_before_strategy_scoring(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "idos-config"
    (config_dir / "universe").mkdir(parents=True)
    (config_dir / "universe" / "operable.yml").write_text(yaml.safe_dump({"operable_tickers": [{"ticker": "TEST", "type": "us_equity"}]}), encoding="utf-8")
    profile = {"enabled": True, "core": "CORE_4_ALPHA_ASYMMETRY", "sleeve": "ALPHA_ASYMMETRY", "thesis_type": "STRATEGIC",
        "discovery_profile": "multibaggers", "research_profile": "multibaggers", "entry_policy": "MANUAL_REVIEW", "strategy_version": "1.0",
        "parameters": {**parameters(), "supported_asset_types": ["us_equity"]}}
    (config_dir / "strategies.yml").write_text(yaml.safe_dump({"default_strategy": "COMPOUNDER", "strategies": {"MULTIBAGGERS": profile}}), encoding="utf-8")

    class FakeCache:
        payload = valid_payload()
        def get(self, _key): return self.payload

    cache = FakeCache()
    config = {"base_path": str(tmp_path), "config_path": str(config_dir), "journal_path": str(tmp_path / "idos-journal"), "data_cache": cache, "refresh_missing": False}
    cache.payload["merged_data"].pop("market_data_normalization")
    with monkeypatch.context() as patch:
        patch.setattr(
            MultibaggersDiscoveryEngine,
            "evaluate",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("strategy scoring must wait for global market eligibility")
            ),
        )
        result = MultibaggersPipeline(config).run()
    assert result["blocked"] == 1
    assert result["created"] == 0
    assert "MARKET_DATA_NORMALIZATION_INCOMPLETE" in result["results"][0]["reason_codes"]

    cache.payload = valid_payload()
    cache.payload["merged_data"]["avg_dollar_volume_usd"] = 99_999
    with monkeypatch.context() as patch:
        patch.setattr(
            MultibaggersDiscoveryEngine,
            "evaluate",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("strategy scoring must wait for global market eligibility")
            ),
        )
        result = MultibaggersPipeline(config).run()
    assert result["blocked"] == 1
    assert result["created"] == 0
    assert "GLOBAL_LIQUIDITY_BELOW_MINIMUM" in result["results"][0]["reason_codes"]


def test_multibaggers_uses_shared_operable_universe_and_profile_asset_filter(tmp_path: Path):
    config_dir = tmp_path / "idos-config"
    (config_dir / "universe").mkdir(parents=True)
    profile = {"enabled": True, "core": "CORE_4_ALPHA_ASYMMETRY", "sleeve": "ALPHA_ASYMMETRY", "thesis_type": "STRATEGIC",
        "discovery_profile": "multibaggers", "research_profile": "multibaggers", "entry_policy": "MANUAL_REVIEW", "strategy_version": "1.0",
        "parameters": {**parameters(), "supported_asset_types": ["us_equity"]}}
    (config_dir / "strategies.yml").write_text(yaml.safe_dump({"default_strategy": "COMPOUNDER", "strategies": {"MULTIBAGGERS": profile}}), encoding="utf-8")
    (config_dir / "universe" / "operable.yml").write_text(yaml.safe_dump({"operable_tickers": [{"ticker": "QQQ", "type": "etf"}]}), encoding="utf-8")

    class CacheMustNotBeRead:
        def get(self, _key):
            raise AssertionError("discovery must not read data for an inoperable ticker")

    result = MultibaggersPipeline({"base_path": str(tmp_path), "config_path": str(config_dir), "data_cache": CacheMustNotBeRead()}).run()

    assert result["status"] == "no_eligible_tickers"
    assert result["candidate_source"].endswith("operable.yml")
    assert result["excluded_tickers"] == ["QQQ"]
    assert result["processed"] == 0
    assert not (tmp_path / "idos.db").exists()


def test_manual_review_stops_assessment_before_buy_list(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import yaml
    from idos.data.sqlite import SQLiteStore
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
    monkeypatch.setattr(assessment, "DecisionOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(assessment, "_register_authorization_rules", lambda *args: None)
    monkeypatch.setattr(
        assessment,
        "build_context",
        lambda *args, **kwargs: {
            "strategy_id": "MULTIBAGGERS",
            "research_profile": "multibaggers",
            "entry_policy": "MANUAL_REVIEW",
            "proposed_weight": 3.0,
            "asymmetry": 4.0,
            "knowledge_base": {"dynamic": {"metrics": {}}},
        },
    )

    result = assessment.run_full_pipeline("OPP-MB-TEST", "TEST", tmp_path)

    assert result["status"] == "decision_pending"
    assert result["recommendation"] == "WAIT"
    assert result["board_approved"] is False
    assert not (tmp_path / "idos-journal" / "portfolio" / "buylist.yml").exists()
    proposal = yaml.safe_load((journal / "decision_proposal.yml").read_text(encoding="utf-8"))
    resolution = yaml.safe_load((journal / "board_resolution.yml").read_text(encoding="utf-8"))
    assert proposal["status"] == "PENDING_HUMAN_REVIEW"
    assert resolution["approved"] is False

def test_engine_reads_metric_observations_from_merged_cache_payload():
    payload = valid_payload()
    observations = payload.pop("metric_observations")
    payload["merged_data"]["metric_observations"] = observations

    result = MultibaggersDiscoveryEngine(parameters(), "1.2").evaluate(
        "TEST", payload, payload["as_of"]
    )

    assert result.passed is True
    assert result.discovery_score is not None

