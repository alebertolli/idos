import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from idos.market.liquidity import FxObservation
from idos.market.liquidity import expected_us_market_sessions
from idos.workers.data.refresh_worker import DataRefreshWorker
from idos.workers.data.validator import DataValidator


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


def test_refresh_worker_routes_etfs_to_yahoo_without_reporting_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    worker = DataRefreshWorker()
    worker._asset_type_for_ticker = lambda _ticker: "etf"
    worker._fetch_sec_fundamentals = lambda _ticker, _asset_type: None
    worker._normalize_market_gate_metrics = lambda *_args, **_kwargs: {
        "asset_type": "etf",
        "market_cap_usd": None,
        "avg_dollar_volume_usd": 125_000_000,
        "market_data_normalization": {"status": "complete", "errors": []},
        "liquidity_provenance": {"basis": "UNDERLYING_USD_PROXY"},
    }
    worker._save_company_info = lambda *_args, **_kwargs: None
    worker._save_price_history = lambda *_args, **_kwargs: None

    calls = []
    errors_reported = []

    class Provider:
        def __init__(self, name, result):
            self.name = name
            self.result = result

        def execute(self, context):
            calls.append((self.name, context))
            if self.name == "stockanalysis":
                raise AssertionError("ETFs must not query StockAnalysis")
            return self.result

    class Cache:
        def get(self, _key):
            return None

        def set(self, *_args, **_kwargs):
            return None

    class ErrorManager:
        def report(self, **event):
            errors_reported.append(event)

    yahoo_output = {
        "ticker": "XLF",
        "quote_currency": "USD",
        "exchange": "NMS",
        "price_history": [40.0, 41.0],
        "price_history_dates": ["2026-10-19", "2026-10-20"],
        "volume_history": [1_000_000, 1_100_000],
        "price_history_basis": "close_unadjusted",
    }
    worker.sources["stockanalysis"] = Provider("stockanalysis", None)
    worker.sources["yfinance"] = Provider(
        "yfinance", SimpleNamespace(status="success", output=yahoo_output)
    )
    worker.retry = SimpleNamespace(execute=lambda method, context: method(context))
    worker.cache = Cache()
    worker.error_manager = ErrorManager()

    result = worker.run({"tickers": ["XLF"]})

    assert result["tickers"] == ["XLF"]
    assert calls == [("yfinance", {"ticker": "XLF"})]
    assert not any("degradacion de fuente" in event["message"] for event in errors_reported)


def test_refresh_worker_fetches_sec_fundamentals_only_for_equities():
    config = Path(__file__).parents[3] / "idos-config"
    worker = DataRefreshWorker({"config_path": str(config)})
    calls = []
    cached = {}

    class Cache:
        def get(self, _key):
            return None

        def set(self, key, value, *, source, ttl_seconds):
            cached.update(key=key, value=value, source=source, ttl_seconds=ttl_seconds)

    class SecWorker:
        user_agent = "IDOS tests contact@example.org"

        def execute(self, context):
            calls.append(context)
            return SimpleNamespace(
                status="success",
                output={"revenue_growth_pct": 12.5, "source": "sec_edgar"},
            )

    worker.cache = Cache()
    worker.sources["sec_edgar"] = SecWorker()

    assert worker._fetch_sec_fundamentals("AAPL", "etf") is None
    assert calls == []

    result = worker._fetch_sec_fundamentals("AAPL", "us_equity")

    assert result["revenue_growth_pct"] == 12.5
    assert calls == [{"ticker": "AAPL", "include_filings": False}]
    assert cached["source"] == "sec_edgar"
    assert cached["ttl_seconds"] == 86400

    result = worker._fetch_sec_fundamentals("AAPL", "equity")
    assert result["revenue_growth_pct"] == 12.5
    assert calls[-1] == {"ticker": "AAPL", "include_filings": False}


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


def test_refresh_worker_keeps_levered_fcf_separate_and_prefers_stockanalysis_fundamentals():
    validated = {"merged_data": {"fcf": 4, "operating_margin_pct": 8}, "field_sources": {}}
    DataRefreshWorker._preserve_financial_observations(validated, {
        "stockanalysis.com": {"fcf": 4, "operating_margin_pct": 8},
        "yfinance": {"levered_fcf": -2, "operating_margin_pct": 0.08,
                     "financial_currency": "USD", "financial_data_observed_at": "2026-10-18T00:00:00+00:00"},
    })
    assert validated["merged_data"]["fcf"] == 4
    assert validated["merged_data"]["operating_margin_pct"] == 8
    assert validated["field_sources"]["fcf"] == ["stockanalysis.com"]
    assert validated["merged_data"]["financial_observations"]["fcf"]["values"] == {
        "stockanalysis.com": 4,
    }


