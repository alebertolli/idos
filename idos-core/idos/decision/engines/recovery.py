from typing import Any
from idos.decision.engines.base import BaseAssessmentEngine, AssessmentResult


class RecoveryAssessmentEngine(BaseAssessmentEngine):
    name = "RecoveryAssessmentEngine"
    version = "1.0"

    DIMENSIONS = {
        "business_momentum": 0.25,
        "valuation_gap": 0.20,
        "market_expectations": 0.15,
        "catalysts": 0.20,
        "technical_confirmation": 0.10,
        "risk_compression": 0.10,
    }

    def evaluate(self, context: dict[str, Any]) -> AssessmentResult:
        dim_scores = {}
        dim_findings = []

        dim_scores["business_momentum"] = self._score_business_momentum(context)
        dim_scores["valuation_gap"] = self._score_valuation_gap(context)
        dim_scores["market_expectations"] = self._score_market_expectations(context)
        dim_scores["catalysts"] = self._score_catalysts(context)
        dim_scores["technical_confirmation"] = self._score_technical(context)
        dim_scores["risk_compression"] = self._score_risk_compression(context)

        score = sum(dim_scores[k] * w for k, w in self.DIMENSIONS.items())
        score = int(round(max(0, min(100, score))))

        findings = []
        for dim, s in dim_scores.items():
            level = "HIGH" if s >= 70 else "MEDIUM" if s >= 40 else "LOW"
            findings.append({"type": "DIMENSION", "dimension": dim, "score": s, "level": level})

        recommendation = "HIGH_PROBABILITY" if score >= 70 else "MODERATE" if score >= 40 else "LOW_PROBABILITY"
        confidence = "HIGH" if score >= 75 else "MEDIUM"

        return AssessmentResult(
            engine=self.name,
            version=self.version,
            score=score,
            confidence=confidence,
            findings=findings,
            risks=[],
            recommendation=recommendation,
        )

    def _score_business_momentum(self, ctx: dict[str, Any]) -> int:
        m = ctx.get("knowledge_base", {}).get("dynamic", {}).get("metrics", {})
        s = 50
        if m.get("revenue_growth", 0) > 15: s += 10
        if m.get("eps_growth", 0) > 15: s += 10
        if m.get("fcf_growth", 0) > 15: s += 10
        if m.get("roic", 0) > 15: s += 10
        if m.get("operating_margin", 0) < 5: s -= 15
        return max(0, min(100, s))

    def _score_valuation_gap(self, ctx: dict[str, Any]) -> int:
        m = ctx.get("knowledge_base", {}).get("dynamic", {}).get("metrics", {})
        s = 50
        pe_c = m.get("pe_ratio", 0)
        pe_h = m.get("pe_historical_avg", 0)
        if pe_h and pe_c and pe_c < pe_h * 0.7: s += 20
        mos = ctx.get("margin_of_safety", 0)
        if mos > 40: s += 15
        elif mos >= 20: s += 10
        fcf = m.get("fcf_yield", 0)
        if fcf > 5: s += 10
        return max(0, min(100, s))

    def _score_market_expectations(self, ctx: dict[str, Any]) -> int:
        m = ctx.get("knowledge_base", {}).get("dynamic", {}).get("metrics", {})
        s = 50
        eps_revisions = m.get("eps_revision_trend", 0)
        if eps_revisions > 0: s += 15
        short_interest = m.get("short_interest_pct", 100)
        if short_interest > 10: s += 10
        analyst_rating = m.get("analyst_consensus", 0)
        if analyst_rating > 4: s += 10
        return max(0, min(100, s))

    def _score_catalysts(self, ctx: dict[str, Any]) -> int:
        cat = ctx.get("catalysts", [])
        s = 30
        for c in cat:
            impact = c.get("impact", "low")
            if impact == "high": s += 15
            elif impact == "medium": s += 10
            else: s += 5
            if c.get("timeline", "long") == "short": s += 5
        return max(0, min(100, s))

    def _score_technical(self, ctx: dict[str, Any]) -> int:
        m = ctx.get("knowledge_base", {}).get("dynamic", {}).get("metrics", {})
        s = 50
        wyckoff = m.get("wyckoff_phase", "")
        if wyckoff == "accumulation": s += 20
        elif wyckoff == "absorption": s += 10
        weinstein = m.get("weinstein_stage", "")
        if weinstein == "stage_1": s += 10
        elif weinstein == "stage_2": s += 5
        rs = m.get("relative_strength", 0)
        if rs > 0: s += 10
        return max(0, min(100, s))

    def _score_risk_compression(self, ctx: dict[str, Any]) -> int:
        m = ctx.get("knowledge_base", {}).get("dynamic", {}).get("metrics", {})
        events = ctx.get("risk_events", [])
        s = 50
        leverage = m.get("debt_to_equity", 999)
        if leverage < 0.5: s += 10
        elif leverage > 2: s -= 10
        litigation = m.get("litigation_risk", "high")
        if litigation == "resolved": s += 15
        elif litigation == "low": s += 5
        for e in events:
            if e.get("type") == "regulatory" and e.get("resolution") == "favorable":
                s += 10
        return max(0, min(100, s))
