import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from idos.market.liquidity import FxObservation
from idos.market.liquidity import expected_us_market_sessions
from idos.market.liquidity import normalize_aum_usd
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
        "price_history_basis": "close_unadjusted",
    })

    assert history == {
        "prices": [10.0, 11.0],
        "dates": ["2026-01-01", "2026-01-02"],
        "volumes": [100, 120],
        "price_basis": "close_unadjusted",
    }


def test_refresh_worker_rejects_misaligned_yahoo_history():
    assert DataRefreshWorker._extract_price_history({
        "price_history": [10.0],
        "price_history_dates": [],
        "volume_history": [],
    }) is None


def test_refresh_worker_rejects_unaligned_volume_history():
    assert DataRefreshWorker._extract_price_history({
        "price_history": [10.0, 11.0],
        "price_history_dates": ["2026-01-01", "2026-01-02"],
        "volume_history": [100],
        "price_history_basis": "close_unadjusted",
    }) is None


def test_refresh_worker_cache_payload_keeps_flat_metrics_and_field_provenance():
    payload = DataRefreshWorker._cache_file_payload({
        "merged_data": {"market_cap": 100.0, "ticker": "ACWI"},
        "source_count": 2,
        "sources_used": ["stockanalysis.com", "yfinance"],
        "field_sources": {
            "market_cap": ["stockanalysis.com", "yfinance"],
            "roic_pct": ["stockanalysis.com"],
        },
        "conflicts": [],
    })

    assert payload["market_cap"] == 100.0
    assert payload["ticker"] == "ACWI"
    assert payload["data_provenance"]["source_count"] == 2
    assert payload["data_provenance"]["field_sources"]["roic_pct"] == ["stockanalysis.com"]


def test_refresh_worker_normalizes_yahoo_underlying_metrics_with_exchange_sessions(monkeypatch):
    worker = DataRefreshWorker()
    latest = date(2026, 10, 16)
    sessions = _stub_weekday_sessions(monkeypatch, latest)
    history = {
        "dates": [session.isoformat() for session in sessions],
        "prices": [10.0] * 20,
        "volumes": [20_000] * 20,
        "price_basis": "close_unadjusted",
    }

    result = worker._normalize_market_gate_metrics(
        "TEST",
        {
            "quote_currency": "USD",
            "market_cap_currency": "USD",
            "market_cap": 3_000_000_000,
            "exchange": "NMS",
        },
        history,
        asset_type="us_equity",
    )

    assert result["market_cap_usd"] == 3_000_000_000
    assert result["avg_dollar_volume_usd"] == 200_000
    assert result["liquidity_provenance"]["valid_observations"] == 20
    assert result["market_data_normalization"]["status"] == "complete"
    assert result["liquidity_provenance"]["basis"] == "UNDERLYING_USD_PROXY"


def test_refresh_worker_reuses_only_complete_provenance_bearing_market_gates():
    complete = {
        "merged_data": {
            "asset_type": "us_equity",
            "size_metric_usd": 3_000_000_000,
            "size_metric_provenance": {"source": "yfinance", "as_of": "2026-10-16"},
            "market_cap_usd": 3_000_000_000,
            "avg_dollar_volume_usd": 200_000,
            "market_cap_provenance": {"source": "yfinance", "as_of": "2026-10-16"},
            "liquidity_provenance": {"price_source": "yfinance"},
            "market_data_normalization": {"status": "complete"},
        }
    }
    legacy = {"merged_data": {"market_cap_usd": 3_000_000_000, "avg_dollar_volume_usd": 200_000}}
    blocked = {"merged_data": {**complete["merged_data"], "market_data_normalization": {"status": "blocked"}}}

    assert DataRefreshWorker._has_normalized_market_gates(complete)
    assert not DataRefreshWorker._has_normalized_market_gates(legacy)
    assert not DataRefreshWorker._has_normalized_market_gates(blocked)


