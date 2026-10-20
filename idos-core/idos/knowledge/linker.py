from pathlib import Path
from typing import Any

import yaml


class CrossCompanyLinker:
    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path)
        self._companies_dir = self.base_path / "companies"

    def _load_company(self, ticker: str) -> dict[str, Any] | None:
        path = self._companies_dir / ticker.upper() / "company.yml"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _load_ddd_report(self, ticker: str) -> dict[str, Any] | None:
        from pathlib import Path as P
        from datetime import datetime
        base = self._companies_dir / ticker.upper()
        opps_dir = base / "case_file" / "opportunities"
        if not opps_dir.exists():
            return None
        opp_dirs = sorted(opps_dir.iterdir(), reverse=True)
        for opp_dir in opp_dirs:
            report_path = opp_dir / "ddd_report.yml"
            if report_path.exists():
                with open(report_path, encoding="utf-8") as f:
                    return yaml.safe_load(f)
        return None

    def _list_all_tickers(self) -> list[str]:
        if not self._companies_dir.exists():
            return []
        result = []
        for d in sorted(self._companies_dir.iterdir()):
            if d.is_dir() and not d.name.startswith("_") and (d / "company.yml").exists():
                result.append(d.name)
        return result

    def find_related(self, ticker: str) -> dict[str, list[str]]:
        ticker = ticker.upper()
        company = self._load_company(ticker)
        if not company:
            return {}

        target_sector = company.get("sector", "").lower()
        target_industry = company.get("industry", "").lower()
        target_name_lower = company.get("name", ticker).lower()

        ddd = self._load_ddd_report(ticker)
        competitor_names: list[str] = []
        if ddd:
            for cat in ddd.get("dominio_catalizadores", []):
                cat_desc = cat.get("descripcion", "") or cat.get("description", "")
                if cat_desc:
                    competitor_names.append(cat_desc.lower())
            for risk in ddd.get("dominio_riesgos", []):
                risk_desc = risk.get("riesgo", "") or risk.get("description", "")
                if risk_desc:
                    competitor_names.append(risk_desc.lower())

        all_tickers = self._list_all_tickers()
        same_sector: list[str] = []
        same_industry: list[str] = []
        by_competitor: list[str] = []
        other: list[str] = []

        for other_ticker in all_tickers:
            if other_ticker == ticker:
                continue
            other_company = self._load_company(other_ticker)
            if not other_company:
                continue

            other_name = other_company.get("name", "").lower()
            other_sector = other_company.get("sector", "").lower()
            other_industry = other_company.get("industry", "").lower()

            if other_sector and other_sector == target_sector:
                same_sector.append(other_ticker)
            if other_industry and other_industry == target_industry:
                same_industry.append(other_ticker)

            for comp_keyword in competitor_names:
                comp_words = set(comp_keyword.split())
                other_words = set(other_name.split())
                if comp_words & other_words:
                    if other_ticker not in by_competitor:
                        by_competitor.append(other_ticker)

        result: dict[str, list[str]] = {}
        if same_sector:
            result["same_sector"] = same_sector
        if same_industry:
            result["same_industry"] = same_industry
        if by_competitor:
            result["competitor"] = by_competitor
        return result

    def render_links_section(self, ticker: str) -> str:
        related = self.find_related(ticker)
        if not related:
            return ""

        lines = ["## Related Companies\n"]
        for category, tickers in related.items():
            label = category.replace("_", " ").title()
            link_strs = []
            for t in tickers:
                comp = self._load_company(t) or {}
                name = comp.get("name", t)
                link_strs.append(f"[[{t}|{name}]]")
            lines.append(f"- **{label}**: {', '.join(link_strs)}")

        return "\n".join(lines)

    def inject_links(self, ticker: str, wiki_md: str) -> str:
        links_section = self.render_links_section(ticker)
        if not links_section:
            return wiki_md
        if "## Related Companies" in wiki_md:
            import re
            wiki_md = re.sub(r"\n## Related Companies\n.*?(?=\n## |\Z)", "", wiki_md, flags=re.DOTALL)
        return wiki_md.rstrip() + "\n\n---\n\n" + links_section
