import sys
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.decision.assessment_pipeline import run_full_pipeline

for ticker, opp_id in [('AVGO', 'OPP-20260807-009'), ('GFI', 'OPP-20260725-002'), ('HWM', 'OPP-20260807-003')]:
    r = run_full_pipeline(opp_id, ticker, '.', force_reprocess=True)
    print(f"{ticker} {opp_id}: rules_failed={r['rules_failed']}, conv={r['conviction_score']}")
