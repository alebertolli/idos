#!/usr/bin/env python3
"""DDD Monthly Re-Assessment - Step 8: Thesis + Conviction + Portfolio."""

import json
import os
import sys
import yaml
from datetime import datetime
from pathlib import Path

from idos.data.sqlite import SQLiteStore
from idos.data.journal import JournalRepository
from idos.config import load_config
from idos.timezone import AR_TZ


def main():
    # Configuration from environment (set by workflow)
    force = os.environ.get('FORCE', 'false').lower() == 'true'
    tickers_env = os.environ.get('TICKER', '')
    tickers = [t.strip().upper() for t in tickers_env.split(',') if t.strip()] if tickers_env else []
    event_type = os.environ.get('EVENT_TYPE', 'monthly')

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
    from idos.config import load_config as load_config_path

    _mp = Path('idos-config/models.yml')
    _llm_svc = LLMService(str(_mp)) if _mp.exists() else LLMService()
    prompts_path = 'idos-config/prompts'

    w = MonthlyReassessmentWorker({'llm_service': _llm_svc, 'prompts_path': prompts_path})

    result = w.execute({'base_path': workspace})
    r = result.output if hasattr(result, 'output') else result

    # Print summary
    print('[MONTHLY] active={} thesis_reassessed={} changed={} conviction={} proposals={} exits={}'
          .format(
              r.get('total_active', 0),
              r.get('thesis_reassessed', 0),
              r.get('thesis_changed', 0),
              r.get('conviction_recalibrated', 0),
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
        'event_type': event_type,
        'force': force,
        'timestamp': datetime.now(AR_TZ).isoformat()
    }

    Path('cache').mkdir(parents=True, exist_ok=True)
    with open(results_file, 'w', encoding='utf-8') as f:
        f.write(json.dumps(monthly_data, indent=2))

    print('[MONTHLY] Results saved to cache/monthly_reassessment.json')

# Generate weekly digest if end of month
from datetime import date
import calendar
today = date.today()
last_day = calendar.monthrange(today.year, today.month)[1]
days_left = last_day - today.day

if days_left <= 2:
    print('[MONTHLY] Fin de mes detectado - generando digest semanal')
    # Generate digest
    from idos.decision.assessment_pipeline import build_digest
    try:
        # Read total and errors from ddd results
        ddd_data = json.loads(open('cache/ddd_results.json', encoding='utf-8').read()) if Path('cache/ddd_results.json').exists() else {'total': 0, 'errors': []}
        build_digest(workspace, ddd_data.get('total', 0), ddd_data.get('errors', []))
        print('[MONTHLY] Weekly digest generated')
    except Exception as e:
        print('[MONTHLY] Digest generation error: {}'.format(e))
    else:
        print('[MONTHLY] No es fin de mes ({}/{}), saliendo'.format(today.day, last_day))


if __name__ == '__main__':
    main()