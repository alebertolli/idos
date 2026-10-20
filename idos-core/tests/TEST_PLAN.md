# IDOS — Plan de Testing Integral

> **Vigencia:** las cifras, estados y ejemplos de los apartados 2–6 son el
> plan inicial y no describen la cobertura actual. La auditoría vigente, la
> matriz completa de funcionalidades y los pendientes están en
> `SDD/26.AUDITORIA-FUNCIONAL-COBERTURA.md` y en el apartado §14 de este plan.

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
| `test_post_mortem_generates` | Worker genera resumen determinista sin usar `llm_service` | pm_id, versión de análisis y status = "completed"; proveedor no invocado |
| `test_post_mortem_archives` | Oportunidad termina en ARCHIVED | Estado final ARCHIVED |
| `test_post_mortem_persists` | Post-mortem guardado en directorio | Archivo YAML existe en post_mortem/ |
| `test_post_mortem_injects_entry_snapshot` | Informe conserva los datos relevantes del snapshot de entrada | Tesis, precio, catalizadores, riesgos y Wyckoff en `analysis.evidence.entry` |
| `test_post_mortem_reports_prediction_evidence_without_strategy_recommendations` | Predicciones y falsaciones se resumen desde los registros | Conteo cumplido/fallido, vacíos explícitos y sin recomendación de estrategia por caso único |
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
idos position-exit MELI --reason manual --reviewer <gestor> --justification "<motivo y evidencia>"  # registra decisión local; no envía orden
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
6. En la Buy List comprobar que una tesis vigente aparece como `Vigente`, y que
   tesis vencidas, invalidadas, no vinculadas o sin agenda verificable quedan
   marcadas como revisión requerida; ninguna debe mostrar `Listo` ni presentarse
   como recomendación actual.

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
6. En reportes sistemáticos, verificar rango del perfil, fecha/señal, ausencia
   de probabilidades y volatilidad inventadas, hipótesis con texto e invalidación
   configurada, valor intrínseco `No aplica` y propuesta pendiente visible.
   Reportes anteriores sin versión de método vigente requieren regeneración.
7. Verificar Monthly → Research → Assessment con snapshots: selección positiva
   consistente permite WAIT; resultado posterior negativo/incompleto bloquea sin
   reutilizar una selección anterior; una prueba bounded de otro ticker no
   invalida el caso; cambio de señal requiere re-research y reporte coincidente.
   Confirmar mismo selector en preview/ejecución, no-op sin llamadas a proveedores
   cuando no quedan candidatos y ausencia de consultas corporativas/portfolio
   en el Assessment sistemático.

### 8.4 Frontera privada de portfolio y Risk Audit

El motor Risk Audit v2.1 tiene cobertura local de fixture sintético en
`tests/test_portfolio/test_risk_audit_v21.py`: duration/convexity, PD×LGD,
spread duration, perfiles con versión incompatible, datos/convexidad faltantes,
corte de evidencia, cinco límites
de sizing, presupuesto y permanencia de `allocation_authorized: false`. Esto
demuestra el cálculo con contrato explícito; no demuestra una auditoría de la
cartera familiar ni cobertura completa. Antes de declarar REQ-20-05 completo,
confirmar el caso CLI en CI y agregar fixtures de liquidez/clasificación,
monedas económicas, correlaciones y escenarios Argentina/combined desde la
fuente privada validada.

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


### §9 COMPOUNDER Scout configurable (antes de cada release)

