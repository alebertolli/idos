from typing import Any
from idos.decision.engines.base import BaseAssessmentEngine, AssessmentResult


class PortfolioAssessmentEngine(BaseAssessmentEngine):
    name = "PortfolioAssessmentEngine"
    version = "1.0"

    def evaluate(self, context: dict[str, Any]) -> AssessmentResult:
        portfolio = context.get("portfolio", {})
        company = context.get("company", {})
        score = 60
        findings = []
        risks = []

        current_weight = portfolio.get("total_weight", 0)
        new_weight = context.get("proposed_weight", 3.0)
        if current_weight + new_weight <= 20:
            score += 10
            findings.append({"type": "POSITIVE", "detail": "Portfolio has capacity for new position"})
        else:
            score -= 15
            risks.append({"type": "CAPACITY", "detail": "Portfolio near full allocation"})

        sector = company.get("sector", "")
        sector_exposure = portfolio.get("sector_exposure", {}).get(sector, 0)
        if sector_exposure + new_weight <= 25:
            score += 10
            findings.append({"type": "POSITIVE", "detail": f"Sector {sector} within diversification limits"})
        else:
            score -= 15
            risks.append({"type": "SECTOR", "detail": f"Sector {sector} would exceed 25% limit"})

        correlations = portfolio.get("thematic_correlations", {})
        company_themes = context.get("themes", [])
        correlated_weight = 0
        for theme in company_themes:
            correlated_weight += correlations.get(theme, 0)
        if correlated_weight + new_weight <= 30:
            score += 5
        else:
            score -= 10
            risks.append({"type": "THEMATIC", "detail": "Thematic correlation limit approached"})

        num_positions = portfolio.get("num_positions", 0)
        if num_positions < 8:
            score += 5
            findings.append({"type": "POSITIVE", "detail": f"Only {num_positions} positions, adding increases diversification"})
        elif num_positions > 15:
            score -= 5
            risks.append({"type": "DIVERSIFICATION", "detail": f"Already {num_positions} positions, consider concentration"})

        score = max(0, min(100, score))
        recommendation = "EXCELLENT_FIT" if score >= 75 else "GOOD_FIT" if score >= 50 else "POOR_FIT"

        return AssessmentResult(
            engine=self.name,
            version=self.version,
            score=score,
            confidence="HIGH" if score >= 75 else "MEDIUM",
            findings=findings,
            risks=risks,
            recommendation=recommendation,
        )
