#!/usr/bin/env python3
"""DDD Assessment Pipeline - Steps 3-7: Assessment Engines + Conviction + Rules + Board + Entry."""

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

    workspace = os.environ.get('GITHUB_WORKSPACE', '.')
    os.chdir(workspace)

    results_file = 'cache/ddd_results.json'
    if not Path(results_file).exists():
        print('[ASSESSMENT] No results file found')
        sys.exit(0)

    results = json.loads(open(results_file, encoding='utf-8').read())
    processed = results.get('processed', [])
    assessments = results.get('assessments', [])
    errors = results.get('errors', [])
    total = results.get('total', 0)

    # Use assessment results if available, else use processed
    items = assessments if assessments else processed

    if not items:
        print('[ASSESSMENT] No opportunities to assess')
        # Write empty results
        results['assessments'] = []
        Path('cache').mkdir(parents=True, exist_ok=True)
        with open(results_file, 'w', encoding='utf-8') as f:
            f.write(json.dumps(results, indent=2))
        sys.exit(0)

    # Import assessment pipeline
    from idos.decision.assessment_pipeline import run_full_pipeline

    # Filter items by tickers if specified
    if tickers:
        items = [item for item in items if item.get('ticker', '').upper() in tickers]

    print('[ASSESSMENT] Processing {} opportunities{}'.format(
        len(items), ', filtered by ticker' if tickers else ''))

    processed_items = []
    errors_list = []

    for opp in items:
        ticker = opp.get('ticker', '').upper()
        opp_id = opp.get('opp_id', '')

        if not ticker or not opp_id:
            print('[ASSESSMENT] Skipping opportunity without ticker or opp_id')
            continue

        # Check if already assessed
        if any(a.get('opp_id') == opp_id for a in assessments):
            print('[ASSESSMENT] Skipping already assessed: {} {}'.format(ticker, opp_id))
            continue

        mode = 'FORCE' if opp.get('force', force) else 'NORMAL'
        print('\n[STEP 3-7] Running assessment pipeline for {} ({}) [{}]...'.format(ticker, opp_id, mode))

        try:
            result = run_full_pipeline(opp_id, ticker, workspace, force_reprocess=opp.get('force', False))
            assessments.append(result)
            processed_items.append({
                'ticker': ticker,
                'opp_id': opp_id,
                'status': result.get('status', 'completed'),
                'conviction_score': result.get('conviction_score', '?'),
                'recommendation': result.get('recommendation', '?'),
            })
            print('[STEP 3-7] {}: conviction={}, recommendation={}'.format(ticker,
                result.get('conviction_score', '?'), result.get('recommendation', '?')))
        except Exception as e:
            import traceback
            traceback.print_exc()
            error_msg = str(e)
            errors_list.append({
                'ticker': ticker,
                'error': error_msg,
                'opp_id': opp_id
            })
            print('[STEP 3-7] {}: ERROR - {}'.format(ticker, error_msg))

    # Update results
    results['assessments'] = assessments
    results['errors'] = errors_list if errors_list else errors
    results['total'] = total

    # Save results
    Path('cache').mkdir(parents=True, exist_ok=True)
    with open(results_file, 'w', encoding='utf-8') as f:
        f.write(json.dumps(results, indent=2))

    print('\n[ASSESSMENT] Done: {} assessed, {} errors'.format(
        len(assessments), len(errors_list)))

    # Generate digest after assessment
    from idos.decision.assessment_pipeline import build_digest
    print('[ASSESSMENT] Generating digest...')
    try:
        build_digest(workspace)
        print('[ASSESSMENT] Digest generated successfully')
    except Exception as e:
        print('[ASSESSMENT] Digest generation error: {}'.format(e))


if __name__ == '__main__':
    main()