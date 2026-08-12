# IDOS — Investment Decision Operating System

Sistema de gestión de inversiones para Family Office. Automatiza screening, due diligence,
due diligence, monitoreo de cartera, generación de reportes y notificaciones.
Implementa el ciclo de vida completo de inversión: desde el descubrimiento
hasta el post-mortem y archive.

---

## 1. Primeros Pasos

### 1.1 Instalación

```bash
git clone <repo>
cd idos
pip install -e idos-core
```

### 1.2 Inicialización

```bash
idos init
```

Crea la estructura de directorios:

```
idos-config/
  universe/watchlist.md       ← tickers a monitorear
  universe/operable.yml       ← lista de activos operables (CEDEARs + broker)
  universe/cedears.yml        ← lista de CEDEARs conocidos
  screeners/                  ← 5 screeners programaticos (value, growth, etc.)
  finviz_screener.yml         ← config de filtros Finviz
  data_sources.yml            ← fuentes de datos financieros
  hmf.yml                     ← config central de límites (hipótesis, riesgo, sizing)
  rules/entry_rules.yml       ← reglas de entrada (asimetría 3:1, etc.)
  prompts/scout/              ← 5 prompts de screening
  prompts/research/           ← 4 prompts de investigación
  prompts/portfolio/          ← prompts de portfolio (post-mortem, etc.)
idos-knowledge/
  companies/{TICKER}/
    company.yml
    knowledge_base/
      static/
        wiki.md
idos-journal/
  companies/{TICKER}/
    case_file/
    opportunities/{OPP_ID}/
      assessments/
      decisions/
      post_mortem/
      entry_snapshot.yml     ← snapshot del momento de entrada (tesis, assessments, técnicos, catalizadores, riesgos)
  portfolio/
    positions/
    watchlist.yml
idos.db                       ← SQLite (índice de búsqueda + telemetría)
```

### 1.3 Configuración Mínima

El sistema funciona con valores por defecto. Para LLM:

```bash
# OpenRouter (recomendado)
set OPENROUTER_API_KEY=sk-or-v1-...
set IDOS_LLM_PROVIDER=openrouter
set IDOS_LLM_MODEL=openai/gpt-4o

# Gemini
set GEMINI_API_KEY=AIza...
set IDOS_LLM_PROVIDER=gemini
set IDOS_LLM_MODEL=gemini-2.0-flash

# OpenAI directo
set OPENAI_API_KEY=sk-...
set IDOS_LLM_PROVIDER=openai
set IDOS_LLM_MODEL=gpt-4o
```

---

## 2. Configuración del Universo Invertible

### 2.1 Archivo watchlist.md

Edita `idos-config/universe/watchlist.md`.

```markdown
## Seguimiento Activo
| Ticker | Nombre | Sector | Market Cap | Motivo | Prioridad |
|--------|--------|--------|------------|--------|-----------|
| MELI | MercadoLibre | Technology | $85B | Crecimiento LatAm | ALTA |
| V | Visa | Financials | $560B | Calidad defensiva | ALTA |

## Watchlist Secundaria
| Ticker | Nombre | Catalizador | Timeline |
|--------|--------|-------------|----------|
| SE | Sea Limited | Recuperación Garena | Q4 2026 |
```

### 2.2 Fuentes de Datos

| Fuente | Prioridad | TTL | Propósito |
|--------|-----------|-----|-----------|
| stockanalysis.com | 1 (primaria) | 12h | 50+ métricas financieras |
| yahoo_finance | 2 (fallback) | 1h | Precios históricos OHLCV + ratios |
| finviz.com | 3 | 12h | Screening visual complementario |
| SEC EDGAR | 4 | 24h | Filings oficiales (10-K/10-Q) |
| yfinance (SPY) | benchmark | 24h | Fuerza relativa del Entry Engine (SPY 1y) |

Validación cruzada automática cuando hay múltiples fuentes disponibles.

### 2.3 Lista de Activos Operables

