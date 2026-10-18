"""Regression tests for fail-closed monthly universe pipeline outcomes."""

from pathlib import Path

from idos.workers.data.universe_pipeline import UniversePipeline
from idos.workers.data.pipeline_report import PipelineMetrics
from idos.workers.base import WorkerResult, WorkerStatus


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
        monkeypatch.setattr(pipeline, step, lambda metrics: None)

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
    assert "relative_strength_3m" in result["missing_critical_metrics"]


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

    def fail_candidate_load(metrics):
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
