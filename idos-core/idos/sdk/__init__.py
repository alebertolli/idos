from idos.core.context import IDOSContext
from idos.data.knowledge import KnowledgeRepository
from idos.data.journal import JournalRepository
from idos.data.sqlite import SQLiteStore
from idos.ai.llm import LLMClient, LLMResponse
from idos.ai.service import LLMService
from idos.events.bus import get_event_bus, EventBus
from idos.events.types import Event
from idos.state.machine import OpportunityStateMachine, StateMachine, Transition
from idos.models.enums import (
    OpportunityStatus,
    HypothesisStatus,
    DecisionType,
    AssessmentStatus,
    EvidenceType,
    ConfidenceLevel,
    ConvictionTrend,
)
from idos.models.knowledge import (
    Company,
    KnowledgeBase,
    Hypothesis,
    Prediction,
    Evidence,
    Rule,
)
from idos.models.journal import (
    Opportunity,
    CaseFile,
    Assessment,
    Decision,
    PortfolioPosition,
    Review,
    ProvenanceEntry,
)
from idos.models.conviction import Conviction
from idos.telemetry.trace import get_tracer, Tracer
from idos.workers.base import BaseWorker, WorkerResult, WorkerStatus
from idos.notifications.center import NotificationCenter, Notification, get_notification_center
from idos.resilience.retry import RetryMechanism, RetryPolicy
from idos.resilience.circuit import CircuitBreaker, CircuitState
from idos.resilience.health import HealthMonitor, HealthStatus
from idos.resilience.checkpoint import CheckpointManager, RunManifest
from idos.resilience.self_healing import SelfHealer
from idos.resilience.adaptive import AdaptiveRouter, ProviderScore, TaskRequirement
from idos.resilience.cost_control import CostController, CostBudget
from idos.resilience.degrade import GracefulDegradation, FallbackMode
from idos.resilience.audit import AuditTrail, AuditEntry
from idos.resilience.ratelimit import RateLimiter
from idos.knowledge.wiki import AtomicWiki, WikiSection, WikiMetadata
from idos.knowledge.lifecycle import KnowledgeLifecycle, KnowledgeObject, KnowledgeStatus
from idos.knowledge.claims import Claim, ClaimStore, ClaimStatus
from idos.knowledge.contradiction import ContradictionDetector, Contradiction
from idos.provenance.engine import ProvenanceEngine
from idos.market.prices import PriceProvider
from idos.sdk.agent import AgentBase
from idos.workers.automation.gha_error_reporter import GHAErrorReporter, create_issue
from idos.workers.automation.auto_fix_agent import AutoFixAgent
from idos.rules.engine import RulesEngine
from idos.rules.evaluators import RuleEvaluator
from idos.decision.orchestrator import DecisionOrchestrator
from idos.decision.board import DecisionBoard
from idos.decision.conviction import ConvictionCalculator
from idos.portfolio.engine import PortfolioEngine
from idos.portfolio.entry import EntryEngine
from idos.portfolio.exit import ExitEngine
from idos.portfolio.risk import RiskEngine
from idos.portfolio.sizing import PositionSizer
from idos.portfolio.wyckoff import WyckoffAnalyzer
from idos.discovery.scout import ScoutEngine
from idos.discovery.screening import FinvizScreener
from idos.discovery.operability import OperabilityFilter


def create_context(base_path: str | None = None) -> IDOSContext:
    from pathlib import Path
    if base_path:
        return IDOSContext.create(Path(base_path))
    return IDOSContext.defaults()


def configure(base_path: str):
    ctx = create_context(base_path)
    store = SQLiteStore(ctx.sqlite_path)
    knowledge = KnowledgeRepository(ctx.knowledge_path)
    journal = JournalRepository(ctx.journal_path)
    tracer = get_tracer()
    tracer.configure(store)
    return ctx, store, knowledge, journal


__all__ = [
    "IDOSContext", "KnowledgeRepository", "JournalRepository", "SQLiteStore",
    "LLMClient", "LLMResponse", "LLMService",
    "get_event_bus", "EventBus", "Event",
    "OpportunityStateMachine", "StateMachine", "Transition",
    "OpportunityStatus", "HypothesisStatus", "DecisionType", "AssessmentStatus",
    "EvidenceType", "ConfidenceLevel", "ConvictionTrend",
    "Company", "KnowledgeBase", "Hypothesis", "Prediction", "Evidence", "Rule",
    "Opportunity", "CaseFile", "Assessment", "Decision", "PortfolioPosition",
    "Review", "ProvenanceEntry", "Conviction",
    "get_tracer", "Tracer",
    "BaseWorker", "WorkerResult", "WorkerStatus",
    "NotificationCenter", "Notification", "get_notification_center",
    "RetryMechanism", "RetryPolicy",
    "CircuitBreaker", "CircuitState",
    "HealthMonitor", "HealthStatus",
    "CheckpointManager", "RunManifest",
    "SelfHealer",
    "AdaptiveRouter", "ProviderScore", "TaskRequirement",
    "CostController", "CostBudget",
    "GracefulDegradation", "FallbackMode",
    "AuditTrail", "AuditEntry",
    "RateLimiter",
    "AtomicWiki", "WikiSection", "WikiMetadata",
    "KnowledgeLifecycle", "KnowledgeObject", "KnowledgeStatus",
    "Claim", "ClaimStore", "ClaimStatus",
    "ContradictionDetector", "Contradiction",
    "ProvenanceEngine",
    "PriceProvider",
    "AgentBase",
    "RulesEngine", "RuleEvaluator",
    "DecisionOrchestrator", "DecisionBoard", "ConvictionCalculator",
    "PortfolioEngine", "EntryEngine", "ExitEngine", "RiskEngine",
    "PositionSizer", "WyckoffAnalyzer",
    "ScoutEngine", "FinvizScreener", "OperabilityFilter",
    "AutoFixAgent", "GHAErrorReporter", "create_issue",
    "create_context", "configure",
]
