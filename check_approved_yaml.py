import sys, sqlite3, json
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.data.sqlite import SQLiteStore
from idos.data.journal import JournalRepository

bp = Path('.')
journal = JournalRepository(bp / 'idos-journal')

# Check APPROVED YAML files
approved_yaml_dir = Path('idos-journal/companies')
approved = []
for d in approved_yaml_dir.iterdir():
    if not d.is_dir():
        continue
    opp_dir = d / 'case_file' / 'opportunities'
    if not opp_dir.exists():
        continue
    for opp in opp_dir.iterdir():
        if not opp.is_dir():
            continue
        yml_file = opp / 'opportunity.yml'
        if not yml_file.exists():
            continue
        import yaml
        data = yaml.safe_load(yml_file.read_text(encoding='utf-8'))
        if data and data.get('status') == 'APPROVED':
            approved.append({'ticker': d.name, 'opp_id': data.get('id'), 'last_thesis': data.get('last_thesis_assessment_at')})

print(f'APPROVED in YAML: {len(approved)}')
for a in approved[:5]:
    print(f'  {a}')
