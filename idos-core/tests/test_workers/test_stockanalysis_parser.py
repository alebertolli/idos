"""Test stockanalysis.com HTML parser logic without network calls."""

from bs4 import BeautifulSoup

from idos.workers.data.stockanalysis import StockAnalysisWorker


def _make_table(rows: list[tuple[str, str]]) -> str:
    trs = ""
    for label, value in rows:
        trs += f"<tr><td>{label}</td><td>{value}</td></tr>"
    return f"<table>{trs}</table>"


def test_parse_market_cap():
    worker = StockAnalysisWorker()
    html = _make_table([("Market Cap", "$85.3B")])
    soup = BeautifulSoup(html, "lxml")
    data = worker._parse_statistics(soup, "MELI")
    assert data.get("market_cap") == 85_300_000_000


def test_parse_pe_ratio():
    worker = StockAnalysisWorker()
    html = _make_table([("Price / Earnings (TTM)", "28.5")])
    soup = BeautifulSoup(html, "lxml")
    data = worker._parse_statistics(soup, "MELI")
    assert data.get("pe_ratio_ttm") == 28.5


def test_parse_roic():
    worker = StockAnalysisWorker()
    html = _make_table([("Return on Invested Capital", "22.4%")])
    soup = BeautifulSoup(html, "lxml")
    data = worker._parse_statistics(soup, "MELI")
    assert data.get("roic_pct") == 22.4


def test_parse_debt_equity():
    worker = StockAnalysisWorker()
    html = _make_table([("Debt / Equity Ratio", "1.45")])
    soup = BeautifulSoup(html, "lxml")
    data = worker._parse_statistics(soup, "MELI")
    assert data.get("debt_equity_ratio") == 1.45


def test_parse_revenue_growth():
    worker = StockAnalysisWorker()
    html = _make_table([("Revenue Growth", "18.5%")])
    soup = BeautifulSoup(html, "lxml")
    data = worker._parse_statistics(soup, "MELI")
    assert data.get("revenue_growth_pct") == 18.5


def test_parse_revenue_growth_forecast_separately_from_actual_growth():
    worker = StockAnalysisWorker()
    html = _make_table([
        ("Revenue Growth Forecast (3Y)", "29.38%"),
        ("EPS Growth Forecast (3Y)", "45.21%"),
    ])
    soup = BeautifulSoup(html, "lxml")
    data = worker._parse_statistics(soup, "ASML")

    assert data["revenue_growth_forecast_3y_pct"] == 29.38
    assert data["eps_growth_forecast_3y_pct"] == 45.21
    assert "revenue_growth_pct" not in data


def test_parse_missing_value():
    worker = StockAnalysisWorker()
    html = _make_table([("Dividend (FWD)", "—")])
    soup = BeautifulSoup(html, "lxml")
    data = worker._parse_statistics(soup, "MELI")
    assert data.get("dividend_fwd") is None


def test_parse_multiple_metrics():
    worker = StockAnalysisWorker()
    html = _make_table([
        ("Market Cap", "$85.3B"),
        ("P/E Ratio (TTM)", "28.5"),
        ("Revenue Growth", "18.5%"),
        ("Debt / Equity Ratio", "1.45"),
        ("ROIC", "22.4%"),
        ("Employees", "35,000"),
    ])
    soup = BeautifulSoup(html, "lxml")
    data = worker._parse_statistics(soup, "MELI")
    assert data.get("market_cap") == 85_300_000_000
    assert data.get("roic_pct") == 22.4
    assert data.get("revenue_growth_pct") == 18.5


def test_parse_range_52w():
    worker = StockAnalysisWorker()
    html = _make_table([("52-Week Range", "1,200.00 - 2,050.00")])
    soup = BeautifulSoup(html, "lxml")
    data = worker._parse_statistics(soup, "MELI")
    assert data.get("range_52w") == "1200.00 - 2050.00"


def test_parse_beta():
    worker = StockAnalysisWorker()
    html = _make_table([("Beta (5Y)", "1.25")])
    soup = BeautifulSoup(html, "lxml")
    data = worker._parse_statistics(soup, "MELI")
    assert data.get("beta_5y") == 1.25


