# IDOS — Investment Decision Operating System

Sistema de gestión de inversiones para Family Office. Automatiza screening,
due diligence, monitoreo de cartera, generación de reportes y notificaciones.

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
idos-config/          ← configuración, prompts, universo
  universe/watchlist.md   ← tickers a monitorear
  data_sources.yml        ← fuentes de datos financieros
  prompts/scout/          ← 4 prompts de screening
  prompts/research/       ← 5 prompts de investigación
idos-knowledge/       ← base de conocimiento por compañía
  companies/{TICKER}/
    company.yml
    knowledge_base/
idos-journal/         ← journal de inversiones
  companies/{TICKER}/
  portfolio/
```

### 1.3 Configuración Mínima

El sistema funciona con valores por defecto. Para LLM:

```bash
# Usando OpenRouter (recomendado, default)
set OPENROUTER_API_KEY=sk-or-v1-...   # https://openrouter.ai/keys
set IDOS_LLM_PROVIDER=openrouter
set IDOS_LLM_MODEL=openai/gpt-4o      # cualquier modelo OpenRouter

# O usando Gemini
set GEMINI_API_KEY=AIza...             # https://aistudio.google.com/apikey
set IDOS_LLM_PROVIDER=gemini
set IDOS_LLM_MODEL=gemini-2.0-flash

# O usando OpenAI directo
set OPENAI_API_KEY=sk-...
set IDOS_LLM_PROVIDER=openai
set IDOS_LLM_MODEL=gpt-4o
```

---

## 2. Configuración del Universo Invertible

### 2.1 Archivo watchlist.md

Edita `idos-config/universe/watchlist.md`. Este archivo es el punto de partida
del Scout. El sistema lee la tabla **Seguimiento Activo** en cada ciclo.

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

Agrega o quita tickers libremente. El sistema ignora duplicados.

### 2.2 Fuentes de Datos

Archivo `idos-config/data_sources.yml`:

| Fuente | Prioridad | TTL | Propósito |
|--------|-----------|-----|-----------|
| stockanalysis.com | 1 (primaria) | 12h | 50+ métricas financieras |
| yahoo_finance | 2 (fallback) | 1h | Precios históricos + ratios |
| finviz.com | 3 | 12h | Screening visual complementario |
| SEC EDGAR | 4 | 24h | Filings oficiales (10-K/10-Q) |

El sistema intenta stockanalysis.com primero. Si falla, usa yfinance. Valida
cruzadamente cuando hay múltiples fuentes disponibles.

---

## 3. Uso del CLI

El CLI se llama con `python -m idos.cli.main` o mediante el entry point `idos`
(si el directorio `Scripts` de Python está en PATH).

```bash
# Opción A: entry point (requiere PATH configurado)
idos <comando>

# Opción B: módulo Python (siempre funciona)
python -m idos.cli.main <comando>
```

En adelante se muestra con `idos`, pero si no lo encuentra usá la opción B.

### 3.1 Gestión de Compañías

```bash
idos company-add MELI             # Agrega compañía al knowledge base
idos company-show MELI            # Muestra datos de compañía
```

### 3.2 Gestión de Oportunidades

```bash
idos opp-create MELI              # Crea nueva oportunidad de inversión
idos opp-list                     # Lista oportunidades activas
idos opp-transition OPP-001 ENTRY_PENDING  # Avanza en el lifecycle
```

### 3.3 Monitoreo de Cartera

```bash
idos watchlist                    # Muestra watchlist activa
idos position-list                # Lista posiciones abiertas
idos dashboard                    # Resumen general del sistema
idos event-log                    # Log de eventos recientes
```

### 3.4 Workers

Los workers se ejecutan desde los workflows de GitHub Actions o vía script:

```bash
python -m idos.workers.data.scout_worker --help
python -c "from idos.workers.data.scout_worker import ScoutWorker; ..."
```

---

## 4. Workers y Automatización

### 4.1 Workers Disponibles

| Worker | Función | Frecuencia |
|--------|---------|------------|
| **ScoutWorker** | Screening 5 dimensiones sobre watchlist.md | Semanal (lunes) |
| **DataRefreshWorker** | Obtiene datos financieros de múltiples fuentes | Diario (pre-market) |
| **StockAnalysisWorker** | Scraper de stockanalysis.com | Bajo demanda |
| **YahooFinanceWorker** | Precios históricos y métricas vía yfinance | Bajo demanda |
| **FinvizWorker** | Snapshot complementario de finviz | Bajo demanda |
| **SECEdgarWorker** | Descarga de filings SEC | Trimestral |
| **DigestWorker** | Genera weekly digest en español | Viernes |
| **GitQueueWorker** | Commit automático de cambios a git | Cada 10 min |
| **LLMWorker** | Ejecuta prompts contra LLM configurado | Bajo demanda |

### 4.2 Scheduling Automático

```python
from idos.workers.scheduler.service import SchedulerService, ScheduledJob
from idos.workers.data.scout_worker import ScoutWorker

