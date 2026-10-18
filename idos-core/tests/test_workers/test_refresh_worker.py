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


def test_refresh_worker_reuses_aligned_yahoo_history():
    history = DataRefreshWorker._extract_price_history({
        "price_history": [10.0, 11.0],
        "price_history_dates": ["2026-01-01", "2026-01-02"],
        "volume_history": [100, 120],
    })

    assert history == {
        "prices": [10.0, 11.0],
        "dates": ["2026-01-01", "2026-01-02"],
        "volumes": [100, 120],
    }


def test_refresh_worker_rejects_misaligned_yahoo_history():
    assert DataRefreshWorker._extract_price_history({
        "price_history": [10.0],
        "price_history_dates": [],
        "volume_history": [],
    }) is None