def test_parse_ticker():
    worker = StockAnalysisWorker()
    html = _make_table([("Market Cap", "$10B")])
    soup = BeautifulSoup(html, "lxml")
    data = worker._parse_statistics(soup, "AAPL")
    # ticker is injected by run(), not parser; but parser should not crash


def test_parse_provider_data_update_date_as_source_metadata():
    worker = StockAnalysisWorker()
    soup = BeautifulSoup(
        "<main>Data Source: S&amp;P Global. Last updated: Oct 19, 2026</main>",
        "lxml",
    )

    assert worker._parse_provider_updated_date(soup) == "2026-10-19"


def test_parse_provider_data_update_date_rejects_unrecognized_or_missing_date():
    worker = StockAnalysisWorker()

    assert worker._parse_provider_updated_date(BeautifulSoup("Last updated: N/A", "lxml")) is None
    assert worker._parse_provider_updated_date(BeautifulSoup("No update metadata", "lxml")) is None


def test_run_persists_provider_date_separately_from_retrieval_timestamp(monkeypatch):
    from types import SimpleNamespace

    import idos.workers.data.stockanalysis as stockanalysis_module

    html = """
    <table><tr><td>Operating Margin</td><td>20%</td></tr></table>
    <footer>Data Source: S&amp;P Global Market Intelligence. Last updated: Oct 19, 2026</footer>
    """
    monkeypatch.setattr(
        stockanalysis_module.requests,
        "get",
        lambda *args, **kwargs: SimpleNamespace(text=html, raise_for_status=lambda: None),
    )
    monkeypatch.setattr(stockanalysis_module.time, "sleep", lambda _delay: None)

    result = StockAnalysisWorker().run({"ticker": "ASML"})

    assert result["provider_data_updated_date"] == "2026-10-19"
    assert result["financial_data_observed_at"]
    assert result["provider_data_updated_date"] != result["financial_data_observed_at"]
    assert result["data_provenance"]["field_sources"]["provider_data_updated_date"] == ["stockanalysis.com"]



def test_parse_financials_captures_ttm_growth_and_period_end():
    worker = StockAnalysisWorker()
    html = _make_table([
        ("Fiscal Year", "TTM"),
        ("Period Ending", "Sep '26"),
        ("Revenue Growth", "22.54%"),
    ])

    result = worker._parse_financials(BeautifulSoup(html, "lxml"))

    assert result["revenue_growth_pct"] == 22.54
    assert result["period_end_date"] == "2026-09-30"
    assert result["financial_data_as_of_date"] == "2026-09-30"
    assert result["financial_period_type"] == "TTM"
    assert result["revenue_growth_history"][0]["unit"] == "percent"


def test_parse_period_end_supports_full_month_and_invalid_input():
    assert StockAnalysisWorker._parse_period_end("September 2026") == "2026-09-30"
    assert StockAnalysisWorker._parse_period_end("not available") is None


def test_run_merges_statistics_and_financials_with_field_source_urls(monkeypatch):
    from types import SimpleNamespace

    import idos.workers.data.stockanalysis as stockanalysis_module

    statistics_html = """
    <table><tr><td>Operating Margin</td><td>38.55%</td></tr></table>
    <footer>Last updated: Oct 19, 2026</footer>
    """
    financials_html = """
    <table>
      <tr><td>Fiscal Year</td><td>TTM</td><td>2025</td></tr>
      <tr><td>Period Ending</td><td>Sep '26</td><td>Dec '25</td></tr>
      <tr><td>Revenue Growth</td><td>22.54%</td><td>18.2%</td></tr>
    </table>
    <footer>Last updated: Oct 14, 2026</footer>
    """

    def fake_get(url, **_kwargs):
        body = financials_html if "/financials/" in url else statistics_html
        return SimpleNamespace(text=body, raise_for_status=lambda: None)

    monkeypatch.setattr(stockanalysis_module.requests, "get", fake_get)
    monkeypatch.setattr(stockanalysis_module.time, "sleep", lambda _delay: None)

    result = StockAnalysisWorker().run({"ticker": "ASML"})
    provenance = result["data_provenance"]

    assert result["operating_margin_pct"] == 38.55
    assert result["revenue_growth_pct"] == 22.54
    assert result["period_end_date"] == "2026-09-30"
    assert result["provider_data_updated_date"] == "2026-10-19"
    assert result["financials_data_updated_date"] == "2026-10-14"
    assert provenance["field_urls"]["operating_margin_pct"].endswith("/statistics/")
    assert provenance["field_urls"]["revenue_growth_pct"].endswith("/financials/")
    assert provenance["field_urls"]["period_end_date"].endswith("/financials/")
    assert result["financial_metric_metadata"]["operating_margin_pct"] == {
        "period_type": "TTM", "period_end_date": "2026-09-30",
        "unit": "percentage_points", "currency": None,
        "source_url": "https://stockanalysis.com/stocks/ASML/statistics/",
    }
    assert result["financial_metric_metadata"]["revenue_growth_pct"]["period_type"] == "TTM"
    assert result["financial_metric_metadata"]["revenue_growth_pct"]["period_end_date"] == "2026-09-30"