1. Verificar que el perfil habilitado declare versión, tres predicados positivos y métricas únicas; política inválida debe fallar cerrada.
2. Probar valor positivo, cero, negativo, ausente, booleano, no numérico, infinito y conflicto de signos entre fuentes para cada criterio.
3. Probar gate de mercado para equity/ETF, normalización/procedencia incompleta y que AUM nunca sea requerido.
4. Ejecutar una corrida manual acotada en rama de prueba; revisar candidatos, métricas, proveedor/unidad/corte disponible, estados Scout, oportunidades y convicción cero.
5. Ejecutar Research/Assessment sobre una oportunidad elegible y confirmar que Research evalúa ROIC/moat y la decisión permanece sujeta a revisión humana.
6. Renderizar Discovery y verificar filtros/pendientes y separación pública/privada. No desplegar a Pages sin la autorización correspondiente.
7. Validar compatibilidad histórica, revisar `git diff --check`, suite focalizada y log remoto; registrar SHA/run y todo dato ausente.
8. Con una ejecución `candidate_tickers` acotada, verificar que `passed=true` llegue intacto al Monthly Evaluation, que una Opportunity `UNDER_RESEARCH` elegible no se degrade, que la Watchlist previa se conserve y fusione los resultados acotados, y que las oportunidades existentes registren `latest_discovery_evidence` sin sobrescribir su evidencia inicial ni su estado.
9. En DDD manual con `ticker` definido, confirmar que Research, Assessment y Monthly Re-Assessment procesen el alcance solicitado; el selector debe limitar thesis monitor, recalibración y competencia de capital, mientras la ejecución sin selector conserva el comportamiento global configurado.

10. Para `FULL_DDD`, validar de forma fail-closed 3–5 hipótesis con enunciado, razón, predicción cuantitativa y texto, fecha objetivo ISO futura, criterio de falsación y condición explícita de abandono; rechazar fechas vencidas o ejercicios fiscales pasados; comprobar round-trip YAML/SQLite de horizonte, texto/valor/unidad/fecha, dependencias y campos HMF. Un resultado inválido debe quedar en `hypothesis_validation_failed`, conservar el último DDD utilizable y detenerse antes de persistir hipótesis, Assessment o Decision.
11. Assessment debe mostrar cobertura de métricas core y procedencia (fuente y fecha de corte); `0` es un valor válido si está presente, pero una fecha/fuente ausente impide marcar calidad `good`. La lectura de decisiones persistidas debe usar `yaml.safe_load` sin tipos específicos de Python.
12. En dashboard público, mostrar DDD e hipótesis no aprobadas únicamente como provisionales, con fecha/fuente/cobertura; al registrar aprobación válida reflejar el estado atribuible. Verificar que `data.json` y artifact no contengan identidad del revisor ni posiciones, tenencias, liquidez o Risk Audit del portfolio privado.


### §13 Gate de procedencia financiera

1. Verificar que toda estrategia que evalúe métricas financieras requiera fuente y fecha de corte ISO válida y no futura; comprobar que una configuración de estrategia no pueda desactivar `RULE-010`. Las estrategias sistemáticas deben seguir exigiendo procedencia/fecha de su snapshot de señal en su gate específico.
2. Probar fecha ausente, formato inválido, fecha imposible y fecha futura: `RULE-010` debe fallar con motivo explícito y la decisión debe quedar bloqueada.
3. Probar cobertura parcial 4/5 con fuente/corte válidos (80%): la regla de procedencia pasa sin convertir el campo faltante en cero; cobertura pobre, fuente ausente o fecha inválida bloquean.
4. Revisar el Assessment y el Decision persistidos para confirmar el estado, el motivo de `RULE-010` y la procedencia; el dashboard debe exponer calidad parcial sin mostrar el caso como aprobado.
5. Persistir y mostrar `rules_details` de la evaluación, incluyendo `RULE-008` cuando corresponda. Mostrar cálculos basados en probabilidades de catalizadores como provisionales. Los agentes deben validar automáticamente el contrato Bear/Base/Bull, procedencia, precios, horizonte y moneda; un set válido y con B/R suficiente debe quedar listo para Decision Board sin aprobación previa. Escenarios inválidos, fuente sin evidencia de entrada, porcentaje que no suma 100%, precio no ordenado, URL no HTTPS, fecha inválida/futura o moneda distinta deben bloquear RULE-008; un registro histórico sin detalle debe indicarlo explícitamente.
6. Si `financial_period_end_timestamp` llega desde el proveedor, convertir segundos Unix a fecha UTC ISO y conservar la fuente del campo; rechazar milisegundos, valores fuera de rango y fechas futuras.
7. No debe existir un workflow humano `Scenario Review` previo al Board. `Decision Review` debe validar dentro de la única acción de Decision Board el escenario actual, el hash vinculado al Assessment, la identidad autenticada, la fecha, la justificación y la confirmación explícita de fuentes y fechas. Los cambios de escenarios, una fuente sin evidencia de entrada, identidad vacía, hash obsoleto o confirmación ausente deben impedir aprobar y no escribir resolución ni Buy List.
8. Assessment debe persistir `PENDING_HUMAN_REVIEW` y no crear `board_resolution.approved=true`, Buy List ni estado `APPROVED` a partir de una recomendación automática. El Board debe ser la primera interacción humana de la nueva Opportunity, exigir decisión, revisor y justificación, y no permitir aprobar propuestas con gates fallidos. Board Review debe clasificar cualquier recomendación sin resolución como pendiente/bloqueada, nunca `AUTO_APPROVED`.
9. `Decision Review` debe validar hash de Assessment vigente, `recommendation=APPROVE`, gates y escenarios automáticamente validados cuando RULE-008 aplique; la aprobación en la misma acción confirma fuentes y fechas. Una aprobación agrega únicamente a la Buy List pública con `approved_for_buylist=true`, mantiene la etapa de Research y no genera posiciones ni `ENTRY_PENDING`. Un hash viejo, gate fallido, segunda Opportunity del mismo ticker ya listada, precio/objetivo ausente o escenario distinto del evaluado bloquean la mutación. Al crear Research/Assessment nuevo, comprobar que se invalida la aprobación previa y se retira sólo su entrada de Buy List, con registro histórico conservado.
10. `BuyListRefreshWorker` debe conservar una Opportunity con `approved_for_buylist=true` aunque siga en Research/Assessment; `EntryMonitorWorker` no debe tratar ese flag como autorización de operación. Confirmar `positions/` y demás datos de portfolio vacíos en el build público.


