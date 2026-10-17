from idos.resilience.error_manager import CATEGORY_DATOS, SEVERITY_HIGH
from idos.workers.data.refresh_worker import DataRefreshWorker


SAMPLE_UNIVERSE = """| TICKER | Name |
|-------|------|
| MELI | MercadoLibre |
| GOOGL | Alphabet |
"""


def test_refresh_worker_loads_tickers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    universe = tmp_path / "universe.md"
    universe.write_text(SAMPLE_UNIVERSE, encoding="utf-8")

    w = DataRefreshWorker({"universe_path": str(universe)})
    tickers = w._load_tickers_from_universe()
    assert "MELI" in tickers
    assert "GOOGL" in tickers


def test_refresh_worker_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    w = DataRefreshWorker({"universe_path": str(tmp_path / "nonexistent.md")})
    assert w._load_tickers_from_universe() == []


def test_refresh_worker_empty_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    w = DataRefreshWorker()
    result = w.run({"tickers": []})
    assert result["tickers_processed"] == 0


def test_refresh_worker_reports_high_severity_when_all_sources_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    worker = DataRefreshWorker()
    reports = []

    def fail_fast(_execute, _context):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(worker.retry, "execute", fail_fast)
    monkeypatch.setattr(worker.error_manager, "report", lambda **kwargs: reports.append(kwargs))

    result = worker.run({"tickers": ["TEST", "OTHER"]})

    assert result["tickers_processed"] == 0
    high_reports = {
        report["ticker"]
        for report in reports
        if report["category"] == CATEGORY_DATOS
        and report["severity"] == SEVERITY_HIGH
        and report["message"] == "no data from any source"
    }
    assert high_reports == {"TEST", "OTHER"}
