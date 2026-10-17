import math
from typing import Any
from idos.decision.engines.base import BaseAssessmentEngine, AssessmentResult


class RiskAssessmentEngine(BaseAssessmentEngine):
    name = "RiskAssessmentEngine"
    version = "1.1"

    def evaluate(self, context: dict[str, Any]) -> AssessmentResult:
        knowledge_base = context.get("knowledge_base", {})
        dynamic = knowledge_base.get("dynamic", {}) if isinstance(knowledge_base, dict) else {}
        if not isinstance(dynamic, dict):
            dynamic = {}
        m = dynamic.get("metrics", {})
        if not isinstance(m, dict):
            m = {}
        availability = dynamic.get("metric_availability", {})
        if not isinstance(availability, dict):
            availability = {}
        portfolio = context.get("portfolio", {})
        if not isinstance(portfolio, dict):
            portfolio = {}
        score = 70
        findings = []
        risks = []

        def metric(name: str) -> float | None:
            aliases = {"debt_to_equity": ("debt_equity_ratio",)}
            source_names = (name, *aliases.get(name, ()))
            present = any(key in m for key in source_names)
            if availability.get(name) is False or not present:
                risks.append({"type": "DATA_QUALITY", "metric": name, "detail": f"{name} is UNKNOWN"})
                return None
            raw = next((m[key] for key in source_names if key in m), None)
            if isinstance(raw, bool):
                value = None
            else:
                try:
                    value = float(raw)
                except (TypeError, ValueError, OverflowError):
                    value = None
            if value is None or not math.isfinite(value) or value < 0:
                risks.append({"type": "DATA_QUALITY", "metric": name, "detail": f"{name} is UNKNOWN or invalid"})
                return None
            return value

        debt_equity = metric("debt_to_equity")
        volatility = metric("volatility_90d")
        current_ratio = metric("current_ratio")

        if debt_equity is not None and debt_equity > 2:
            score -= 20
            risks.append({"type": "LEVERAGE", "detail": f"High debt/equity: {debt_equity:.1f}x"})
        elif debt_equity is not None and debt_equity > 1:
            score -= 10
            risks.append({"type": "LEVERAGE", "detail": f"Moderate leverage: {debt_equity:.1f}x"})
        elif debt_equity is not None and debt_equity < 0.3:
            score += 10
            findings.append({"type": "POSITIVE", "detail": "Low leverage"})

        if volatility is not None and volatility > 40:
            score -= 10
            risks.append({"type": "VOLATILITY", "detail": f"High volatility: {volatility}%"})
        elif volatility is not None and volatility > 30:
            score -= 5

        if current_ratio is not None and current_ratio < 1.0:
            score -= 10
            risks.append({"type": "LIQUIDITY", "detail": f"Current ratio below 1: {current_ratio:.1f}x"})

        if "position_weight" in portfolio:
            raw_concentration = portfolio["position_weight"]
            try:
                concentration = float(raw_concentration) if not isinstance(raw_concentration, bool) else math.nan
            except (TypeError, ValueError, OverflowError):
                concentration = math.nan
            if not math.isfinite(concentration) or concentration < 0:
                risks.append({"type": "DATA_QUALITY", "metric": "position_weight", "detail": "position_weight is UNKNOWN or invalid"})
            elif concentration > 3.0:
                score -= 10
                risks.append({"type": "CONCENTRATION", "detail": f"Position at {concentration}% exceeds 3% limit"})

        score = max(0, min(100, score))
        incomplete = any(risk["type"] == "DATA_QUALITY" for risk in risks)
        if incomplete:
            score = 0
            recommendation = "INSUFFICIENT_DATA"
            confidence = "LOW"
        else:
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