### §14 Cobertura funcional actual — 2026-10-19

La suite actual contiene 97 archivos `test_*.py` bajo `idos-core/tests`. La
ejecución completa local terminó con **608 passed, 1 skipped y 2 warnings** en
263,53 s. Los warnings son `PytestUnknownMarkWarning` para las marcas `smoke` y
`e2e`; conviene registrarlas en `pyproject.toml`. El detalle funcional y las
áreas no cubiertas están trazados en `SDD/26.AUDITORIA-FUNCIONAL-COBERTURA.md`.

La ejecución Windows requirió instalar `exchange-calendars` (ya declarada) y
usar un plugin temporal para aislar `tmp_path`/`tempfile` por restricciones del
sandbox sobre `%TEMP%`; el plugin no forma parte del producto y se elimina
después. En CI Linux la suite debe ejecutarse sin ese adaptador.

La suite local no valida workflows GitHub, proveedores reales, Pages ni una
decisión atribuida al gestor. Monthly Universe, Daily Refresh y DDD acotados a
AAPL fueron revisados en §8.3.5–8.3.6 de
`SDD/25.PLAN-E2E-EN-RAMA-DE-PRUEBA.md`. La revisión de escenarios se consolidó
en la única acción `Decision Review`; queda pendiente ejecutarla con una
propuesta vigente y una decisión real del gestor en una rama de prueba.

`DecisionBoardWorker` se conserva como shim legado que siempre responde
`SKIPPED`; no ejecuta LLM, no persiste evaluaciones y no cambia estados. Los
tests de worker y lifecycle verifican la ausencia de efectos automáticos. La
simulación de entrada del lifecycle parte de una aprobación humana explícita
en el fixture.

#### Secuencia posterior al deployment

1. Confirmar ref/SHA autorizados; usar un activo de `operable.yml` y conservar
   los workflows habilitados.
2. Ejecutar Monthly Universe acotado; revisar conteos, gates globales y de
   estrategia, cobertura/procedencia y persistencia. Un no-op no valida etapas
   posteriores.
3. Ejecutar Research sólo si existe oportunidad elegible; inspeccionar tesis,
   hipótesis, fechas futuras, falsaciones, evidencia y errores estructurados.
4. Verificar que agentes completen automáticamente Assessment, RULE-008 y
   la preparación del paquete Bear/Base/Bull, con fuentes, horizonte, moneda,
   hash y bloqueos explícitos; no pedir confirmación previa al gestor.
5. Registrar una sola revisión humana en Decision Board, incluyendo decisión,
   confirmación de fuentes/fechas y justificación; verificar actor, hash, gates
   y Buy List sin generar posiciones.
6. Ejecutar Daily Refresh con simulación desactivada; revisar gate, calendario,
   Buy List, allowlist de artefactos y ausencia de datos privados.
