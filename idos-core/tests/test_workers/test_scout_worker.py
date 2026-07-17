import tempfile
from pathlib import Path

from idos.workers.data.scout_worker import ScoutWorker


SAMPLE_UNIVERSE = """# Universo IDOS

## Seguimiento Activo
| Ticker | Nombre | Sector | Prioridad |
|--------|--------|--------|-----------|
| MELI | MercadoLibre | Technology | ALTA |
| V | Visa | Financials | ALTA |
"""


def test_scout_worker_loads_tickers():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(SAMPLE_UNIVERSE)
        tmp = f.name

    try:
        w = ScoutWorker({"universe_path": tmp})
        tickers = w._load_tickers()
        assert "MELI" in tickers
        assert "V" in tickers
        assert len(tickers) == 2
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_scout_worker_no_file():
    w = ScoutWorker({"universe_path": "/nonexistent/path.md"})
    tickers = w._load_tickers()
    assert tickers == []


def test_scout_worker_no_universe_path():
    w = ScoutWorker()
    tickers = w._load_tickers()
    assert tickers == []


def test_scout_worker_screen_no_data():
    w = ScoutWorker()
    result = w._run_scout("MELI", {})
    assert result.ticker == "MELI"
    assert result.score >= 0


def test_scout_worker_screen_with_data():
    w = ScoutWorker({"universe_path": ""})
    result = w._run_scout("MELI", {
        "market_cap": 100_000_000_000,
        "volume_avg": 5_000_000,
        "pe_ratio_ttm": 25.0,
        "roic_pct": 22.5,
        "operating_margin_pct": 18.0,
        "revenue_growth_pct": 20.0,
    })
    assert result.score >= 70
    assert result.passed is True


def test_scout_worker_duplicates():
    content = "| AAPL | Apple | Tech |\n| AAPL | Apple | Tech |\n| MSFT | Microsoft | Tech |\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(content)
        tmp = f.name

    try:
        w = ScoutWorker({"universe_path": tmp})
        tickers = w._load_tickers()
        assert len(tickers) == 2
        assert tickers.count("AAPL") == 1
    finally:
        Path(tmp).unlink(missing_ok=True)