def test_refresh_worker_keeps_unspecified_growth_period_non_comparable():
    sources = {
        "stockanalysis.com": {
            "revenue_growth_pct": 22.54,
            "financial_data_observed_at": "2026-10-20T00:00:00+00:00",
            "financial_metric_metadata": {
                "revenue_growth_pct": {
                    "period_type": "TTM", "period_end_date": "2026-09-30",
                    "unit": "percentage_points", "currency": None,
                },
            },
        },
        "yfinance": {
            "revenue_growth_pct": 55.2,
            "financial_data_observed_at": "2026-10-20T00:00:01+00:00",
            "financial_metric_metadata": {
                "revenue_growth_pct": {
                    "period_type": "PROVIDER_REPORTED_UNSPECIFIED", "period_end_date": "2026-09-27",
                    "unit": "percentage_points", "currency": None,
                },
            },
        },
    }
    validated = DataValidator().cross_validate(sources)
    DataRefreshWorker._preserve_financial_observations(validated, sources)

    observation = validated["merged_data"]["financial_observations"]["revenue_growth_pct"]
    assert validated["merged_data"]["revenue_growth_pct"] == 22.54
    assert validated["conflicts"] == []
    assert observation["period_status"] == "SINGLE_SOURCE"
    assert observation["values"] == {"stockanalysis.com": 22.54}
    assert observation["non_comparable_values"] == {"yfinance": 55.2}
    assert observation["non_comparable_reason"] == "missing_period_unit_or_cutoff"


def test_refresh_worker_preserves_yahoo_levered_fcf_provenance():
    source = DataRefreshWorker._yahoo_market_source({
        "ticker": "ASML", "source": "yahoo_finance", "fcf": 99,
        "levered_fcf": 10_374_124_544, "financial_currency": "EUR",
        "financial_metric_metadata": {"levered_fcf": {"period_type": "TTM"}},
    }, None)

    assert source["levered_fcf"] == 10_374_124_544
    assert source["financial_currency"] == "EUR"
    assert source["financial_metric_metadata"]["levered_fcf"]["period_type"] == "TTM"
    assert "fcf" not in source


def test_refresh_worker_normalizes_usd_metrics_without_country_calendar_gate(monkeypatch):
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
            "exchange": "LSE",
        },
        history,
        asset_type="us_equity",
    )

    assert result["quote_currency"] == "USD"
    assert result["market_cap_usd"] == 3_000_000_000
    assert result["avg_dollar_volume_usd"] == 200_000
    assert result["liquidity_provenance"]["valid_observations"] == 20
    assert result["liquidity_provenance"]["currency"] == "USD"
    assert result["liquidity_provenance"]["as_of"] == sessions[-1].isoformat()
    assert result["market_data_normalization"]["status"] == "complete"
    assert result["liquidity_provenance"]["basis"] == "UNDERLYING_USD_PROXY"


def test_refresh_worker_normalizes_country_neutral_equity_type():
    worker = DataRefreshWorker()
    result = worker._normalize_market_gate_metrics(
        "ASML",
        {
            "quote_currency": "USD", "market_cap_currency": "USD",
            "market_cap": 3_000_000_000,
            "avg_dollar_volume_usd": 250_000,
            "liquidity_provenance": {"source": "provider", "as_of": "2026-10-22"},
        },
        None,
        asset_type="equity",
    )

    assert result["market_data_normalization"]["status"] == "complete"
    assert result["market_cap_usd"] == 3_000_000_000
    assert DataRefreshWorker._has_normalized_market_gates(result)


def test_market_gate_retains_yahoo_endpoint_diagnostics():
    result = DataRefreshWorker()._normalize_market_gate_metrics(
        "TEST",
        {"provider_errors": ["info: summary endpoint unavailable"]},
        None,
        asset_type="us_equity",
    )

    assert "Yahoo info: summary endpoint unavailable" in result["market_data_normalization"]["errors"]
    assert any("USD-denominated" in item for item in result["market_data_normalization"]["errors"])


