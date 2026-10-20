import sqlite3
c = sqlite3.connect('idos.db')
c.row_factory = sqlite3.Row
rows = c.execute("SELECT COUNT(*) as cnt FROM opportunities").fetchall()
print(f'Total: {dict(rows[0])}')
rows = c.execute("SELECT id, ticker, status, last_thesis_assessment_at FROM opportunities LIMIT 5").fetchall()
for r in rows:
    print(dict(r))
print('---')
rows = c.execute("SELECT id, ticker, status, last_thesis_assessment_at FROM opportunities WHERE last_thesis_assessment_at IS NULL OR last_thesis_assessment_at = '' LIMIT 5").fetchall()
print(f'with NULL/empty: {len(rows)}')
for r in rows:
    print(dict(r))
