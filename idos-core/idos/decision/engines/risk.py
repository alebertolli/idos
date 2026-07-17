from typing import Any
from idos.decision.engines.base import BaseAssessmentEngine, AssessmentResult


class RiskAssessmentEngine(BaseAssessmentEngine):
    name = "RiskAssessmentEngine"
    version = "1.0"

    def evaluate(self, context: dict[str, Any]) -> AssessmentResult:
        m = context.get("knowledge_base", {}).get("dynamic", {}).get("metrics", {})
        portfolio = context.get("portfolio", {})
        score = 70
        findings = []
        risks = []

        debt_equity = m.get("debt_to_equity", 0)
        if debt_equity > 2:
            score -= 20
            risks.append({"type": "LEVERAGE", "detail": f"High debt/equity: {debt_equity:.1f}x"})
        elif debt_equity > 1:
            score -= 10
            risks.append({"type": "LEVERAGE", "detail": f"Moderate leverage: {debt_equity:.1f}x"})
        elif debt_equity < 0.3:
            score += 10
            findings.append({"type": "POSITIVE", "detail": "Low leverage"})

        volatility = m.get("volatility_90d", 0)
        if volatility > 40:
            score -= 10
            risks.append({"type": "VOLATILITY", "detail": f"High volatility: {volatility}%"})
        elif volatility > 30:
            score -= 5

        current_ratio = m.get("current_ratio", 1)
        if current_ratio < 1.0:
            score -= 10
            risks.append({"type": "LIQUIDITY", "detail": f"Current ratio below 1: {current_ratio:.1f}x"})

        concentration = portfolio.get("position_weight", 0)
        if concentration > 3.0:
            score -= 10
            risks.append({"type": "CONCENTRATION", "detail": f"Position at {concentration}% exceeds 3% limit"})

        score = max(0, min(100, score))
        recommendation = "LOW_RISK" if score >= 70 else "MODERATE_RISK" if score >= 40 else "HIGH_RISK"
        confidence = "HIGH" if score >= 75 else "MEDIUM"

        return AssessmentResult(
            engine=self.name,
            version=self.version,
            score=score,
            confidence=confidence,
            findings=findings,
            risks=risks,
            recommendation=recommendation,
        )
