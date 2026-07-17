import re
import time
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

from idos.workers.base import BaseWorker, WorkerResult, WorkerStatus

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

BASE_URL = "https://stockanalysis.com/stocks/{ticker}/statistics/"


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

        time.sleep(self.delay)

        soup = BeautifulSoup(resp.text, "lxml")
        data = self._parse_statistics(soup, ticker)
        data["ticker"] = ticker
        data["source"] = "stockanalysis.com"
        data["url"] = url

        return data

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

    _LABEL_MAP: dict[str, str] = {
        "market cap": "market_cap",
        "enterprise value": "enterprise_value",
        "shares outstanding": "shares_outstanding",
        "float shares": "float_shares",
        "employees": "employees",
        "revenue (ttm)": "revenue_ttm",
        "revenue / share (ttm)": "revenue_per_share_ttm",
        "revenue growth": "revenue_growth_pct",
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
        "price / sales (ttm)": "ps_ratio_ttm",
        "p/fcf ratio (ttm)": "p_fcf_ratio",
        "price / book": "pb_ratio",
        "eps growth (this year)": "eps_growth_this_year_pct",
        "eps growth (next year)": "eps_growth_next_year_pct",
        "eps growth (next 5 years)": "eps_growth_5y_pct",
        "revenue growth (next year)": "revenue_growth_next_year_pct",
        "return on assets": "roa_pct",
        "return on equity": "roe_pct",
        "return on invested capital": "roic_pct",
        "debt / equity ratio": "debt_equity_ratio",
        "current ratio": "current_ratio",
        "gross margin": "gross_margin_pct",
        "net margin": "net_margin_pct",
        "fcf yield": "fcf_yield_pct",
        "fcf per share": "fcf_per_share",
        "short ratio": "short_ratio",
        "short % of float": "short_pct_of_float",
        "analyst recommendation": "analyst_recommendation",
        "price target (avg)": "price_target_avg",
        "52-week range": "range_52w",
        "52-week low": "low_52w",
        "52-week high": "high_52w",
        "50-day moving average": "ma_50d",
        "200-day moving average": "ma_200d",
        "avg volume (today)": "volume_avg",
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
        "fcf yield": "fcf_yield_pct",
        "gross margin": "gross_margin_pct",
        "net margin": "net_margin_pct",
        "operating margin": "operating_margin_pct",
        "ebitda margin": "ebitda_margin_pct",
        "revenue": "revenue_ttm",
    }

    def _set_metric(self, data: dict[str, Any], label: str, value: str):
        normalized = label.lower().strip()
        key = self._LABEL_MAP.get(normalized)
        if key is None:
            for pattern, mapped in self._LABEL_MAP.items():
                if normalized.startswith(pattern) or normalized.endswith(pattern):
                    key = mapped
                    break
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