7. Generar dashboard; inspeccionar JSON, HTML y vista renderizada para tesis,
   recomendación, asimetría, riesgos, antigüedad, alertas y Buy List. Confirmar
   `positions=[]`, `ledger=[]`, `portfolio={}`.
8. Probar alertas en fixtures: crear, actualizar, resolver y verificar
   deduplicación por tipo/fuente, ID estable y eliminación del snapshot cuando
   la condición se resuelve antes de habilitar avisos. La misma condición debe
   actualizar el mensaje sin crear otra alerta; distintas estrategias u
   oportunidades mantienen referencias independientes.
9. Validar Post-Mortem/learning en almacenamiento privado; sus propuestas no
   deben cambiar perfiles sin revisión, comparación y versionado aprobados.
10. Sólo tras configurar la fuente privada, probar importación con fixture
    ficticio, reconciliación y Risk Audit conforme a SDD/21.
11. En el fixture de portfolio, incluir balances de Cash y obligaciones PENDING
    en más de una moneda; exigir referencia de fuente por fila y FX fechado no
    posterior al corte. Verificar activos brutos, pasivos, valor neto,
    proporción sobre activos y que Risk Audit permanezca NOT_ASSESSED sin
    autorizar allocation. Omitir una lista debe declarar balance parcial.

### Cadencia de re-research de tesis

1. Validar el valor por defecto de 30 días y que cada perfil estratégico pueda
   configurar `parameters.thesis_review_interval_days` como entero positivo.
   Rechazar booleanos, cero, negativos y valores de otro tipo; los perfiles
   sistemáticos no reciben agenda de tesis fundamental.
2. Confirmar que Research guarda `next_thesis_review_at` en SQLite y journal;
   reiniciar el proceso y verificar que el dashboard y Monthly Reassessment
   conservan la misma fecha.
3. Con una fecha futura, ejecutar Monthly Reassessment y verificar que el
   ticker se cuenta como omitido y que ThesisMonitor/LLM no se invoca. Con una
   fecha vencida, comprobar una única revisión y que `last_thesis_assessment_at`
   y la siguiente fecha avanzan juntas por el intervalo configurado.
4. En el dashboard, comprobar fecha, cadencia y alerta de tesis vencida en
   oportunidades previas a cartera; verificar que perfiles sistemáticos no
   muestran una revisión fundamental aplicable.
5. Repetir tras cambiar el intervalo del perfil y comprobar el recálculo desde
   la última revisión. Probar persistencia en una base SQLite creada con el
   esquema anterior y confirmar la migración aditiva.
6. En una ejecución remota de prueba, seleccionar una sola oportunidad vencida
   y revisar selector, proveedor/modelo, costo esperado, artifacts y commits;
   comprobar que una oportunidad no vencida no consume Research ni cambia su
   tesis. Registrar ref, SHA, run y resultado sin convertir un no-op en E2E.
7. Para eventos materiales, comprobar que sólo perfiles habilitados y no
   sistemáticos procesan sus triggers configurados; cubrir estados elegibles,
   Buy List por `(ticker, opp_id)`, exclusión de posiciones y perfiles
   deshabilitados. Exigir ticker, tipo, fecha del evento, fuente, URL HTTPS,
   resumen y timestamp de observación; rechazar evidencia ausente, futura,
   duplicada o de otro ticker. El modo `preview_only` debe mostrar selección y
   evidencia normalizada, y omitir Research, Assessment, Monthly Re-Assessment,
   digest y commits. Ejecutar una sola prueba remota en la rama de test con un
   ticker, revisar el artifact y confirmar ausencia de llamadas IA y cambios
   Git. El calendario Yahoo/yfinance sólo sugiere la fecha de resultados; no
   demuestra que el reporte se haya publicado. Research debe contrastar el
   evento con fuentes primarias. Una prueba real de Research debe verificar
   que prompt, snapshot, journal y auditoría conservan la misma evidencia y que
   el Research previo no se reemplaza ante respuesta inválida.

### Asimetría Bear/Base/Bull y RULE-008

1. Aceptar exactamente un escenario BEAR, BASE y BULL con probabilidades que
   sumen 100%, precios ordenados, horizonte posterior a la fecha de análisis,
   moneda igual a la cotización y fuentes HTTPS fechadas.