scheduler = SchedulerService()
scheduler.register(ScheduledJob(
    name="scout_semanal",
    worker=ScoutWorker({"universe_path": "idos-config/universe/watchlist.md"}),
    interval_type="monday",
    at_time="09:00",
))
scheduler.start()
```

### 4.3 Pipeline Completo

El sistema ejecuta este pipeline semanal automáticamente:

```
1. DataRefreshWorker → obtiene datos de mercado para todos los tickers
2. ScoutWorker → ejecuta screening 5 dimensiones
3. WatchlistManager → actualiza watchlist con scores
4. RankingSystem → rankea oportunidades
5. DigestWorker → genera reporte semanal
```

---

## 5. Monitoreo

### 5.1 Dashboard

```bash
idos dashboard
```

Muestra:
- Oportunidades activas
- Posiciones abiertas
- Peso total de cartera
- Scores de screening recientes
- Alertas de riesgo activas

### 5.2 Log de Eventos

```bash
idos event-log
```

Muestra todos los eventos del sistema ordenados por timestamp:
- Creación de oportunidades
- Transiciones de estado
- Resultados de screening
- Alertas de riesgo
- Decisiones de entry/exit

### 5.3 Estado de Workers

```bash
idos worker status
```

Muestra por cada worker: última ejecución, cantidad de runs, fallos,
y si hay resultado disponible.

### 5.4 Trazas de Telemetría

Cada ejecución de worker queda registrada en SQLite con:
- ID de ejecución
- Worker que ejecutó
- Paso dentro del worker
- Tokens usados (si aplica LLM)
- Latencia
- Estado (éxito/fallo)
- Detalle del error si falló

Para ver: `idos.db` → tabla `telemetry_traces`.

### 5.5 Logs de Error

Los errores se registran en:
1. **SQLite**: `idos.db` → `telemetry_traces` (status = "failed")
2. **WorkerResult**: cada worker devuelve `WorkerResult` con `.error` y `.status`
3. **EventBus**: eventos de error publicados como `worker:failed`

Para inspeccionar errores:

```python
from idos.data.sqlite import SQLiteStore
store = SQLiteStore()
traces = store.get_traces(worker="scout_worker", status="failed")
for t in traces:
    print(t["detail"])
```

---

## 6. Notificaciones

### 6.1 Telegram

Para activar notificaciones vía Telegram necesitas dos cosas:

**1. Bot Token**: Habla con [@BotFather](https://t.me/BotFather) en Telegram:
   - Envía `/newbot` y sigue las instrucciones
   - Te dará un token como `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`
   - Usa `/setprivacy` y desactívalo para que el bot lea mensajes

**2. Chat ID**: Tu ID personal o de grupo:
   - Inicia un chat con tu bot nuevo y envía `/start`
   - Visita: `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
   - Busca `"chat":{"id":-123456789}` en la respuesta JSON

Configura como variables de entorno:

```bash
set IDOS_TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
set IDOS_TELEGRAM_CHAT_ID=-123456789
```

Notificaciones por prioridad:
- **🔴 HIGH**: Alertas de riesgo, oportunidades detectadas → Telegram inmediato
- **🟡 MEDIUM**: Cambios de estado, convicción update → Email digest diario
- **🟢 LOW**: Weekly digest → Dashboard

### 6.2 Digest Semanal

Generado automáticamente los viernes por `DigestWorker`. Incluye:
- Oportunidades identificadas en la semana
- Alertas de riesgo activas
- Posiciones activas y su estado
- Estado de oportunidades en seguimiento

### 6.3 Alertas de Riesgo

