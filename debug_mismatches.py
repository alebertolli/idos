import sys, yaml, json
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.data.sqlite import SQLiteStore
from idos.data.journal import JournalRepository
from idos.data.knowledge import KnowledgeRepository
from idos.decision.assessment_pipeline import run_full_pipeline, build_context
from idos.decision.orchestrator import DecisionOrchestrator
from idos.decision.conviction import ConvictionCalculator
from idos.rules.engine import RulesEngine
from idos.decision.engines.business import BusinessAssessmentEngine
from idos.decision.engines.valuation import ValuationAssessmentEngine
from idos.decision.engines.recovery import RecoveryAssessmentEngine
from idos.decision.engines.risk import RiskAssessmentEngine
from idos.decision.engines.portfolio import PortfolioAssessmentEngine

bp = Path('.')
sqlite = SQLiteStore(bp / 'idos.db')
journal = JournalRepository(bp / 'idos-journal')
knowledge = KnowledgeRepository(bp / 'idos-knowledge')

# MISMATCH cases
for ticker, opp_id in [('CSCO', 'OPP-20260813-098'), ('GRMN', 'OPP-20260730-001'), ('IBN', 'OPP-20260807-008'), ('WFC', 'OPP-20260725-038')]:
    print(f'\n{"="*60}')
    print(f'{ticker} {opp_id}')

    # Re-run pipeline
    r = run_full_pipeline(opp_id, ticker, '.', force_reprocess=True)
    dp_path = bp / 'idos-journal' / 'companies' / ticker / 'case_file' / 'opportunities' / opp_id / 'decision_proposal.yml'
    dp = yaml.safe_load(dp_path.read_text(encoding='utf-8'))

    # Get fresh scores from assessment engines
    ctx = build_context(opp_id, ticker, bp, sqlite, knowledge, journal)
    orch = DecisionOrchestrator()
    orch.register_engine(BusinessAssessmentEngine())
    orch.register_engine(ValuationAssessmentEngine())
    orch.register_engine(RecoveryAssessmentEngine())
    orch.register_engine(RiskAssessmentEngine())
    orch.register_engine(PortfolioAssessmentEngine())
    orch.conviction_calc = ConvictionCalculator()
    assessments = orch._run_assessments(ctx)
    conv = orch.conviction_calc.calculate(assessments)

    print(f'  Stored conviction: {dp.get("conviction_score")}')
    print(f'  Fresh conviction: {conv.overall}')
    print(f'  Stored business: {dp.get("assessments", {}).get("BusinessAssessmentEngine", {}).get("score")}')
    print(f'  Fresh business:  {assessments.get("BusinessAssessmentEngine").score if "BusinessAssessmentEngine" in assessments else "N/A"}')
    print(f'  Stored risk: {dp.get("assessments", {}).get("RiskAssessmentEngine", {}).get("score")}')
    print(f'  Fresh risk:  {assessments.get("RiskAssessmentEngine").score if "RiskAssessmentEngine" in assessments else "N/A"}')
    print(f'  Stored rerating: {dp.get("assessments", {}).get("RecoveryAssessmentEngine", {}).get("score")}')
    print(f'  Fresh rerating:  {assessments.get("RecoveryAssessmentEngine").score if "RecoveryAssessmentEngine" in assessments else "N/A"}')
    print(f'  Stored rules_failed: {r.get("rules_failed")}')
