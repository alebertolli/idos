import sys
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.data.sqlite import SQLiteStore
from idos.data.journal import JournalRepository

sqlite = SQLiteStore(Path('idos.db'))
journal = JournalRepository(Path('idos-journal'))

for t in ['AAPL', 'ACN']:
    print(f'--- {t} ---')
    for opp in sqlite.list_opportunities():
        if opp.get('ticker') == t:
            print(f'  SQLite: opp_id={opp["id"]} status={opp.get("status")}')
    for d in journal.list_all_opportunities():
        if d.get('ticker') == t:
            print(f'  YAML:   opp_id={d["id"]} status={d.get("status")}')
