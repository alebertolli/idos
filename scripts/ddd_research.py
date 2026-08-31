#!/usr/bin/env python3
"""DDD Research Worker — decides which opportunities need (re)research.

Selection rules (NORMAL mode):
  - DISCOVERED or WATCHLIST: process (new entry to Research)
  - UNDER_RESEARCH: process only if:
      * no last_research_at  (no thesis ever generated), OR
      * last_research_at > STALE_DAYS ago  (thesis stale, needs refresh)
  - Other statuses (APPROVED, ENTRY_PENDING, ACCUMULATING, etc.): skip.
  - Tickers in BUY_LIST or PORTFOLIO: skip (already past Research).
FORCE mode: process any status (skip transitions, no status change).
"""

import json
import os
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path

from idos.data.sqlite import SQLiteStore
from idos.data.journal import JournalRepository
from idos.timezone import AR_TZ


STALE_DAYS = 30
THRESHOLD = 60
SKIP_TICKERS = set()  # populated from buylist + positions below


def _parse_dt(s):
    if not s:
        return None
    try:
        if isinstance(s, datetime):
            return s
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _load_skip_tickers():
    skip = set()
    bl = Path("idos-journal/portfolio/buylist.yml")
    if bl.exists():
        try:
            d = yaml.safe_load(bl.read_text(encoding="utf-8")) or {}
            for e in d.get("entries", []):
                if e.get("ticker"):
                    skip.add(e["ticker"].upper())
        except Exception:
            pass
    pos_dir = Path("idos-journal/paper/positions")
    if pos_dir.exists():
        for f in pos_dir.glob("*.yml"):
            try:
                d = yaml.safe_load(f.read_text(encoding="utf-8"))
                if isinstance(d, dict) and d.get("ticker"):
                    skip.add(d["ticker"].upper())
            except Exception:
                pass
    return skip


def _needs_research(opp: dict, now: datetime) -> tuple[bool, str]:
    """Return (should_process, reason)."""
    status = opp.get("status", "")
    score = (opp.get("conviction") or {}).get("overall", 0)
    ticker = opp.get("ticker", "").upper()
    last_at = _parse_dt(opp.get("last_research_at") or opp.get("updated_at"))
    days = (now - last_at.replace(tzinfo=None)).days if last_at else None

    if status in ("DISCOVERED", "WATCHLIST"):
        return True, f"new entry: {status} (score={score})"
    if status == "UNDER_RESEARCH":
        if ticker in SKIP_TICKERS:
            return False, f"in BUY_LIST/PORTFOLIO"
        if days is None:
            return True, "UNDER_RESEARCH sin last_research_at"
        if days > STALE_DAYS:
            return True, f"UNDER_RESEARCH stale ({days}d > {STALE_DAYS}d)"
        return False, f"UNDER_RESEARCH fresh ({days}d <= {STALE_DAYS}d) — skip DDD"
    return False, f"status {status} not processable"


