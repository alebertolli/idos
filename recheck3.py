import sys
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.decision.assessment_pipeline import run_full_pipeline
for ticker, opp_id in [('AAPL', 'OPP-20260813-073'), ('ACN', 'OPP-20260813-001')]:
    r = run_full_pipeline(opp_id, ticker, '.', force_reprocess=True)
    print(f"{ticker} {opp_id}: rules_failed={r['rules_failed']}, conv={r['conviction_score']}, board={r['board_approved']}")
