from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import StrEnum
from typing import Any


class PipelineStage(StrEnum):
    EVENT_CLASSIFICATION = "EVENT_CLASSIFICATION"
    RELEVANCE_ANALYSIS = "RELEVANCE_ANALYSIS"
    KNOWLEDGE_UPDATE = "KNOWLEDGE_UPDATE"
    RULE_INJECTION = "RULE_INJECTION"
    DECISION_PROPOSAL = "DECISION_PROPOSAL"


@dataclass
class PipelineContext:
    event_type: str = ""
    ticker: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    findings: dict[str, Any] = field(default_factory=dict)
    rules_applied: list[str] = field(default_factory=list)
    proposal: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""

    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.now(UTC).isoformat()


class PipelineStageHandler:
    def process(self, stage: PipelineStage, ctx: PipelineContext) -> PipelineContext:
        method = getattr(self, f"handle_{stage.value.lower()}", None)
        if method:
            return method(ctx)
        return ctx


class DecisionPipeline(PipelineStageHandler):
    def run(self, ctx: PipelineContext) -> PipelineContext:
        stages = list(PipelineStage)
        for stage in stages:
            ctx = self.process(stage, ctx)
        ctx.completed_at = datetime.now(UTC).isoformat()
        return ctx

    def handle_event_classification(self, ctx: PipelineContext) -> PipelineContext:
        ctx.findings["classified_as"] = ctx.event_type
        return ctx

    def handle_relevance_analysis(self, ctx: PipelineContext) -> PipelineContext:
        ctx.findings["relevant"] = bool(ctx.ticker and ctx.event_type)
        return ctx

    def handle_knowledge_update(self, ctx: PipelineContext) -> PipelineContext:
        ctx.findings["knowledge_updated"] = True
        return ctx

    def handle_rule_injection(self, ctx: PipelineContext) -> PipelineContext:
        ctx.rules_applied.append("position_sizing")
        ctx.rules_applied.append("risk_limits")
        return ctx

    def handle_decision_proposal(self, ctx: PipelineContext) -> PipelineContext:
        ctx.proposal = {
            "action": "review" if ctx.findings.get("relevant") else "ignore",
            "ticker": ctx.ticker,
            "confidence": 0.5,
        }
        return ctx
