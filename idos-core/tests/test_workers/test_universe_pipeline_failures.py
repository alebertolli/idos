"""Regression tests for fail-closed monthly universe pipeline outcomes."""

from pathlib import Path

from idos.workers.data.universe_pipeline import UniversePipeline


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
        "_run_screener",
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
    assert result.output["finviz_count"] == 0
    assert "zero tickers" in result.error


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

    def fail_screener(metrics):
        metrics.errors.append({"step": "finviz", "error": "challenge page"})

    monkeypatch.setattr(pipeline, "_run_screener", fail_screener)
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
    assert result.output["errors"] == [{"step": "finviz", "error": "challenge page"}]
    assert "finviz: challenge page" in result.error