2. Rechazar escenario duplicado/ausente, probabilidades inválidas, fuente
   posterior, fecha futura, moneda distinta y distribuciones sin retornos
   positivos y negativos.
3. Rechazar cada URL de escenario que no coincida con una URL provista en
   `research_input_snapshot.scenario_market_evidence`; si falta evidencia de
   entrada, no considerar verificables las fuentes. Mantener la aceptación de
   fuentes coincidentes y probar normalización sólo de host/ruta.
4. Verificar que el ratio usa retornos ponderados contra el precio actual y que
   RULE-008 se calcula automáticamente con el contrato y el hash vigente. Un
   set válido y sobre el umbral debe llegar a Decision Board sin interacción
   humana anterior; un cambio de precio objetivo, probabilidad, fuente o fecha
   entre Assessment y Board debe bloquear la aprobación.
5. Confirmar que el dashboard omite el conjunto de escenarios con fuentes no
   respaldadas por la evidencia de entrada, muestra el motivo de bloqueo y nunca
   autoriza compra. Los escenarios válidos se muestran como propuesta de agentes
   pendiente del Decision Board; la confirmación de fuentes y decisión del gestor
   se registran juntas en `Decision Review`. Los históricos sin detalle deben
   declararse como no persistidos.

### Alcance seguro de workflows manuales

1. Probar que la selección manual vacía, no operable y por encima del límite
   falla antes de ejecutar workers o solicitar datos a proveedores. Confirmar
   normalización, deduplicación y registro de los tickers elegidos.
2. Verificar en Monthly Universe, Daily Refresh y DDD el límite manual de
   cinco símbolos operables. Monthly preview y el DDD reusable deben recibir la
   misma lista, y ningún selector downstream puede ampliar el alcance. Los cron
   conservan su selección normal y no quedan sujetos a la guardia manual. La
   re-revisión explícita de Buy List sigue limitada a un ticker.
3. En GitHub Actions, ejecutar Monthly Universe con un candidato COMPOUNDER y
   un ETF MOMENTUM_ETF; revisar que cada estrategia procese sólo los activos
   compatibles y que el mismo conjunto llegue a preview y DDD. Confirmar que
   `candidate_count` no exceda la selección, no haya solicitudes para el resto
   de `operable.yml`, y auditar resultados, rate limits, artifacts y commits.
   Una corrida verde sin Research de ambas estrategias no satisface el E2E.
4. Inducir un fallo controlado de reporting sin proveedor IA: verificar que el
   error reporter incluya workflow, ref, run y extracto de logs, cree una issue,
   y no importe ni invoque AutoFixAgent. El análisis de reparación sólo ocurre
   después del comando explícito de autorización.
5. Para re-revisar Buy List, ejecutar DDD sólo en rama de prueba con
   `review_buylist=true`, `force=true` y un único ticker operable, aun cuando
   DDD admita hasta cinco tickers para la selección normal. Confirmar
   que se selecciona el `opp_id` exacto, se rechazan selección vacía/múltiple o
   posición paper, el nuevo Research invalida la aprobación anterior, retira
   sólo esa entrada y conserva `decisions/*.yml`. Probar que Decision Review
   rechaza el hash/proposal invalidado y que Pages no se dispara desde esa rama.
   Revisar costo/proveedor, logs, artefactos y commit antes de aceptar el run.
6. Para respuestas JSON de Research, confirmar que Gemini recibe
   `responseMimeType=application/json`, que el adaptador combina todas las
   partes textuales y que `finishReason != STOP` dispara fallback y detiene la
   respuesta incompleta. Una salida que falle parsing o contrato debe preservar
   el Research anterior y omitir Assessment; registrar proveedor/modelo, causa
   de parsing y ejecución remota acotada antes de considerar la corrección
   validada.
7. Sin conector de portfolio privado, confirmar que `PortfolioAssessmentEngine`
   devuelve `NOT_ASSESSED` con placeholder neutral y no interpreta ausencia de
   archivos o posiciones paper como capacidad/diversificación del fondo. En el
   dashboard público comprobar que esa falta de datos es visible y que no se
   publica ninguna posición, ledger ni valor patrimonial.
