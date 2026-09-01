import sys
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.decision.assessment_pipeline import run_full_pipeline

for ticker, opp_id in [('AAPL', 'OPP-20260813-073'), ('ACN', 'OPP-20260813-001')]:
    print(f'\n===== {ticker} {opp_id} =====')
    r = run_full_pipeline(opp_id, ticker, '.', force_reprocess=True)
    print(f"  rules_failed: {r['rules_failed']}")
    print(f"  conviction: {r['conviction_score']}")
    print(f"  board_approved: {r['board_approved']}")
    print(f"  data_quality: {r['data_quality']}")
    print(f"  assessments: {r.get('assessments', {})}")
