# IDOS — Investment Decision Operating System

Sistema de gestión de inversiones para Family Office. Automatiza screening,
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
  screeners/                  ← 5 screeners programaticos (value, growth, etc.)
  data_sources.yml            ← fuentes de datos financieros
  rules/entry_rules.yml       ← reglas de entrada (asimetría 3:1, etc.)
  prompts/scout/              ← 5 prompts de screening
  prompts/research/           ← 4 prompts de investigación
  prompts/portfolio/          ← 1 prompt de Wyckoff (entry)
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
idos entry-evaluate MELI          # Evalúa precio + Wyckoff → ENTRY_PENDING/ACCUMULATING
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

---

## 4. Ciclo de Vida de la Inversión

El sistema cubre los 14 estados del **Investment Lifecycle Framework** (SDD-7)
con workers automatizados para cada transición:

```
DISCOVERED ──► SCREENED ──► WATCHLIST ──► UNDER_DEEP_DD ──► APPROVED
    ▲              │              │              │
    │         [ScoutWorker]  [manual/event]  [ResearchWorker]
    │                                           │
    │                                     [DecisionBoardWorker]
    │                                           │
    └──── ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┘ (si rechazado)
                                                │
                                          APPROVED
                                                │
                                     [EntryMonitorWorker]
                                                │
                                          ENTRY_PENDING
                                                │
                                     [EntryMonitorWorker + Wyckoff LLM]
                                                │
                                          ACCUMULATING ──► FULL_POSITION
                                                │
                                          MONITORING
                                          ▲    │    ▲
                                          │    ▼    │
                                          │ REDUCING│
                                          │    │    │
                                          └────▼────┘
                                             EXITED
                                                │
                                     [PostMortemWorker]
                                                │
                                          POST_MORTEM
                                                │
                                          ARCHIVED
```

### Workers del Ciclo de Vida

| Worker | Estado Origen | Estado Destino | Trigger |
|--------|--------------|----------------|---------|
| **ScoutWorker** | DISCOVERED | SCREENED → WATCHLIST | Semanal (lunes) |
| **ResearchWorker** | WATCHLIST | UNDER_DEEP_DD | `opp-research` o evento |
| **DecisionBoardWorker** | UNDER_DEEP_DD | APPROVED / WATCHLIST | `opp-approve` |
| **EntryMonitorWorker** | APPROVED / ENTRY_PENDING | ACCUMULATING | `entry-evaluate` o diario |
| **PostMortemWorker** | EXITED | POST_MORTEM → ARCHIVED | `position-exit` |

Workers auxiliares:

| Worker | Función | Frecuencia |
|--------|---------|------------|
| **DataRefreshWorker** | Obtiene datos financieros de múltiples fuentes | Diario (pre-market) |
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

| Prompt | Propósito |
|--------|-----------|
| `portfolio/wyckoff.yml` (v1.0) | **Análisis Wyckoff** vía LLM: 3 leyes, 9 pruebas de compra, eventos (PS/SC/AR/ST/Spring/LPS/SOS), punto de entrada (JAC/Spring), precio objetivo P&F, stop loss |

### 5.4 Wyckoff LLM Integration

El Entry Engine utiliza análisis Wyckoff dual:

- **Modo LLM** (recomendado): Usa el prompt `portfolio/wyckoff.yml` con los datos OHLCV de Yahoo Finance para identificar eventos Wyckoff reales, evaluar las 9 pruebas de compra, estimar precio objetivo vía conteo P&F, y sugerir stop loss.
- **Modo Algorítmico** (fallback): Análisis por tercios de precio/volumen cuando no hay LLM configurado.

Auto-detección: si hay LLM configurado, lo usa; si no, cae al algoritmo.

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

El **DecisionBoardWorker** evalúa el output del DDD contra estas reglas
automáticamente al ejecutar `opp-approve`.

---

## 7. Arquitectura de Datos

### Pipeline de Screening

```
watchlist.md (10,000 tickers)
    │
    ▼
┌─────────────────────────────────────┐
│ STEP 1: FinvizScreener (0 LLM)      │
│ Reglas programáticas sobre datos    │
│ cacheados (Value, Growth, Momentum) │
└──────────────┬──────────────────────┘
               │ ~1,000-3,000
               ▼
┌─────────────────────────────────────┐
│ STEP 2: OperabilityFilter (0 LLM)   │
│ CEDEARs + broker directo            │
└──────────────┬──────────────────────┘
               │ ~200-600
               ▼
┌─────────────────────────────────────┐
│ STEP 3: ScoutEngine (0 LLM)         │
│ Score detallado: size, liquidity,   │
│ momentum, value, quality            │
└──────────────┬──────────────────────┘
               │ ~30-80 (top scored)
               ▼
         watchlist.md
               │
               ▼
┌─────────────────────────────────────┐
│ STEP 4: Data Refresh (scraping)     │
│ Solo para watchlisted               │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ STEP 5: Deep Research (LLM)         │
│ DDD + AOIF + Hypothesis             │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ Decision Board → Portfolio          │
└─────────────────────────────────────┘
```

### Fuentes de Datos

```
stockanalysis.com ─┐
yfinance ──────────┤──► DataCache (SQLite con TTL)
finviz.com ────────┤    │
SEC EDGAR ────────┘    │
                       ▼
               DataValidator (validación cruzada)
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
   ScoutEngine   EntryEngine   RiskEngine
   (screening)   (Wyckoff +    (alertas)
                  price zone)
          │            │
          ▼            ▼
   ResearchWorker  EntryMonitorWorker
   (DDD+AOIF+Hyp)  (monitoreo diario)
          │
          ▼
   DecisionBoardWorker
   (evaluación vs reglas)
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

### 8.2 Digest Semanal

Generado automáticamente los viernes por `DigestWorker`. Incluye oportunidades
de la semana, alertas activas, posiciones y estado del pipeline.

### 8.3 Alertas de Riesgo

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
idos entry-evaluate MELI                  # Precio + Wyckoff → señal de entrada
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
**Solución**: Verifica que el ticker exista en stockanalysis.com.

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
```

---

*IDOS v0.2.0 — Family Office Investment Decision Operating System*
*360+ tests · 28 comandos CLI · Ciclo de vida completo · Dual-mode Wyckoff*
