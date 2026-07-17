# PLAN DE IMPLEMENTACIÓN — IDOS PRODUCTION READY

## Diagnóstico General

El sistema tiene ~80% de la lógica de dominio implementada pero ~90% de la infraestructura,
integraciones externas y automatización faltante. No puede ejecutar tareas agendadas, no
obtiene datos financieros reales, no envía notificaciones, y no está conectado a LLMs.

---

## FASE 1: INFRAESTRUCTURA CRÍTICA (Prioridad Máxima)

### 1.1 Sistema de Obtención de Datos Financieros (Data Workers)
**SDDs: 11, 12, 14, 16, 17**

Evaluación de alternativas para obtención de datos:

| Alternativa | Ventajas | Desventajas | Costo |
|------------|----------|-------------|-------|
| **stockanalysis.com scraping** | Datos completos (50+ métricas), free, sin API key | Requiere HTML parsing, puede romperse, ToS | Gratis |
| **finviz.com scraping** | Buena UI, datos rápidos | Similar a stockanalysis, rate limiting | Gratis |
| **yfinance (Yahoo Finance)** | Librería Python madura, datos históricos, fácil | Precios delayed ~15min, precisión variable | Gratis |
| **FinancialModelingPrep API** | JSON estructurado, financial statements históricos | $49/mo por nivel Starter | $49/mo |
| **Polygon.io** | Tiempo real, opciones, forex | $199/mo por datos fundamentales | $199/mo |
| **SEC EDGAR (sec-api.io)** | Datos oficiales, 10-K/10-Q | Solo filings, sin ratios, parsing complejo | $0-$29/mo |

✅ **Recomendación: Estrategía Híbrida Multicapa**
- **Capa 1 (Primaria): stockanalysis.com** — scraping con BeautifulSoup para 50+ métricas financieras clave
- **Capa 2 (Fallback + Histórico): yfinance** — para precios históricos, ratios, y financial statements
- **Capa 3 (Oficial): SEC EDGAR API** — para 10-K/10-Q oficiales cuando se requiera precisión absoluta
- **Caché local:** SQLite con TTL configurable para evitar requests duplicados

**Archivos a crear:**
- `idos/workers/data/stockanalysis.py` — Scraper de stockanalysis.com
- `idos/workers/data/finviz.py` — Scraper de finviz para screening
- `idos/workers/data/yahoo.py` — Cliente yfinance
- `idos/workers/data/sec_edgar.py` — Descarga de filings SEC
- `idos/workers/data/cache.py` — Sistema de caché con TTL
- `idos/workers/data/validator.py` — Validación cruzada entre fuentes
- `idos-config/data_sources.yml` — Configuración de fuentes, TTLs, URLs

### 1.2 Integración con LLM (AI Workers)
**SDDs: 2, 5, 10, 12, 15, 16**

- Conectar `LLMClient` con proveedores reales (Gemini 2.5 Pro primario, GPT-4o secundario)
- Implementar `PromptRenderer` que inyecte datos reales en los prompts
- Implementar `StructuredOutputParser` para extraer JSON de respuestas LLM
- Integrar `PromptRegistry` con los workers

### 1.3 Worker Execution Framework + Scheduling
**SDDs: 7, 9, 12, 14, 16**

- Implementar `BaseWorker` class con ciclo de vida (init → execute → checkpoint → complete)
- Usar `schedule` (librería Python liviana) para tareas periódicas
- Tabla de scheduling:

| Tarea | Frecuencia | Worker |
|-------|-----------|--------|
| Scout Screening | Semanal (lunes) | ScoutWorker |
| Data Refresh | Diario (pre-market) | DataWorker |
| Risk Engine | Diario (cierre) | RiskWorker |
| Conviction Review | Mensual | ConvictionWorker |
| Portfolio Rebalance | Mensual | RebalanceWorker |
| Git Commit Queue | Cada 10 min | GitQueueWorker |
| DIGEST Semanal | Viernes | DigestWorker |
| 10-Q/10-K Processing | Trimestral | FilingWorker |