def test_refresh_worker_reuses_only_complete_provenance_bearing_market_gates():
    complete = {
        "merged_data": {
            "asset_type": "us_equity",
            "quote_currency": "USD",
            "size_metric_usd": 3_000_000_000,
            "size_metric_provenance": {"source": "yfinance", "as_of": "2026-10-16", "currency": "USD"},
            "market_cap_usd": 3_000_000_000,
            "avg_dollar_volume_usd": 200_000,
            "market_cap_provenance": {"source": "yfinance", "as_of": "2026-10-16", "currency": "USD"},
            "liquidity_provenance": {"source": "yfinance", "as_of": "2026-10-16", "currency": "USD", "basis": "UNDERLYING_USD_PROXY"},
            "market_data_normalization": {"status": "complete"},
        }
    }
    legacy = {"merged_data": {"market_cap_usd": 3_000_000_000, "avg_dollar_volume_usd": 200_000}}
    blocked = {"merged_data": {**complete["merged_data"], "market_data_normalization": {"status": "blocked"}}}

    assert DataRefreshWorker._has_normalized_market_gates(complete)
    without_currency = {"merged_data": {
        key: value for key, value in complete["merged_data"].items() if key != "quote_currency"
    }}
    assert DataRefreshWorker._has_normalized_market_gates(without_currency)
    assert not DataRefreshWorker._has_normalized_market_gates(legacy)
    assert not DataRefreshWorker._has_normalized_market_gates(blocked)


def test_refresh_worker_uses_direct_usd_metrics_without_ars_conversion():
    worker = DataRefreshWorker()
    result = worker._normalize_market_gate_metrics(
        "TEST",
        {
            "quote_currency": "ARS",
            "market_cap_currency": "ARS",
            "market_cap_usd": 2_000_000_000,
            "avg_dollar_volume_usd": 100_000,
            "market_cap_provenance": {"source": "underlying", "as_of": "2026-10-16"},
            "liquidity_provenance": {"source": "underlying", "as_of": "2026-10-16"},
        },
        None,
        asset_type="us_equity",
    )

    assert result["market_cap_usd"] == 2_000_000_000
    assert result["avg_dollar_volume_usd"] == 100_000
    assert result["market_data_normalization"]["status"] == "complete"
    assert result["market_data_normalization"]["fx_conversion_used"] is False
    assert result["liquidity_provenance"]["currency"] == "USD"


def test_refresh_worker_leaves_local_currency_values_pending_without_usd_metrics():
    result = DataRefreshWorker()._normalize_market_gate_metrics(
        "TEST",
        {"quote_currency": "ARS", "market_cap_currency": "ARS", "market_cap": 2_000_000_000_000},
        None,
        asset_type="us_equity",
    )

    assert result["market_data_normalization"]["status"] == "blocked"
    assert result.get("market_cap_usd") is None
    assert result.get("avg_dollar_volume_usd") is None
    assert any("USD-denominated" in error for error in result["market_data_normalization"]["errors"])


def test_etf_gate_accepts_liquidity_without_any_size_metric(monkeypatch):
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
        },
        history,
        asset_type="etf",
    )

    assert result.get("aum_usd") is None
    assert result.get("market_cap_usd") is None
    assert result.get("size_metric_usd") is None
    assert result["market_data_normalization"]["status"] == "complete"
    assert DataRefreshWorker._has_normalized_market_gates(result)
    assert not DataRefreshWorker._has_normalized_market_gates({**result, "liquidity_provenance": None})
    # Changing the instrument classification cannot bypass equity capital requirements.
    assert not DataRefreshWorker._has_normalized_market_gates({**result, "asset_type": "us_equity"})


def test_etf_gate_ignores_invalid_size_but_requires_aligned_liquidity(monkeypatch):
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
            "aum": None, "market_cap": -1,
        },
        history,
        asset_type="etf",
    )

    assert result["market_data_normalization"]["status"] == "complete"
    assert result.get("size_metric_usd") is None
    blocked = worker._normalize_market_gate_metrics(
        "TESTETF", {"quote_currency": "USD", "exchange": "NMS"}, None, asset_type="etf",
    )
    assert blocked["market_data_normalization"]["status"] == "blocked"
    assert not DataRefreshWorker._has_normalized_market_gates(blocked)


def _stub_weekday_sessions(monkeypatch, latest: date) -> list[date]:
    from datetime import timedelta

    dates = []
    cursor = latest
    while len(dates) < 20:
        if cursor.weekday() < 5:
            dates.append(cursor)
        cursor -= timedelta(days=1)
    result = sorted(dates)
    return result