El archivo `idos-config/universe/operable.yml` contiene la lista curada de
activos que realmente se pueden operar (CEDEARs en BYMA + acciones US directas
disponibles en tu broker). Se usa como pre-filter del scout para que solo
pasen a análisis los tickers que puedas comprar.

Mantenimiento manual via CLI:

```bash
idos operable-add AAPL --name "Apple Inc." --type cedear --source broker_ppi
idos operable-list
idos operable-check MELI
idos operable-import ./lista_cedears.csv
```

### 2.4 Screeners Programaticos

Directorio `idos-config/screeners/` con 5 screeners inspirados en Finviz. Cada
screener es un conjunto de reglas programaticas (sin LLM) que filtran tickers
por multiples fundamentales o tecnicos.

| Screener | Descripcion | Reglas |
|----------|-------------|--------|
| `value.yml` | Multiples bajos vs sector | PE < 20, PB < 3, EV/EBITDA < 15, FCF Yield > 3% |
| `growth.yml` | Crecimiento y rentabilidad | Revenue Growth > 10%, ROE > 12%, ROIC > 8% |
| `momentum.yml` | Tendencia alcista | Price 3M > 5%, RSI > 50, Price 12M > 5% |
| `quality.yml` | Negocios de alta calidad | ROIC > 10%, Op Margin > 15%, D/E < 1.5 |
| `deep_value.yml` | Infravalorado extremo | PE < 15, PB < 1.5, FCF Yield > 5% |

```bash
idos screener-list              # Lista screeners disponibles
idos screener-run AAPL          # Evalua AAPL contra todos los screeners
idos screener-run AAPL --name value  # Evalua contra screener especifico
```

---

## 3. Uso del CLI

```bash
# Entry point (si PATH configurado)
idos <comando>

# Alternativa universal
python -m idos.cli.main <comando>
```

### 3.1 Gestión de Compañías

```bash
idos company-add MELI             # Agrega compañía al knowledge base
idos company-show MELI            # Muestra datos de compañía
```

### 3.2 Ciclo de Investigación

```bash
idos opp-create MELI              # Crea nueva oportunidad → DISCOVERED
idos opp-research MELI            # Ejecuta DDD+AOIF+Hypothesis → UNDER_DEEP_DD
idos opp-approve MELI             # Decision Board: evalúa vs reglas → APPROVED/WATCHLIST
idos opp-reject MELI              # Rechazo manual → WATCHLIST
idos opp-show MELI                # Estado completo + transiciones
idos opp-list                     # Lista oportunidades activas
idos opp-transition OPP-001 ACCUMULATING  # Avance manual
```

### 3.3 Entry y Monitoreo

```bash
idos entry-evaluate MELI          # Evalúa precio + indicador técnico → ENTRY_PENDING/ACCUMULATING
idos watchlist                    # Muestra watchlist activa
idos position-list                # Lista posiciones abiertas
idos position-exit MELI --reason thesis_broken  # Cierra posición + post-mortem automático
idos dashboard                    # Resumen general del sistema
idos event-log                    # Log de eventos recientes
idos schedule-status              # Estado del scheduler
```

### 3.4 Gestión de Activos Operables

```bash
idos operable-add AAPL --name "Apple Inc." --type cedear --source broker_ppi  # Agrega activo operable
idos operable-remove AAPL           # Elimina activo
idos operable-list                  # Lista todos los activos operables
idos operable-list --type cedear    # Filtra por tipo
idos operable-list --source broker_ppi  # Filtra por fuente
idos operable-check MELI            # Verifica si un ticker está en la lista
idos operable-import ./cedears.csv  # Importación masiva desde CSV
idos operable-stats                 # Estadísticas por tipo y fuente
```

### 3.5 Screeners

```bash
idos screener-list                  # Lista screeners disponibles (Value, Growth, etc.)
idos screener-run AAPL              # Evalúa AAPL contra todos los screeners
idos screener-run AAPL --name value # Evalúa contra screener específico
```

### 3.6 Universe Pipeline

```bash
idos universe-build              # Ejecuta pipeline completo: Finviz → Filter → Fetch → Scout → Opportunities
idos universe-fetch              # Fetch datos financieros para tickers operables
idos universe-status             # Muestra estadísticas del universo y cache
```