---

## FASE 2: CONECTIVIDAD CON EL MUNDO REAL

### 2.1 Notificaciones (Telegram + Email)
**SDD: 10**

- Integración con Telegram Bot (`python-telegram-bot` v21+)
- Integración con Email (SMTP)
- Sistema de ruteo por prioridad:
  - 🔴 HIGH → Telegram inmediato
  - 🟡 MEDIUM → Email digest diario
  - 🟢 LOW → Dashboard / weekly digest
- Weekly Digest auto-generado en Markdown

### 2.2 Prompts Validados y Mejorados (post-revisión FO)
Incorporar todas las correcciones del analista sénior de Family Office (ver sección de prompts más abajo)

---

## FASE 3: UX COMPLETA EN ESPAÑOL

### 3.1 Reportes en Español
Todos los reportes del sistema deben generarse en español:

- `ReportGenerator.reportes.py` — Generador de reportes en español
- `DashboardAPI` — Dashboard con textos en español
- `NotificationTemplateEngine` — Notificaciones en español
- Weekly Digest en español
- DD Report en español
- Post Mortem en español (nuevo)

### 3.2 CLI con flags de idioma
EL CLI actual está en inglés → migrar a español con flag `--lang=en` opcional

---

## FASE 4: TICKER UNIVERSE DESDE .MD

### 4.1 Archivo de Universo Configurable
Crear `idos-config/universe/watchlist.md` con formato:

```markdown
# Universo Invertible - Family Office IDOS
## Seguimiento Activo
| Ticker | Nombre | Sector | Market Cap | Motivo | Prioridad |
|--------|--------|--------|------------|--------|-----------|
| MELI | MercadoLibre | Technology | $85B | Crecimiento LatAm | ALTA |
| V | Visa | Financials | $560B | Calidad defensiva | ALTA |
| GOOGL | Alphabet | Technology | $2T | Moat digital | ALTA |

## Watchlist Secundaria
| Ticker | Nombre | Catalizador | Timeline |
|--------|--------|-------------|----------|
| XYZ | Empresa X | Nuevo CEO | Q3 2026 |
```

El `ScoutWorker` lee este archivo como punto de partida del screening.

---

## PLAN DE EJECUCIÓN POR SPRINTS

### SPRINT 1: Data Foundation (3-4 días)
- [ ] Implementar `DataWorker` + scraper stockanalysis.com
- [ ] Implementar `DataCache` con SQLite
- [ ] Implementar `FinancialDataValidator` (cruzado entre fuentes)
- [ ] Configurar `data_sources.yml`
- [ ] Tests de integración con datos reales

### SPRINT 2: Prompt Enhancement + LLM Integration (2-3 días)
- [ ] Actualizar los 9 prompts con correcciones del analista FO
- [ ] Conectar `LLMClient` con Gemini y OpenAI
- [ ] Implementar `StructuredOutputParser`
- [ ] Implementar `AIPipeline` que integre prompts + datos + LLM
- [ ] E2E test con datos reales de MELI

### SPRINT 3: Scheduling + Workers (2 días)
- [ ] Implementar `BaseWorker` + `SchedulerService`
- [ ] Implementar `ScoutWorker` (lee universe.md, ejecuta scout con datos reales)
- [ ] Implementar `DataRefreshWorker`
- [ ] Implementar `GitQueueWorker`
- [ ] Implementar `DigestWorker`

### SPRINT 4: Notificaciones (1-2 días)
- [ ] Implementar `TelegramNotifier`
- [ ] Implementar `EmailNotifier`
- [ ] Sistema de ruteo de alertas por prioridad
- [ ] Weekly Digest en español

### SPRINT 5: Español + Reportes (1 día)
- [ ] Traducir CLI a español
- [ ] Generar todos los reportes en español
- [ ] Dashboard en español
- [ ] Notificaciones en español

---

## PROMPTS: CORRECCIONES PRIORITARIAS POST-REVISION FO

Basado en la revisión del analista sénior de Family Office:

### size_liquidity.yml — ALTA PRIORIDAD
- [ ] Añadir `min_dollar_volume: $5M` como threshold configurable
- [ ] Añadir `days_to_liquidate_2pct` al output
- [ ] Añadir `avg_spread_bps` al output
- [ ] Scoring: 70% liquidez, 30% tamaño
- [ ] Reemplazar "Mid-Cap or above preferred" con hard pass/fail configurable
- [ ] Añadir `free_float_pct` y `adv_usd` al input

### momentum.yml — ALTA PRIORIDAD
- [ ] Añadir `rsi_14d`, `volume_ratio_50d`, `relative_strength_vs_sector` al input
- [ ] Score: 40% tendencia, 30% consistencia, 20% posición en rango, 10% volumen
- [ ] `near_high` → `pct_from_52w_high` numérico
- [ ] Añadir `momentum_quality_score` separado

### value.yml — ALTA PRIORIDAD
- [ ] Input: `sector_avg_ev_ebitda`, `sector_avg_pb`, `pe_percentile_5y`, `pb_percentile_5y`
- [ ] Añadir `peg_ratio`, `buyback_yield`, `fcf_conversion_pct`
- [ ] `value_trap_risk = true` si (PER < 10 AND revenue_growth_3y < 0 AND D/E > 2)

### quality.yml — MEDIA PRIORIDAD
- [ ] Añadir `interest_coverage_ratio`, `fcf_conversion_pct`, `excess_return_roic_wacc`
- [ ] `earnings_stability` → `earnings_stability_score` 0-100 basado en desviación estándar
- [ ] Scoring: 30% rentabilidad, 25% salud financiera, 25% crecimiento, 20% eficiencia
- [ ] Añadir `customer_concentration_risk`, `revenue_visibility_pct`

### synthesis.yml — MEDIA PRIORIDAD
- [ ] Añadir `override_triggers` como condiciones explícitas
- [ ] Añadir `portfolio_fit_score` (0-100)
- [ ] `composite_score = weighted_sum * min_dimension_penalty`
- [ ] Añadir `position_size_pct_of_aum: [min, max]`

### ddd.yml — ALTA PRIORIDAD
- [ ] Reestructurar a 7 dominios SDD explícitos
- [ ] Añadir sección ESG + Supply Chain
- [ ] Añadir `excess_return_roic_wacc`, `fcf_adjusted`, `debt_maturity_profile`
- [ ] `evidence_quality: { verified_facts, llm_inferences, open_questions }`

### hypotheses.yml — BAJA PRIORIDAD
- [ ] Añadir `priority: critical|important|informational`
- [ ] Añadir `magnitude: { metric, expected_value, unit }`
- [ ] Añadir `depends_on: []`

---

## MÉTRICAS DE ÉXITO

1. ✅ Sistema obtiene datos financieros reales de stockanalysis.com + validación cruzada
2. ✅ Scout ejecuta screening sobre universe.md con datos reales
3. ✅ DecisionEngine produce conviction con datos financieros reales
4. ✅ DDD + AOIF ejecutan análisis vía LLM con prompts validados
5. ✅ Notificaciones llegan a Telegram/Email
6. ✅ Scheduling ejecuta tareas diarias/semanales/mensuales automáticamente
7. ✅ Todo reporte y UI en español
8. ✅ Tests existentes siguen pasando (213+ nuevos)
9. ✅ E2E test con MELI real desde universe.md hasta entry signal

---

## RIESGOS IDENTIFICADOS

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|-------------|---------|------------|
| stockanalysis.com cambia HTML | Media | Alto | Tests de parsing periódicos + fallback yfinance |
| API keys LLM expuestas | Baja | Crítico | Variables de entorno + .env + .gitignore |
| Rate limiting en scraping | Alta | Medio | Caché + delays configurables + rotación de user-agents |
| Precisión de datos financieros | Media | Alto | Validación cruzada entre 2+ fuentes |
| Costos de API LLM en producción | Alta | Medio | Límites de tokens por ejecución + modelo más barato para tareas simples |
