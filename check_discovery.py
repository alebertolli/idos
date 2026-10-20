import json
from pathlib import Path
data = json.loads(Path('site/data.json').read_text(encoding='utf-8'))
pool = data.get('discovery_pool', [])
print(f'Discovery pool size: {len(pool)}')
with_date = [e for e in pool if e.get('added_at')]
print(f'Entries with added_at: {len(with_date)}')
for e in with_date[:3]:
    print(f'  ticker={e["ticker"]} added_at={e["added_at"]} score={e["score"]}')
