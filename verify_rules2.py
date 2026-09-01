import sys, yaml, json
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.data.sqlite import SQLiteStore
from idos.data.journal import JournalRepository
from idos.data.knowledge import KnowledgeRepository
from idos.decision.assessment_pipeline import run_full_pipeline, build_context
from idos.decision.orchestrator import DecisionOrchestrator
from idos.decision.conviction import ConvictionCalculator
from idos.decision.engines.business import BusinessAssessmentEngine
from idos.decision.engines.valuation import ValuationAssessmentEngine
from idos.decision.engines.recovery import RecoveryAssessmentEngine
from idos.decision.engines.risk import RiskAssessmentEngine
from idos.decision.engines.portfolio import PortfolioAssessmentEngine

bp = Path('.')
sqlite = SQLiteStore(bp / 'idos.db')
journal = JournalRepository(bp / 'idos-journal')
knowledge = KnowledgeRepository(bp / 'idos-knowledge')

data = json.loads(Path('site/data.json').read_text(encoding='utf-8'))
under_research = [o for o in data.get('opportunities', []) if o.get('status') == 'UNDER_RESEARCH']
print(f'UNDER_RESEARCH count: {len(under_research)}\n')

mismatches = 0

for o in sorted(under_research, key=lambda x: x['ticker']):
    ticker = o['ticker']
    opp_id = o['opp_id']

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
    asym = ctx.get('asymmetry') or {}
    br_ratio = asym.get('benefit_risk_ratio', 0) if isinstance(asym, dict) else 0

    bq = assessments.get('BusinessAssessmentEngine').score
    risk = assessments.get('RiskAssessmentEngine').score
    rerating = assessments.get('RecoveryAssessmentEngine').score
    conv_v = conv.overall

    calc_001 = bq >= 70
    calc_004 = risk >= 50
    calc_003 = rerating >= 50
    calc_005 = conv_v >= 65
    calc_008 = br_ratio >= 3.0

    expected_failed = sorted([rid for rid, passed in [
        ('RULE-001', calc_001), ('RULE-004', calc_004), ('RULE-003', calc_003),
        ('RULE-005', calc_005), ('RULE-008', calc_008)
    ] if not passed])

    r = run_full_pipeline(opp_id, ticker, '.', force_reprocess=True)
    actual_failed = sorted(r.get('rules_failed', []))

    mismatch = actual_failed != expected_failed
    if mismatch:
        mismatches += 1
        print(f'MISMATCH {ticker} ({opp_id})')
        print(f'  bq={bq} risk={risk} rerating={rerating} conv={conv_v} asym={br_ratio}')
        print(f'  calc_001={calc_001} calc_004={calc_004} calc_003={calc_003} calc_005={calc_005} calc_008={calc_008}')
        print(f'  EXPECTED failed: {expected_failed}')
        print(f'  ACTUAL failed:   {actual_failed}')
        print()

print(f'\nTotal mismatches: {mismatches} / {len(under_research)}')
