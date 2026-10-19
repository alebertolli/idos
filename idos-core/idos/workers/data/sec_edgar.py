import time
from typing import Any, Optional
from xml.etree import ElementTree

import requests

from idos.workers.base import BaseWorker, WorkerResult, WorkerStatus

EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index?q={ticker}&dateRange=custom&startdt={start}&enddt={end}"
CIK_LOOKUP_URL = "https://www.sec.gov/cgi-bin/browse-edgar?CIK={ticker}&action=getcompany&owner=exclude&output=atom"

HEADERS = {
    "User-Agent": "IDOS FamilyOffice research@familyoffice.com",
    "Accept": "application/xml, text/html",
}


class SECEdgarWorker(BaseWorker):
    name = "sec_edgar"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.timeout = self.config.get("timeout", 30)
        self.delay = self.config.get("delay", 0.5)

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        ticker = context.get("ticker", "").upper().strip()
        if not ticker:
            msg = "No ticker provided"
            raise ValueError(msg)

        cik = self._lookup_cik(ticker)
        if not cik:
            return {"ticker": ticker, "source": "sec_edgar", "cik": None, "filings": []}

        time.sleep(self.delay)

        filings = self._get_recent_filings(ticker)
        return {
            "ticker": ticker,
            "cik": cik,
            "source": "sec_edgar",
            "filings": filings,
        }

    def _lookup_cik(self, ticker: str) -> Optional[str]:
        try:
            url = CIK_LOOKUP_URL.format(ticker=ticker)
            resp = requests.get(url, headers=HEADERS, timeout=self.timeout)
            resp.raise_for_status()
            root = ElementTree.fromstring(resp.content)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entry = root.find("atom:entry", ns)
            if entry is not None:
                cik_text = entry.find("atom:category", ns)
                if cik_text is not None and "CIK" in (cik_text.get("term", "") or ""):
                    cik_val = cik_text.get("term", "").replace("CIK=", "").strip()
                    return cik_val if cik_val else None
            return None
        except Exception:
            return None

    def _get_recent_filings(self, ticker: str, count: int = 10) -> list[dict[str, Any]]:
        try:
            url = EDGAR_SEARCH_URL.format(ticker=ticker, start="20240101", end="20261231")
            resp = requests.get(url, headers=HEADERS, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            filings = []
            hits = data.get("hits", {}).get("hits", [])
            for hit in hits[:count]:
                source = hit.get("_source", {})
                filings.append({
                    "form_type": source.get("file_type"),
                    "description": source.get("file_description"),
                    "filed_date": source.get("file_date"),
                    "form_url": source.get("file_url"),
                })
            return filings
        except Exception:
            return []
