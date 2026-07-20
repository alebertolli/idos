from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from idos.timezone import AR_TZ

@dataclass
class DDDResult:
    ticker: str
    summary: str = ""
    business_quality: str = ""
    management_quality: str = ""
    competitive_position: str = ""
    risks_identified: list[str] = field(default_factory=list)
    catalysts: list[dict] = field(default_factory=list)
    thesis_statement: str = ""
    score: int = 0
    completed_at: str = ""

    def __post_init__(self):
        if not self.completed_at:
            self.completed_at = datetime.now(AR_TZ).isoformat()

class DeepDueDiligenceWorker:
    def run(self, ticker: str, data: dict[str, Any]) -> DDDResult:
        kb = data.get("knowledge_base", {})
        static = kb.get("static", {})
        metrics = kb.get("dynamic", {}).get("metrics", {})

        risks = []
        if metrics.get("debt_to_equity", 0) > 2:
            risks.append("High leverage")
        if metrics.get("operating_margin", 99) < 5:
            risks.append("Thin operating margins")
        if metrics.get("revenue_growth", 0) < 0:
            risks.append("Declining revenue")

        catalysts = data.get("catalysts", [])
        if not catalysts:
            catalysts = [{"description": "Operational improvement", "impact": "medium", "timeline": "medium"}]

        roic = metrics.get("roic", 0)
        score = 50
        if roic > 20: score += 20
        elif roic > 10: score += 10
        if metrics.get("operating_margin", 0) > 20: score += 15
        if metrics.get("revenue_growth", 0) > 15: score += 10
        score = max(0, min(100, score))

        business_quality = "EXCEPTIONAL" if score >= 75 else "GOOD" if score >= 50 else "WEAK"
        moat = static.get("moat_description", "")
        thesis = f"{ticker} - {business_quality} business"

        return DDDResult(
            ticker=ticker.upper(),
            summary=data.get("summary", f"Deep Due Diligence completed for {ticker}"),
            business_quality=business_quality,
            management_quality=data.get("management_quality", "UNKNOWN"),
            competitive_position=f"Moat: {moat}" if moat else "Limited competitive advantages",
            risks_identified=risks,
            catalysts=catalysts,
            thesis_statement=thesis,
            score=score,
        )
