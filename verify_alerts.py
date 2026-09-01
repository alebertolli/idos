import json
d = json.loads(open('site/data.json', encoding='utf-8').read())
opps = d.get('opportunities', [])
print(f'Total opps: {len(opps)}')
from collections import Counter
statuses = Counter(o.get('status') for o in opps)
print(f'Statuses: {dict(statuses)}')
is_stale = [o for o in opps if o.get('is_stale')]
is_thesis_stale = [o for o in opps if o.get('is_thesis_stale')]
print(f'is_stale: {len(is_stale)}')
for o in is_stale:
    print(f'  {o["ticker"]} {o["status"]} stale_days={o.get("stale_days")}')
print(f'is_thesis_stale: {len(is_thesis_stale)}')
for o in is_thesis_stale:
    print(f'  {o["ticker"]} {o["status"]} thesis_days={o.get("thesis_not_assessed_days")}')
print()
print('Alerts:')
for a in d.get('alerts', []):
    print(f'  [{a["severity"]}] {a["ticker"]}: {a["message"]}')
