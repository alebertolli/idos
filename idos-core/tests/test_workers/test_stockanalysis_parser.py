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


def test_worker_requires_ticker():
    worker = StockAnalysisWorker()
    import pytest
    with pytest.raises(ValueError, match="No ticker provided"):
        worker.run({})
