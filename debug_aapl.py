import sys
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.data.sqlite import SQLiteStore
from idos.data.journal import JournalRepository

sqlite = SQLiteStore(Path('idos.db'))
journal = JournalRepository(Path('idos-journal'))

# Look at the OPP for AAPL/ACN
for ticker, opp_id in [('AAPL', 'OPP-20260813-073'), ('ACN', 'OPP-20260813-001')]:
    print(f'\n===== {ticker} {opp_id} =====')
    opps_sql = sqlite.list_opportunities()
    opp_sql = next((o for o in opps_sql if o.get('id') == opp_id), None)
    if opp_sql:
        print(f'  SQLite score: {opp_sql.get("score")}')
        print(f'  SQLite status: {opp_sql.get("status")}')
        print(f'  All SQLite keys: {list(opp_sql.keys())}')
    opp_yml = journal.load_opportunity(ticker, opp_id)
    if opp_yml:
        print(f'  YAML score: {opp_yml.get("score")}')
        print(f'  YAML status: {opp_yml.get("status")}')
        print(f'  All YAML keys: {list(opp_yml.keys())}')
