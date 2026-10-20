import sys, yaml, json
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.data.journal import JournalRepository

journal = JournalRepository(Path('idos-journal'))
data = json.loads(Path('site/data.json').read_text(encoding='utf-8'))
opps = data.get('opportunities', [])
approved = [o for o in opps if o.get('status') == 'APPROVED']
print(f'Site APPROVED count: {len(approved)}')

for o in approved[:5]:
    yml = journal.load_opportunity(o['ticker'], o['opp_id'])
    if yml:
        print(f"  {o['ticker']} last_thesis={yml.get('last_thesis_assessment_at')!r} thesis_active={yml.get('thesis_active')}")
