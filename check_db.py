import sys
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.data.sqlite import SQLiteStore
sqlite = SQLiteStore(Path('idos.db'))
c = sqlite.conn
rows = c.execute("SELECT id, ticker, status FROM opportunities WHERE status = 'APPROVED' LIMIT 5").fetchall()
print(f'rows: {len(rows)}')
for r in rows:
    print(dict(r))
print()
rows = c.execute("SELECT id, ticker, status, last_thesis_assessment_at FROM opportunities WHERE last_thesis_assessment_at != '' LIMIT 5").fetchall()
print(f'with thesis_assessment: {len(rows)}')
for r in rows:
    print(dict(r))
