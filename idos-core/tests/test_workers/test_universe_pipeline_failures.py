"""Regression tests for fail-closed monthly universe pipeline outcomes."""

from pathlib import Path

from idos.workers.data.universe_pipeline import UniversePipeline
from idos.workers.data.pipeline_report import PipelineMetrics
from idos.workers.data.pipeline_report import PipelineReportGenerator
from idos.workers.base import WorkerResult, WorkerStatus


def test_latest_market_quote_keeps_only_aligned_sourced_currency_data():
    quote = UniversePipeline._latest_market_quote({
        "price_history": [100.0, 120.0],
        "price_history_dates": ["2026-10-16", "2026-10-19"],
        "quote_currency": "USD",
        "data_provenance": {"field_sources": {"price_history": ["yfinance"]}},
    })

    assert quote == {
        "price": 120.0, "as_of_date": "2026-10-19", "currency": "USD", "source": "yfinance",
    }


def test_latest_market_quote_rejects_missing_source_or_currency():
    assert UniversePipeline._latest_market_quote({
        "price_history": [120.0], "price_history_dates": ["2026-10-19"], "quote_currency": "USD",
    }) is None
    assert UniversePipeline._latest_market_quote({
        "price_history": [120.0], "price_history_dates": ["2026-10-19"],
        "data_provenance": {"field_sources": {"price_history": ["yfinance"]}},
    }) is None


def test_zero_ticker_universe_run_is_not_reported_as_success(tmp_path, monkeypatch):
    project_root = Path(__file__).resolve().parents[3]
    pipeline = UniversePipeline(
        {
            "config_path": str(project_root / "idos-config"),
            "journal_path": str(tmp_path),
            "cache_path": str(tmp_path / "cache"),
        }
    )
    monkeypatch.setattr(pipeline, "_send_notification", lambda report: None)
    for step in (
        "_load_candidate_universe",
        "_run_filter",
        "_run_pre_score",
        "_run_fetch",
        "_run_scout",
        "_run_opportunity_creation",
        "_run_monthly_evaluation",
    ):
        monkeypatch.setattr(pipeline, step, lambda metrics, requested_tickers=None: None)

    result = pipeline.execute({})

    assert result.status == "failed"
    assert result.output["candidate_count"] == 0
    assert "zero candidates" in result.error


def test_candidate_universe_uses_all_operable_asset_types_without_external_screener(tmp_path):
    config_dir = tmp_path / "config"
    (config_dir / "universe").mkdir(parents=True)
    (config_dir / "strategies.yml").write_text(
        "version: '1.0'\ndefault_strategy: COMPOUNDER\n"
        "strategies:\n  COMPOUNDER:\n"
        "    enabled: true\n    discovery_profile: compounder\n"
        "    core: CORE_3_GROWTH\n    sleeve: HIGH_CONVICTION\n"
        "    thesis_type: STRATEGIC\n    entry_policy: VALUATION_ZONE\n"
        "    research_profile: strategic\n",
        encoding="utf-8",
    )
    (config_dir / "universe" / "operable.yml").write_text(
        "operable_tickers:\n"
        "  - ticker: AAPL\n    type: us_equity\n"
        "  - ticker: SPY\n    type: etf\n"
        "  - ticker: AAPL.BA\n    type: cedear\n",
        encoding="utf-8",
    )
    pipeline = UniversePipeline({"config_path": str(config_dir)})
    metrics = PipelineMetrics()

    pipeline._load_candidate_universe(metrics)

    assert metrics.candidate_tickers == ["AAPL", "AAPL.BA", "SPY"]
    assert metrics.candidate_count == 3
    assert Path(metrics.candidate_source).parts[-2:] == ("universe", "operable.yml")