### 3.7 DDD Pipeline (GitHub Actions) — Multi-Trigger

El pipeline completo de decisión se ejecuta via GitHub Actions con 4 triggers:

| Trigger | Descripción | Modo |
|---------|-------------|------|
| `schedule` (día 2 cada mes) | Batch mensual de oportunidades DISCOVERED | NORMAL |
| `workflow_run` (Monthly Universe) | Post-universe automático | NORMAL |
| `workflow_dispatch` (manual) | Ticker específico + flag **force** opcional | NORMAL / FORCE |
| `repository_dispatch` (quarterly-results) | Post-earnings automático (1 día después) | **FORCE** |

**FORCE mode**: reprocesa la oportunidad en cualquier estado (no solo DISCOVERED),
regenera research + assessments, pero **no cambia el status** — el usuario revisa
y decide manualmente.

```bash
# Opcional: ejecutar localmente un paso específico
python -c "from idos.decision.assessment_pipeline import run_full_pipeline; print(run_full_pipeline('OPP-001', 'GFI', '.'))"
```

#### 3.7.1 Earnings Event-Driven

Configurar fechas de earnings en `idos-config/events/earnings.yml`:

```yaml
tickers:
  AAPL:
    earnings_date: "2026-07-25"
    triggered_at: null
  MSFT:
    earnings_date: "2026-07-28"
    triggered_at: null
```

El **Daily Refresh** (cada día hábil) chequea si `hoy >= earnings_date` y
dispara un `repository_dispatch` al DDD Pipeline. El campo `triggered_at` se
actualiza automáticamente para evitar re-disparos.

#### 3.7.2 Manual Force Mode

Desde **Actions → DDD Research Pipeline → Run workflow**:

| Input | Descripción |
|-------|-------------|
| `ticker` | Ticker específico (obligatorio en force mode) |
| `force` | `true` = reprocesa cualquier estado, no cambia status |

---

## 4. Ciclo de Vida de la Inversión

El sistema cubre los 14 estados del **Investment Lifecycle Framework** (SDD-7)
con workers automatizados para cada transición:

```
DISCOVERED ─────────────► UNDER_DEEP_DD ──► APPROVED
    │  (nace toda            │     │             │
    │   oportunidad)         │     │             │
    │ (sin SCREENED)   [ResearchWorker]     [AssessmentPipeline]
    │                        │  (Steps 3-7: 5 Engines
    │                        │   + Conviction + Rules
    │                        │   + Board + Entry)
    │                 ┌──────┴────────┐
    │                 ▼               ▼
    │            APPROVED        WATCHLIST
    │                 │           (destino de
    │                 ▼           no-aprobación)
    │           ENTRY_PENDING
    │                 │
    │                 ▼          [EntryMonitorWorker → señal
    │            ACCUMULATING    + PaperTrader ejecuta
    │                 │          + execute_entry_signals]
    │                 ▼
    │              EXITED
    │                 │
    │                 ▼          [PostMortemWorker]
    │            POST_MORTEM
    │                 │
    │                 ▼
    │            ARCHIVED
    │
    └───── WATCHLIST (no-promocional): rechazo/baja
                  → puede volver a UNDER_DEEP_DD
```

> Nota de fidelidad: `SCREENED`, `UNDER_RESEARCH`, `FULL_POSITION`, `MONITORING` y
> `REDUCING` están definidos en la state machine pero **no son escritos por ningún worker
> de producción** (solo vía `opp-transition` manual). `WATCHLIST` es destino de
> no-aprobación, no etapa de promoción. Ver SDD-7 §7.

### Workers del Ciclo de Vida

