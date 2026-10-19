# IDOS — Plan de Testing Integral

## Objetivo

Validar el ciclo de vida completo de inversión (SDD-7 ILF) cubriendo
tareas automatizadas (scheduled) e intervenciones manuales (CLI).

---

## 1. Estrategia de Testing

| Nivel | Propósito | Herramientas | Tiempo estimado |
|-------|-----------|-------------|-----------------|
| **Unitario** | Validar lógica aislada de cada componente | pytest, asserts simples | ~2 min |
| **Integración** | Validar workers con datos simulados (sin LLM real) | pytest, fixtures en conftest.py | ~5 min |
| **Smoke** | Validar que CLI, prompts y schedule arranquen | pytest + subprocess / import | ~1 min |
| **E2E Lifecycle** | Pipeline completo DISCOVERED → ARCHIVED con mocks | pytest, in-memory DB, tmp_path | ~3 min |
| **Manual** | Validación visual de CLI commands por un humano | terminal | ~10 min |

### 1.1 Principios

- **Sin llamadas de red**: todas las fuentes externas (API, scraping) se mockean
- **Sin LLM real**: `LLMClient` se mockea para devolver JSON predecible
- **Aislamiento**: cada test usa `tmp_path` o `:memory:` para no contaminar datos reales
- **Determinismo**: datos de prueba fijos, sin aleatoriedad

---

## 2. Cobertura por Worker

### 2.1 Workers Existentes (326 tests ya pasan)

| Worker | Tests | Archivo | Estado |
|--------|-------|---------|--------|
| ScoutEngine | 3 | `test_discovery/test_scout.py` | ✅ |
| SupplyDemandIndicator (compuesto) | 5+ | `test_portfolio/test_wyckoff.py` | ✅ |
| EntryEngine | 3 | `test_portfolio/test_entry.py` | ✅ |
| ExitEngine | 6 | `test_portfolio/test_exit.py` | ✅ |
| RiskEngine | 7 | `test_portfolio/test_risk.py` | ✅ |
| PositionSizer | 4 | `test_portfolio/test_sizing.py` | ✅ |
| DDD | 2 | `test_research/test_ddd.py` | ✅ |
| AOIF | 2 | `test_research/test_aoif.py` | ✅ |
| Hypothesis | 4 | `test_research/test_hypothesis.py` | ✅ |
| SchedulerService | 7 | `test_workers/test_scheduler.py` | ✅ |
| ScoutWorker | 6 | `test_workers/test_scout_worker.py` | ✅ |
| DataRefreshWorker | 3 | `test_workers/test_refresh_worker.py` | ✅ |
| DigestWorker | 5 | `test_workers/test_digest_worker.py` | ✅ |
| LLMClient | 7 | `test_ai/test_llm.py` | ✅ |
| PromptRegistry | 1 | `test_ai/test_prompts.py` | ✅ |
| StateMachine | 5 | `test_state.py` | ✅ |
| BaseWorker | 4 | `test_workers/test_base_worker.py` | ✅ |
| DataCache | 7 | `test_workers/test_data_cache.py` | ✅ |
| DataValidator | 7 | `test_workers/test_data_validator.py` | ✅ |

### 2.2 Nuevos Workers (a implementar)

| Worker | Tests | Archivo | Prioridad |
|--------|-------|---------|-----------|
| ResearchWorker | 5 | `test_workers/test_research_worker.py` | 🔴 |
| DecisionBoardWorker | 4 | `test_workers/test_decision_board_worker.py` | 🔴 |
| EntryMonitorWorker | 5 | `test_workers/test_entry_monitor_worker.py` | 🔴 |
| PostMortemWorker | 5 | `test_workers/test_post_mortem_worker.py` | 🔴 |

### 2.3 Nuevos Tests Transversales

| Test | Archivo | Prioridad |
|------|---------|-----------|
| E2E Lifecycle completo | `test_lifecycle.py` | 🔴 |
| CLI commands smoke | `test_cli.py` | 🟡 |
| Prompt loading + validez | (ampliar `test_prompts.py`) | 🟡 |

