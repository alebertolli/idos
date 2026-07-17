# Validación Manual E2E — IDOS

Guía paso a paso para validar el sistema completo con una compañía nueva.
Usaremos **GOOGL (Alphabet)** como ejemplo. Todos los comandos en español.

---

## Requisitos

```bash
cd C:\REPOS\idos
pip install -e idos-core
```

---

## Paso 1: Verificar Tests

```bash
cd idos-core
python -m pytest -v --tb=short
```

✅ **Esperado**: 271 passed, 0 failed

---

## Paso 2: Inicializar Sistema

```bash
idos init
```

✅ **Esperado**: Mensaje verde "IDOS initialized successfully"
✅ **Verificar**: directorios `idos-knowledge/companies/`, `idos-journal/companies/`, `idos-config/`

---

## Paso 3: Configurar Universo

Editar `idos-config\universe\watchlist.md` y verificar que GOOGL esté listado:

```markdown
## Seguimiento Activo
| GOOGL | Alphabet | Technology | $2T | Moat digital | ALTA |
```

---

## Paso 4: Agregar Compañía a Knowledge Base

```bash
idos compañía agregar GOOGL --name "Alphabet Inc." --sector "Technology"
```

Si el CLI está en inglés por ahora:

```bash
idos company-add GOOGL --name "Alphabet Inc." --sector "Technology"
```

✅ **Esperado**: "Company GOOGL added"
✅ **Verificar**: `idos\idos-knowledge\companies\GOOGL\company.yml` creado

---

## Paso 5: Ver Compañía

```bash
idos company-show GOOGL
```

✅ **Esperado**: Tabla con ticker, name, sector

---

## Paso 6: Ejecutar Scout Worker (Screening Manual)

Ejecutamos el worker de screening directamente desde Python:

```python
# validate_scout.py
from idos.workers.data.scout_worker import ScoutWorker

worker = ScoutWorker({
    "universe_path": "idos-config/universe/watchlist.md",
    "min_score": 50,
})

result = worker.execute({
    "tickers": ["GOOGL"],
    "refresh_data": False,   # True para datos reales de stockanalysis.com
})

print(f"Status: {result.status}")
print(f"Tickers screened: {result.output['tickers_screened']}")
print(f"Passed: {result.output['passed_count']}")
for r in result.output.get("results", []):
    print(f"  {r['ticker']}: score={r['score']}, passed={r['passed']}")
    print(f"  Details: {r['details']}")
```

```bash
python validate_scout.py
```

✅ **Esperado**: GOOGL screened con score > 50, passed=True
✅ **Verificar**: sub-scores (size, liquidity, momentum, value, quality)

---

## Paso 7: Agregar a Watchlist Manualmente

```bash
idos watchlist
```

✅ **Esperado**: Ver GOOGL en la watchlist con su score

---

## Paso 8: Crear Oportunidad

```bash
idos opp-create GOOGL
```

✅ **Esperado**: "Opportunity OPP-20260717-XXX created for GOOGL"
✅ **Verificar**: `idos opp-list` muestra la oportunidad con status DISCOVERED

---

## Paso 9: Avanzar por el Lifecycle

```bash
idos opp-transition OPP-20260717-XXX SCREENED
idos opp-transition OPP-20260717-XXX WATCHLIST
idos opp-transition OPP-20260717-XXX UNDER_RESEARCH
```

✅ **Esperado**: Cada transición muestra "OPP-XXX: DISCOVERED -> SCREENED" etc.
✅ **Verificar**: `idos opp-list` muestra status actualizado

---

## Paso 10: Probar el Dashboard

```bash
idos dashboard
```

✅ **Esperado**: Muestra:
- Active Opportunities: ≥1
- Portfolio Positions: (puede ser 0)
- Total Weight: 0.0% (si no hay posiciones)
- Watchlist: ≥1

---

## Paso 11: Probar Event Log

```bash
idos event-log
```

✅ **Esperado**: Lista de eventos recentes (company:created, opportunity:created, opportunity:transitioned)

---

## Paso 12: Probar Workers Financieros (con datos reales)