| Worker | Estado Origen | Estado Destino | Trigger |
|--------|--------------|----------------|---------|
| **ResearchWorker** | DISCOVERED (NORMAL) / cualquier estado (FORCE) | UNDER_DEEP_DD / sin cambio | DDD Pipeline STEP 2 (schedule, workflow_run, workflow_dispatch, repository_dispatch) |
| **AssessmentPipeline** | UNDER_DEEP_DD (NORMAL) / cualquier estado (FORCE) | APPROVED / PENDING_REVIEW / sin cambio | DDD Pipeline STEP 3-7 |
| **EntryMonitorWorker** | APPROVED / ENTRY_PENDING | ACCUMULATING | `entry-evaluate` o diario |
| **PostMortemWorker** | EXITED | POST_MORTEM → ARCHIVED | `position-exit` |

Workers del DDD Pipeline (GitHub Actions):

| Paso | Componente | Función |
|------|-----------|---------|
| STEP 2 | **ResearchWorker** | DDD + AOIF + Hypothesis → assessment en journal |
| STEP 3 | **5 Assessment Engines** | Business, Valuation, Recovery, Risk, Portfolio → scores 0-100 |
| STEP 4 | **ConvictionCalculator** | Weighted avg de scores (weights en `scoring.yml`) |
| STEP 5 | **RulesEngine** | 8 entry rules (RULE-001 a RULE-008) |
| STEP 6 | **DecisionBoard** | Submit proposal + auto-review → BoardResolution |
| STEP 7 | **EntryEngine** | Indicador compuesto + price zone + portfolio fit (si APPROVED) |

Workers auxiliares:

| Worker | Función | Frecuencia |
|--------|---------|------------|
| **DataRefreshWorker** | Obtiene datos financieros de múltiples fuentes | Diario (pre-market) |
| **BuyListRefreshWorker** | Actualiza `target_price` y `buy_zone_top` de la Buy List desde la valoración | Diario |
| **StockAnalysisWorker** | Scraper de stockanalysis.com | Bajo demanda |
| **YahooFinanceWorker** | Precios históricos OHLCV y métricas vía yfinance | Bajo demanda |
| **FinvizWorker** | Snapshot complementario de finviz | Bajo demanda |
| **SECEdgarWorker** | Descarga de filings SEC | Trimestral |
| **DigestWorker** | Genera weekly digest en español | Viernes |
| **GitQueueWorker** | Commit automático de cambios a git | Cada 10 min |
| **LLMWorker** | Ejecuta prompts contra LLM configurado | Bajo demanda |
| **TelegramBot** | Bot interactivo de comandos Telegram | Bajo demanda o daemon |

---

## 5. Prompts y LLM

### 5.1 Scout (Discovery)

| Prompt | Propósito |
|--------|-----------|
| `scout/size_liquidity.yml` | Tamaño y liquidez (market cap, ADV, spread, free float) |
| `scout/momentum.yml` | Momentum con RSI, volumen relativo y fuerza sectorial |
| `scout/value.yml` | Valoración con percentiles históricos y sectoriales |
| `scout/quality.yml` | Calidad con excess return, ROIC, FCF conversion |
| `scout/synthesis.yml` | Síntesis con override triggers y position sizing |

### 5.2 Research (Due Diligence)

| Prompt | Propósito |
|--------|-----------|
| `research/ddd.yml` (v3.0) | **Deep Due Diligence**: Fase 0 (clasificación en 10 categorías), Fase 1 (error de mercado / second level thinking), + 7 dominios SDD |
| `research/aoif.yml` | AOIF 8-step protocol con 3 escenarios probabilísticos |
| `research/hypothesis.yml` | Generación de hipótesis falsables con predicciones y criterios |
| `research/wiki.yml` | Generación de wiki de conocimiento |

### 5.3 Portfolio (Entry)

El filtro de entrada es **100% algorítmico** (0 LLM). No usa prompts: el `EntryEngine` computa un indicador compuesto de oferta/demanda sobre datos OHLCV.

### 5.4 Indicador Compuesto de Entrada

El Entry Engine utiliza un indicador compuesto determinista y reproducible:

| Componente | Peso |
|-----------|------|
| Estructura (fin de mínimos, ruptura de base, MA50/200) | 40% |
| Oferta/Demanda (volumen, climax, sequía de volumen) | 30% |
| Fuerza Relativa vs SPY (Weinstein) | 20% |
| Volatilidad (contracción de rango) | 10% |

