import sys
from pathlib import Path
sys.path.insert(0, 'idos-core')
from idos.decision.assessment_pipeline import build_context
from idos.decision.engines.business import BusinessAssessmentEngine
from idos.data.sqlite import SQLiteStore
from idos.data.journal import JournalRepository
from idos.data.knowledge import KnowledgeRepository

bp = Path('.')
sqlite = SQLiteStore(bp / 'idos.db')
knowledge = KnowledgeRepository(bp / 'idos-knowledge')
journal = JournalRepository(bp / 'idos-journal')

for ticker, opp_id in [('AVGO', 'OPP-20260807-009'), ('GFI', 'OPP-20260725-002'), ('HWM', 'OPP-20260807-003')]:
    print(f'\n===== {ticker} {opp_id} =====')
    ctx = build_context(opp_id, ticker, bp, sqlite, knowledge, journal)
    eng = BusinessAssessmentEngine()
    res = eng.evaluate(ctx)
    print(f'  business score: {res.score} (need >=70 for RULE-001)')
    print(f'  findings: {len(res.findings)}')
    for f in res.findings[:5]:
        print(f'    + {f.get("detail")}')
    print(f'  static keys: {list(ctx.get("knowledge_base", {}).get("static", {}).keys())}')
    print(f'  metrics: {ctx.get("knowledge_base", {}).get("dynamic", {}).get("metrics", {}).get("roic")}')
    print(f'  knowledge_base present: {bool(ctx.get("knowledge_base"))}')
