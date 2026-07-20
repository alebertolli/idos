import re
import time
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from idos.workers.base import BaseWorker
from idos.timezone import AR_TZ

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

class FinvizScreenerScraper(BaseWorker):
    name = "finviz_screener_scraper"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.base_url = config.get("base_url", "https://finviz.com/screener.ashx")
        self.view = config.get("view", "151")
        self.filters = config.get("filters", "")
        self.filter_type = config.get("filter_type", "2")
        self.sort_by = config.get("sort_by", "volume")
        self.delay = config.get("delay", 2.0)
        self.timeout = config.get("timeout", 30)
        self.max_pages = config.get("max_pages", 100)
        self.results_per_page = config.get("results_per_page", 20)

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        cache_path = Path(self.config.get("cache_path", "cache"))
        cache_file = cache_path / "finviz_screener_cache.json"
        cache_ttl_days = self.config.get("cache_ttl_days", 7)

        if cache_file.exists():
            import json
            from datetime import datetime
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            cached_at = datetime.fromisoformat(cached.get("cached_at", "2000-01-01"))
            age_days = (datetime.now(AR_TZ) - cached_at).days
            if age_days < cache_ttl_days:
                print(f"[FINVIZ-SCREENER] Using cached data ({age_days} days old, {len(cached.get('tickers', []))} tickers)")
                return {"tickers": cached["tickers"], "total": cached["total"], "from_cache": True}

        all_tickers = []
        page = 1
        total = 0

        while page <= self.max_pages:
            url = self._build_url(page)
            headers = {
                "User-Agent": USER_AGENTS[0],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }

            try:
                resp = requests.get(url, headers=headers, timeout=self.timeout)
                resp.raise_for_status()
            except requests.RequestException as e:
                print(f"[FINVIZ-SCREENER] Error fetching page {page}: {e}")
                break

            soup = BeautifulSoup(resp.text, "lxml")

            if page == 1:
                total = self._parse_total(soup)
                print(f"[FINVIZ-SCREENER] Total results: {total}")

            tickers = self._parse_page(soup)
            if not tickers:
                break

            all_tickers.extend(tickers)
            print(f"[FINVIZ-SCREENER] Page {page}: {len(tickers)} tickers (total: {len(all_tickers)})")

            if len(all_tickers) >= total:
                break

            page += 1
            time.sleep(self.delay)

        cache_path.mkdir(parents=True, exist_ok=True)
        import json
        from datetime import datetime
        cache_data = {
            "tickers": all_tickers,
            "total": total,
            "cached_at": datetime.now(AR_TZ).isoformat(),
        }
        cache_file.write_text(json.dumps(cache_data, indent=2), encoding="utf-8")

        return {"tickers": all_tickers, "total": total, "from_cache": False}

    def _build_url(self, page: int) -> str:
        start = (page - 1) * self.results_per_page
        params = f"v={self.view}"
        if self.filters:
            params += f"&f={self.filters}"
        params += f"&ft={self.filter_type}"
        params += f"&o={self.sort_by}"
        if start > 0:
            params += f"&r={start}"
        return f"{self.base_url}?{params}"

    def _parse_total(self, soup: BeautifulSoup) -> int:
        total_el = soup.find(id="screener-total")
        if not total_el:
            total_el = soup.find(["td", "div", "span"], class_="count-text")
        if total_el:
            text = total_el.get_text(strip=True)
            match = re.search(r"(?:#\d+\s*/|of)\s*([\d,]+)", text)
            if match:
                return int(match.group(1).replace(",", ""))
        results_label = soup.find(string=re.compile(r"Results:\s*[\d,]+"))
        if results_label:
            match = re.search(r"([\d,]+)", results_label.split(":")[1])
            if match:
                return int(match.group(1).replace(",", ""))
        return 0

    def _parse_page(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        tickers = []
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            header_cells = rows[0].find_all(["td", "th"])
            headers = [c.get_text(strip=True).lower().replace(" ", "_") for c in header_cells]
            if "ticker" not in headers:
                continue
            ticker_idx = headers.index("ticker")
            for row in rows[1:]:
                cells = row.find_all("td")
                if len(cells) <= ticker_idx:
                    continue
                ticker_cell = cells[ticker_idx]
                ticker = ticker_cell.get("data-boxover-ticker", "")
                if not ticker:
                    ticker = ticker_cell.get_text(strip=True)
                if not ticker or not re.match(r"^[A-Z.]+$", ticker):
                    continue
                entry = {"ticker": ticker}
                for i, h in enumerate(headers):
                    if i < len(cells) and i != ticker_idx:
                        entry[h] = cells[i].get_text(strip=True)
                tickers.append(entry)
        return tickers