def test_candidate_universe_manual_subset_must_be_operable(tmp_path):
    config_dir = tmp_path / "config"
    (config_dir / "universe").mkdir(parents=True)
    (config_dir / "strategies.yml").write_text(
        "version: '1.0'\ndefault_strategy: COMPOUNDER\nstrategies:\n"
        "  COMPOUNDER:\n    enabled: true\n    discovery_profile: compounder\n"
        "    core: CORE_3_GROWTH\n    sleeve: HIGH_CONVICTION\n"
        "    thesis_type: STRATEGIC\n    entry_policy: VALUATION_ZONE\n"
        "    research_profile: strategic\n",
        encoding="utf-8",
    )
    (config_dir / "universe" / "operable.yml").write_text(
        "operable_tickers:\n  - ticker: QQQ\n    type: etf\n  - ticker: GLD\n    type: etf\n",
        encoding="utf-8",
    )
    pipeline = UniversePipeline({"config_path": str(config_dir)})
    metrics = PipelineMetrics()

    pipeline._load_candidate_universe(metrics, ["gld", "QQQ"])

    assert metrics.candidate_tickers == ["GLD", "QQQ"]
    assert metrics.candidate_count == 2
    assert metrics.errors == []

    invalid_metrics = PipelineMetrics()
    pipeline._load_candidate_universe(invalid_metrics, ["GLD", "AAPL"])

    assert invalid_metrics.candidate_tickers == []
    assert invalid_metrics.errors[0]["step"] == "candidate_universe"
    assert "AAPL" in invalid_metrics.errors[0]["error"]


def test_candidate_universe_applies_strategy_asset_type_filter(tmp_path):
    config_dir = tmp_path / "config"
    (config_dir / "universe").mkdir(parents=True)
    (config_dir / "strategies.yml").write_text(
        "version: '1.0'\ndefault_strategy: COMPOUNDER\nstrategies:\n"
        "  COMPOUNDER:\n    enabled: true\n    discovery_profile: compounder\n"
        "    core: CORE_3_GROWTH\n    sleeve: HIGH_CONVICTION\n"
        "    thesis_type: STRATEGIC\n    entry_policy: VALUATION_ZONE\n"
        "    research_profile: strategic\n"
        "    parameters:\n      supported_asset_types: [us_equity]\n",
        encoding="utf-8",
    )
    (config_dir / "universe" / "operable.yml").write_text(
        "operable_tickers:\n  - ticker: AAPL\n    type: us_equity\n"
        "  - ticker: QQQ\n    type: etf\n",
        encoding="utf-8",
    )
    pipeline = UniversePipeline({"config_path": str(config_dir)})
    metrics = PipelineMetrics()

    pipeline._load_candidate_universe(metrics, ["AAPL", "QQQ"])

    assert metrics.candidate_tickers == ["AAPL"]
    assert metrics.candidate_count == 1

    etf_only_metrics = PipelineMetrics()
    pipeline._load_candidate_universe(etf_only_metrics, ["QQQ"])
    assert etf_only_metrics.candidate_tickers == []
    assert etf_only_metrics.errors == []


def test_candidate_universe_manual_selection_is_hard_bounded(tmp_path):
    config_dir = tmp_path / "config"
    (config_dir / "universe").mkdir(parents=True)
    (config_dir / "strategies.yml").write_text(
        "version: '1.0'\ndefault_strategy: COMPOUNDER\nstrategies:\n"
        "  COMPOUNDER:\n    enabled: true\n    discovery_profile: compounder\n"
        "    core: CORE_3_GROWTH\n    sleeve: HIGH_CONVICTION\n"
        "    thesis_type: STRATEGIC\n    entry_policy: VALUATION_ZONE\n"
        "    research_profile: strategic\n",
        encoding="utf-8",
    )
    entries = "operable_tickers:\n" + "".join(
        f"  - ticker: TICK{i}\n    type: us_equity\n" for i in range(6)
    )
    (config_dir / "universe" / "operable.yml").write_text(entries, encoding="utf-8")
    pipeline = UniversePipeline({"config_path": str(config_dir)})
    metrics = PipelineMetrics()

    pipeline._load_candidate_universe(metrics, [f"TICK{i}" for i in range(6)])

    assert metrics.candidate_tickers == []
    assert "5-ticker limit" in metrics.errors[0]["error"]


def test_fetch_embedded_errors_do_not_mark_missing_data_as_fetched(tmp_path, monkeypatch):
    project_root = Path(__file__).resolve().parents[3]
    pipeline = UniversePipeline({"config_path": str(project_root / "idos-config")})
    pipeline._get_cached_data = lambda cache_path, ticker: {}

    class RefreshWithoutData:
        def __init__(self, config):
            pass

        def execute(self, context):
            return WorkerResult(
                status=WorkerStatus.SUCCESS,
                worker="data_refresh",
                output={"data": {}, "errors": [f"{context['tickers'][0]}: source rate-limited"]},
            )

    monkeypatch.setattr("idos.workers.data.universe_pipeline.DataRefreshWorker", RefreshWithoutData)
    metrics = PipelineMetrics(candidate_tickers=["AAPL"], candidate_count=1)

    pipeline._run_fetch(metrics)

    assert metrics.fetch_new == 0
    assert metrics.fetch_errors == [{"ticker": "AAPL", "error": "AAPL: source rate-limited"}]
    assert metrics.candidate_tickers == []
    assert metrics.errors[0]["step"] == "data_quality"