El `RiskEngine` evalúa automáticamente:
- Drawdown > 15%
- Volatilidad > 30%
- D/E > 2.0
- Concentración > 3% por posición
- Stop loss alcanzado

---

## 7. Lifecycle de Oportunidades

El sistema gestiona 14 estados secuenciales:

```
DISCOVERED → SCREENED → WATCHLIST → UNDER_RESEARCH → UNDER_DEEP_DD →
APPROVED → ENTRY_PENDING → ACCUMULATING → FULL_POSITION → MONITORING →
REDUCING → EXITED → POST_MORTEM → ARCHIVED
```

Transiciones permitidas desde cada estado:

```bash
idos opp transicionar OPP-001 WATCHLIST    # Avanzar
idos opp transicionar OPP-001 ARCHIVED     # Archivar
```

---

## 8. Arquitectura de Datos

```
stockanalysis.com ─┐
yfinance ──────────┤──► DataCache (SQLite con TTL)
finviz.com ────────┤    │
SEC EDGAR ────────┘    │
                       ▼
               DataValidator (validación cruzada)
                       │
                       ├──► ScoutEngine (screening)
                       ├──► EntryEngine (price zone + Wyckoff)
                       ├──► RiskEngine (alertas)
                       └──► DecisionOrchestrator (convicción)
```

### 8.1 Caché

Todas las respuestas se cachean en SQLite con TTL configurable. Si un dato
está en caché y no ha expirado, se devuelve sin hacer llamada externa.

### 8.2 Validación Cruzada

Cuando hay múltiples fuentes disponibles, el `DataValidator`:
1. Calcula el promedio de valores numéricos
2. Detecta discrepancias > 20% entre fuentes
3. Reporta conflictos para revisión manual
4. Prioriza stockanalysis.com como fuente primaria

---

## 9. Prompts y LLM

### 9.1 Prompts de Screening (Scout)

| Prompt | Propósito |
|--------|-----------|
| `scout/size_liquidity.yml` | Tamaño y liquidez |
| `scout/momentum.yml` | Momentum con RSI y volumen relativo |
| `scout/value.yml` | Valoración con percentiles históricos |
| `scout/quality.yml` | Calidad con excess return y FCF conversion |
| `scout/synthesis.yml` | Síntesis con override triggers |

### 9.2 Prompts de Investigación (Research)

| Prompt | Propósito |
|--------|-----------|
| `research/ddd.yml` | Deep Due Diligence (7 dominios SDD) |
| `research/aoif.yml` | AOIF 8-step protocol |
| `research/hypothesis.yml` | Generación de hipótesis falsables |
| `research/wiki.yml` | Generación de wiki de conocimiento |

### 9.3 Validación de Prompts

Todos los prompts fueron revisados por un analista senior de Family Office.
Los puntos clave validados:
- Output en español con formato JSON
- Umbrales numéricos específicos (no vaguedades)
- Scoring ponderado explícito
- Detección de value traps, momentum traps, señales contradictorias
- Override triggers para override manual

---

## 10. Resolución de Problemas

### 10.1 Error: "No data from any source"

**Causa**: Las fuentes externas no respondieron o el ticker es inválido.
**Solución**: Verifica que el ticker exista en stockanalysis.com.
           Revisa `data_sources.yml` > `sources > enabled: true`.

### 10.2 Error: "No LLM API key configured"

**Causa**: Faltan variables de entorno.
**Solución**: Configura `IDOS_LLM_API_KEY` o ejecuta sin LLM (modo stub).

### 10.3 Worker falla repetidamente

**Causa**: Rate limiting o cambios en estructura HTML de fuentes.
**Solución**: Revisa `data_sources.yml` > `delay`. Aumenta el delay si es
           necesario. Reporta cambios de HTML como issue.

### 10.4 Tests

```bash
cd idos-core
python -m pytest -v        # 326+ tests
```

---

## 11. Comandos Rápidos

```bash
# Si `idos` no está en PATH, anteponer: python -m idos.cli.main <comando>
idos init                  # Inicializar sistema
idos dashboard             # Dashboard general
idos watchlist             # Ver watchlist
idos position-list         # Ver posiciones
idos event-log             # Ver eventos recientes
idos opp-list              # Listar oportunidades
```

---

*IDOS v0.1.0 — Family Office Investment Operating System*
*Genera reportes, notificaciones y alertas en español.*
