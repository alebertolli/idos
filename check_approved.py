import sys
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.data.sqlite import SQLiteStore
sqlite = SQLiteStore(Path('idos.db'))
opps = sqlite.list_opportunities()
approved = [o for o in opps if o.get('status') == 'APPROVED']
print(f'APPROVED count: {len(approved)}')
for o in approved[:5]:
    print(f'  {o["ticker"]} last_thesis={o.get("last_thesis_assessment_at")!r}')
