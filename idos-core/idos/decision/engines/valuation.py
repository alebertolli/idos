from typing import Any
from idos.decision.engines.base import BaseAssessmentEngine, AssessmentResult


class ValuationAssessmentEngine(BaseAssessmentEngine):
    name = "ValuationAssessmentEngine"
    version = "1.1"

    def evaluate(self, context: dict[str, Any]) -> AssessmentResult:
        metrics = context.get("knowledge_base", {}).get("dynamic", {}).get("metrics", {})
        score = 50
        findings = []
        risks = []

        price_margin = context.get("price_margin", 0)
        if price_margin > 30:
            score += 15
            findings.append({"type": "POSITIVE", "detail": f"Price target upside: {price_margin:.1f}%"})
        elif price_margin > 20:
            score += 10
            findings.append({"type": "POSITIVE", "detail": f"Price target upside: {price_margin:.1f}%"})
        elif price_margin < 0:
            score -= 10
            risks.append({"type": "VALUATION", "detail": f"Price target below current: {price_margin:.1f}%"})

        pe_current = metrics.get("pe_ratio", 0)
        pe_historical = metrics.get("pe_historical_avg", 0)
        if pe_historical and pe_current:
            if pe_current < pe_historical * 0.7:
                score += 15
                findings.append({"type": "POSITIVE", "detail": f"PER {pe_current:.1f}x below historical {pe_historical:.1f}x"})
            elif pe_current > pe_historical * 1.3:
                score -= 10
                risks.append({"type": "VALUATION", "detail": f"PER {pe_current:.1f}x above historical {pe_historical:.1f}x"})

        ev_ebitda = metrics.get("ev_ebitda", 0)
        sector_avg = metrics.get("sector_avg_ev_ebitda", 0)
        if sector_avg and ev_ebitda:
            if ev_ebitda < sector_avg * 0.8:
                score += 10
                findings.append({"type": "POSITIVE", "detail": "EV/EBITDA below sector average"})

        fcf_yield = metrics.get("fcf_yield", 0)
        if fcf_yield > 5:
            score += 10
            findings.append({"type": "POSITIVE", "detail": f"FCF Yield: {fcf_yield:.1f}%"})
        elif fcf_yield < 0:
            score -= 10
            risks.append({"type": "FCF", "detail": "Negative free cash flow yield"})

        margin_of_safety = context.get("margin_of_safety", 0)
        if margin_of_safety > 40:
            score += 10
            findings.append({"type": "POSITIVE", "detail": f"Margin of safety: {margin_of_safety:.0f}%"})
        elif margin_of_safety >= 20:
            score += 5

        score = max(0, min(100, score))
        recommendation = "ATTRACTIVE" if score >= 70 else "FAIR" if score >= 40 else "EXPENSIVE"

        return AssessmentResult(
            engine=self.name,
            version=self.version,
            score=score,
            confidence="HIGH" if score >= 75 else "MEDIUM",
            findings=findings,
            risks=risks,
            recommendation=recommendation,
        )