---

## 3. Descripción de Tests por Worker

### 3.1 ResearchWorker (`test_research_worker.py`)

| Test | Descripción | Verifica |
|------|-------------|----------|
| `test_research_completes` | Worker ejecuta DDD+AOIF+Hypothesis con mock LLM | opp_id devuelto, score > 0, hypotheses_count > 0 |
| `test_research_transition` | Oportunidad pasa de WATCHLIST a UNDER_DEEP_DD | Estado en SQLite, transición registrada |
| `test_research_assessment_saved` | Assessment guardado en journal | Archivo YAML existe con campos obligatorios |
| `test_research_rejects_invalid_state` | Worker rechaza oportunidad en estado incorrecto | status = "skipped" |
| `test_research_saves_hypotheses` | Hipótesis generadas se persisten en case_file | case_file.yml contiene opp_id |

### 3.2 DecisionBoardWorker (`test_decision_board_worker.py`)

| Test | Descripción | Verifica |
|------|-------------|----------|
| `test_decision_board_approves` | DDD cumple todas las reglas → APPROVED | status = "APPROVED", decision_id presente |
| `test_decision_board_rejects` | DDD no cumple reglas → WATCHLIST | status = "WATCHLIST" |
| `test_decision_board_rules_evaluated` | Cada regla se evalúa individualmente | rules_detail tiene todas las entry_rules |
| `test_decision_board_decision_saved` | Decisión guardada en journal/decisions | Archivo YAML existe con tipo BOARD_* |

### 3.3 EntryMonitorWorker (`test_entry_monitor_worker.py`)

| Test | Descripción | Verifica |
|------|-------------|----------|
| `test_entry_monitor_accumulates` | Precio en zona + indicador técnico OK → ACCUMULATING | Estado transiciona, entry_executed = true |
| `test_entry_monitor_blocks` | Precio fuera de zona → no acumula | Estado sigue ENTRY_PENDING |
| `test_entry_monitor_price_zone` | Evalúa margen de seguridad correctamente | margin_of_safety_pct calculado |
| `test_entry_monitor_approves_to_pending` | APPROVED → ENTRY_PENDING automático | Transición registrada |
| `test_entry_monitor_skips_wrong_state` | Worker ignora oportunidades no listas | status = "skipped" |

### 3.4 PostMortemWorker (`test_post_mortem_worker.py`)

| Test | Descripción | Verifica |
|------|-------------|----------|
| `test_post_mortem_generates` | Worker genera post-mortem con mock LLM | pm_id devuelto, status = "completed" |
| `test_post_mortem_archives` | Oportunidad termina en ARCHIVED | Estado final ARCHIVED |
| `test_post_mortem_persists` | Post-mortem guardado en directorio | Archivo YAML existe en post_mortem/ |
| `test_post_mortem_injects_entry_snapshot` | El prompt incluye thesis/catalizadores/riesgos y wyckoff del snapshot de entrada | "TESIS AL MOMENTO DE ENTRADA" + fase score en prompt |
| `test_post_mortem_skips_wrong_state` | Worker ignora si no está EXITED | status = "skipped" |

### 3.4b EntrySnapshot (`test_portfolio/test_entry_snapshot.py`)

| Test | Descripción | Verifica |
|------|-------------|----------|
| `test_captures_all_domains` | Snapshot congela thesis, assessments, wyckoff de entrada, catalizadores, riesgos, dominios y fundamentales | Campos presentes con valores del momento de entrada |
| `test_save_load_roundtrip` | Snapshot se persiste y recarga desde `entry_snapshot.yml` | Round-trip idéntico |

### 3.5 E2E Lifecycle (`test_lifecycle.py`)

| Test | Descripción | Verifica |
|------|-------------|----------|
| `test_full_lifecycle` | Pipeline completo DISCOVERED → ARCHIVED | 13 transiciones, estado final ARCHIVED |
| `test_lifecycle_with_decision_rejection` | DDD pobre → WATCHLIST (no ARCHIVED) | Rechazado vuelve a WATCHLIST |

