import os
import re
import time
from typing import Any, Optional
from xml.etree import ElementTree

import requests

from idos.workers.base import BaseWorker, WorkerResult, WorkerStatus
from idos.workers.data.sec_company_facts import SOURCE_URL, normalize_company_facts

EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index?q={ticker}&dateRange=custom&startdt={start}&enddt={end}"
CIK_LOOKUP_URL = "https://www.sec.gov/cgi-bin/browse-edgar?CIK={ticker}&action=getcompany&owner=exclude&output=atom"

_CONTACT_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


class SECEdgarWorker(BaseWorker):
    name = "sec_edgar"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.timeout = self.config.get("timeout", 30)
        self.delay = self.config.get("delay", 0.5)
        user_agent_env = str(self.config.get("user_agent_env", "IDOS_SEC_USER_AGENT"))
        self.user_agent = str(
            self.config.get("user_agent") or os.environ.get(user_agent_env, "")
        ).strip()

    @property
    def headers(self) -> dict[str, str]:
        if not self.user_agent or not _CONTACT_EMAIL.search(self.user_agent):
            raise ValueError(
                "Set IDOS_SEC_USER_AGENT to an identifying application name and monitored contact email"
            )
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, application/atom+xml, text/xml",
            "Accept-Encoding": "gzip, deflate",
        }

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        ticker = context.get("ticker", "").upper().strip()
        if not ticker:
            msg = "No ticker provided"
            raise ValueError(msg)

        headers = self.headers

        cik = self._lookup_cik(ticker)
        if not cik:
            return {
                "ticker": ticker, "source": "sec_edgar", "cik": None,
                "filings": [], "data_quality_warnings": ["sec_cik_not_found"],
            }

        time.sleep(self.delay)
        fundamentals = self._get_company_facts(ticker, cik, headers)
        filings = []
        if context.get("include_filings", True):
            time.sleep(self.delay)
            filings = self._get_recent_filings(ticker)
        return {
            "ticker": ticker,
            "cik": cik,
            "source": "sec_edgar",
            "filings": filings,
            **fundamentals,
        }

    def _lookup_cik(self, ticker: str) -> Optional[str]:
        url = CIK_LOOKUP_URL.format(ticker=ticker)
        resp = requests.get(url, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        try:
            root = ElementTree.fromstring(resp.content)
        except ElementTree.ParseError as exc:
            raise ValueError("SEC returned malformed company lookup data") from exc
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entry = root.find("atom:entry", ns)
        if entry is not None:
            cik_text = entry.find("atom:category", ns)
            if cik_text is not None and "CIK" in (cik_text.get("term", "") or ""):
                cik_val = cik_text.get("term", "").replace("CIK=", "").strip()
                return cik_val if cik_val else None
        return None

    def _get_company_facts(
        self, ticker: str, cik: str, headers: dict[str, str]
    ) -> dict[str, Any]:
        padded_cik = str(cik).strip().lstrip("0").zfill(10)
        url = SOURCE_URL.format(cik=padded_cik)
        try:
            response = requests.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            normalized = normalize_company_facts(ticker, padded_cik, response.json())
            normalized["financial_data_observed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return normalized
        except (requests.RequestException, ValueError) as exc:
            return {
                "ticker": ticker,
                "cik": padded_cik,
                "source": "sec_edgar",
                "data_quality_warnings": [f"sec_companyfacts_unavailable:{type(exc).__name__}"],
                "data_provenance": {
                    "source_count": 1, "sources_used": ["sec_edgar"],
                    "field_sources": {}, "field_urls": {}, "conflicts": [],
                },
            }
    def _get_recent_filings(self, ticker: str, count: int = 10) -> list[dict[str, Any]]:
        try:
            url = EDGAR_SEARCH_URL.format(ticker=ticker, start="20240101", end="20261231")
            resp = requests.get(url, headers=self.headers, timeout=self.timeout)
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

