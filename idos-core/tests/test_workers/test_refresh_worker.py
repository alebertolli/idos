import tempfile
from pathlib import Path

from idos.workers.data.refresh_worker import DataRefreshWorker


SAMPLE_UNIVERSE = """| TICKER | Name |
|-------|------|
| MELI | MercadoLibre |
| GOOGL | Alphabet |
"""


def test_refresh_worker_loads_tickers():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(SAMPLE_UNIVERSE)
        tmp = f.name
    try:
        w = DataRefreshWorker({"universe_path": tmp})
        tickers = w._load_tickers_from_universe()
        assert "MELI" in tickers
        assert "GOOGL" in tickers
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_refresh_worker_no_file():
    w = DataRefreshWorker({"universe_path": "/nonexistent.md"})
    assert w._load_tickers_from_universe() == []


def test_refresh_worker_empty_context():
    w = DataRefreshWorker()
    result = w.run({"tickers": []})
    assert result["tickers_processed"] == 0
