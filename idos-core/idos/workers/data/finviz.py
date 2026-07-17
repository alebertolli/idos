import time
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

from idos.workers.base import BaseWorker, WorkerResult, WorkerStatus

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

BASE_URL = "https://finviz.com/quote.ashx?t={ticker}"


class FinvizWorker(BaseWorker):
    name = "finviz"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.timeout = self.config.get("timeout", 30)
        self.delay = self.config.get("delay", 1.5)

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        ticker = context.get("ticker", "").upper().strip()
        if not ticker:
            msg = "No ticker provided"
            raise ValueError(msg)

        url = BASE_URL.format(ticker=ticker)
        headers = {
            "User-Agent": USER_AGENTS[0],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        resp = requests.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()

        time.sleep(self.delay)

        soup = BeautifulSoup(resp.text, "lxml")
        data = self._parse_snapshot(soup, ticker)
        data["ticker"] = ticker
        data["source"] = "finviz.com"
        return data

    def _parse_snapshot(self, soup: BeautifulSoup, ticker: str) -> dict[str, Any]:
        data: dict[str, Any] = {}
        table = soup.find("table", class_="snapshot-table2")
        if not table:
            return data

        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            for i in range(0, len(cells) - 1, 2):
                label = cells[i].get_text(strip=True)
                value = cells[i + 1].get_text(strip=True)
                key = self._normalize_label(label)
                if key:
                    data[key] = self._parse_value(value)
        return data

    def _normalize_label(self, label: str) -> Optional[str]:
        mapping = {
            "Index": "index",
            "P/E": "pe_ratio",
            "EPS (ttm)": "eps_ttm",
            "Insider Own": "insider_own_pct",
            "Shs Outstand": "shares_outstanding",
            "Market Cap": "market_cap",
            "Forward P/E": "forward_pe",
            "EPS next Y": "eps_growth_next_year_pct",
            "Insider Trans": "insider_transactions",
            "Shs Float": "float_shares",
            "Income": "net_income",
            "PEG": "peg_ratio",
            "EPS next Q": "eps_growth_next_quarter_pct",
            "Inst Own": "institutional_own_pct",
            "Book/sh": "book_value_per_share",
            "Sales": "revenue_ttm",
            "P/S": "ps_ratio",
            "EPS this Y": "eps_growth_this_year_pct",
            "Inst Trans": "institutional_transactions",
            "Cash/sh": "cash_per_share",
            "ROI": "roi_pct",
            "EPS next 5Y": "eps_growth_5y_pct",
            "ROE": "roe_pct",
            "LT Debt/Eq": "debt_equity_ratio",
            "ROA": "roa_pct",
            "52-Wk High": "high_52w",
            "SMA50": "ma_50d",
            "Curr R/R": "current_ratio",
            "RSI (14)": "rsi_14",
            "SMA200": "ma_200d",
            "Rel Volume": "relative_volume",
            "Volume": "volume",
            "Target Price": "price_target_avg",
            "Beta": "beta_5y",
            "Dividend": "dividend_fwd",
            "Gross Margin": "gross_margin_pct",
            "Oper. Margin": "operating_margin_pct",
            "Profit Margin": "net_margin_pct",
            "P/B": "pb_ratio",
            "P/FCF": "p_fcf_ratio",
        }
        return mapping.get(label.strip())

    def _parse_value(self, value: str) -> Any:
        cleaned = value.strip().replace(",", "")
        if cleaned in ("-", "", "N/A"):
            return None
        try:
            cleaned_pct = cleaned.replace("%", "").replace("$", "").replace("+", "")
            if cleaned_pct.endswith("B"):
                return float(cleaned_pct[:-1]) * 1_000_000_000
            if cleaned_pct.endswith("M"):
                return float(cleaned_pct[:-1]) * 1_000_000
            if cleaned_pct.endswith("%"):
                return float(cleaned_pct[:-1])
            return float(cleaned_pct)
        except ValueError:
            return cleaned
