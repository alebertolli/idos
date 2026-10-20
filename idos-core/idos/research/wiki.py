from typing import Any


class WikiBuilder:
    SECTIONS = ["business_model", "products", "moat", "competition", "management",
                "risks", "financial_highlights", "catalysts", "thesis"]

    def build(self, ticker: str, data: dict[str, Any]) -> dict[str, str]:
        kb = data.get("knowledge_base", {})
        static = kb.get("static", {})
        metrics = kb.get("dynamic", {}).get("metrics", {})

        products_list = static.get("products") or ["To be identified"]
        competitors_list = data.get("competitors") or ["To be identified"]

        return {
            "business_model": self._section("Business Model", static.get("business_model") or "To be researched"),
            "products": self._section("Products & Services", "\n".join(f"- {p}" for p in products_list)),
            "moat": self._section("Competitive Moat", static.get("moat_description") or "To be analyzed"),
            "competition": self._section("Competition", "\n".join(f"- {c}" for c in competitors_list)),
            "management": self._section("Management", static.get("management_history") or "To be evaluated"),
            "risks": self._section("Risk Factors", ""),
            "financial_highlights": self._build_financial_section(metrics),
            "catalysts": self._build_catalyst_section(data.get("catalysts") or []),
            "thesis": self._section("Investment Thesis", data.get("thesis") or "To be formulated"),
        }

    def render_markdown(self, wiki_data: dict[str, str]) -> str:
        sections = []
        for section_name in self.SECTIONS:
            content = wiki_data.get(section_name, "")
            if content:
                sections.append(content)
        return "\n\n---\n\n".join(sections)

    def _section(self, title: str, content: str) -> str:
        return f"## {title}\n\n{content}"

    def _build_financial_section(self, metrics: dict) -> str:
        lines = ["## Financial Highlights"]
        for k, v in [("ROIC", "roic"), ("Operating Margin", "operating_margin"),
                      ("Revenue Growth", "revenue_growth"), ("FCF Yield", "fcf_yield"),
                      ("Debt/Equity", "debt_to_equity"), ("PER", "pe_ratio"),
                      ("EV/EBITDA", "ev_ebitda")]:
            val = metrics.get(v)
            if val is not None:
                lines.append(f"- **{k}**: {val}")
        return "\n".join(lines) if len(lines) > 1 else f"## Financial Highlights\n\nTo be populated"

    def _build_catalyst_section(self, catalysts: list[dict]) -> str:
        if not catalysts:
            return "## Catalysts\n\nTo be identified"
        lines = ["## Catalysts"]
        for c in catalysts:
            desc = c.get("description", c.get("detail", "Catalyst"))
            impact = c.get("impact", "medium")
            timeline = c.get("timeline", "medium")
            lines.append(f"- **{desc}** (Impact: {impact}, Timeline: {timeline})")
        return "\n".join(lines)