Clasificación (bandas configurables en `idos-config/portfolio.yml`):
- 🟢 **Demanda dominante** (score ≥ 65) → entrada habilitada
- 🟡 **Absorción** (45–64) → entrada habilitada
- 🟠 **Oferta dominante** (25–44) → entrada bloqueada
- 🔴 **Distribución** (< 25) → entrada bloqueada

Los umbrales se calibran vía post-mortem: el Learning Domain propone ajustes (subir/bajar) que requieren revisión humana.

---

## 6. Reglas de Entrada

Archivo `idos-config/rules/entry_rules.yml`:

| Regla | Condición | Acción |
|-------|-----------|--------|
| RULE-001 | Business quality score >= 70 | PASS |
| RULE-002 | Valuation score >= 60 | PASS |
| RULE-003 | Rerating probability score >= 60 | PASS |
| RULE-004 | Risk score >= 50 | PASS |
| RULE-005 | Overall conviction >= 65 | PASS |
| RULE-006 | Max position weight <= 3.0% | BLOCK si excede |
| RULE-007 | Max sector exposure <= 25% | BLOCK si excede |
| RULE-008 | Asymmetry ratio >= 3.0 | PASS |

Estas reglas se evalúan automáticamente en el **STEP 5** del DDD Pipeline
(GitHub Actions). Si todas pasan y conviction >= 75 la oportunidad se
aprueba; si alguna falla pero conviction >= 50 pasa a PENDING_REVIEW.

---

## 7. Arquitectura de Datos

### Pipeline de Screening (Universe)

```
watchlist.md (10,000 tickers)
    │
    ▼
┌──────────────────────────────────────────┐
│ STEP 1: FinvizScreener (0 LLM)          │
│ Reglas programáticas sobre datos         │
│ cacheados (Value, Growth, Momentum)     │
└─────────────────┬────────────────────────┘
                  │ ~1,000-3,000
                  ▼
┌──────────────────────────────────────────┐
│ STEP 2: OperabilityFilter (0 LLM)        │
│ CEDEARs + broker directo                 │
└─────────────────┬────────────────────────┘
                  │ ~200-600
                  ▼
┌──────────────────────────────────────────┐
│ STEP 3: ScoutEngine (0 LLM)             │
│ Score detallado: size, liquidity,        │
│ momentum, value, quality                 │
└─────────────────┬────────────────────────┘
                  │ ~30-80 (top scored)
                  ▼
            watchlist.yml
                  │
                  ▼
┌──────────────────────────────────────────┐
│ STEP 4: Data Refresh (scraping)          │
│ Solo para watchlisted                    │
└─────────────────┬────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────┐
│ STEP 5: ScoutWorker (LLM)               │
│ Synthesis con override triggers          │
└─────────────────┬────────────────────────┘
                  │ ~30-80 passing scout
                  ▼
┌──────────────────────────────────────────┐
│ STEP 6: Opportunity Creation             │
│ Score >= 70 → DISCOVERED en journal      │
└─────────────────┬────────────────────────┘
                  │
                  ▼
         DDD Pipeline (GHA)
```

### Pipeline de Decisión (DDD)