Pipeline del E2E:
```
1. Crear compañía + oportunidad (DISCOVERED)
2. ScoutWorker → SCREENED → WATCHLIST
3. ResearchWorker → UNDER_DEEP_DD
4. DecisionBoardWorker → APPROVED
5. EntryMonitorWorker → ENTRY_PENDING → ACCUMULATING
6. Transicionar manual → FULL_POSITION → MONITORING
7. ExitEngine → EXITED
8. PostMortemWorker → POST_MORTEM → ARCHIVED
```

---

## 4. Datos de Prueba

### 4.1 Ticker Simulado

```python
TEST_TICKER = "TEST"
TEST_OPP_ID = "OPP-2026-TEST-001"
```

### 4.2 Mock LLM Outputs

Cada worker recibe un `LLMClient` mockeado que devuelve JSON predecible.
Definido en `conftest.py` como fixture `mock_llm_client`.

### 4.3 Precios Simulados para el Indicador Compuesto

```python
MOCK_PRICE_DATA = [
    {"close": 100.0 + i * 0.5 + (5 if i > 40 else 0), "volume": 1000000 + (i * 10000)}
    for i in range(252)  # ~1 año de datos
]
```

---

## 5. Ejecución

### 5.1 Todos los tests

```bash
cd idos-core
pytest -v
```

### 5.2 Tests por categoría

```bash
pytest -v tests/test_workers/          # Workers (nuevos + existentes)
pytest -v tests/test_portfolio/        # Portfolio (entry, exit, indicador)
pytest -v tests/test_discovery/        # Scout
pytest -v tests/test_research/         # DDD, AOIF, Hypothesis
pytest -v tests/test_lifecycle.py      # E2E lifecycle
pytest -v tests/test_cli.py            # CLI smoke
```

### 5.3 Tests marcados

```bash
pytest -v -m "e2e"        # Solo E2E lifecycle
pytest -v -m "smoke"      # Solo smoke tests
pytest -v -m "unit"       # Solo unitarios
pytest -v -m "slow"       # Tests lentos (con LLM real opcional)
```

### 5.4 Tests manuales (requieren intervención humana)

```bash
idos opp-research MELI     # Ver salida en consola
idos entry-evaluate MELI   # Ver señal de entrada
idos position-exit MELI --reason manual  # Ver post-mortem
```

---

## 6. Criterios de Aceptación

1. ✅ 326+ tests unitarios existentes siguen pasando
2. ✅ 18+ tests nuevos de workers creados
3. ✅ 1 test E2E de lifecycle completo
4. ✅ 5+ tests de smoke para CLI
5. ✅ Sin regresiones en cobertura existente
6. ✅ Todos los tests se ejecutan sin red ni LLM real

---

## 7. Riesgos y Mitigaciones

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| LLM outputs no-deterministas | Tests frágiles | Mock LLMClient con respuestas fijas |
| Archivos YAML temporales no limpiados | Contaminación entre tests | Usar tmp_path de pytest |
| Estado global (EventBus singleton) | Tests acoplados | Reiniciar bus en setUp |
| SQLite en disco | Datos residuales | Usar ":memory:" o tmp_path |

## 8. Validación E2E posterior al deployment

Este plan se ejecuta después de que el gestor revise y apruebe la rama y el
despliegue de GitHub Pages. La validación remota en rama no equivale a
deployment. No habilitar datos reales de cartera ni acciones de trading durante
estas pruebas.

### 8.1 Dashboard público hasta Buy List

1. Verificar que el workflow de Pages se ejecutó con el commit aprobado y que la
   URL pública carga sin errores de red ni errores JavaScript.
2. Revisar visualmente Discovery, Research, Assessment, Decision y Buy List;
   confirmar que cada registro muestra estrategia, ticker, etapa, fecha de
   datos, tesis disponible, asimetría si está documentada, riesgos/catalizadores,
   fuentes y estado de revisión humana.
