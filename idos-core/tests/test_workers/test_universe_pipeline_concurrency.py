from types import SimpleNamespace
import time
from threading import get_ident

import yaml

from idos.workers.data import universe_pipeline
from idos.workers.data.pipeline_report import PipelineMetrics
from idos.workers.data.universe_pipeline import UniversePipeline


def test_fetch_creates_an_isolated_refresh_worker_per_ticker(tmp_path, monkeypatch):
    created_workers = []

    class FakeRefreshWorker:
        def __init__(self, config):
            self.config = config
            self.owner_thread = get_ident()
            self.tickers = []
            created_workers.append(self)

        def execute(self, context):
            assert self.owner_thread == get_ident()
            time.sleep(0.05)
            self.tickers.extend(context["tickers"])
            return SimpleNamespace(status="success", error=None)

    monkeypatch.setattr(universe_pipeline, "DataRefreshWorker", FakeRefreshWorker)

    pipeline = UniversePipeline.__new__(UniversePipeline)
    pipeline.config = {"cache_path": str(tmp_path), "max_fetch_workers": 2}
    pipeline._get_cached_data = lambda _cache_path, _ticker: {}
    metrics = PipelineMetrics(finviz_tickers=["AAA", "BBB", "CCC", "DDD"])

    pipeline._run_fetch(metrics)

    assert len(created_workers) == 2
    assert len({id(worker) for worker in created_workers}) == 2
    assert sorted(ticker for worker in created_workers for ticker in worker.tickers) == ["AAA", "BBB", "CCC", "DDD"]
    assert metrics.fetch_new == 4
    assert metrics.fetch_errors == []


def test_compounder_universe_intersects_finviz_with_operable_allowlist(tmp_path):
    config_dir = tmp_path / "idos-config"
    universe_dir = config_dir / "universe"
    universe_dir.mkdir(parents=True)
    (universe_dir / "operable.yml").write_text(
        yaml.safe_dump({"operable_tickers": [{"ticker": "AAA"}, {"ticker": "CCC"}]}),
        encoding="utf-8",
    )

    pipeline = UniversePipeline.__new__(UniversePipeline)
    pipeline.config_path = str(config_dir)
    metrics = PipelineMetrics(finviz_count=3, finviz_tickers=["AAA", "BBB", "CCC"])

    pipeline._run_filter(metrics)

    assert metrics.finviz_tickers == ["AAA", "CCC"]
    assert metrics.operable_count == 2
    assert metrics.operable_filtered == 1
