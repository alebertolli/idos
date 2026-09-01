import json
from pathlib import Path
data = json.loads(Path('site/data.json').read_text(encoding='utf-8'))
opps = data.get('opportunities', [])
under_research = [o for o in opps if o.get('status') == 'UNDER_RESEARCH']
approved = [o for o in opps if o.get('status') == 'APPROVED']
print(f'UNDER_RESEARCH: {len(under_research)}')
for o in under_research:
    print(f'  {o["ticker"]} {o["opp_id"]}')
print(f'\nAPPROVED: {len(approved)}')
for o in approved:
    print(f'  {o["ticker"]} {o["opp_id"]}')
aapl_st = [o['status'] for o in opps if o['ticker'] == 'AAPL']
acn_st = [o['status'] for o in opps if o['ticker'] == 'ACN']
print(f'\nAAPL status: {aapl_st}')
print(f'ACN status: {acn_st}')
