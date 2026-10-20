import calendar
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

from idos.workers.base import BaseWorker, WorkerResult, WorkerStatus

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

BASE_URL = "https://stockanalysis.com/stocks/{ticker}/statistics/"
FINANCIALS_URL = "https://stockanalysis.com/stocks/{ticker}/financials/"
FORECAST_URL = "https://stockanalysis.com/stocks/{ticker}/forecast/"


class StockAnalysisWorker(BaseWorker):
    name = "stockanalysis"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.timeout = self.config.get("timeout", 30)
        self.delay = self.config.get("delay", 1.0)

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        ticker = context.get("ticker", "").upper().strip()
        if not ticker:
            msg = "No ticker provided"
            raise ValueError(msg)

        url = BASE_URL.format(ticker=ticker)
        headers = {
            "User-Agent": USER_AGENTS[0],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        resp = requests.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        data = self._parse_statistics(soup, ticker)
        provider_updated_date = self._parse_provider_updated_date(soup)
        if provider_updated_date:
            data["provider_data_updated_date"] = provider_updated_date

        financials_url = FINANCIALS_URL.format(ticker=ticker.lower())
        source_urls = [url]
        try:
            time.sleep(self.delay)
            financials_response = requests.get(
                financials_url, headers=headers, timeout=self.timeout
            )
            financials_response.raise_for_status()
            source_urls.append(financials_url)
            financials_soup = BeautifulSoup(financials_response.text, "lxml")
            financials_data = self._parse_financials(financials_soup)
            data.update(financials_data)
            financials_updated_date = self._parse_provider_updated_date(financials_soup)
            if financials_updated_date:
                data["financials_data_updated_date"] = financials_updated_date
        except requests.RequestException:
            # Preserve statistics data; missing financial metrics remain subject
            # to the existing fail-closed Scout/Assessment quality gates.
            data["data_quality_warnings"] = ["stockanalysis_financials_page_unavailable"]

        data["financial_data_observed_at"] = datetime.now(timezone.utc).isoformat()
        data["ticker"] = ticker
        data["source"] = "stockanalysis.com"
        data["url"] = url
        metric_metadata = {}
        for field in ("operating_margin_pct", "fcf"):
            if field in data and isinstance(data[field], (int, float)):
                metric_metadata[field] = {
                    "period_type": "TTM",
                    "period_end_date": data.get("period_end_date"),
                    "unit": "percentage_points" if field.endswith("_pct") else "provider_financial_currency",
                    "currency": data.get("financial_currency"),
                    "source_url": url,
                }
        if "revenue_growth_pct" in data:
            metric_metadata["revenue_growth_pct"] = {
                "period_type": data.get("financial_period_type"),
                "period_end_date": data.get("period_end_date"),
                "unit": "percentage_points",
                "currency": None,
                "source_url": financials_url,
            }
        if metric_metadata:
            data["financial_metric_metadata"] = metric_metadata
        field_sources = {
            key: ["stockanalysis.com"]
            for key in data
            if key not in {
                "ticker", "source", "url", "financial_data_observed_at",
                "data_quality_warnings",
            }
        }
        field_sources["financial_data_observed_at"] = ["stockanalysis.com"]
        financial_fields = {
            "revenue_growth_pct", "period_end_date", "financial_period_type",
            "financials_data_updated_date", "financial_metric_metadata",
        }
        field_urls = {
            key: financials_url if key in financial_fields else url
            for key in field_sources
        }
        data["data_provenance"] = {
            "source_count": 1,
            "sources_used": ["stockanalysis.com"],
            "source_urls": source_urls,
            "field_sources": field_sources,
            "field_urls": field_urls,
            "conflicts": [],
        }

        return data

    @staticmethod
    def _parse_provider_updated_date(soup: BeautifulSoup) -> str | None:
        """Return StockAnalysis's displayed data-update date, never retrieval time."""
        match = re.search(
            r"last updated\s*:\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
            soup.get_text(" ", strip=True),
            re.IGNORECASE,
        )
        if not match:
            return None
        for date_format in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(match.group(1), date_format).date().isoformat()
            except ValueError:
                continue
        return None

    def _parse_financials(self, soup: BeautifulSoup) -> dict[str, Any]:
        """Extract TTM revenue growth and its accounting period from financials."""
        for table in soup.find_all("table"):
            revenue_growth: float | None = None
            period_end_date: str | None = None
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                values = [cell.get_text(" ", strip=True) for cell in cells]
                if len(values) < 2:
                    continue

                label = re.sub(r"\s+", " ", values[0]).strip().lower()
                if label == "revenue growth":
                    parsed = self._parse_value(values[1])
                    if isinstance(parsed, (float, int)):
                        revenue_growth = float(parsed)
                elif label == "period ending":
                    period_end_date = self._parse_period_end(values[1])

            # Pair the period with revenue growth from the same statement table.
            if revenue_growth is not None:
                result: dict[str, Any] = {"revenue_growth_pct": revenue_growth}
                if period_end_date:
                    result["period_end_date"] = period_end_date
                    result["financial_period_type"] = "TTM"
                return result
        return {}

    @staticmethod
    def _parse_period_end(value: str) -> str | None:
        match = re.search(r"\b([A-Za-z]{3,9})\s+['’]?(\d{2,4})\b", value.strip())
        if not match:
            return None
        for month_format in ("%b", "%B"):
            try:
                month = datetime.strptime(match.group(1), month_format).month
                year_text = match.group(2)
                year = int(year_text)
                if len(year_text) == 2:
                    year += 2000 if year < 70 else 1900
                day = calendar.monthrange(year, month)[1]
                return datetime(year, month, day).date().isoformat()
            except ValueError:
                continue
        return None

    def _parse_statistics(self, soup: BeautifulSoup, ticker: str) -> dict[str, Any]:
        data: dict[str, Any] = {}
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) >= 2:
                    label = cells[0].get_text(strip=True)
                    value = cells[1].get_text(strip=True)
                    self._set_metric(data, label, value)
        return data

    def fetch_forecast(self, ticker: str) -> dict[str, Any]:
        """Fetch analyst price targets (USD) from the stockanalysis.com forecast page.

        Returns keys: price_target_avg, price_target_low, price_target_median,
        price_target_high. Empty dict on failure to parse.
        """
        url = FORECAST_URL.format(ticker=ticker.lower())
        headers = {
            "User-Agent": USER_AGENTS[0],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        resp = requests.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        time.sleep(self.delay)
        soup = BeautifulSoup(resp.text, "lxml")
        data = self._parse_forecast(soup)
        data["ticker"] = ticker.upper()
        data["source"] = "stockanalysis.com"
        data["url"] = url
        return data

    @staticmethod
    def _parse_forecast_value(value: str) -> Optional[float]:
        m = re.search(r"\$([\d,]+\.?\d*)", value or "")
        if not m:
            return None
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None

    def _parse_forecast(self, soup: BeautifulSoup) -> dict[str, Any]:
        data: dict[str, Any] = {}
        headers: list[str] = []
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True) for th in table.find_all("th")]
            if any("target" in h.lower() for h in headers) and any("average" in h.lower() for h in headers):
                for row in table.find_all("tr"):
                    cells = row.find_all("td")
                    texts = [c.get_text(strip=True) for c in cells]
                    if not texts:
                        continue
                    if "price" not in texts[0].lower():
                        continue
                    for col, header in enumerate(headers):
                        if col == 0 or col >= len(texts):
                            continue
                        num = self._parse_forecast_value(texts[col])
                        if num is None:
                            continue
                        hlow = header.lower()
                        if "low" in hlow:
                            data["price_target_low"] = num
                        elif "median" in hlow:
                            data["price_target_median"] = num
                        elif "high" in hlow:
                            data["price_target_high"] = num
                        elif "average" in hlow or "target" in hlow:
                            data["price_target_avg"] = num
                break

        if "price_target_avg" not in data:
            text = soup.get_text(" ", strip=True)
            m = re.search(r"average price target of \$([\d,]+\.?\d*)", text, re.IGNORECASE)
            if m:
                data["price_target_avg"] = float(m.group(1).replace(",", ""))

        return data

    _LABEL_MAP: dict[str, str] = {
        "market cap": "market_cap",
        "enterprise value": "enterprise_value",
        "shares outstanding": "shares_outstanding",
        "float shares": "float_shares",
        "employees": "employees",
        "revenue (ttm)": "revenue_ttm",
        "revenue / share (ttm)": "revenue_per_share_ttm",
        "revenue growth": "revenue_growth_pct",
        "revenue growth (ttm)": "revenue_growth_pct",
        "revenue growth forecast (3y)": "revenue_growth_forecast_3y_pct",
        "gross profit (ttm)": "gross_profit_ttm",
        "ebitda": "ebitda",
        "ebitda margin": "ebitda_margin_pct",
        "operating income (ttm)": "operating_income_ttm",
        "operating margin": "operating_margin_pct",
        "net income (ttm)": "net_income_ttm",
        "earnings per share (ttm)": "eps_ttm",
        "diluted eps (ttm)": "diluted_eps_ttm",
        "dividend (fwd)": "dividend_fwd",
        "dividend yield (fwd)": "dividend_yield_pct",
        "payout ratio": "payout_ratio_pct",
        "shares outstanding/free float": "free_float_pct",
        "price / earnings (ttm)": "pe_ratio_ttm",
        "pe ratio": "pe_ratio_ttm",
        "forward pe": "forward_pe",
        "price / sales (ttm)": "ps_ratio_ttm",
        "ps ratio": "ps_ratio_ttm",
        "forward ps": "forward_ps",
        "p/fcf ratio (ttm)": "p_fcf_ratio",
        "p/fcf ratio": "p_fcf_ratio",
        "price / book": "pb_ratio",
        "pb ratio": "pb_ratio",
        "peg ratio": "peg_ratio",
        "eps growth (this year)": "eps_growth_this_year_pct",
        "eps growth (next year)": "eps_growth_next_year_pct",
        "eps growth (next 5 years)": "eps_growth_5y_pct",
        "eps growth forecast (3y)": "eps_growth_forecast_3y_pct",
        "revenue growth (next year)": "revenue_growth_next_year_pct",
        "return on assets": "roa_pct",
        "return on assets (roa)": "roa_pct",
        "return on equity": "roe_pct",
        "return on equity (roe)": "roe_pct",
        "return on invested capital": "roic_pct",
        "return on invested capital (roic)": "roic_pct",
        "debt / equity ratio": "debt_equity_ratio",
        "debt / equity": "debt_equity_ratio",
        "current ratio": "current_ratio",
        "quick ratio": "quick_ratio",
        "gross margin": "gross_margin_pct",
        "net margin": "net_margin_pct",
        "pretax margin": "pretax_margin_pct",
        "fcf yield": "fcf_yield_pct",
        "fcf margin": "fcf_margin_pct",
        "fcf per share": "fcf_per_share",
        "short ratio": "short_ratio",
        "short ratio (days to cover)": "short_ratio",
        "short % of float": "short_pct_of_float",
        "analyst recommendation": "analyst_recommendation",
        "analyst consensus": "analyst_consensus",
        "price target": "price_target_avg",
        "price target (avg)": "price_target_avg",
        "52-week range": "range_52w",
        "52-week low": "low_52w",
        "52-week high": "high_52w",
        "50-day moving average": "ma_50d",
        "200-day moving average": "ma_200d",
        "avg volume (today)": "volume_avg",
        "average volume (20 days)": "volume_avg",
        "relative volume": "relative_volume",
        "beta (5y)": "beta_5y",
        "volume": "volume",
        "avg volume (week)": "volume_avg_week",
        "avg volume (month)": "volume_avg_month",
        "avg volume (quarter)": "volume_avg_quarter",
        "p/e ratio (ttm)": "pe_ratio_ttm",
        "p/e": "pe_ratio_ttm",
        "roic": "roic_pct",
        "roe": "roe_pct",
        "roa": "roa_pct",
        "debt / equity": "debt_equity_ratio",
        "d/e": "debt_equity_ratio",
        "fcf": "fcf",
        "free cash flow": "fcf",
        "fcf yield": "fcf_yield_pct",
        "gross margin": "gross_margin_pct",
        "net margin": "net_margin_pct",
        "operating margin": "operating_margin_pct",
        "ebitda margin": "ebitda_margin_pct",
        "ebitda": "ebitda",
        "ebit": "ebit",
        "ev / ebitda": "ev_ebitda",
        "ev / ebit": "ev_ebit",
        "ev / fcf": "ev_fcf",
        "ev / sales": "ev_sales",
        "debt / ebitda": "debt_ebitda",
        "revenue": "revenue_ttm",
    }

    def _set_metric(self, data: dict[str, Any], label: str, value: str):
        normalized = label.lower().strip()
        key = self._LABEL_MAP.get(normalized)
        if key is None:
            return
        data[key] = self._parse_value(value)

    def _parse_value(self, value: str) -> Any:
        cleaned = value.strip()
        if cleaned == "" or cleaned == "—" or cleaned == "N/A":
            return None
        cleaned = cleaned.replace(",", "").replace("$", "").replace("%", "")
        if cleaned.endswith("B"):
            try:
                return float(cleaned[:-1]) * 1_000_000_000
            except ValueError:
                return cleaned
        if cleaned.endswith("M"):
            try:
                return float(cleaned[:-1]) * 1_000_000
            except ValueError:
                return cleaned
        if cleaned.endswith("T"):
            try:
                return float(cleaned[:-1]) * 1_000_000_000_000
            except ValueError:
                return cleaned
        try:
            return float(cleaned)
        except ValueError:
            return cleaned

