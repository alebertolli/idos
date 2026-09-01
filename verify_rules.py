import sys, yaml, json
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.data.sqlite import SQLiteStore
from idos.data.journal import JournalRepository
from idos.data.knowledge import KnowledgeRepository
from idos.decision.assessment_pipeline import run_full_pipeline

bp = Path('.')
sqlite = SQLiteStore(bp / 'idos.db')
journal = JournalRepository(bp / 'idos-journal')
knowledge = KnowledgeRepository(bp / 'idos-knowledge')

data = json.loads(Path('site/data.json').read_text(encoding='utf-8'))
under_research = [o for o in data.get('opportunities', []) if o.get('status') == 'UNDER_RESEARCH']
print(f'UNDER_RESEARCH count: {len(under_research)}\n')

for o in sorted(under_research, key=lambda x: x['ticker']):
    ticker = o['ticker']
    opp_id = o['opp_id']

    dp_path = bp / 'idos-journal' / 'companies' / ticker / 'case_file' / 'opportunities' / opp_id / 'decision_proposal.yml'

    dp_before = yaml.safe_load(dp_path.read_text(encoding='utf-8')) if dp_path.exists() else {}
    assessments_before = dp_before.get('assessments', {})

    bq = assessments_before.get('BusinessAssessmentEngine', {}).get('score', 0)
    risk = assessments_before.get('RiskAssessmentEngine', {}).get('score', 0)
    rerating = assessments_before.get('RecoveryAssessmentEngine', {}).get('score', 0)
    conv_before = dp_before.get('conviction_score', 0)

    from idos.decision.assessment_pipeline import build_context
    ctx = build_context(opp_id, ticker, bp, sqlite, knowledge, journal)
    asym = ctx.get('asymmetry') or {}
    br_ratio = asym.get('benefit_risk_ratio', 0) if isinstance(asym, dict) else 0

    calc_001 = bq >= 70
    calc_004 = risk >= 50
    calc_003 = rerating >= 50
    calc_005 = conv_before >= 65
    calc_008 = br_ratio >= 3.0

    expected_failed = sorted([rid for rid, passed in [
        ('RULE-001', calc_001), ('RULE-004', calc_004), ('RULE-003', calc_003),
        ('RULE-005', calc_005), ('RULE-008', calc_008)
    ] if not passed])

    r = run_full_pipeline(opp_id, ticker, '.', force_reprocess=True)
    actual_failed = sorted(r.get('rules_failed', []))

    mismatch = actual_failed != expected_failed

    print(f'{"MISMATCH " if mismatch else "OK      "} {ticker} ({opp_id})')
    print(f'  RULE-001 business={bq} >= 70 -> {"PASS" if calc_001 else "FAIL"}  (actual: {"FAIL" if "RULE-001" in actual_failed else "PASS"})')
    print(f'  RULE-004 risk={risk} >= 50 -> {"PASS" if calc_004 else "FAIL"}  (actual: {"FAIL" if "RULE-004" in actual_failed else "PASS"})')
    print(f'  RULE-003 rerating={rerating} >= 50 -> {"PASS" if calc_003 else "FAIL"}  (actual: {"FAIL" if "RULE-003" in actual_failed else "PASS"})')
    print(f'  RULE-005 conviction={conv_before} >= 65 -> {"PASS" if calc_005 else "FAIL"}  (actual: {"FAIL" if "RULE-005" in actual_failed else "PASS"})')
    print(f'  RULE-008 asymmetry(br)={br_ratio:.2f} >= 3.0 -> {"PASS" if calc_008 else "FAIL"}  (actual: {"FAIL" if "RULE-008" in actual_failed else "PASS"})')
    if mismatch:
        print(f'  EXPECTED failed: {expected_failed}')
        print(f'  ACTUAL failed:   {actual_failed}')
    print()
