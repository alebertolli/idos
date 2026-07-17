from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any


@dataclass
class AOIFStep:
    name: str
    result: dict[str, Any]
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


@dataclass
class AOIFResult:
    opportunity_id: str
    ticker: str
    steps: list[AOIFStep] = field(default_factory=list)
    score: int = 0
    inference: str = ""
    completed: bool = False
    completed_at: str = ""


class AOIFProtocol:
    STEPS = [
        "business_understanding",
        "financial_analysis",
        "competitive_analysis",
        "management_evaluation",
        "risk_assessment",
        "valuation_analysis",
        "scenario_analysis",
        "thesis_formulation",
    ]

    def __init__(self):
        self._results: dict[str, AOIFResult] = {}

    def execute(self, opportunity_id: str, ticker: str, data: dict[str, Any]) -> AOIFResult:
        result = AOIFResult(opportunity_id=opportunity_id, ticker=ticker.upper())

        for step_name in self.STEPS:
            step_result = getattr(self, f"_step_{step_name}", lambda d: {"status": "completed"})(data)
            result.steps.append(AOIFStep(name=step_name, result=step_result))

        metrics = data.get("knowledge_base", {}).get("dynamic", {}).get("metrics", {})
        roic = metrics.get("roic", 0)
        margin = metrics.get("operating_margin", 0)
        growth = metrics.get("revenue_growth", 0)
        result.score = min(100, int((roic + margin + growth) / 3)) if any([roic, margin, growth]) else 50

        result.inference = f"AOIF analysis completed for {ticker}. Score: {result.score}/100"
        result.completed = True
        result.completed_at = datetime.now(UTC).isoformat()

        self._results[opportunity_id] = result
        return result

    def get_result(self, opportunity_id: str) -> AOIFResult | None:
        return self._results.get(opportunity_id)

    def _step_business_understanding(self, data: dict) -> dict:
        static = data.get("knowledge_base", {}).get("static", {})
        return {"business_model": static.get("business_model", "N/A"),
                "products": static.get("products", []), "status": "completed"}

    def _step_financial_analysis(self, data: dict) -> dict:
        metrics = data.get("knowledge_base", {}).get("dynamic", {}).get("metrics", {})
        return {"roic": metrics.get("roic"), "margin": metrics.get("operating_margin"),
                "growth": metrics.get("revenue_growth"), "status": "completed"}

    def _step_competitive_analysis(self, data: dict) -> dict:
        static = data.get("knowledge_base", {}).get("static", {})
        return {"moat": static.get("moat_description", "N/A"),
                "competitors": data.get("competitors", []), "status": "completed"}

    def _step_management_evaluation(self, data: dict) -> dict:
        return {"quality": data.get("management_quality", "UNKNOWN"), "status": "completed"}

    def _step_risk_assessment(self, data: dict) -> dict:
        risks = []
        m = data.get("knowledge_base", {}).get("dynamic", {}).get("metrics", {})
        if m.get("debt_to_equity", 0) > 2: risks.append("High leverage")
        if m.get("operating_margin", 99) < 5: risks.append("Low margins")
        return {"risks": risks, "status": "completed"}

    def _step_valuation_analysis(self, data: dict) -> dict:
        m = data.get("knowledge_base", {}).get("dynamic", {}).get("metrics", {})
        return {"pe_ratio": m.get("pe_ratio"), "ev_ebitda": m.get("ev_ebitda"),
                "fcf_yield": m.get("fcf_yield"), "status": "completed"}

    def _step_scenario_analysis(self, data: dict) -> dict:
        return {"scenarios": ["base", "bull", "bear"], "status": "completed"}

    def _step_thesis_formulation(self, data: dict) -> dict:
        return {"thesis": data.get("thesis", f"Investment thesis for {data.get('ticker', 'N/A')}"),
                "status": "completed"}