8. Para cambios deterministas de Assessment, ejecutar DDD manual en la rama de
   prueba con `assessment_only=true` y un solo ticker operable. Confirmar que el
   run exige Research y Assessment previos, reemplaza solo el Assessment del
   `(ticker, opp_id)` elegido, conserva los otros resultados, omite Research y
   Monthly Re-Assessment, y genera artifacts/commit sin invocar IA ni Pages.

### Enrutamiento de fuentes por tipo de activo

1. Para un ETF operable, verificar que `DataRefreshWorker` no invoque
   StockAnalysis, obtenga cotización e historial desde Yahoo, complete el gate
   de liquidez y no registre fallback de fuente por la ausencia de un proveedor
   de fundamentales que no aplica a ETF.
2. Para una acción, verificar que StockAnalysis siga siendo la fuente primaria;
   si falla y Yahoo devuelve datos, mantener el registro de degradación de baja
   severidad definido en SDD/16.
3. En una rama de prueba de GitHub Actions, ejecutar Daily Refresh con un solo
   ETF operable, simulación y dispatch de eventos desactivados. Confirmar el
   proveedor consultado, estado del gate, ausencia del aviso falso de fallback,
   ausencia de procesamiento portfolio, modo dry-run del reporter y commit sólo
   en la rama elegida. Run de referencia XLF: #39454652158; status success,
   Yahoo único proveedor, gate `complete`, `no_errors`, simulación y dispatch
   omitidos. Los archivos operativos del run se retiraron de la rama después
   de registrar la evidencia; el artefacto y los logs de Actions permanecen.

### 8.6 Registro E2E de producción — 2026-10-20

La corrida acotada se ejecutó en `main` después de integrar PR #139. Usó
`ALAB,XLF` desde `operable.yml`, mantuvo `run_portfolio_simulation=false` y
`dispatch_research_events=false`, y no consumió ni publicó datos privados.

| Control | Evidencia | Resultado |
| --- | --- | --- |
| Monthly Universe #73 | [Run 39450970531](https://github.com/alebertolli/idos/actions/runs/39450970531), commit `72e27ee` | COMPOUNDER evaluó y creó ALAB; MOMENTUM_ETF seleccionó XLF con señal 0,702. La lista de tickers acotada llegó al DDD reusable. |
| Research y Assessment | Job DDD del mismo run, commit `3d445ce` | ALAB: DDD 84, escenarios Bear/Base/Bull 30/50/20, horizonte 2028; convicción 68 y bloqueado por RULE-008. XLF: señal sistemática válida, `WAIT`, sin fundamentos/escenarios corporativos inventados. |
| Daily Refresh #160 | [Run 39451792827](https://github.com/alebertolli/idos/actions/runs/39451792827), commit `70d24cc` | Refrescó ALAB/XLF, benchmark y calendario; Buy List con 18 elementos. Simulación, riesgo y operaciones se omitieron. XLF usó fallback de yfinance y quedó issue [#140](https://github.com/alebertolli/idos/issues/140). |
| Pages #241 | [Run 39451924369](https://github.com/alebertolli/idos/actions/runs/39451924369) | Deploy del SHA `70d24cc`; artefacto `data.json`: 274 oportunidades, 18 Buy List, `positions=[]`, `ledger=[]`, `portfolio={}`. La ficha ALAB expone tesis y escenarios provisionales, fuentes y el gate humano; XLF queda identificado como sistemático. |

El job funcional pasó, pero la salida de Research muestra indisponibilidad
intermitente de proveedores para tareas auxiliares: timeout/503 de Gemini,
payload 413 de Groq para Wiki y 429/402 de OpenRouter. El DDD principal sí
respondió por Groq; la generación Wiki dejó una contradicción registrada. En
consecuencia, revisar las afirmaciones y fuentes de la ficha antes de usarla.
La captura móvil evidencia que la tabla de escenarios requiere desplazamiento
horizontal.

Quedan pendientes antes del cierre funcional: revisión atribuida del gestor
(RULE-008 y Decision Review), investigar/cerrar el fallback XLF, validar las
fuentes de hipótesis, revisar ergonomía móvil, ejecutar las pruebas privadas de
Risk Audit sólo con fixture/contrato privado, probar Learning/replay, y validar
MULTIBAGGERS cuando su adaptador/datos estén listos. La cartera real seguirá sin
ser evaluada hasta conectar y validar la hoja privada.

