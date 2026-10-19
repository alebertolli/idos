import json
from pathlib import Path

data = json.loads(Path('site/data.json').read_text(encoding='utf-8'))
opps = data.get('opportunities', [])

print('OPP status + rules_failed from DASHBOARD:\n')
print(f'{"Ticker":<8} {"Status":<18} {"rules_failed":<50}')
print('-' * 80)
for o in sorted(opps, key=lambda x: (x['status'], x['ticker'])):
    s = o.get('status')
    if s in ('UNDER_RESEARCH', 'APPROVED', 'WATCHLIST'):
        rf = o.get('proposal', {}).get('rules_failed', [])
        rf_str = str(rf) if rf else '[]'
        print(f'{o["ticker"]:<8} {s:<18} {rf_str}')
