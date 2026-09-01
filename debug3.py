import sys, json
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.data.sqlite import SQLiteStore
from idos.data.journal import JournalRepository

sqlite = SQLiteStore(Path('idos.db'))
journal = JournalRepository(Path('idos-journal'))

data = json.loads(Path('site/data.json').read_text(encoding='utf-8'))
opps = {o['opp_id']: o for o in data.get('opportunities', [])}

for t, oid in [('AAPL', 'OPP-20260813-073'), ('ACN', 'OPP-20260813-001')]:
    print(f'\n--- {t} {oid} ---')
    o = opps.get(oid, {})
    print(f'  dashboard status: {o.get("status")}')
    print(f'  dashboard stale: {o.get("is_stale")}')
    print(f'  dashboard last_research: {o.get("last_research")}')

    opp_sql = sqlite.get_opportunity(oid)
    if opp_sql:
        print(f'  SQLite status: {opp_sql.get("status")}')
    else:
        print(f'  SQLite: not found')

    opp_yml = journal.load_opportunity(t, oid)
    if opp_yml:
        print(f'  YAML status: {opp_yml.get("status")}')
        print(f'  YAML last_research_at: {opp_yml.get("last_research_at")}')
