#!/usr/bin/env python3
"""DDD Research Worker - Creates opportunities on the fly for DDD pipeline."""

import json
import os
import sys
import yaml
from datetime import datetime
from pathlib import Path

from idos.data.sqlite import SQLiteStore
from idos.data.journal import JournalRepository
from idos.timezone import AR_TZ


def main():
    # Configuration from environment (set by workflow)
    force = os.environ.get('FORCE', 'false').lower() == 'true'
    tickers_env = os.environ.get('TICKER', '')
    tickers = [t.strip().upper() for t in tickers_env.split(',') if t.strip()] if tickers_env else []
    event_type = os.environ.get('EVENT_TYPE', 'monthly')

    journal = Path('idos-journal')
    os.chdir(os.environ.get('GITHUB_WORKSPACE', '.'))

    opportunities = []
    companies_dir = journal / 'companies'

    if companies_dir.exists():
        for d in sorted(companies_dir.iterdir()):
            if not d.is_dir():
                continue
            ticker = d.name
            if tickers and ticker.upper() not in tickers:
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
                    if data:
                        if force or data.get('status') in ('DISCOVERED', 'WATCHLIST'):
                            opportunities.append({
                                'opp_id': data['id'],
                                'ticker': data['ticker'].upper(),
                                'score': data.get('conviction', {}).get('overall', 0),
                                'current_status': data.get('status', 'UNKNOWN'),
                            })
                except Exception as e:
                    print('[DDD] Error reading {}: {}'.format(yf, e))

    if not opportunities:
        if force and tickers:
            for t in tickers:
                print('[DDD] Force mode for {} but no opportunity found, creating one on the fly'.format(t))
                from idos.data.sqlite import SQLiteStore
                from idos.data.journal import JournalRepository
                from datetime import datetime
                from idos.timezone import AR_TZ

                existing_opps = SQLiteStore('idos.db').list_opportunities()
                seq = len(existing_opps) + 1
                new_opp_id = 'OPP-{}-{:03d}'.format(datetime.now(AR_TZ).strftime("%Y%m%d"), seq)
                now = datetime.now(AR_TZ).isoformat()
                new_opp_text = json.dumps({
                    'id': new_opp_id,
                    'ticker': t,
                    'status': 'DISCOVERED',
                    'conviction': {'overall': 0},
                    'created_at': now,
                    'updated_at': now,
                })
                jr = JournalRepository(journal)
                jr.save_opportunity(t, new_opp_text)
                SQLiteStore('idos.db').save_opportunity(new_opp_text)
                opportunities.append({
                    'opp_id': new_opp_id,
                    'ticker': t,
                    'score': 0,
                    'current_status': 'DISCOVERED',
                })
                print('[DDD] Created new opportunity {} for {}'.format(new_opp_id, t))
        else:
            print('[DDD] No DISCOVERED opportunities to process')
            Path('cache/ddd_results.json').write_text(json.dumps({
                'processed': [], 'assessments': [], 'errors': [],
                'status': 'none', 'event_type': event_type, 'force': force
            }), encoding='utf-8')
            sys.exit(0)

    labels = 'FORCE' if force else 'DISCOVERED'
    print('[DDD] Found {} {}'.format(len(opportunities), labels))

    from idos.workers.ai.research_worker import ResearchWorker
    from idos.data.sqlite import SQLiteStore
    from idos.models.enums import OpportunityStatus

    processed = []
    errors = []

    for opp in opportunities:
        ticker = opp['ticker']
        opp_id = opp['opp_id']
        cur_status = opp['current_status']
        print('\n[STEP 2] {} {} {} status={}...'.format("FORCE" if force else "NORMAL", ticker, opp_id, cur_status))

        try:
            db = SQLiteStore('idos.db')
            # ... rest of processing
            # This is where the research worker would process each opportunity
            print('[STEP 2] Processing {}...'.format(ticker))

        except Exception as e:
            print('[DDD] Error processing {}: {}'.format(ticker, e))
            errors.append(ticker)

    # Summary
    print('\n[STEP 2] Processed {} opportunities, errors in {}'.format(len(processed), len(errors)))


if __name__ == '__main__':
    main()