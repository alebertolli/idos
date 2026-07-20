from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from pathlib import Path
import yaml
from idos.timezone import AR_TZ

@dataclass
class WikiMetadata:
    freshness: str = ""  # ISO date
    confidence: float = 0.0
    last_review: str = ""
    owner: str = "system"
    source_count: int = 0
    review_frequency_days: int = 90

    def to_dict(self) -> dict[str, Any]:
        return {
            "freshness": self.freshness,
            "confidence": self.confidence,
            "last_review": self.last_review,
            "owner": self.owner,
            "source_count": self.source_count,
            "review_frequency_days": self.review_frequency_days,
        }

    @classmethod
    def fresh(cls) -> "WikiMetadata":
        now = datetime.now(AR_TZ).isoformat()
        return cls(freshness=now, confidence=0.0, last_review=now)

@dataclass
class WikiSection:
    name: str
    content: str = ""
    metadata: WikiMetadata = field(default_factory=WikiMetadata.fresh)
    claims: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "content": self.content,
            "metadata": self.metadata.to_dict(),
            "claims": self.claims,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WikiSection":
        meta = WikiMetadata(**data.get("metadata", {}))
        return cls(
            name=data["name"],
            content=data.get("content", ""),
            metadata=meta,
            claims=data.get("claims", []),
        )

ATOMIC_SECTIONS = [
    "business",
    "management",
    "competition",
    "risks",
    "valuation",
    "timeline",
    "financial_highlights",
    "catalysts",
    "investment_thesis",
]

class AtomicWiki:
    def __init__(self, base_path: str | Path = "idos-knowledge"):
        self.base_path = Path(base_path)
        self._wiki_dir = self.base_path / "companies"
        self._sections: dict[str, dict[str, WikiSection]] = {}

    def _company_dir(self, ticker: str) -> Path:
        p = self._wiki_dir / ticker.upper() / "wiki"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _section_path(self, ticker: str, section: str) -> Path:
        return self._company_dir(ticker) / f"{section}.md"

    def _meta_path(self, ticker: str, section: str) -> Path:
        return self._company_dir(ticker) / f"{section}.meta.yml"

    def get_section(self, ticker: str, section: str) -> WikiSection | None:
        key = f"{ticker}.{section}"
        if key in self._sections:
            return self._sections[key].get(section)
        md_path = self._section_path(ticker, section)
        meta_path = self._meta_path(ticker, section)
        if not md_path.exists():
            return None
        content = md_path.read_text(encoding="utf-8")
        meta = WikiMetadata.fresh()
        claims: list[str] = []
        if meta_path.exists():
            meta_data = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
            claims = meta_data.pop("claims", [])
            meta = WikiMetadata(**meta_data)
        section_obj = WikiSection(name=section, content=content.strip(), metadata=meta, claims=claims)
        self._sections.setdefault(ticker.upper(), {})[section] = section_obj
        return section_obj

    def set_section(self, ticker: str, section: WikiSection):
        ticker = ticker.upper()
        md_path = self._section_path(ticker, section.name)
        meta_path = self._meta_path(ticker, section.name)
        md_path.write_text(section.content + "\n", encoding="utf-8")
        meta_dict = section.metadata.to_dict()
        meta_dict["claims"] = section.claims
        meta_path.write_text(yaml.dump(meta_dict, allow_unicode=True), encoding="utf-8")
        self._sections.setdefault(ticker, {})[section.name] = section

    def all_sections(self, ticker: str) -> list[WikiSection]:
        results = []
        for section_name in ATOMIC_SECTIONS:
            s = self.get_section(ticker, section_name)
            if s:
                results.append(s)
        return results

    def list_tickers(self) -> list[str]:
        if not self._wiki_dir.exists():
            return []
        return [d.name for d in self._wiki_dir.iterdir() if d.is_dir() and (d / "wiki").exists()]

    def get_metadata(self, ticker: str, section: str) -> WikiMetadata | None:
        s = self.get_section(ticker, section)
        return s.metadata if s else None

    def update_freshness(self, ticker: str, section: str):
        s = self.get_section(ticker, section)
        if s:
            s.metadata.freshness = datetime.now(AR_TZ).isoformat()
            self.set_section(ticker, s)

    def migrate_from_monolith(self, ticker: str, monolith_path: str | Path):
        content = Path(monolith_path).read_text(encoding="utf-8")
        sections_raw = content.split("\n## ")
        for raw in sections_raw:
            if not raw.strip():
                continue
            raw = raw.strip()
            if raw.startswith("## "):
                raw = raw[3:]
            lines = raw.split("\n")
            name = lines[0].strip().lower().replace(" ", "_").replace("&", "and")
            body = "\n".join(lines[1:]).strip()
            body = body.replace("\n---", "").strip()
            if name and body:
                section = WikiSection(name=name, content=body, metadata=WikiMetadata.fresh())
                self.set_section(ticker, section)
