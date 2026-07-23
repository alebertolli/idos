from pathlib import Path
from typing import Any
import yaml


class KnowledgeRepository:
    def __init__(self, base_path: Path):
        self.base = base_path

    def company_path(self, ticker: str) -> Path:
        return self.base / "companies" / ticker.upper()

    def company_file(self, ticker: str) -> Path:
        return self.company_path(ticker) / "company.yml"

    def knowledge_base_path(self, ticker: str) -> Path:
        return self.company_path(ticker) / "knowledge_base"

    def exists(self, ticker: str) -> bool:
        return self.company_file(ticker).exists()

    def save_company(self, ticker: str, data: dict[str, Any]):
        path = self.company_path(ticker)
        path.mkdir(parents=True, exist_ok=True)
        filepath = path / "company.yml"
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    def load_company(self, ticker: str) -> dict[str, Any] | None:
        filepath = self.company_file(ticker)
        if not filepath.exists():
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def save_wiki(self, ticker: str, content: str):
        kb_path = self.knowledge_base_path(ticker) / "static"
        kb_path.mkdir(parents=True, exist_ok=True)
        wiki_path = kb_path / "wiki.md"
        with open(wiki_path, "w", encoding="utf-8") as f:
            f.write(content)

    def load_wiki(self, ticker: str) -> str | None:
        wiki_path = self.knowledge_base_path(ticker) / "static" / "wiki.md"
        if not wiki_path.exists():
            return None
        with open(wiki_path, "r", encoding="utf-8") as f:
            return f.read()

    def get_wiki_text(self, ticker: str) -> str:
        from idos.knowledge.wiki import AtomicWiki
        atomic = AtomicWiki(self.base)
        sections = atomic.all_sections(ticker)
        if sections:
            parts = []
            for s in sections:
                parts.append(f"## {s.name.replace('_', ' ').title()}\n\n{s.content}")
            return "\n\n---\n\n".join(parts)
        wiki = self.load_wiki(ticker)
        if wiki:
            return wiki
        return ""

    def list_all_tickers(self) -> list[str]:
        companies_dir = self.base / "companies"
        if not companies_dir.exists():
            return []
        result = []
        for d in sorted(companies_dir.iterdir()):
            if d.is_dir() and not d.name.startswith("_") and (d / "company.yml").exists():
                result.append(d.name)
        return result

    def list_all_companies(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for ticker in self.list_all_tickers():
            company = self.load_company(ticker)
            if company:
                result[ticker] = company
        return result

    def generate_index(self) -> str:
        companies = self.list_all_companies()
        by_sector: dict[str, list[tuple[str, str]]] = {}
        for ticker, data in companies.items():
            sector = data.get("sector") or data.get("industry") or "Other"
            name = data.get("name", ticker)
            by_sector.setdefault(sector, []).append((ticker, name))

        lines = [
            "---",
            "id: idos-index",
            "aliases:",
            "  - IDOS Company Index",
            "  - Companies",
            "---",
            "",
            "# IDOS Company Index",
            "",
            f"Total: {len(companies)} companies tracked",
            "",
        ]
        for sector in sorted(by_sector):
            entries = sorted(by_sector[sector], key=lambda x: x[0])
            lines.append(f"## {sector}")
            for ticker, name in entries:
                wiki_path = self.knowledge_base_path(ticker) / "static" / "wiki.md"
                has_wiki = "📄" if wiki_path.exists() else "⏳"
                lines.append(f"- {has_wiki} [[{ticker}|{name}]]")
            lines.append("")

        lines.append("---")
        lines.append(f"*Generated: auto-updated on each research run*")
        return "\n".join(lines)
