import sys, json
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.data.journal import JournalRepository
import yaml

journal = JournalRepository(Path('idos-journal'))

# Get portfolio statuses
portfolio_statuses = {'ACCUMULATING', 'FULL_POSITION', 'MONITORING', 'REDUCING'}

data = json.loads(Path('site/data.json').read_text(encoding='utf-8'))
opps = data.get('opportunities', [])

# Check APPROVED - should NOT have stale alerts
approved = [o for o in opps if o.get('status') == 'APPROVED']
print(f'APPROVED count: {len(approved)}')
print(f'APPROVED stale: {sum(1 for o in approved if o.get("is_stale"))}')
print(f'APPROVED thesis_stale: {sum(1 for o in approved if o.get("is_thesis_stale"))}')

# Check portfolio positions
portfolio = [o for o in opps if o.get('status') in portfolio_statuses]
print(f'Portfolio count: {len(portfolio)}')

# Check stale only in UNDER_RESEARCH/SCREENED
research_stale = [o for o in opps if o.get('is_stale')]
print(f'Research stale: {len(research_stale)}')

# Check thesis stale
thesis_stale = [o for o in opps if o.get('is_thesis_stale')]
print(f'Thesis stale: {len(thesis_stale)}')

# Show stale RESEARCH opps
print()
print('Research stale opps:')
for o in research_stale:
    print(f'  {o["ticker"]} {o["status"]} {o.get("stale_days")}d')

# Check if APPROVED have thesis_not_assessed_days
print()
for o in approved[:3]:
    print(f'  {o["ticker"]} APPROVED: thesis_not_assessed_days={o.get("thesis_not_assessed_days")} is_thesis_stale={o.get("is_thesis_stale")}')

# Check which portfolio statuses exist
status_counts = {}
for o in opps:
    s = o.get('status', 'UNKNOWN')
    status_counts[s] = status_counts.get(s, 0) + 1
print()
print(f'Status distribution: {status_counts}')