```python
# validate_data.py
from idos.workers.data.stockanalysis import StockAnalysisWorker
from idos.workers.data.yahoo import YahooFinanceWorker
from idos.workers.data.cache import DataCache
from idos.workers.data.validator import DataValidator

ticker = "GOOGL"

# Probar stockanalysis.com
sa = StockAnalysisWorker()
result = sa.execute({"ticker": ticker})
print(f"StockAnalysis: {result.status}")
if result.status == "success":
    print(f"  Market Cap: {result.output.get('market_cap', 'N/A')}")
    print(f"  PE Ratio: {result.output.get('pe_ratio_ttm', 'N/A')}")
    print(f"  ROIC: {result.output.get('roic_pct', 'N/A')}")

# Probar yfinance
yf = YahooFinanceWorker()
result = yf.execute({"ticker": ticker, "period": "1y"})
print(f"\nYahoo Finance: {result.status}")
if result.status == "success":
    print(f"  Price: {result.output.get('price', 'N/A')}")
    print(f"  Market Cap: {result.output.get('market_cap', 'N/A')}")
    print(f"  Price Change 1y: {result.output.get('price_change_12m', 'N/A')}")

# Probar caché
cache = DataCache()
cached = cache.get(f"raw:stockanalysis:{ticker}")
print(f"\nCached: {'YES' if cached else 'NO'}")

# Probar validador cruzado
v = DataValidator()
validation = v.cross_validate({
    "stockanalysis.com": {"pe_ratio": 25.0, "market_cap": 2_000_000_000_000},
    "yfinance": {"pe_ratio": 24.5, "market_cap": 2_050_000_000_000},
})
print(f"\nCross-validate conflicts: {len(validation['conflicts'])}")
print(f"Merged PE: {validation['merged_data'].get('pe_ratio', 'N/A')}")
```

```bash
python validate_data.py
```

✅ **Esperado**: Datos reales de GOOGL desde stockanalysis.com y yfinance
✅ **Verificar**: Caché funciona (segunda corrida es instantánea)

---

## Paso 13: Probar Scheduler

```python
# validate_scheduler.py
import time
from idos.workers.base import BaseWorker
from idos.workers.scheduler.service import SchedulerService, ScheduledJob

class TestWorker(BaseWorker):
    name = "test_e2e"
    def run(self, context):
        print(f"  Worker executed with ticker={context.get('ticker')}")
        return {"result": "ok"}

s = SchedulerService()
s.register(ScheduledJob("test_e2e", TestWorker(), "minutes", 1,
                         context={"ticker": "GOOGL"}))

print("Scheduler registered. Checking status...")
status = s.job_status()
print(f"  Jobs: {list(status.keys())}")
print("✅ Scheduler OK")
```

```bash
python validate_scheduler.py
```

✅ **Esperado**: Scheduler registrado sin errores, job visible en status

---

## Paso 14: Probar DigestWorker

```python
# validate_digest.py
from idos.workers.data.digest_worker import DigestWorker

w = DigestWorker()
result = w.execute({
    "scout_results": [
        {"ticker": "GOOGL", "passed": True, "score": 85, "reason": "Moat digital, calidad"},
        {"ticker": "MELI", "passed": True, "score": 78, "reason": "Crecimiento LatAm"},
    ],
    "risk_alerts": [],
    "opportunities": [
        {"id": "OPP-001", "ticker": "GOOGL", "status": "WATCHLIST", "conviction": 75},
    ],
})

print(result.output["digest"][:500])
print(f"\n✅ Digest generado: {result.output['line_count']} líneas")
```

```bash
python validate_digest.py
```

✅ **Esperado**: Digest semanal en español con GOOGL, oportunidades y riesgo

---

## Paso 15: Probar Pipeline Completo (E2E)

