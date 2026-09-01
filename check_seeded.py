import sys
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.data.sqlite import SQLiteStore
sqlite = SQLiteStore(Path('idos.db'))
opps = sqlite.list_opportunities()
for o in opps:
    if o.get('status') == 'APPROVED' and not o.get('last_thesis_assessment_at'):
        print(f'{o["ticker"]} {o["id"]}: last_thesis={o.get("last_thesis_assessment_at")!r}, updated={o.get("updated_at")}')
        break
print('done')