```
┌─ Triggers ──────────────────────────────────┐
│                                             │
│  📅 Schedule (día 2) ──────┐               │
│  🔄 Monthly Universe ──────┤               │
│  👤 Manual (workflow_dispatch) ─┤           │
│  📊 Quarterly Results (repo_dispatch) ──┘   │
│                                             │
│  FORCE mode: permite reprocesar cualquier   │
│  estado, no cambia status                   │
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────┐
│ STEP 2: ResearchWorker (LLM)            │
│ DDD (deep due diligence)                │
│ AOIF (8-step protocol)                  │
│ Hypothesis generation                    │
│ → NORMAL: Status → UNDER_DEEP_DD        │
│ → FORCE:  Status intacto               │
└─────────────────┬────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────┐
│ STEP 3: 5 Assessment Engines (0 LLM)    │
│ BusinessAssessmentEngine                 │
│ ValuationAssessmentEngine                │
│ RecoveryAssessmentEngine                 │
│ RiskAssessmentEngine                     │
│ PortfolioAssessmentEngine                │
│ → 5 scores 0-100 + findings/risks        │
└─────────────────┬────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────┐
│ STEP 4: ConvictionCalculator             │
│ Weighted avg (weights en scoring.yml)    │
│ → Conviction(overall, confidence, trend) │
└─────────────────┬────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────┐
│ STEP 5: RulesEngine                      │
│ 8 entry rules (entry_rules.yml)          │
│ → rules_passed / rules_failed            │
└─────────────────┬────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────┐
│ STEP 6: DecisionBoard                    │
│ Submit proposal → auto-review            │
│ → BoardResolution(approved=True/False)   │
│   + decision_type (BUY/HOLD)             │
└─────────────────┬────────────────────────┘
                  │
         ┌────────┴────────┐
         ▼                  ▼
   APPROVED          PENDING_REVIEW
         │            (si BLOCKED)
         ▼
┌──────────────────────────────────────────┐
│ STEP 7: EntryEvaluation                  │
│ Indicador compuesto + price zone          │
│ Portfolio fit check                       │
│ → EntrySignal(all_conditions_met)        │
└──────────────────────────────────────────┘
         │
         ▼
   Output: decision_proposal.yml
           board_resolution.yml
           entry_evaluation.yml
         + Notificación (Telegram + Email)
         + Event type en notificación
```

### Output del DDD Pipeline

Por cada oportunidad procesada se generan 3 archivos YAML en
`idos-journal/companies/{TICKER}/case_file/opportunities/{OPP-ID}/`:

| Archivo | Contenido |
|---------|-----------|
| `decision_proposal.yml` | Assessments scores, conviction, recommendation, rules results |
| `board_resolution.yml` | Approved (bool), decision_type, decision_id, justification |
| `entry_evaluation.yml` | Solo si APPROVED: fase técnica (indicador compuesto), margin of safety, price zone |

### Fuentes de Datos

```
stockanalysis.com ─┐
yfinance ──────────┤──► DataCache (SQLite con TTL)
finviz.com ────────┤    │
SEC EDGAR ────────┘    │
                       ▼
               DataValidator (validación cruzada)
                       │
          ┌────────────┼────────────────┐
          ▼            ▼                ▼
    ScoutEngine   EntryEngine       RiskEngine
    (screening)   (indicador +      (alertas)
                   price zone)
          │            │
          ▼            │
   UniversePipeline    │
   (STEP 6: opps)     │
          │            │
          ▼            ▼
    DDD Pipeline (GitHub Actions)
    ┌──────────────────────────────────┐
    │ Triggers: schedule, workflow_run,│
    │ workflow_dispatch (force),       │
    │ repository_dispatch (quarterly)   │
    ├──────────────────────────────────┤
    │ STEP 2: ResearchWorker           │
    │ STEP 3: Assessment Engines       │
    │ STEP 4: ConvictionCalculator     │
    │ STEP 5: RulesEngine              │
    │ STEP 6: DecisionBoard            │
    │ STEP 7: EntryEvaluation          │
    └──────────────────────────────────┘
          │
          ▼
   idos-journal/companies/{TICKER}/case_file/opportunities/{OPP-ID}/
   ├── decision_proposal.yml
   ├── board_resolution.yml
   └── entry_evaluation.yml (si approved)
```

### 7.1 Caché

Respuestas cacheadas en SQLite con TTL configurable (12h stockanalysis,
1h yahoo, 24h SEC). Si un dato está en caché y no ha expirado, se devuelve
sin hacer llamada externa.

### 7.2 Validación Cruzada

Cuando hay múltiples fuentes disponibles, el `DataValidator`:
1. Calcula el promedio de valores numéricos
2. Detecta discrepancias > 20% entre fuentes
3. Reporta conflictos para revisión manual
4. Prioriza stockanalysis.com como fuente primaria

---

## 8. Notificaciones

### 8.1 Telegram

```bash
set IDOS_TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
set IDOS_TELEGRAM_CHAT_ID=-123456789
```

