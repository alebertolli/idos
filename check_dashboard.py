import json
from pathlib import Path
data = json.loads(Path('site/data.json').read_text(encoding='utf-8'))
opps = data.get('opportunities', [])
print(f'Total opportunities: {len(opps)}')
research_statuses = ['DISCOVERED', 'WATCHLIST', 'SCREENED']
res = []
for o in opps:
    s = o.get('status')
    if s in research_statuses:
        res.append(f'{o["ticker"]} {o["opp_id"]} status={s}')
for r in res:
    print(r)
print(f'\nResearch section count: {len(res)}')