### 8.7 Reset operativo ejecutado — 2026-10-20

El reset se ejecutó mediante PR [#143](https://github.com/alebertolli/idos/pull/143). Se eliminaron 277 carpetas de oportunidades, tesis/assessments, eventos, decisiones, reportes, caches, simulaciones/ledger, claims y datos derivados. Buy List y Watch List quedaron vacías. Se conservaron código, configuración (`operable.yml` incluido), SDD, tests, fixtures, plantillas, schemas y archivos base `case_file.yml`.

Pages [#39458682671](https://github.com/alebertolli/idos/actions/runs/39458682671) compiló y desplegó el SHA integrado. El artefacto confirmó cero oportunidades, Buy List, Watch List, posiciones, ledger, alertas y elementos del discovery pool; `portfolio={}`. CI [#39457663035](https://github.com/alebertolli/idos/actions/runs/39457663035) pasó en Python 3.11 y 3.12.

Por solicitud expresa, `main` se reinició como raíz Git limpia: commit `45d5ec33669878808bda2d57b54444e017351945`, sin padres y con el mismo árbol de producción más las actualizaciones de SDD. Sólo se reescribió la referencia `main`; ramas y tags no se modificaron. CI de la raíz limpia [#39459588588](https://github.com/alebertolli/idos/actions/runs/39459588588) pasó en Python 3.11 y 3.12. Los 13 workflows registrados quedaron activos. El reset no equivale a aceptación funcional final: la revisión del gestor, Learning/replay, MULTIBAGGERS y Portfolio privado siguen pendientes.

GitHub Actions: `alebertolli/idos` es un repositorio público y estos workflows
usan runners GitHub-hosted estándar Linux; la documentación de GitHub indica que
esas ejecuciones en repositorios públicos son gratuitas e ilimitadas. Los
proveedores LLM mantienen cuotas/rate limits independientes; los runners más
grandes y el almacenamiento de artefactos tienen reglas aparte. Ver
[GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
y [runner selection](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job).

### 8.8 Presentación móvil de asimetría — 2026-10-20

La ficha conserva la tabla Bear/Base/Bull en escritorio y muestra tarjetas
apiladas en pantallas de hasta 720 px. Cada tarjeta presenta escenario,
probabilidad, precio objetivo, racionales, supuestos y enlaces con fecha de
fuente, sin depender del desplazamiento horizontal de la tabla.

Validación en la rama: suite `test_site/test_builder.py` (39 passed),
`node --check` del JavaScript generado y `git diff --check` pasaron. CI
[#39461594753](https://github.com/alebertolli/idos/actions/runs/39461594753)
pasó en Python 3.11 y 3.12. Pages preview
[#39461643195](https://github.com/alebertolli/idos/actions/runs/39461643195)
compiló y subió el artefacto; deploy se omitió por ser una rama de prueba. El
artefacto confirma el CSS/JS responsive y cero oportunidades. Después del
deploy a producción, comprobar el render en un dispositivo móvil.

### 8.9 E2E multi estrategia y aclaración sistemática del dashboard — 2026-10-20

En `codex/e2e-runtime-validation-20261020`, Monthly
[#39463375893](https://github.com/alebertolli/idos/actions/runs/39463375893)
procesó ALAB/COMPOUNDER y XLF/MOMENTUM_ETF desde `operable.yml`; DDD
[#39463619515](https://github.com/alebertolli/idos/actions/runs/39463619515)
completó ambas investigaciones y evaluaciones; Daily
[#39464009200](https://github.com/alebertolli/idos/actions/runs/39464009200)
refrescó ambos tickers con portfolio, simulación y eventos deshabilitados;
Pages [#39464136795](https://github.com/alebertolli/idos/actions/runs/39464136795)
compiló preview sin publicar la rama.

El dataset incluyó 2 oportunidades, 0 decisiones, Buy List vacía, Watch List
con ALAB y ninguna posición, ledger o cartera. ALAB quedó bloqueado por
RULE-008 tras recibir URL de escenarios no incluidas en evidencia; XLF quedó
`WAIT` sin escenarios fundamentales. El dashboard ahora explica que Bear/Base/Bull
no aplican a estrategias sistemáticas. Regresión cubierta por
`test_public_site_keeps_deterministic_systematic_report_separate_from_fundamental_review`.
Validación local: `pytest idos-core/tests/test_site/test_builder.py -q`
resultó en 39 passed; `node --check` y `git diff --check` pasaron. CI
[#39465227681](https://github.com/alebertolli/idos/actions/runs/39465227681)
pasó en Python 3.11/3.12. Pages preview
[#39465318968](https://github.com/alebertolli/idos/actions/runs/39465318968)
validó los datos reales de ALAB/XLF: XLF `not_applicable` y ALAB RULE-008
bloqueada. El arreglo se integró como PR #146 y Pages
[#39466121233](https://github.com/alebertolli/idos/actions/runs/39466121233)
desplegó el SHA `9c0eb15` con el estado operativo de producción vacío.

### Gate de interacción humana única en Decision Board — 2026-10-20

1. Ejecutar Discovery, Research y Assessment sin credenciales ni inputs de
   gestor; comprobar que los workers completan la etapa y producen estados
   explícitos aunque una regla deje el caso bloqueado.
2. Verificar que ningún workflow, script o pantalla pida aprobación o
   confirmación humana antes de Decision Board.
3. En Decision Board, exigir una única acción autenticada que incluya la
   decisión, justificación, confirmación de fuentes/fechas y hash vigente del
   paquete evaluado. Cualquier cambio de escenarios entre Assessment y Board,
   evidencia no trazable, falta de identidad o confirmación debe impedir
   escritura.
4. Verificar que la aprobación válida agrega únicamente a Buy List; no crea
   posición, orden ni ENTRY_PENDING. Rechazo y falta de aprobación permanecen
   auditables y no generan autorización implícita.
5. Revisar el dashboard para confirmar que el paquete está completo y que las
   alertas/gates están explicados como pendientes de Decision Board sin
   solicitar acciones previas.


### Decision Review en producción

Tras integrar el workflow, comprobar que el enlace de Decision Board abre la acción manual desde `main`. Verificar con una propuesta real que los inputs autenticados pasan las validaciones, que un rechazo sólo registra la resolución y que una aprobación válida agrega Buy List sin crear posiciones u órdenes. No ejecutar decisiones sintéticas en `main`; probar casos negativos con fixtures locales o en una rama de prueba.



### Coherencia financiera de Research y artifact DDD

- Ejecutar una prueba con FCF observado y procedencia; comprobar que el prompt
  recibe valor, unidad/moneda, período, corte y fuente, y que no sustituye
  datos ausentes por cero ni etiqueta FCF reportado como ajustado.
- Ejecutar Research y Assessment para un ticker seleccionado en rama de prueba;
  inspeccionar que el expediente llegue a Decision Board y conserve su estado
  pendiente sin aprobación automática.
- Confirmar que el artifact DDD contiene únicamente reportes y decisiones de
  las oportunidades creadas/actualizadas durante ese run y que nunca incluye
  posiciones ni datos privados de Portfolio.
- Ejecutar Pages build en la misma rama y comprobar tesis, escenarios,
  procedencia, alertas de quality y estado pendiente de Decision Board.


### E2E del checkpoint humano único

- Confirmar en la misma oportunidad que Discovery, Research y Assessment se
  completan sin interacción humana y producen el expediente de Decision Board.
- Verificar que RULE-008 se valida automáticamente con evidencia de entrada
  trazable; un paquete válido queda pendiente del gestor y no simula identidad,
  aprobación ni confirmación humana.
- Confirmar que antes de Decision Board no se crean Buy List aprobada,
  posiciones, órdenes ni autorizaciones de operación.
- Inspeccionar el dashboard de preview para ver tesis, asimetría, procedencia,
  reglas/gates y estado pendiente de decisión; comprobar Buy List vacía y
  ausencia de posiciones, ledger y portfolio privado.
- Evidencia 2026-10-20: Monthly #39480735385, DDD #39483387219 / artifact
  #12292412140, Pages preview #39483933896 y Daily Refresh #39484102319.
  Ejecuciones de prueba en ramas; no equivalen a publicación ni a aceptación
  del gestor. Portfolio privado queda fuera de alcance hasta conectar su fuente.
