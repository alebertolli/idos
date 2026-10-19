"""Regression tests for Finviz screener response validation."""

from pathlib import Path

from idos.workers.data.finviz_screener import FinvizScreenerScraper


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


def test_unrecognized_finviz_page_fails_without_caching_empty_results(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "idos.workers.data.finviz_screener.requests.get",
        lambda *args, **kwargs: FakeResponse("<html><body>challenge page</body></html>"),
    )
    cache_path = tmp_path / "cache"
    worker = FinvizScreenerScraper({"cache_path": str(cache_path), "max_pages": 1})

    result = worker.execute({})

    assert result.status == "failed"
    assert "recognizable screener result count" in result.error
    assert not (cache_path / "finviz_screener_cache.json").exists()


def test_reported_results_without_parseable_tickers_fail_without_caching(tmp_path, monkeypatch):
    html = '<html><span id="screener-total">#1 / 1</span></html>'
    monkeypatch.setattr(
        "idos.workers.data.finviz_screener.requests.get",
        lambda *args, **kwargs: FakeResponse(html),
    )
    cache_path = tmp_path / "cache"
    worker = FinvizScreenerScraper({"cache_path": str(cache_path), "max_pages": 1})

    result = worker.execute({})

    assert result.status == "failed"
    assert "reported 1 screener results" in result.error
    assert not (cache_path / "finviz_screener_cache.json").exists()
