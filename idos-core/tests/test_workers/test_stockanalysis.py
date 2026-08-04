from bs4 import BeautifulSoup

from idos.workers.data.stockanalysis import StockAnalysisWorker

FORECAST_HTML = """
<html><body>
<h1>ASML Stock Forecast</h1>
<p>According to 44 analysts, ASML Holding stock has a consensus rating of "Strong Buy"
and an average price target of $2,126.</p>
<table>
<tr><th>Target</th><th>Low</th><th>Average</th><th>Median</th><th>High</th></tr>
<tr><td>Price</td><td>$885.98</td><td>$2,126</td><td>$2,302</td><td>$2,862</td></tr>
<tr><td>Change</td><td>-46.06%</td><td>+29.45%</td><td>+40.14%</td><td>+74.24%</td></tr>
</table>
</body></html>
"""


class TestStockAnalysisForecast:
    def test_parse_forecast_table(self):
        worker = StockAnalysisWorker()
        soup = BeautifulSoup(FORECAST_HTML, "lxml")
        data = worker._parse_forecast(soup)

        assert data["price_target_avg"] == 2126.0
        assert data["price_target_low"] == 885.98
        assert data["price_target_median"] == 2302.0
        assert data["price_target_high"] == 2862.0

    def test_parse_forecast_regex_fallback(self):
        html = ("<html><body><p>has an average price target of $2,126 "
                "and a low of $885.98.</p></body></html>")
        worker = StockAnalysisWorker()
        soup = BeautifulSoup(html, "lxml")
        data = worker._parse_forecast(soup)

        assert data["price_target_avg"] == 2126.0

    def test_parse_forecast_empty_page(self):
        worker = StockAnalysisWorker()
        soup = BeautifulSoup("<html><body><p>No data</p></body></html>", "lxml")
        data = worker._parse_forecast(soup)

        assert data == {}