Además de notificaciones automáticas, hay un **bot interactivo** que responde comandos:

| Comando | Descripción |
|---------|-------------|
| `/watchlist` | Watchlist actual con scores |
| `/dashboard` | Resumen del sistema |
| `/scout AAPL,GOOGL` | Screening bajo demanda |
| `/opp-list` | Oportunidades activas |
| `/position-list` | Posiciones abiertas |
| `/event-log` | Eventos recientes |
| `/help` | Lista de comandos |

```bash
idos telegram-bot                  # Una ejecución
nohup idos telegram-bot --daemon & # Modo daemon (Codespace)
```

En workflows GHA, se usa `if: failure()` para alertas inmediatas de fallo.

Prioridades:
- **🔴 HIGH**: Alertas de riesgo, oportunidades detectadas → Telegram inmediato
- **🟡 MEDIUM**: Cambios de estado, convicción update → Email digest diario
- **🟢 LOW**: Weekly digest → Dashboard

### 8.2 DDD Pipeline Notifications

Cada ejecución del DDD Pipeline (GitHub Actions) envía:

- **Telegram**: resumen con scores, recomendaciones, y link al detalle en el repo
- **Email**: mismo contenido vía SMTP (configurar `IDOS_SMTP_*` secrets)

### 8.3 Digest Semanal

Generado automáticamente los viernes por `DigestWorker`. Incluye oportunidades
de la semana, alertas activas, posiciones y estado del pipeline.

### 8.4 Alertas de Riesgo

El `RiskEngine` evalúa automáticamente: drawdown > 15%, volatilidad > 30%,
D/E > 2.0, concentración > 3%, stop loss alcanzado.

---

## 9. Manual de Intervención (sin UI)

Todas las operaciones del ciclo de vida están disponibles vía CLI:

```bash
# Investigación
idos opp-research MELI                    # DDD + AOIF + Hypothesis
idos opp-approve MELI                     # Decision Board (evalúa reglas)
idos opp-reject MELI --reason "falta_moat"  # Rechazar → Watchlist

# Entry
idos entry-evaluate MELI                  # Precio + indicador técnico → señal de entrada
idos position-exit MELI --reason thesis_broken  # Cerrar + post-mortem
idos position-exit MELI --reason valuation_target  # Salida por valoración
idos position-exit MELI --reason stop_loss  # Stop loss alcanzado
idos position-exit MELI --reason portfolio_rebalance  # Rotación de capital

# Screening y Watchlist
idos scout                                # Ejecutar screening completo
idos watchlist                            # Ver watchlist con scores

# Notificaciones
idos telegram-bot                         # Procesar comandos Telegram
idos telegram-bot --daemon                # Modo escucha continua

# Diagnóstico
idos opp-show MELI                        # Estado + transiciones históricas
idos schedule-status                      # Workers programados
```

Para ver el estado completo de una oportunidad (incluyendo todas las
transiciones, assessments generados, y decisiones tomadas):

```bash
idos opp-show TICKER
```

---

## 10. Resolución de Problemas

### 10.1 Error: "No data from any source"

**Causa**: Las fuentes externas no respondieron o el ticker es inválido.
**Solución**: Verifica que el ticker exista en stockanalysis.com. Los errores de datos se registran en `cache/data_errors.json` y se reportan en un issue consolidado diario (`⚠️ IDOS: errores de datos`).

### 10.2 Error: "No LLM API key configured"

**Causa**: Faltan variables de entorno.
**Solución**: Configura `IDOS_LLM_API_KEY` o ejecuta sin LLM (modo stub).

### 10.3 Worker falla repetidamente

**Causa**: Rate limiting o cambios en estructura HTML de fuentes.
**Solución**: Aumenta `delay` en `data_sources.yml`. Reporta cambios de HTML.

### 10.4 Tests

```bash
cd idos-core
python -m pytest -v        # 360+ tests
```

---

## 11. Comandos Rápidos

