import tempfile
from pathlib import Path

from idos.discovery.scout import ScoutEngine
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
    w = ScoutWorker({"universe_path": "/nonexistent/path.md", "operable_path": "/nonexistent/operable.yml"})
    tickers = w._load_tickers()
    assert tickers == []


def test_scout_worker_no_universe_path():
    w = ScoutWorker({"operable_path": "/nonexistent/operable.yml"})
    tickers = w._load_tickers()
    assert tickers == []


def test_scout_worker_screen_no_data():
    w = ScoutWorker()
    result = w._run_scout("MELI", {})
    assert result.ticker == "MELI"
    assert result.score >= 0


def test_scout_worker_screen_with_data():
    w = ScoutWorker({"universe_path": "", "min_score": 70})
    result = w._run_scout("MELI", {
        "market_cap": 100_000_000_000,
        "volume_avg": 5_000_000,
        "relative_strength_3m": 80,
        "relative_strength_12m": 70,
        "price_volume_trend": 5,
        "roic_pct": 22.5,
        "operating_margin_pct": 18.0,
        "revenue_growth_pct": 20.0,
    })
    # New V1 model with min_score=70: Transition(50%) + Quality(25%) + Market(25%)
    # Transition: 50 + (80/100)*30 + (70/100)*20 = 50+24+14 = 88 * 0.5 = 44
    # Quality: 50 + (22.5/15)*20 = 50+30 = 80 * 0.25 = 20
    # Market: 50 + (80/100)*30 + (70/100)*20 = 50+24+14 = 88 * 0.25 = 22
    # Total: 44 + 20 + 22 = 86
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