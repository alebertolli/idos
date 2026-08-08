from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from idos.decision.engines.base import AssessmentResult
from idos.decision.conviction import ConvictionCalculator
from idos.rules.engine import RulesEngine
from idos.events.bus import get_event_bus
from idos.events.types import Event
from idos.timezone import AR_TZ

class PipelineStage(StrEnum):
    CLASSIFICATION = "CLASSIFICATION"
    RELEVANCE = "RELEVANCE"
    IMPACT = "IMPACT"
    ORCHESTRATION = "ORCHESTRATION"
    PROPOSAL = "PROPOSAL"

@dataclass
class DecisionProposal:
    type: str
    opportunity_id: str
    assessments: dict[str, AssessmentResult]
    rules_passed: list[str]
    rules_failed: list[str]
    conviction_score: int
    recommendation: str
    rules_details: dict[str, str] = field(default_factory=dict)
    reasoning: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(AR_TZ).isoformat()

class DecisionOrchestrator:
    def __init__(self, rules_engine: RulesEngine | None = None):
        self.conviction_calc = ConvictionCalculator()
        self.rules_engine = rules_engine or RulesEngine()
        self._engines: dict[str, Any] = {}

    def register_engine(self, engine: Any):
        self._engines[engine.name] = engine

    def run_pipeline(self, event_type: str, context: dict[str, Any]) -> DecisionProposal | None:
        stage = self._classify(event_type)
        if not stage:
            return None

        if not self._check_relevance(event_type, context):
            return None

        assessments = self._run_assessments(context)
        conv = self.conviction_calc.calculate(assessments)
        rules_passed, rules_failed, rules_details = self._evaluate_rules(context, assessments, conv)

        if rules_failed:
            recommendation = "BLOCKED"
            reasoning = f"Rules blocked: {', '.join(rules_failed)}"
        else:
            if conv.overall >= 70:
                recommendation = "APPROVE"
            elif conv.overall >= 50:
                recommendation = "PENDING_REVIEW"
            else:
                recommendation = "REJECT"
            reasoning = f"Conviction: {conv.overall}/100, {len(rules_passed)} rules passed"

        proposal = DecisionProposal(
            type=event_type,
            opportunity_id=context.get("opportunity_id", ""),
            assessments=assessments,
            rules_passed=rules_passed,
            rules_failed=rules_failed,
            conviction_score=conv.overall,
            recommendation=recommendation,
            rules_details=rules_details,
            reasoning=reasoning,
        )

        bus = get_event_bus()
        bus.publish(Event(
            type="decision:proposal",
            data={"recommendation": recommendation, "conviction": conv.overall},
            source="DecisionOrchestrator",
        ))

        return proposal

    def _classify(self, event_type: str) -> PipelineStage | None:
        classifications = {
            "scout:completed": PipelineStage.CLASSIFICATION,
            "opportunity:created": PipelineStage.CLASSIFICATION,
            "opportunity:transitioned": PipelineStage.IMPACT,
            "quarterly:results": PipelineStage.IMPACT,
            "price:target_reached": PipelineStage.ORCHESTRATION,
            "risk:alert": PipelineStage.IMPACT,
            "thesis:broken": PipelineStage.ORCHESTRATION,
        }
        stage = classifications.get(event_type)
        if stage:
            bus = get_event_bus()
            bus.publish(Event(type="pipeline:classified", data={"event": event_type, "stage": stage}))
        return stage

    def _check_relevance(self, event_type: str, context: dict[str, Any]) -> bool:
        if context.get("force_relevance", False):
            return True
        active_opps = context.get("active_opportunities", [])
        ticker = context.get("ticker", "")
        if ticker and not any(o.get("ticker") == ticker for o in active_opps):
            if event_type not in ("scout:completed", "opportunity:created"):
                return False
        return True

    def _run_assessments(self, context: dict[str, Any]) -> dict[str, AssessmentResult]:
        # Permite al Decision Board reutilizar assessments ya calculadas en el
        # journal en lugar de reevaluar los engines (evita duplicación y
        # dependencia de datos financieros en vivo).
        precomputed = context.get("precomputed_assessments")
        if precomputed is not None:
            results = {}
            for engine, score in precomputed.items():
                results[engine] = AssessmentResult(
                    engine=engine,
                    version="precomputed",
                    score=int(score),
                    confidence="HIGH" if score >= 75 else "MEDIUM" if score >= 50 else "LOW",
                )
            return results

        results = {}
        for name, engine in self._engines.items():
            try:
                results[name] = engine.evaluate(context)
            except Exception as e:
                results[name] = AssessmentResult(
                    engine=name, version=engine.version,
                    score=0, confidence="LOW",
                    findings=[{"type": "ERROR", "detail": str(e)}],
                    recommendation="ERROR",
                )
        bus = get_event_bus()
        bus.publish(Event(type="assessments:completed", data={"count": len(results)}))
        return results

    def _evaluate_rules(self, context: dict[str, Any],
                        assessments: dict[str, AssessmentResult],
                        conviction: Any) -> tuple[list[str], list[str], dict[str, str]]:
        if not self.rules_engine:
            return [], [], {}
        # Mapear scores de engines a los nombres de dominio que esperan los
        # evaluadores de reglas (business_quality, valuation, rerating, risk).
        domain = {
            "business_quality": self._score_for(assessments, "BusinessAssessmentEngine"),
            "valuation": self._score_for(assessments, "ValuationAssessmentEngine"),
            "rerating": self._score_for(assessments, "RecoveryAssessmentEngine"),
            "risk": self._score_for(assessments, "RiskAssessmentEngine"),
            "portfolio": self._score_for(assessments, "PortfolioAssessmentEngine"),
        }
        ctx = {**context, "assessments": domain, "conviction": {"overall": conviction.overall}}
        passed, failed, details = [], [], {}
        for result in self.rules_engine.evaluate_all(ctx):
            if result.passed:
                passed.append(result.rule_id)
            else:
                failed.append(result.rule_id)
            details[result.rule_id] = result.details
        return passed, failed, details

    @staticmethod
    def _score_for(assessments: dict[str, AssessmentResult], name: str) -> int:
        r = assessments.get(name)
        return r.score if r is not None else 0
