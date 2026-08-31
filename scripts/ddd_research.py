#!/usr/bin/env python3
"""DDD Research Worker — decides which opportunities need (re)research.

Selection rules:
  NORMAL mode (monthly cron):
    - SCREENED: process -> UNDER_RESEARCH
    - UNDER_RESEARCH with stale > 30d: process with force_reprocess=True
    - All others: skip
  FORCE mode (30-day re-research, manual, earnings):
    - UNDER_RESEARCH: re-research (no status change)
    - All others: skip
  Tickers in BUY_LIST or PORTFOLIO: skip in both modes.
"""

import json
import os
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path


STALE_DAYS = 30
SKIP_TICKERS = set()


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


def _is_stale(opp: dict) -> tuple[bool, int | None]:
    """Return (is_stale, days_since_last_research)."""
    last_at = _parse_dt(opp.get("last_research_at") or opp.get("updated_at"))
    if not last_at:
        return True, None
    now = datetime.now(timezone.utc)
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)
    days = (now - last_at).days
    return days > STALE_DAYS, days


def _needs_research(opp: dict, force: bool) -> tuple[bool, bool, str]:
    """Return (should_process, force_reprocess, reason)."""
    status = opp.get("status", "")
    ticker = opp.get("ticker", "").upper()
    score = (opp.get("conviction") or {}).get("overall", 0)

    if ticker in SKIP_TICKERS:
        return False, False, "in BUY_LIST/PORTFOLIO"

    if force:
        if status == "UNDER_RESEARCH":
            return True, True, f"FORCE re-research UNDER_RESEARCH (score={score})"
        return False, False, f"FORCE: status {status} not re-researchable"

    if status == "SCREENED":
        return True, False, f"new entry: SCREENED (score={score})"

    if status == "UNDER_RESEARCH":
        stale, days = _is_stale(opp)
        if stale:
            reason = f"stale UNDER_RESEARCH ({days}d > {STALE_DAYS}d)" if days is not None else f"stale UNDER_RESEARCH (no last_research_at)"
            return True, True, reason
        days_str = f"{days}d" if days is not None else "no last_research_at"
        return False, False, f"UNDER_RESEARCH fresh ({days_str} <= {STALE_DAYS}d)"

    return False, False, f"status {status} not processable in NORMAL mode"


def main():
    force = os.environ.get('FORCE', 'false').lower() == 'true'
    tickers_env = os.environ.get('TICKER', '')
    tickers = [t.strip().upper() for t in tickers_env.split(',') if t.strip()] if tickers_env else []
    event_type = os.environ.get('EVENT_TYPE', 'monthly')

    journal = Path('idos-journal')
    os.chdir(os.environ.get('GITHUB_WORKSPACE', '.'))
    global SKIP_TICKERS
    SKIP_TICKERS = _load_skip_tickers()

    opportunities = []
    skipped_list = []
    companies_dir = journal / 'companies'

    if companies_dir.exists():
        for d in sorted(companies_dir.iterdir()):
            if not d.is_dir():
                continue
            ticker = d.name.upper()
            if tickers and ticker not in tickers:
                continue
            if ticker in SKIP_TICKERS:
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
                    status = data.get('status', '')
                    score = data.get('conviction', {}).get('overall', 0)

                    should, opp_force, reason = _needs_research(data, force)
                    if should:
                        opportunities.append({
                            'opp_id': data['id'],
                            'ticker': ticker,
                            'score': score,
                            'current_status': status,
                            'reason': reason,
                            'force_reprocess': opp_force,
                        })
                    else:
                        skipped_list.append({
                            'opp_id': data['id'],
                            'ticker': ticker,
                            'status': status,
                            'reason': reason,
                        })
                except Exception as e:
                    print('[DDD] Error reading {}: {}'.format(yf, e))

    if not opportunities and not force:
        print('[DDD] No opportunities to process (no SCREENED found)')
        Path('cache/ddd_results.json').write_text(json.dumps({
            'processed': [], 'errors': [],
            'status': 'none', 'event_type': event_type, 'force': force,
            'skipped': skipped_list,
        }, indent=2), encoding='utf-8')
        sys.exit(0)

    print('[DDD] To process: {}'.format(len(opportunities)))
    for o in opportunities:
        print('  - {} {} ({}) reason={}'.format(
            o['ticker'], o['opp_id'], o['current_status'], o.get('reason', '')))
    if skipped_list:
        print('[DDD] Skipped: {}'.format(len(skipped_list)))
        for s in skipped_list[:5]:
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
        opp_force = opp.get('force_reprocess', False)
        print('\n[STEP 2] ResearchWorker -> {} {} (force={}) ...'.format(ticker, opp_id, opp_force))
        try:
            ctx = {
                'ticker': ticker,
                'opp_id': opp_id,
                'base_path': str(base_path),
                'force_reprocess': opp_force,
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
        'skipped': skipped_list,
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