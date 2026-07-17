from typing import Any
from idos.decision.engines.base import BaseAssessmentEngine, AssessmentResult


class BusinessAssessmentEngine(BaseAssessmentEngine):
    name = "BusinessAssessmentEngine"
    version = "1.0"

    def evaluate(self, context: dict[str, Any]) -> AssessmentResult:
        kb = context.get("knowledge_base", {})
        dynamic = kb.get("dynamic", {})
        metrics = dynamic.get("metrics", {})
        static = kb.get("static", {})

        score = 50
        findings = []
        risks = []

        roic = metrics.get("roic", 0)
        if roic > 20:
            score += 15
            findings.append({"type": "POSITIVE", "detail": f"Exceptional ROIC: {roic}%"})
        elif roic > 15:
            score += 10
            findings.append({"type": "POSITIVE", "detail": f"Strong ROIC: {roic}%"})

        revenue_growth = metrics.get("revenue_growth", 0)
        if revenue_growth > 20:
            score += 10
            findings.append({"type": "POSITIVE", "detail": f"High revenue growth: {revenue_growth}%"})
        elif revenue_growth > 10:
            score += 5

        margin = metrics.get("operating_margin", 0)
        if margin > 25:
            score += 10
            findings.append({"type": "POSITIVE", "detail": f"Excellent margins: {margin}%"})
        elif margin > 15:
            score += 5

        moat = static.get("moat_description", "")
        if moat:
            score += 5
            findings.append({"type": "POSITIVE", "detail": "Identifiable competitive moat"})

        if roic < 5:
            score -= 15
            risks.append({"type": "CAPITAL_ALLOCATION", "detail": f"Low ROIC: {roic}%"})

        if margin < 5:
            score -= 10
            risks.append({"type": "MARGIN", "detail": f"Thin operating margin: {margin}%"})

        score = max(0, min(100, score))

        recommendation = "FAVORABLE" if score >= 70 else "NEUTRAL" if score >= 40 else "UNFAVORABLE"

        return AssessmentResult(
            engine=self.name,
            version=self.version,
            score=score,
            confidence="HIGH" if score >= 75 else "MEDIUM",
            findings=findings,
            risks=risks,
            recommendation=recommendation,
        )