```bash
idos init                  # Inicializar estructura
idos dashboard             # Dashboard general
idos opp-list              # Oportunidades activas
idos opp-research MELI     # Investigar oportunidad
idos opp-approve MELI      # Evaluar para aprobación
idos entry-evaluate MELI   # Señal de entrada
idos position-list         # Posiciones activas
idos position-exit MELI --reason manual  # Salida + post-mortem
idos event-log             # Eventos recientes
idos schedule-status       # Estado del scheduler
idos scout                 # Screening completo
idos watchlist             # Watchlist con scores
idos telegram-bot          # Bot Telegram interactivo
idos telegram-bot --daemon # Modo daemon
idos operable-list         # Activos operables
idos operable-check MELI   # Verificar si es operable
idos operable-add AAPL --type cedear  # Agregar activo operable
idos operable-import ./lista.csv      # Importación masiva
idos operable-stats                   # Estadísticas
idos screener-list                  # Screeners disponibles
idos screener-run AAPL              # Evaluar ticker contra screeners
idos site-build                     # Generar UI estática en ./site
```

---

## 12. Interfaz Web (estática, sin servidor)

El sistema incluye una **UI estática** publicable en **GitHub Pages** (gratis) que
permite revisar el estado del portfolio, las oportunidades, la Buy List, la wiki y
el aprendizaje, desde la perspectiva de un gestor.

### 12.1 Vista previa

```
idos site-build                 # genera ./site (index.html + data.json + wiki/*.html)
# Abre ./site/index.html en tu navegador
```

### 12.2 Vistas incluidas

| Vista | Qué muestra |
|-------|-------------|
| **Dashboard** | Acciones sugeridas (BUY/EXIT/LEARNING), funnel de oportunidades por estado, alertas (research stale, cerca de stop, convicción DETERIORATING, precio sobre valor intrínseco) |
| **Oportunidades** | Activas (WATCHLIST / UNDER_DEEP_DD / APPROVED) con scores de los 5 engines, upside %, última investigación; toggle para **cerradas** (EXITED/POST_MORTEM/ARCHIVED) |
| **Buy List** | Último precio, zona de compra (`buy_zone_top`), target, margen, última fecha de KB, estado Wyckoff y fecha, catalizadores |
| **Portfolio** | Activos, peso %, entry, último precio, P/L por activo y total, stop loss (distancia), target, concentración por sector |
| **Watchlist** | Candidatos del Discovery Domain (Scout), con score y razón |
| **Wiki** | Índice de 60+ compañías → página por ticker con ficha y markdown renderizado |
| **Learning** | Post-mortems de oportunidades cerradas (lecciones, sesgos, `would_invest_again`, precisión Wyckoff). El post-mortem evalúa la tesis y el análisis del **momento de entrada** desde el snapshot (`entry_snapshot.yml`), no los datos del cierre |

Al hacer clic en cualquier ticker se abre la **Case View** integrada: decisión,
scores, tesis/riesgos del DDD, última investigación (con badge de staleness),
Wyckoff y post-mortem si existe.

### 12.3 Datos y frescura

El sitio se alimenta de los YAML del journal, del conocimiento y de la cache diaria
de precios (`idos.db#price_history`, último cierre disponible). Los campos P/L y
precios del portfolio quedan marcados como `—` si aún no hay precios cacheados.

El umbral de “research stale” por defecto es **30 días**, configurable en
`idos-config/ui.yml`:

```yaml
stale_days: 30
```

### 12.4 Publicación automática

El workflow **`gh-pages.yml`** regenera y publica el sitio en Pages automáticamente
tras: el *Daily Data Refresh*, los pipelines (DDD / Universe / Rebalance / Digest),
o cualquier push a `idos-journal/**` / `idos-knowledge/**` / `idos-config/ui.yml`.

> Para publicar en tu repo: Settings → Pages → Source `GitHub Actions`.
> La URL será `https://<tu-usuario>.github.io/<repo>/`.

---

*IDOS v0.2.0 — Family Office Investment Decision Operating System*
*360+ tests · 28 comandos CLI · Ciclo de vida completo · Entry 100% algorítmico · UI estática*

<!-- Test auto-commit skill -->