3. Confirmar que las pruebas parciales o los datos incompletos están
   identificados como tales y que no aparecen como señal global de estrategia.
4. Comprobar en `site/data.json`, HTML, archivos de caché publicados y artifacts
   que no se expongan `positions`, `ledger`, `portfolio`, `entry_signals`,
   `exit_signals`, `rebalance_result`, resultados de simulación, identificadores
   de cuentas, saldos ni obligaciones. El límite visible y publicable termina
   en Buy List.
5. Guardar commit, URL, fecha, resultado de cada comprobación y captura de la
   vista revisada por el gestor.

### 8.2 Multi estrategia y gates comunes

1. Confirmar que todas las estrategias activas consumen el registro común
   `idos-config/universe/operable.yml` y que el gate común aplica capitalización
   mínima USD 2.000 millones sólo a acciones; ETFs no requieren tamaño ni AUM.
   Ambos requieren volumen promedio mínimo USD 100.000 en USD, con
   base `UNDERLYING_USD_PROXY` cuando corresponda.
2. Comprobar ventana de 20 ruedas, cobertura mínima de 80%, FX hasta 4 días
   calendario, lado vendedor y referencia MEP/CCL explícita por activo ARS.
3. Verificar que la selección, filtros propios y estado de cada estrategia se
   mantienen aislados y que los reportes identifican `bounded` vs. universo
   completo. MULTIBAGGERS permanece deshabilitada hasta cerrar el gap de score.
4. Para acciones sin market cap verificable, confirmar `blocked` y ausencia de
   oportunidad/dispatch habilitante. Para ETFs sin AUM ni market cap, confirmar
   que la liquidez válida permite evaluar su señal mensual; volumen bajo o
   sin procedencia bloquea. Una reclasificación ETF → acción exige market cap.

### 8.3 Research y calidad de decisión

1. Seleccionar un candidato operable que pase cobertura, frescura, procedencia
   por campo y hard flags; registrar proveedor/modelo, costo esperado y alcance
   antes de una llamada LLM real.
2. Ejecutar Monthly Universe → DDD Research → Assessment/Decision → Buy List;
   inspeccionar conteos y artefactos, no solo el estado verde de Actions.
3. Confirmar que la tesis incluye evidencia fechada, hipótesis, asimetría,
   catalizadores, riesgos, invalidación y fuentes; los faltantes deben bloquear
   o requerir revisión humana, no completar datos inventados.
4. No llamar recomendación de compra/venta a un resultado `WAIT`,
   `PENDING_HUMAN_REVIEW`, `REVIEW_ALLOCATION` ni a un test parcial.
5. Conciliar el contador total de candidatos seleccionados con los procesados,
   errores y omitidos; comprobar que Assessment y digest conservan el total
   reportado por Research y que una ejecución con un caso no informa cero.

### 8.4 Frontera privada de portfolio y Risk Audit

1. Antes de conectar Google Sheets, validar con hoja ficticia privada y
   credenciales de solo lectura; revisar permisos anónimos denegados, schema,
   FX/fechas, identificadores duplicados y conciliación con extractos.
2. Confirmar que snapshots, resultados completos de Risk Audit, alertas de
   portfolio y learning quedan en almacenamiento/proceso privado y ausentes de
   Pages, commits públicos, artifacts y logs.
3. Validar exposiciones y alertas con fixtures de dos cuentas, monedas,
   estrategias y clusters; confirmar el bloqueo cuando falten FX o conciliación.
4. El gestor valida coherencia de posiciones, riesgo total y alertas antes de
   usar datos reales. No habilitar órdenes automáticas.

### 8.5 Criterio de cierre

Cerrar deployment solo cuando los checks de 8.1–8.4 tengan evidencia adjunta,
el gestor haya revisado el dashboard y el portfolio privado esté validado por
separado. Si falta candidato que pase los gates, especificación aprobada,
credenciales privadas o conciliación, registrar el bloqueo y mantener el
comportamiento fail-closed.
