import sys, yaml, json
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.data.journal import JournalRepository

journal = JournalRepository(Path('idos-journal'))

for ticker, opp_id in [('AMD', 'OPP-20260804-001')]:
    print(f'--- {ticker} {opp_id} ---')
    opp = journal.load_opportunity(ticker, opp_id)
    if opp:
        print(f'  status: {opp.get("status")}')
    dp_path = Path('idos-journal') / 'companies' / ticker / 'case_file' / 'opportunities' / opp_id / 'decision_proposal.yml'
    dp = yaml.safe_load(dp_path.read_text(encoding='utf-8')) if dp_path.exists() else {}
    print(f'  rules_failed: {dp.get("rules_failed")}')
    print(f'  rules_passed: {dp.get("rules_passed")}')
    assessments = dp.get('assessments', {})
    print(f'  RiskAssessmentEngine: {assessments.get("RiskAssessmentEngine", {})}')
    print(f'  BusinessAssessmentEngine: {assessments.get("BusinessAssessmentEngine", {}).get("score")}')
    print(f'  conviction_score: {dp.get("conviction_score")}')

    # Check the actual site data
    data = json.loads(Path('site/data.json').read_text(encoding='utf-8'))
    site_opp = next((o for o in data.get('opportunities', []) if o.get('opp_id') == opp_id), None)
    if site_opp:
        print(f'  site status: {site_opp.get("status")}')
        print(f'  site rules_failed: {site_opp.get("proposal", {}).get("rules_failed")}')
