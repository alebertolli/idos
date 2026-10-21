#!/usr/bin/env python3
"""DDD Monthly Re-Assessment - Step 8: Thesis + Conviction + Portfolio."""

import json
import os
from datetime import datetime
from pathlib import Path

from idos.timezone import AR_TZ


def main():
    # Configuration from environment (set by workflow)
    force = os.environ.get('FORCE', 'false').lower() == 'true'
    tickers_env = os.environ.get('TICKER', '')
    tickers = [t.strip().upper() for t in tickers_env.split(',') if t.strip()] if tickers_env else []
    event_type = os.environ.get('EVENT_TYPE', 'monthly')
    skip_portfolio_review = os.environ.get('SKIP_PORTFOLIO_REVIEW', 'false').lower() == 'true'

    workspace = os.environ.get('GITHUB_WORKSPACE', '.')
    os.chdir(workspace)

    results_file = 'cache/monthly_reassessment.json'
    ddd_results = 'cache/ddd_results.json'

    # Load DDD results if available
    ddd_data = None
    if Path(ddd_results).exists():
        ddd_data = json.loads(open(ddd_results, encoding='utf-8').read())
        print('[MONTHLY] Loaded DDD results: {} opportunities'.format(ddd_data.get('total', 0)))

    # Monthly reassessment worker
    from idos.workers.ai.monthly_reassessment_worker import MonthlyReassessmentWorker
    from idos.ai.service import LLMService

    _mp = Path('idos-config/models.yml')
    _llm_svc = LLMService(str(_mp)) if _mp.exists() else LLMService()
    prompts_path = 'idos-config/prompts'

    w = MonthlyReassessmentWorker({'llm_service': _llm_svc, 'prompts_path': prompts_path})

    result = w.execute({
        'base_path': workspace,
        'tickers': tickers,
        'skip_portfolio_review': skip_portfolio_review,
    })
    r = result.output if hasattr(result, 'output') else result

    # Print summary
    print('[MONTHLY] active={} thesis_reassessed={} changed={} conviction={} portfolio_review={} proposals={} exits={}'
          .format(
              r.get('total_active', 0),
              r.get('thesis_reassessed', 0),
              r.get('thesis_changed', 0),
              r.get('conviction_recalibrated', 0),
              r.get('portfolio_review_status', 'unreported'),
              len(r.get('proposals', [])),
              len(r.get('exits_triggered', []))
          ))

    # Save monthly reassessment results
    monthly_data = {
        'active': r.get('total_active', 0),
        'thesis_reassessed': r.get('thesis_reassessed', 0),
        'thesis_changed': r.get('thesis_changed', 0),
        'conviction_recalibrated': r.get('conviction_recalibrated', 0),
        'proposals': len(r.get('proposals', [])),
        'exits_triggered': len(r.get('exits_triggered', [])),
        'portfolio_review_status': r.get('portfolio_review_status', 'unreported'),
        'event_type': event_type,
        'force': force,
        'timestamp': datetime.now(AR_TZ).isoformat()
    }

    Path('cache').mkdir(parents=True, exist_ok=True)
    with open(results_file, 'w', encoding='utf-8') as f:
        f.write(json.dumps(monthly_data, indent=2))

    print('[MONTHLY] Results saved to cache/monthly_reassessment.json')

if __name__ == '__main__':
    main()