def test_scout_rejects_candidates_missing_critical_inputs(tmp_path):
    project_root = Path(__file__).resolve().parents[3]
    pipeline = UniversePipeline({"config_path": str(project_root / "idos-config")})

    result = pipeline._score_ticker(None, "AAPL", {"market_cap": 10_000_000_000})

    assert result["passed"] is False
    assert result["score"] == 0
    assert result["data_quality_valid"] is False
    assert {"operating_margin_pct", "fcf", "revenue_growth_pct"} <= set(result["missing_critical_metrics"])


def test_scout_requires_canonical_usd_liquidity_fields(tmp_path):
    project_root = Path(__file__).resolve().parents[3]
    pipeline = UniversePipeline({"config_path": str(project_root / "idos-config")})
    data = {
        "market_cap": 10_000_000_000,
        "avg_volume": 5_000_000,
        "volume_avg": 5_000_000,
        "roic_pct": 20,
        "debt_equity_ratio": 0.2,
        "relative_strength_3m": 80,
        "relative_strength_12m": 70,
        "price_volume_trend": 5,
    }

    result = pipeline._score_ticker(None, "AAPL", data)

    assert result["passed"] is False
    assert result["data_quality_valid"] is False
    assert "size_metric_usd" in result["missing_critical_metrics"]
    assert "avg_dollar_volume_usd" in result["missing_critical_metrics"]


def test_pipeline_preserves_step_errors_in_failed_result(tmp_path, monkeypatch):
    project_root = Path(__file__).resolve().parents[3]
    pipeline = UniversePipeline(
        {
            "config_path": str(project_root / "idos-config"),
            "journal_path": str(tmp_path),
            "cache_path": str(tmp_path / "cache"),
        }
    )
    monkeypatch.setattr(pipeline, "_send_notification", lambda report: None)

    def fail_candidate_load(metrics, requested_tickers=None):
        metrics.errors.append({"step": "candidate_universe", "error": "registry unavailable"})

    monkeypatch.setattr(pipeline, "_load_candidate_universe", fail_candidate_load)
    for step in (
        "_run_filter",
        "_run_pre_score",
        "_run_fetch",
        "_run_scout",
        "_run_opportunity_creation",
        "_run_monthly_evaluation",
    ):
        monkeypatch.setattr(pipeline, step, lambda metrics: None)

    result = pipeline.execute({})

    assert result.status == "failed"
    assert result.output["errors"] == [{"step": "candidate_universe", "error": "registry unavailable"}]
    assert "candidate_universe: registry unavailable" in result.error


def test_pipeline_report_explains_missing_scout_data_quality_inputs():
    metrics = PipelineMetrics(
        finished_at="2026-10-18T20:00:00-03:00",
        scout_data_quality_rejected=1,
        scout_data_quality_details=[{
            "ticker": "AAPL",
            "missing_critical_metrics": ["operating_margin_pct", "fcf"],
        }],
    )

    report = PipelineReportGenerator().generate(metrics)

    assert "AAPL: missing operating_margin_pct, fcf" in report


def test_monthly_evaluation_preserves_under_research_when_scout_passed(tmp_path):
    import yaml
    project_root = Path(__file__).resolve().parents[3]
    journal = tmp_path / "journal"
    case = journal / "companies" / "AAPL" / "case_file" / "opportunities" / "OPP-1"
    case.mkdir(parents=True)
    path = case / "opportunity.yml"
    path.write_text(yaml.safe_dump({"id": "OPP-1", "ticker": "AAPL", "status": "UNDER_RESEARCH"}), encoding="utf-8")
    pipeline = UniversePipeline({"config_path": str(project_root / "idos-config"), "journal_path": str(journal)})
    metrics = PipelineMetrics(new_watchlist=[{"ticker": "AAPL", "score": 100, "passed": True}])

    pipeline._run_monthly_evaluation(metrics)

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["status"] == "UNDER_RESEARCH"
    assert metrics.downgraded_to_watchlist == 0


