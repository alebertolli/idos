from idos.decision.orchestrator import DecisionOrchestrator, PipelineStage
from idos.decision.engines.business import BusinessAssessmentEngine
from idos.decision.engines.valuation import ValuationAssessmentEngine
from idos.decision.engines.recovery import RecoveryAssessmentEngine
from idos.decision.engines.risk import RiskAssessmentEngine
from idos.decision.engines.portfolio import PortfolioAssessmentEngine


def test_orchestrator_classification():
    orch = DecisionOrchestrator()
    stage = orch._classify("scout:completed")
    assert stage == PipelineStage.CLASSIFICATION
    stage = orch._classify("thesis:broken")
    assert stage == PipelineStage.ORCHESTRATION
    stage = orch._classify("unknown:event")
    assert stage is None


def test_orchestrator_full_pipeline():
    orch = DecisionOrchestrator()
    orch.register_engine(BusinessAssessmentEngine())
    orch.register_engine(ValuationAssessmentEngine())
    orch.register_engine(RiskAssessmentEngine())

    proposal = orch.run_pipeline("opportunity:created", {
        "opportunity_id": "OPP-2026-001",
        "ticker": "MELI",
        "force_relevance": True,
        "knowledge_base": {
            "static": {"moat_description": "Network effects"},
            "dynamic": {
                "metrics": {
                    "roic": 25, "revenue_growth": 22, "operating_margin": 28,
                    "pe_ratio": 15, "pe_historical_avg": 22, "fcf_yield": 4,
                    "debt_to_equity": 0.3, "volatility_90d": 20,
                }
            },
        },
        "margin_of_safety": 35,
        "portfolio": {"position_weight": 1.0},
    })

    assert proposal is not None
    assert proposal.opportunity_id == "OPP-2026-001"
    assert "BusinessAssessmentEngine" in proposal.assessments
    assert "ValuationAssessmentEngine" in proposal.assessments
    assert "RiskAssessmentEngine" in proposal.assessments


def test_orchestrator_relevance_filter():
    orch = DecisionOrchestrator()
    proposal = orch.run_pipeline("price:target_reached", {
        "ticker": "UNKNOWN",
        "active_opportunities": [],
    })
    assert proposal is None


def test_orchestrator_engine_error_handling():
    class FailingEngine:
        name = "FailingEngine"
        version = "1.0"
        def evaluate(self, ctx):
            raise ValueError("Simulated failure")

    orch = DecisionOrchestrator()
    orch.register_engine(FailingEngine())
    proposal = orch.run_pipeline("opportunity:created", {
        "opportunity_id": "OPP-001", "force_relevance": True,
    })
    assert proposal is not None
    assert proposal.assessments["FailingEngine"].score == 0