def main():
    force = os.environ.get('FORCE', 'false').lower() == 'true'
    tickers_env = os.environ.get('TICKER', '')
    tickers = [t.strip().upper() for t in tickers_env.split(',') if t.strip()] if tickers_env else []
    event_type = os.environ.get('EVENT_TYPE', 'monthly')

    journal = Path('idos-journal')
    os.chdir(os.environ.get('GITHUB_WORKSPACE', '.'))
    global SKIP_TICKERS
    SKIP_TICKERS = _load_skip_tickers()

    now = datetime.now(AR_TZ).replace(tzinfo=None)
    opportunities = []
    skipped_stale_skip = []
    companies_dir = journal / 'companies'

    if companies_dir.exists():
        for d in sorted(companies_dir.iterdir()):
            if not d.is_dir():
                continue
            ticker = d.name.upper()
            if tickers and ticker not in tickers:
                continue
            opp_dir = d / 'case_file' / 'opportunities'
            if not opp_dir.exists():
                continue
            for opp in sorted(opp_dir.iterdir()):
                if not opp.is_dir():
                    continue
                yf = opp / 'opportunity.yml'
                if not yf.exists():
                    continue
                try:
                    data = yaml.safe_load(yf.read_text(encoding='utf-8'))
                    if not data:
                        continue
                    if force:
                        opportunities.append({
                            'opp_id': data['id'],
                            'ticker': ticker,
                            'score': data.get('conviction', {}).get('overall', 0),
                            'current_status': data.get('status', 'UNKNOWN'),
                            'reason': 'FORCE mode',
                        })
                        continue
                    should, reason = _needs_research(data, now)
                    if should:
                        opportunities.append({
                            'opp_id': data['id'],
                            'ticker': ticker,
                            'score': data.get('conviction', {}).get('overall', 0),
                            'current_status': data.get('status', 'UNKNOWN'),
                            'reason': reason,
                        })
                    else:
                        skipped_stale_skip.append({
                            'opp_id': data['id'],
                            'ticker': ticker,
                            'status': data.get('status'),
                            'reason': reason,
                        })
                except Exception as e:
                    print('[DDD] Error reading {}: {}'.format(yf, e))

    if not opportunities and not force:
        print('[DDD] No opportunities to process (all fresh or excluded)')
        Path('cache/ddd_results.json').write_text(json.dumps({
            'processed': [], 'assessments': [], 'errors': [],
            'status': 'none', 'event_type': event_type, 'force': force,
            'skipped': skipped_stale_skip,
        }, indent=2), encoding='utf-8')
        sys.exit(0)

    print('[DDD] To process: {}'.format(len(opportunities)))
    for o in opportunities:
        print('  - {} {} ({}) reason={}'.format(
            o['ticker'], o['opp_id'], o['current_status'], o.get('reason', '')))
    print('[DDD] Skipped (stale-skip or excluded): {}'.format(len(skipped_stale_skip)))
    for s in skipped_stale_skip[:10]:
        print('  skip: {} {} ({}) — {}'.format(s['ticker'], s['opp_id'], s['status'], s['reason']))

    # Execute ResearchWorker for each selected opportunity
    from idos.workers.ai.research_worker import ResearchWorker
    from idos.data.sqlite import SQLiteStore
    from idos.data.journal import JournalRepository

    base_path = Path('idos-journal').parent
    sqlite = SQLiteStore(base_path / 'idos.db')
    journal = JournalRepository(base_path / 'idos-journal')

    rw = ResearchWorker()
    rw_results = []
    rw_errors = []
    for opp in opportunities:
        ticker = opp['ticker']
        opp_id = opp['opp_id']
        print('\n[STEP 2] ResearchWorker -> {} {} ...'.format(ticker, opp_id))
        try:
            ctx = {
                'ticker': ticker,
                'opp_id': opp_id,
                'base_path': str(base_path),
                'force_reprocess': force,
                'event_type': event_type,
            }
            r = rw.run(ctx)
            status = r.get('status', 'unknown')
            print('  -> status={} score={}'.format(
                status, r.get('conviction_score', r.get('score', '?'))))
            rw_results.append({
                'opp_id': opp_id, 'ticker': ticker, 'status': status,
                'score': r.get('conviction_score', r.get('score')),
                'reason': opp.get('reason', ''),
            })
            if status == 'skipped':
                rw_errors.append({'ticker': ticker, 'opp_id': opp_id, 'reason': r.get('reason', 'skipped')})
        except Exception as e:
            import traceback
            traceback.print_exc()
            print('  -> ERROR: {}'.format(e))
            rw_errors.append({'ticker': ticker, 'opp_id': opp_id, 'error': str(e)})

    results = {
        'processed': rw_results,
        'skipped': skipped_stale_skip,
        'assessments': [],
        'errors': rw_errors,
        'status': 'research_completed',
        'event_type': event_type,
        'force': force,
        'stale_days_threshold': STALE_DAYS,
    }
    Path('cache').mkdir(parents=True, exist_ok=True)
    Path('cache/ddd_results.json').write_text(
        json.dumps(results, indent=2), encoding='utf-8'
    )
    print('\n[DDD] Research completed for {}, errors in {}'.format(
        len(rw_results), len(rw_errors)))


if __name__ == '__main__':
    main()