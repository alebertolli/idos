from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from pathlib import Path
import re
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
    "products",
    "moat",
    "management",
    "competition",
    "risks",
    "valuation",
    "timeline",
    "financial_highlights",
    "catalysts",
    "investment_thesis",
    "open_questions",
]

class AtomicWiki:
    def __init__(self, base_path: str | Path = "idos-knowledge"):
        self.base_path = Path(base_path)
        self._wiki_dir = self.base_path / "companies"
        self._sections: dict[str, dict[str, WikiSection]] = {}

    @staticmethod
    def _sanitize_section_name(name: str) -> str:
        """Convierte un nombre de sección en un nombre de archivo seguro cross-platform.

        Los headings generados por el LLM pueden contener caracteres ilegales en nombre
        de archivo (`:`, `'`, `<`, `>`, `"`, `|`, `?`, `*`, barras, espacios a los lados),
        lo que rompe el checkout en Windows (ver error: 'here's_a_thinking_process:.md').
        """
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name.strip())
        while safe.startswith("."):
            safe = safe[1:]
        safe = re.sub(r"\s+", "_", safe)
        return safe or "section"

    def _company_dir(self, ticker: str) -> Path:
        p = self._wiki_dir / ticker.upper() / "wiki"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _section_path(self, ticker: str, section: str) -> Path:
        return self._company_dir(ticker) / f"{self._sanitize_section_name(section)}.md"

    def _meta_path(self, ticker: str, section: str) -> Path:
        return self._company_dir(ticker) / f"{self._sanitize_section_name(section)}.meta.yml"

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

    SECTION_HEADER_ALIASES = {
        "business_model": "business",
        "company_overview": "business",
        "business": "business",
        "products_and_services": "products",
        "products_&_services": "products",
        "products": "products",
        "competitive_moat": "moat",
        "moat": "moat",
        "competition": "competition",
        "management": "management",
        "risk_factors": "risks",
        "risks": "risks",
        "financial_highlights": "financial_highlights",
        "catalysts": "catalysts",
        "valuation": "valuation",
        "investment_thesis": "investment_thesis",
        "thesis": "investment_thesis",
        "timeline": "timeline",
        "open_questions": "open_questions",
        "preguntas_abiertas": "open_questions",
        "vision_general": "business",
        "modelo_de_negocio": "business",
        "perfil_financiero": "financial_highlights",
        "management_y_gobierno": "management",
        "tesis_de_inversion": "investment_thesis",
        "riesgos_y_contra_tesis": "risks",
        "catalizadores_y_timeline": "catalysts",
        "marco_de_valoracion": "valuation",
        "1_visión_general_de_la_compañía": "business",
        "1_vision_general_de_la_compania": "business",
        "2_modelo_de_negocio_y_posición_competitiva": "business",
        "2_modelo_de_negocio_y_posicion_competitiva": "business",
        "3_perfil_financiero": "financial_highlights",
        "4_management_y_gobierno_corporativo": "management",
        "4_management_y_gobierno_corporativo": "management",
        "5_tesis_de_inversión": "investment_thesis",
        "5_tesis_de_inversion": "investment_thesis",
        "6_riesgos_y_contra_tesis": "risks",
        "6_riesgos_y_contra-tesis": "risks",
        "7_catalizadores_y_timeline": "catalysts",
        "8_marco_de_valoración": "valuation",
        "8_marco_de_valoracion": "valuation",
        "9_preguntas_abiertas_y_agenda_de_investigación": "open_questions",
        "9_preguntas_abiertas_y_agenda_de_investigacion": "open_questions",
        "related_companies": None,
        "compañías_relacionadas": None,
        "companias_relacionadas": None,
    }

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
            while body.endswith("---"):
                body = body[:-3].strip()
            mapped = self.SECTION_HEADER_ALIASES.get(name, name)
            if mapped is None:
                continue
            mapped = self._sanitize_section_name(mapped)
            if name and body:
                section = WikiSection(name=mapped, content=body, metadata=WikiMetadata.fresh())
                self.set_section(ticker, section)
