from types import SimpleNamespace

from idos.workers.data import yahoo
from idos.workers.data.yahoo import YahooFinanceWorker


def test_yahoo_worker_keeps_fast_info_when_summary_endpoint_fails(monkeypatch):
    class Stock:
        @property
        def info(self):
            raise RuntimeError("summary endpoint unavailable")

        fast_info = {
            "currency": "USD",
            "exchange": "NMS",
            "market_cap": 12_000_000_000,
            "last_price": 120.0,
        }

        def history(self, **kwargs):
            assert kwargs == {"period": "1y", "auto_adjust": False}
            return SimpleNamespace(empty=True)

    monkeypatch.setattr(yahoo.yf, "Ticker", lambda ticker: Stock())

    result = YahooFinanceWorker().run({"ticker": "test"})

    assert result["ticker"] == "TEST"
    assert result["market_cap"] == 12_000_000_000
    assert result["market_cap_currency"] == "USD"
    assert result["quote_currency"] == "USD"
    assert result["exchange"] == "NMS"
    assert result["price"] == 120.0
    assert result["provider_errors"] == ["info: summary endpoint unavailable"]


def test_yahoo_worker_keeps_summary_when_history_endpoint_fails(monkeypatch):
    class Stock:
        info = {
            "currency": "USD",
            "marketCap": 2_000_000_000,
            "currentPrice": 20.0,
        }
        fast_info = {}

        def history(self, **kwargs):
            raise RuntimeError("history endpoint unavailable")

    monkeypatch.setattr(yahoo.yf, "Ticker", lambda ticker: Stock())

    result = YahooFinanceWorker().run({"ticker": "test"})

    assert result["market_cap"] == 2_000_000_000
    assert result["price"] == 20.0
    assert "price_history" not in result
    assert result["provider_errors"] == ["history: history endpoint unavailable"]


def test_yahoo_free_cash_flow_is_labeled_as_levered(monkeypatch):
    class Stock:
        info = {
            "currency": "USD",
            "financialCurrency": "EUR",
            "freeCashflow": 10_374_124_544,
        }
        fast_info = {}

        def history(self, **kwargs):
            return SimpleNamespace(empty=True)

    monkeypatch.setattr(yahoo.yf, "Ticker", lambda ticker: Stock())

    result = YahooFinanceWorker().run({"ticker": "ASML"})

    assert result["levered_fcf"] == 10_374_124_544
    assert result["financial_currency"] == "EUR"
    assert "fcf" not in result


def test_yahoo_financial_metrics_declare_period_and_units(monkeypatch):
    class Stock:
        info = {
            "financialCurrency": "USD",
            "mostRecentQuarter": 1790467200,
            "operatingMargins": 0.183,
            "revenueGrowth": 0.552,
        }
        fast_info = {}

        def history(self, **kwargs):
            return SimpleNamespace(empty=True)

    monkeypatch.setattr(yahoo.yf, "Ticker", lambda ticker: Stock())

    result = YahooFinanceWorker().run({"ticker": "ASML"})

    metadata = result["financial_metric_metadata"]
    assert result["operating_margin_pct"] == 18.3
    assert result["revenue_growth_pct"] == 55.2
    assert metadata["operating_margin_pct"]["period_type"] == "PROVIDER_REPORTED_UNSPECIFIED"
    assert metadata["revenue_growth_pct"]["period_type"] == "PROVIDER_REPORTED_UNSPECIFIED"
    assert metadata["operating_margin_pct"]["period_end_date"] == "2026-09-27"
