import sys
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.data.sqlite import SQLiteStore

sqlite = SQLiteStore(Path('idos.db'))

c = sqlite.conn
for oid in ['OPP-20260813-073', 'OPP-20260813-001']:
    rows = c.execute("SELECT * FROM state_transitions WHERE opportunity_id = ? ORDER BY id", (oid,)).fetchall()
    print(f'\nTransitions for {oid}:')
    if rows:
        for r in rows:
            print(f'  {dict(r)}')
    else:
        print('  (no transitions)')