def test_refresh_worker_normalizes_ars_underlying_with_explicit_fx_reference(monkeypatch):
    worker = DataRefreshWorker()
    latest = date(2026, 10, 16)
    sessions = _stub_weekday_sessions(monkeypatch, latest)

    class FxProvider:
        def history(self, reference, date_from, date_to):
            assert reference == "MEP"
            assert date_from <= sessions[0]
            assert date_to == sessions[-1]
            return [
                FxObservation(
                    observed_at=datetime.combine(day, datetime.min.time(), timezone.utc),
                    sell=1000,
                )
                for day in sessions
            ]

    worker.fx_provider = FxProvider()
    history = {
        "dates": [day.isoformat() for day in sessions],
        "prices": [10_000.0] * len(sessions),
        "volumes": [10_000] * len(sessions),
        "price_basis": "close_unadjusted",
    }
    result = worker._normalize_market_gate_metrics(
        "TEST",
        {
            "quote_currency": "ARS",
            "market_cap_currency": "ARS",
            "market_cap": 2_000_000_000_000,
            "exchange": "NMS",
            "fx_reference": "MEP",
        },
        history,
        asset_type="us_equity",
    )

    assert result["market_cap_usd"] == 2_000_000_000
    assert result["avg_dollar_volume_usd"] == 100_000
    assert result["market_data_normalization"]["status"] == "complete"
    assert result["liquidity_provenance"]["fx_side"] == "sell"


def test_etf_gate_uses_dated_aum_without_populating_market_cap(monkeypatch):
    worker = DataRefreshWorker()
    latest = date(2026, 10, 16)
    sessions = _stub_weekday_sessions(monkeypatch, latest)
    history = {
        "dates": [session.isoformat() for session in sessions],
        "prices": [100.0] * 20,
        "volumes": [2_000] * 20,
        "price_basis": "close_unadjusted",
    }
    result = worker._normalize_market_gate_metrics(
        "TESTETF",
        {
            "quote_currency": "USD", "exchange": "NMS",
            "aum": 2_500_000_000, "aum_currency": "USD",
            "aum_as_of": "2026-10-15", "aum_source": "fund-provider",
            "market_cap": 99_000_000_000, "market_cap_currency": "USD",
        },
        history,
        asset_type="etf",
    )

    assert result["aum_usd"] == 2_500_000_000
    assert result.get("market_cap_usd") is None
    assert result["size_metric_usd"] == result["aum_usd"]
    assert result["size_metric_provenance"]["source"] == "fund-provider"
    assert result["market_data_normalization"]["status"] == "complete"


def test_etf_gate_blocks_missing_aum_date_even_when_market_cap_exists(monkeypatch):
    worker = DataRefreshWorker()
    latest = date(2026, 10, 16)
    sessions = _stub_weekday_sessions(monkeypatch, latest)
    history = {
        "dates": [session.isoformat() for session in sessions],
        "prices": [100.0] * 20,
        "volumes": [2_000] * 20,
        "price_basis": "close_unadjusted",
    }
    result = worker._normalize_market_gate_metrics(
        "TESTETF",
        {
            "quote_currency": "USD", "exchange": "NMS",
            "aum": 2_500_000_000, "aum_currency": "USD",
            "market_cap": 99_000_000_000, "market_cap_currency": "USD",
        },
        history,
        asset_type="etf",
    )

    assert result["market_data_normalization"]["status"] == "blocked"
    assert result.get("size_metric_usd") is None
    assert any("as-of date" in error for error in result["market_data_normalization"]["errors"])


def test_aum_normalization_keeps_metric_and_provenance_separate():
    result = normalize_aum_usd(
        2_000_000_000, currency="USD", as_of=date(2026, 10, 16), source="fund-provider"
    )

    assert result["aum_usd"] == 2_000_000_000
    assert result["aum_provenance"]["as_of"] == "2026-10-16"
    assert "market_cap_usd" not in result


def _stub_weekday_sessions(monkeypatch, latest: date) -> list[date]:
    from datetime import timedelta

    dates = []
    cursor = latest
    while len(dates) < 20:
        if cursor.weekday() < 5:
            dates.append(cursor)
        cursor -= timedelta(days=1)
    result = sorted(dates)
    monkeypatch.setattr(
        "idos.workers.data.refresh_worker.expected_us_market_sessions",
        lambda start, end, exchange: result,
    )
    return result
