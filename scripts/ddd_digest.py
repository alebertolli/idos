#!/usr/bin/env python3
"""DDD Digest Generator - Combined Research + Assessment Digest."""

import json
import os
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path
from datetime import date

from idos.timezone import AR_TZ


def main():
    workspace = os.environ.get('GITHUB_WORKSPACE', '.')
    os.chdir(workspace)

    results_file = 'cache/ddd_results.json'
    digest_file = 'cache/weekly_digest.md'

    if not Path(results_file).exists():
        print('[DIGEST] No results file found')
        sys.exit(0)

    results = json.loads(open(results_file, encoding='utf-8').read())
    processed = results.get('processed', [])
    assessments = results.get('assessments', [])
    errors = results.get('errors', [])
    total = results.get('total', 0)

    # Use assessment results if available, else use processed
    items = assessments if assessments else processed

    now = datetime.now(AR_TZ)

    lines = []
    lines.append('# IDOS DDD Research Digest')
    lines.append('')
    lines.append('_Generado: {} {}_'.format(now.strftime('%Y-%m-%d %H:%M AR'), ''))
    lines.append('')
    lines.append('## Resumen')
    lines.append('')
    lines.append('- 🟢 **Oportunidades procesadas:** {}'.format(len(processed)))
    lines.append('- ✅ **Assessment completados:** {}'.format(len(assessments)))
    approved = sum(1 for a in assessments if isinstance(a, dict) and a.get('board_approved'))
    lines.append('- 🔖 **Approved:** {}'.format(approved))
    lines.append('- 🔴 **Errores:** {}'.format(len(errors)))
    lines.append('- 📊 **Total encontradas:** {}'.format(total))
    lines.append('')

    if processed:
        lines.append('### STEP 2 - Research (DDD + AOIF + Hypothesis)')
        lines.append('')
        for p in processed:
            if not isinstance(p, dict):
                continue
            status = '✅' if p.get('status') == 'completed' else '⚠️'
            ticker = p.get('ticker', '?')
            opp_id = p.get('opp_id', '?')
            lines.append('- {} **{}** ({}): score={}, class={}'.format(
                status, ticker, opp_id, p.get('score', '?'), p.get('classification', '?'))))
        lines.append('')

    if assessments and isinstance(assessments, list):
        lines.append('### STEP 3-7 - Assessment Pipeline')
        lines.append('')
        for a in assessments:
            if not isinstance(a, dict):
                continue
            ticker = a.get('ticker', '?')
            opp_id = a.get('opp_id', '?')
            conv = a.get('conviction_score', '?')
            rec = a.get('recommendation', '?')
            board_ok = a.get('board_approved', False)
            dec_type = a.get('decision_type', '?')
            ass = a.get('assessments', {})
            scores = ' | '.join('{}: {}'.format(k.replace('AssessmentEngine', ''), v)
                                for k, v in ass.items())

            status_emoji = '✅' if board_ok else '⚠️'
            lines.append('- {} **{}**'.format(status_emoji, ticker))
            lines.append('  - Opp: [{}]'.format(opp_id))
            lines.append('  - Conviction: {}/100 | Rec: {}'.format(conv, rec))
            if dec_type:
                lines.append('  - Dec: {}'.format(dec_type))
            if scores:
                lines.append('  - Scores: {}'.format(scores))

            failed = a.get('rules_failed', [])
            details = a.get('rules_details', {})
            if failed:
                lines.append('  - Rules BLOCKED:')
                for rid in failed:
                    d = details.get(rid, '')
                    lines.append('    - 🚫 {}: {}'.format(rid, d))
        lines.append('')

    if errors:
        lines.append('### Errores')
        lines.append('')
        for e in errors:
            lines.append('- ❌ **{}**: {}'.format(e.get('ticker', '?'), e.get('error', '?')))
        lines.append('')

    lines.append('---')
    lines.append('')
    lines.append('[Ver detalle en repositorio](https://github.com/alebertolli/idos/tree/main/idos-journal/companies)')

    digest = '\n'.join(lines)
    Path('cache').mkdir(parents=True, exist_ok=True)
    open(digest_file, 'w', encoding='utf-8').write(digest, encoding='utf-8')

    print('[DIGEST] Generated: {} lines'.format(len(lines)))


if __name__ == '__main__':
    main()