```python
# validate_e2e_full.py
from idos.discovery.scout import ScoutEngine
from idos.discovery.watchlist import WatchlistManager
from idos.discovery.ranking import RankingSystem
from idos.portfolio.entry import EntryEngine
from idos.portfolio.sizing import PositionSizer
from idos.portfolio.risk import RiskEngine
from idos.portfolio.exit import ExitEngine
from idos.decision.conviction import ConvictionCalculator
from idos.research.ddd import DeepDueDiligenceWorker
from idos.ux.reports import ReportGenerator

ticker = "GOOGL"

# 1. Scout
scout = ScoutEngine(min_score=50)
result = scout.scan(ticker, {
    "metrics": {
        "market_cap": 2_000_000_000_000,
        "avg_volume": 30_000_000,
        "pe_ratio": 25,
        "ev_ebitda": 18,
        "roic": 28,
        "operating_margin": 30,
        "debt_to_equity": 0.1,
        "revenue_growth": 15,
    }
})
print(f"1. Scout: score={result.score}, passed={result.passed}")
print(f"   Details: {result.details}")

# 2. Watchlist
wl = WatchlistManager()
wl.add(ticker, result.score, result.reason)
print(f"2. Watchlist: size={len(wl.get_all())}")

# 3. Ranking
ranking = RankingSystem()
ranked = ranking.rank([{"ticker": ticker, "score": result.score, "passed": result.passed}])
print(f"3. Ranking: {ranked}")

# 4. Entry
entry = EntryEngine()
signal = entry.evaluate(
    current_price=180,
    buy_zone_top=200,
    wyckoff_phase="ACCUMULATION",
    thesis_active=True,
    portfolio_total_weight=5.0,
    conviction=85,
)
print(f"4. Entry: price_in_zone={signal.price_in_zone}, can_enter={signal.can_enter}")

# 5. Position Sizing
sizer = PositionSizer(max_position_pct=3.0)
kelly_size = sizer.kelly_size(win_prob=0.65, win_loss_ratio=2.0)
max_size = sizer.calculate_max_size(conviction=85, total_capital=1_000_000, current_exposure=0)
print(f"5. Sizing: kelly={kelly_size:.1%}, max=${max_size:.0f}")

# 6. Conviction
calc = ConvictionCalculator()
conviction = calc.calculate({
    "business": 85,
    "valuation": 70,
    "rerating": 60,
    "risk": 75,
    "portfolio_fit": 80,
})
print(f"6. Conviction: overall={conviction.overall}, confidence={conviction.confidence}")

# 7. Risk
risk = RiskEngine()
alerts = risk.evaluate_all(
    ticker=ticker,
    current_price=180,
    avg_entry=175,
    stop_loss=140,
    volatility_annual=25,
    debt_to_equity=0.1,
    portfolio_weight=5.0,
)
print(f"7. Risk: {len(alerts)} alerts")
for a in alerts:
    print(f"   - {a.alert_type}: {a.message}")

# 8. Exit
exit_engine = ExitEngine()
exit_signal = exit_engine.evaluate(
    current_price=180,
    avg_entry=175,
    pe_ratio=25,
    intrinsic_pe=28,
    conviction_current=85,
    conviction_new=90,
    current_drawdown=2.0,
    stop_loss=140,
)
print(f"8. Exit: should_exit={exit_signal.should_exit}")

# 9. DDD (stub)
ddd = DeepDueDiligenceWorker()
ddd_result = ddd.run(ticker, {
    "business_model": "Publicidad digital + Cloud + YouTube",
    "products": "Search, Google Cloud, YouTube, Waymo",
    "moat_description": "Moat de datos + escala + ecosistema",
    "revenue": 350_000,
    "revenue_growth": 15,
    "operating_margin": 30,
    "roic": 28,
    "debt_to_equity": 0.1,
    "fcf_yield": 3.5,
    "recent_events": "Lanzamiento Gemini 2.5, crecimiento Cloud >30%",
})
print(f"9. DDD: score={ddd_result.score}")

# 10. Report
reports = ReportGenerator()
report = reports.build_dd_report(ticker=ticker, ddd_result=ddd_result)
md = reports.render_markdown(report)
print(f"\n10. Report: {len(md)} chars")
print(md[:300] + "...")

print(f"\n{'='*50}")
print(f"✅ E2E Validation Complete for {ticker}")
print(f"{'='*50}")
```

```bash
python validate_e2e_full.py
```

✅ **Esperado**: Pipeline completo sin errores, todos los componentes responden

---

## Paso 16: Verificar Cobertura de Tests

```bash
cd idos-core
python -m pytest --cov=idos --cov-report=term
```

Si no tenés pytest-cov:

```bash
pip install pytest-cov
```

✅ **Esperado**: Reporte de cobertura por módulo

---

## Paso 17: Probar Prompt Loading

```python
# validate_prompts.py
from idos.ai.prompts import PromptRegistry
from pathlib import Path

registry = PromptRegistry()
prompts_dir = Path("idos-config/prompts")
registry.load(str(prompts_dir))

print(f"Total prompts loaded: {registry.count()}")
for cat in registry.list_by_category():
    print(f"  Category '{cat}': {len(registry.list_by_category()[cat])} prompts")

# Verificar que todos los prompts tienen los campos requeridos
for name in registry.all():
    tmpl = registry.get(name)
    assert "system_prompt" in tmpl, f"Missing system_prompt in {name}"
    assert "user_prompt" in tmpl, f"Missing user_prompt in {name}"
    assert "category" in tmpl, f"Missing category in {name}"
    print(f"  ✅ {name} valid")

print(f"\n✅ All {registry.count()} prompts valid")
```

```bash
python validate_prompts.py
```

✅ **Esperado**: 9 prompts cargados y validados (5 scout + 4 research)

---

## Resumen de Validación

| # | Paso | Comando | ✅ |
|---|------|---------|---|
| 1 | Tests | `pytest` | |
| 2 | Init | `idos init` | |
| 3 | Universe | editar watchlist.md | |
| 4 | Company | `idos company-add` | |
| 5 | Show | `idos company-show` | |
| 6 | Scout | `validate_scout.py` | |
| 7 | Watchlist | `idos watchlist` | |
| 8 | Opportunity | `idos opp-create` | |
| 9 | Lifecycle | `idos opp-transition` | |
| 10 | Dashboard | `idos dashboard` | |
| 11 | Event Log | `idos event-log` | |
| 12 | Data Workers | `validate_data.py` | |
| 13 | Scheduler | `validate_scheduler.py` | |
| 14 | Digest | `validate_digest.py` | |
| 15 | E2E Full | `validate_e2e_full.py` | |
| 16 | Coverage | `pytest --cov` | |
| 17 | Prompts | `validate_prompts.py` | |
