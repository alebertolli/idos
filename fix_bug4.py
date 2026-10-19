import sys, yaml
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.data.sqlite import SQLiteStore
from idos.data.journal import JournalRepository
from idos.decision.assessment_pipeline import run_full_pipeline
from datetime import datetime
from idos.timezone import AR_TZ

sqlite = SQLiteStore(Path('idos.db'))
journal = JournalRepository(Path('idos-journal'))

# Revert AAPL and ACN to their original research states
fixes = [
    ('AAPL', 'OPP-20260813-073', 'UNDER_RESEARCH'),  # ResearchWorker ran for AAPL
    ('ACN',  'OPP-20260813-001', 'SCREENED'),        # ResearchWorker never ran for ACN
]

for ticker, opp_id, target_status in fixes:
    # Fix SQLite
    opp = sqlite.get_opportunity(opp_id)
    if opp:
        old = opp['status']
        opp['status'] = target_status
        sqlite.save_opportunity(opp)
        print(f'SQLite: {ticker} {opp_id}: {old} -> {target_status}')

    # Fix YAML
    yaml_opp = journal.load_opportunity(ticker, opp_id)
    if yaml_opp:
        old = yaml_opp.get('status')
        yaml_opp['status'] = target_status
        journal.save_opportunity(ticker, yaml_opp)
        print(f'YAML:   {ticker} {opp_id}: {old} -> {target_status}')

# Now re-run the pipeline on both
for ticker, opp_id in [('AAPL', 'OPP-20260813-073'), ('ACN', 'OPP-20260813-001')]:
    r = run_full_pipeline(opp_id, ticker, '.', force_reprocess=True)
    print(f'\n{ticker} {opp_id}: status={r["status"]}, rules_failed={r["rules_failed"]}, board_approved={r["board_approved"]}')
    # Verify the actual YAML status
    yaml_opp = journal.load_opportunity(ticker, opp_id)
    if yaml_opp:
        print(f'  YAML status after pipeline: {yaml_opp.get("status")}')