def test_run_keeps_statistics_when_financials_page_is_unavailable(monkeypatch):
    from types import SimpleNamespace

    import requests

    import idos.workers.data.stockanalysis as stockanalysis_module

    def fake_get(url, **_kwargs):
        if "/financials/" in url:
            raise requests.Timeout("financials timeout")
        return SimpleNamespace(
            text="<table><tr><td>Operating Margin</td><td>20%</td></tr></table>",
            raise_for_status=lambda: None,
        )

    monkeypatch.setattr(stockanalysis_module.requests, "get", fake_get)
    monkeypatch.setattr(stockanalysis_module.time, "sleep", lambda _delay: None)

    result = StockAnalysisWorker().run({"ticker": "ASML"})

    assert result["operating_margin_pct"] == 20
    assert "revenue_growth_pct" not in result
    assert result["data_quality_warnings"] == ["stockanalysis_financials_page_unavailable"]
    assert result["data_provenance"]["source_urls"] == [
        "https://stockanalysis.com/stocks/ASML/statistics/"
    ]


def test_worker_requires_ticker():
    worker = StockAnalysisWorker()
    import pytest
    with pytest.raises(ValueError, match="No ticker provided"):
        worker.run({})



def test_parse_financial_statement_histories_with_reported_periods():
    worker = StockAnalysisWorker()
    html = """
    <table>
      <tr><th>Fiscal Year</th><th>TTM</th><th>FY 2025</th><th>FY 2024</th><th>FY 2023</th></tr>
      <tr><td>Period Ending</td><td>Sep '26 Sep 27, 2026</td><td>Dec '25 Dec 31, 2025</td><td>Dec '24 Dec 31, 2024</td><td>Dec '23 Dec 31, 2023</td></tr>
      <tr><td>Revenue Revenue Growth</td><td>39,474</td><td>32,667</td><td>28,263</td><td>27,559</td></tr>
      <tr><td>Revenue Growth</td><td>22.54%</td><td>15.58%</td><td>2.56%</td><td>30.16%</td></tr>
      <tr><td>Net Income Net Income Growth</td><td>13,474</td><td>9,609</td><td>7,572</td><td>7,839</td></tr>
    </table>
    <table>
      <tr><th>Fiscal Year</th><th>TTM</th><th>FY 2025</th><th>FY 2024</th></tr>
      <tr><td>Period Ending</td><td>Sep '26 Sep 27, 2026</td><td>Dec '25 Dec 31, 2025</td><td>Dec '24 Dec 31, 2024</td></tr>
      <tr><td>Free Cash Flow Free Cash Flow Growth</td><td>21,162</td><td>11,085</td><td>9,099</td></tr>
      <tr><td>Free Cash Flow Growth</td><td>136.10%</td><td>21.82%</td><td>176.75%</td></tr>
      <tr><td>Gross Margin</td><td>54.34%</td><td>52.83%</td><td>51.28%</td></tr>
    </table>
    """
    result = worker._parse_financials(BeautifulSoup(html, "lxml"))
    assert result["revenue_history"][0] == {
        "value": 39474.0, "period": "TTM", "period_end": "2026-09-27", "unit": "source_reported_amount",
    }
    assert result["fcf_history"][0]["value"] == 21162.0
    assert result["fcf_growth_history"][0]["value"] == 136.1
    assert result["gross_margin_history"][0]["value"] == 54.34
    assert result["net_income_history"][0]["value"] == 13474.0
    assert result["financial_data_as_of_date"] == "2026-09-27"
