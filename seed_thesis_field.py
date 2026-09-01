import sys, sqlite3
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.data.sqlite import SQLiteStore
from idos.data.journal import JournalRepository
from datetime import datetime
from idos.timezone import AR_TZ

bp = Path('.')
sqlite = SQLiteStore(bp / 'idos.db')
journal = JournalRepository(bp / 'idos-journal')

# Seed last_thesis_assessment_at = updated_at for all APPROVED positions in BOTH SQLite and YAML
c = sqlite.conn
rows = c.execute("SELECT id, ticker, status, updated_at, last_thesis_assessment_at FROM opportunities").fetchall()
seeded = 0
for r in rows:
    r = dict(r)
    if r['status'] not in ('APPROVED', 'ENTRY_PENDING', 'ACCUMULATING', 'FULL_POSITION', 'MONITORING', 'REDUCING'):
        continue
    if r.get('last_thesis_assessment_at'):
        continue
    ts = r.get('updated_at') or datetime.now(AR_TZ).isoformat()
    c.execute("UPDATE opportunities SET last_thesis_assessment_at = ? WHERE id = ?", (ts, r['id']))

    yml = journal.load_opportunity(r['ticker'], r['id'])
    if yml and not yml.get('last_thesis_assessment_at'):
        yml['last_thesis_assessment_at'] = ts
        journal.save_opportunity(r['ticker'], yml)
    seeded += 1

sqlite.conn.commit()
print(f'Seeded {seeded} opportunities with last_thesis_assessment_at')