def test_monthly_scout_merges_results_into_persisted_watchlist(tmp_path, monkeypatch):
    import yaml

    project_root = Path(__file__).resolve().parents[3]
    journal = tmp_path / "journal"
    journal.mkdir()
    original_entries = [
        {"ticker": "NTES", "score": 62, "reason": "Existing research", "added_at": "2026-10-01", "alerts": ["earnings"], "notified": True},
        {"ticker": "VRTX", "score": 61, "reason": "Existing watch", "added_at": "2026-10-02", "alerts": [], "notified": False},
    ]
    (journal / "portfolio").mkdir()
    (journal / "portfolio" / "watchlist.yml").write_text(
        yaml.safe_dump({"entries": original_entries}), encoding="utf-8"
    )
    pipeline = UniversePipeline({
        "config_path": str(project_root / "idos-config"),
        "journal_path": str(journal),
    })
    pipeline._get_cached_data = lambda cache_path, ticker: {}
    pipeline._score_ticker = lambda scout, ticker, data: {
        "ticker": ticker, "score": 100, "scout_score": 100, "passed": True,
        "status": "PASSED", "reason": "All configured filters passed",
        "data_quality_valid": True,
    }
    metrics = PipelineMetrics(candidate_tickers=["AAPL"])

    pipeline._run_scout(metrics)

    saved = yaml.safe_load((journal / "portfolio" / "watchlist.yml").read_text(encoding="utf-8"))
    by_ticker = {entry["ticker"]: entry for entry in saved["entries"]}
    assert set(by_ticker) == {"NTES", "VRTX", "AAPL"}
    assert by_ticker["NTES"] == original_entries[0]
    assert by_ticker["VRTX"] == original_entries[1]
    assert by_ticker["AAPL"]["reason"] == "All configured filters passed"


def test_existing_opportunity_keeps_initial_discovery_and_records_latest_evidence(tmp_path):
    import yaml

    project_root = Path(__file__).resolve().parents[3]
    journal = tmp_path / "journal"
    case = journal / "companies" / "AAPL" / "case_file" / "opportunities" / "OPP-1"
    case.mkdir(parents=True)
    opportunity = case / "opportunity.yml"
    initial_evidence = {"policy": {"version": "legacy"}, "eligibility_status": "PASSED"}
    opportunity.write_text(yaml.safe_dump({
        "id": "OPP-1", "ticker": "AAPL", "strategy_id": "COMPOUNDER",
        "status": "UNDER_RESEARCH", "discovery_evidence": initial_evidence,
    }), encoding="utf-8")
    pipeline = UniversePipeline({
        "config_path": str(project_root / "idos-config"),
        "journal_path": str(journal),
        "cache_path": str(tmp_path / "cache"),
    })
    pipeline._get_cached_data = lambda cache_path, ticker: {
        "operating_margin_pct": 25.0, "fcf": 1_000_000, "revenue_growth_pct": 10.0,
        "price_history": [120.0], "price_history_dates": ["2026-10-19"],
        "quote_currency": "USD",
        "data_provenance": {
            "sources_used": ["test-provider"],
            "field_sources": {"price_history": ["yfinance"]},
        },
    }
    metrics = PipelineMetrics(new_watchlist=[{
        "ticker": "AAPL", "score": 100, "rank": 1, "passed": True,
    }])

    pipeline._run_opportunity_creation(metrics)

    saved = yaml.safe_load(opportunity.read_text(encoding="utf-8"))
    assert metrics.opportunities_created == 0
    assert metrics.opportunities_existing == 1
    assert saved["discovery_evidence"] == initial_evidence
    assert saved["latest_discovery_evidence"]["policy"]["version"] == "positive_fundamentals_v1"
    assert saved["latest_discovery_evidence"]["metrics"] == {
        "operating_margin_pct": 25.0, "fcf": 1_000_000, "revenue_growth_pct": 10.0,
    }
    assert saved["latest_discovery_evidence"]["data_provenance"]["sources_used"] == ["test-provider"]
    assert saved["latest_discovery_evidence"]["market_quote"] == {
        "price": 120.0, "as_of_date": "2026-10-19", "currency": "USD", "source": "yfinance",
    }
    assert saved["status"] == "UNDER_RESEARCH"
