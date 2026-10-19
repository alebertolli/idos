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

        # ROIC
        roic = metrics.get("roic", 0)
        if roic > 20:
            score += 10
            findings.append({"type": "POSITIVE", "detail": f"Exceptional ROIC: {roic}%"})
        elif roic > 15:
            score += 5
            findings.append({"type": "POSITIVE", "detail": f"Strong ROIC: {roic}%"})

        # Revenue growth
        revenue_growth = metrics.get("revenue_growth", 0)
        if revenue_growth > 20:
            score += 8
            findings.append({"type": "POSITIVE", "detail": f"High revenue growth: {revenue_growth}%"})
        elif revenue_growth > 10:
            score += 4

        # Operating margin
        margin = metrics.get("operating_margin", 0)
        if margin > 25:
            score += 8
            findings.append({"type": "POSITIVE", "detail": f"Excellent margins: {margin}%"})
        elif margin > 15:
            score += 4

        # Moat durability
        moat = static.get("moat_description", "")
        if moat:
            score += 5
            findings.append({"type": "POSITIVE", "detail": "Identifiable competitive moat"})
        moat_type = static.get("moat_type", "")
        moat_score = {"network_effect": 10, "switching_cost": 8, "cost_advantage": 7, "intangible": 6, "scale": 5}.get(moat_type, 0)
        if moat_score:
            score += moat_score
            findings.append({"type": "POSITIVE", "detail": f"Moat type: {moat_type} (score: {moat_score})"})

        # Management quality
        management = static.get("management", {})
        ceo_tenure = management.get("ceo_tenure_years", 0)
        if ceo_tenure >= 10:
            score += 8
            findings.append({"type": "POSITIVE", "detail": f"Long-tenured CEO: {ceo_tenure} years"})
        elif ceo_tenure >= 5:
            score += 4
        insider_ownership = management.get("insider_ownership_pct", 0)
        if insider_ownership > 10:
            score += 6
            findings.append({"type": "POSITIVE", "detail": f"High insider ownership: {insider_ownership}%"})
        elif insider_ownership > 3:
            score += 3
        capital_allocation = management.get("capital_allocation_rating", "")
        if capital_allocation in ("excellent", "good"):
            score += 5
            findings.append({"type": "POSITIVE", "detail": f"Capital allocation: {capital_allocation}"})

        # Business model durability
        business_model = static.get("business_model", "")
        recurring_revenue = metrics.get("recurring_revenue_pct", 0)
        if recurring_revenue > 70:
            score += 8
            findings.append({"type": "POSITIVE", "detail": f"Highly recurring revenue: {recurring_revenue}%"})
        elif recurring_revenue > 50:
            score += 4
        competitive_advantages = static.get("competitive_advantages", [])
        if len(competitive_advantages) >= 3:
            score += 6
            findings.append({"type": "POSITIVE", "detail": f"Multiple competitive advantages: {len(competitive_advantages)}"})
        elif len(competitive_advantages) >= 1:
            score += 3

        # Penalties
        if roic < 5:
            score -= 10
            risks.append({"type": "CAPITAL_ALLOCATION", "detail": f"Low ROIC: {roic}%"})
        if margin < 5:
            score -= 8
            risks.append({"type": "MARGIN", "detail": f"Thin operating margin: {margin}%"})
        if ceo_tenure > 0 and ceo_tenure < 2:
            score -= 5
            risks.append({"type": "MANAGEMENT", "detail": "CEO tenure under 2 years"})

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
