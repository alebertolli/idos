import sys
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.data.journal import JournalRepository
from datetime import datetime, timezone
import yaml

journal = JournalRepository(Path('idos-journal'))
now = datetime.now(timezone.utc)

stale_count = 0
for opp in journal.list_all_opportunities():
    lra = opp.get('last_research_at')
    if not lra:
        continue
    try:
        dt = datetime.fromisoformat(lra.replace('Z','+00:00'))
        days = (now - dt).days
        if days > 30:
            stale_count += 1
    except Exception:
        pass
print(f'[BUG 1] Stale >30d: {stale_count} (expected 0)')

discovered = journal.list_discovered_opportunities()
discovered_tickers = [d['ticker'] for d in discovered]
aapl_in = 'AAPL' in discovered_tickers
acn_in = 'ACN' in discovered_tickers
print(f'[BUG 4] AAPL in research: {aapl_in} ACN in research: {acn_in}')
print(f'  Research queue: {sorted(discovered_tickers)}')

buylist_path = Path('idos-journal/portfolio/buylist.yml')
if buylist_path.exists():
    bl = yaml.safe_load(buylist_path.read_text(encoding='utf-8')) or {}
    lrcx = next((e for e in bl.get('entries', []) if e.get('ticker') == 'LRCX'), None)
    print(f'[BUG 5] LRCX in buylist: {lrcx is not None}')
    if lrcx:
        print(f'  status={lrcx.get("status")} approved={lrcx.get("approved")}')
else:
    print('[BUG 5] buylist.yml not found')
