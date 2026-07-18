import sys; sys.path.insert(0, '.')
from unittest.mock import MagicMock
from pathlib import Path
from idos.workers.ai.research_worker import ResearchWorker
from idos.data.sqlite import SQLiteStore
from idos.models.enums import OpportunityStatus
import tempfile

print('Creating ResearchWorker...')
worker = ResearchWorker({'provider': 'test', 'prompts_path': str(Path.cwd())})
print('ResearchWorker created')

tmpdir = Path(tempfile.mkdtemp())
sqlite = SQLiteStore(tmpdir / 'idos.db')
opp_id = 'OPP-2026-TEST-001'
sqlite.save_opportunity({
    'id': opp_id, 'ticker': 'TEST',
    'status': OpportunityStatus.WATCHLIST.value,
    'conviction': {},
})
worker = ResearchWorker({'provider': 'test', 'prompts_path': str(tmpdir)})
worker.llm = MagicMock()
worker.registry = MagicMock()
worker.registry.get.return_value = 'template {ticker} {sector} ...'
worker.registry.get_system.return_value = 'system'
worker.llm.generate_structured.return_value = {
    "clasificacion_oportunidad": {"categoria": "Compounding Machine"},
    "error_mercado": {"conclusion_error_valoracion": "SI", "hipotesis_contraria": "..."},
    "tesis_inversion": "Thesis text",
    "score_general": 82,
    "dominio_riesgos": [],
}

result = worker.execute({
    'ticker': 'TEST',
    'opp_id': opp_id,
    'base_path': str(tmpdir),
})
print('Status:', result.status)
print('Error:', result.error)
