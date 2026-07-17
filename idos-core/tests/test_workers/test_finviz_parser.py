"""Test finviz.com HTML parser logic without network calls."""

from bs4 import BeautifulSoup

from idos.workers.data.finviz import FinvizWorker


SNAPSHOT_HTML = """
<table class="snapshot-table2">
<tr>
  <td>Index</td><td>S&P 500</td>
  <td>P/E</td><td>25.3</td>
</tr>
<tr>
  <td>Market Cap</td><td>85.3B</td>
  <td>EPS (ttm)</td><td>12.45</td>
</tr>
<tr>
  <td>ROE</td><td>28.5%</td>
  <td>RSI (14)</td><td>62.4</td>
</tr>
<tr>
  <td>Beta</td><td>1.25</td>
  <td>Dividend</td><td>-</td>
</tr>
</table>
"""


def test_parse_snapshot():
    worker = FinvizWorker()
    soup = BeautifulSoup(SNAPSHOT_HTML, "lxml")
    data = worker._parse_snapshot(soup, "MELI")
    assert data["pe_ratio"] == 25.3
    assert data["market_cap"] == 85_300_000_000
    assert data["eps_ttm"] == 12.45
    assert data["roe_pct"] == 28.5
    assert data["rsi_14"] == 62.4
    assert data["beta_5y"] == 1.25
    assert data.get("dividend_fwd") is None
