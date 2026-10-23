# Requirements Document

## Introduction

El **Investment Decision Operating System (IDOS)** es la plataforma operativa e intelectual diseñada para gobernar, auditar y optimizar el proceso de asignación de capital a largo plazo de un patrimonio familiar concentrado con exposición significativa a Argentina.

El IDOS no toma decisiones autónomas de asignación de capital. Es un sistema reactivo y orientado a eventos que investiga, estructura evidencias, propone y alerta; el titular del patrimonio confirma y autoriza las transacciones. Toda decisión es inmutable, trazable y reproducible.

El sistema gestiona simultáneamente múltiples estrategias de inversión bajo una arquitectura patrimonial de 4 Cores, con deduplicación operativa por instrumento + estrategia, y reporta obligatoriamente dos dimensiones patrimoniales: crecimiento en moneda fuerte y poder adquisitivo argentino.

---

## Glossary

- **IDOS**: Investment Decision Operating System. La plataforma completa de operación y toma de decisiones de inversión.
- **Opportunity**: Ventana concreta de asignación de capital sobre un instrumento bajo una estrategia específica, identificada por un ID único. La unidad operativa central del sistema. La deduplicación es por `instrumento + strategy_id`.
- **Case_File**: Expediente histórico analítico que el IDOS mantiene sobre un instrumento a lo largo de toda su vida de seguimiento. Agrupa múltiples Opportunities históricas.
- **Company**: Entidad corporativa inmutable del mundo real, identificada por Ticker e ISIN.
- **Knowledge_Base**: Repositorio central de información sobre un instrumento; se divide en Static Knowledge, Dynamic Knowledge y Generated Knowledge.
- **Hypothesis**: Supuesto de inversión concreto y falsable vinculado a una Opportunity. Se organiza en árbol (Principal → Secundarias). Solo requerida por el research_protocol `FULL_DDD`.
- **Prediction**: Proyección observable cuantitativa con variable, valor esperado, horizonte y tolerancia.
- **Assessment**: Evaluación analítica estandarizada generada por un Assessment_Engine. Schema unificado: `{id, engine, version, status, score, confidence, findings, risks, recommendation, evidence, dependencies, generated_at}`.
- **Assessment_Engine**: Motor de análisis especializado. Los engines disponibles son: Business_Assessment_Engine, Valuation_Assessment_Engine, Recovery_Assessment_Engine, Risk_Assessment_Engine, Portfolio_Assessment_Engine, Momentum_Score_Engine, Correlation_Engine, Liquidity_Engine, Distress_Probability_Engine, Recovery_Value_Engine, Duration_Risk_Engine, Credit_Risk_Engine, Inflation_Exposure_Engine.
- **Evidence**: Hecho o dato específico que respalda, debilita o refuta una Hypothesis.
- **Decision**: Registro formal e inmutable de una decisión operativa o de inversión.
- **Decision_Orchestrator**: Componente central que consolida los Assessments, aplica los Gates del IDE v2.0 y determina el resultado de cada decisión.
- **Decision_Board**: Instancia humana de revisión y autorización de las propuestas preparadas por agentes y validadores deterministas. Es la primera interacción humana del flujo; una aprobación automática nunca sustituye la decisión atribuible del gestor.
- **Gate**: Condición de validación estructurada del Decision Engine v2.0. Existen 8 Gates (GATE 0 a GATE 7). Los applicable_gates de cada estrategia determinan cuáles se evalúan.
- **Conviction**: Objeto multidimensional que cuantifica el nivel de convicción sobre una Opportunity. Campos: `overall`, `scores` (pesos configurados por Strategy_Profile), `confidence`, `trend`.
- **IAS**: Investment Attractiveness Score. Ranking relativo de atractivo de una oportunidad respecto al resto.
- **RCS**: Risk Capacity Score. Capacidad actual del portfolio de absorber el riesgo incremental de una nueva posición.
- **Risk_Budget**: Riesgo restante disponible después de considerar la cartera existente. Variable separada de IAS y RCS.
- **BSP**: Business Success Probability. Probabilidad de que el instrumento ejecute con éxito su estrategia.
- **MRP**: Market Recognition Probability. Probabilidad de que el mercado reconozca la mejora mediante rerating.
- **TSP**: Thesis Success Probability. Función combinada de BSP y MRP.
- **Recovery_Index**: Índice compuesto = Probabilidad × Magnitud × Velocidad × Nivel_de_Confianza.
- **RPF**: Rerating Probability Framework. Framework que estima la probabilidad de revalorización del mercado.
- **DPF**: Dual Probability Framework. Modelo que calcula BSP y MRP de forma independiente.
- **Portfolio_Architect**: Módulo del IDE v2.0 que determina el Core, Sleeve, función y Risk Overlays de cada instrumento. Clasifica por función del capital, no por geografía.
- **Core**: Agrupación funcional del capital en la arquitectura patrimonial. Cuatro Cores: Core_1 (Supervivencia y Liquidez), Core_2 (Preservación Patrimonial), Core_3 (Crecimiento Patrimonial), Core_4 (Alfa y Asimetría).
- **Sleeve**: Subdivisiónfuncional dentro de un Core. Ejemplos: Global_Base, Systematic_Return, High_Conviction_Long_Term dentro de Core_3.
- **Strategy_Profile**: Configuración completa de una estrategia en `idos-config/strategies/{strategy_id}.yml`. Define: `discovery_filter`, `research_protocol`, `assessment_engines` (lista con pesos), `entry_policy`, `exit_rules`, `applicable_gates`, `core`, `sleeve`, `position_limits`.
- **Strategy_Catalog**: Colección de todos los Strategy_Profiles habilitados en `idos-config/strategies/`. Incluye por defecto: COMPOUNDER, MOMENTUM_ETF, DEEP_VALUE, CREDIT_BOND, DEFENSIVE_ETF.
- **Strategy_Knowledge_Sources**: Sección obligatoria de un Strategy_Profile que declara la bibliografía canónica y los referentes intelectuales que fundamentan la estrategia. Se usa para proveer contexto al LLM cuando ejecuta tareas de Research y Assessment para esa estrategia, asegurando que el razonamiento se ancle en el marco teórico correcto.
- **Strategy_Authority**: Referente intelectual declarado en el `Strategy_Knowledge_Sources` de un Strategy_Profile. Incluye: nombre del autor, obra(s) principal(es) y el aporte conceptual específico que aplica a la estrategia.
- **discovery_filter**: Configuración del filtro de descubrimiento en el Strategy_Profile. Define screener, criterios y universo de instrumentos.
- **research_protocol**: Protocolo de investigación declarado en el Strategy_Profile. Valores: `FULL_DDD`, `MOMENTUM_SIGNAL`, `CREDIT_ANALYSIS`, `FUNDAMENTAL_LITE`.
- **applicable_gates**: Lista de Gates del Decision Engine que se evalúan para una estrategia específica, declarada en el Strategy_Profile.
- **entry_policy**: Reglas de entrada declaradas en el Strategy_Profile (ej.: Wyckoff para COMPOUNDER, señal mensual para MOMENTUM_ETF, spread threshold para CREDIT_BOND).
- **State_Machine**: Máquina de estados que gestiona el ciclo de vida de cada Opportunity en SQLite.
- **Buy_List**: Lista persistente (YAML) de Opportunities aprobadas y listas para monitoreo de entrada.
- **Scout_Engine**: Componente del Discovery Domain que aplica el `discovery_filter` del Strategy_Profile para analizar el universo y generar score.
- **DDD_Pipeline**: Deep Due Diligence Pipeline. Proceso que lleva las Opportunities de SCREENED a UNDER_RESEARCH aplicando el `research_protocol` de la estrategia.
- **AOIF**: Protocolo de análisis fundamental profundo de 8 pasos ejecutado por el Research_Domain cuando el research_protocol es `FULL_DDD`.
- **Assessment_Pipeline**: Pipeline 100% algorítmico que ejecuta los `assessment_engines` declarados en el Strategy_Profile.
- **Entry_Monitor_Worker**: Worker que monitorea la Buy_List y ejecuta la `entry_policy` de la estrategia.
- **Wyckoff_Indicator**: Indicador compuesto algorítmico de oferta/demanda (0–100) con cuatro componentes: Estructura (40%), Oferta_Demanda (30%), Fuerza_Relativa (20%), Volatilidad (10%). Usado por la `entry_policy` de COMPOUNDER.
- **Monthly_Universe_Pipeline**: Pipeline mensual que ejecuta el `discovery_filter` de todas las estrategias habilitadas y evalúa todas las Opportunities existentes.
- **CASH_FALLBACK**: Estado de un sleeve cuando ningún activo pasa el filtro de la estrategia (e.g., ningún ETF tiene momentum positivo). El sleeve queda en efectivo.
- **Thesis_Monitor_Worker**: Worker que re-evalúa la tesis de posiciones activas del portfolio.
- **Post_Mortem_Worker**: Worker que ejecuta el análisis retrospectivo obligatorio tras el cierre de una posición.
- **LLM_Service**: Servicio singleton de acceso a LLMs con adaptive routing, circuit breaker, rate limiting y telemetría.
- **Jev**: Modelo de decisiones tipadas y probabilísticas de TypeSafe AI (System One). Opera sobre estado estructurado + preguntas tipadas y devuelve respuestas constrained con probabilidades. Sus tres primitivas son: `Choice` (selecciona opción de un enum), `Score` (evalúa en rúbrica ordenada), `Noul` (probabilidad 0-1 de "sí"). Usado en el IDOS para decisiones acotadas dentro del pipeline donde el LLM de texto libre sería excesivo o lento.
- **Jev_Service**: Servicio singleton de acceso a Jev, análogo al LLM_Service pero especializado en decisiones tipadas. Configurado en `idos-config/models.yml` junto con los proveedores LLM.
- **Agent_Memory**: Capa de memoria de un agente del sistema. Se divide en tres tipos: (1) Episódica — historial de análisis, decisiones y conversaciones anteriores; (2) Semántica — embeddings vectoriales de la Knowledge_Base para búsqueda RAG; (3) Procedimental — parámetros aprendidos del ciclo de auto-aprendizaje (pesos RPF, thresholds calibrados).
- **RAG**: Retrieval-Augmented Generation. Patrón donde el agente recupera fragmentos relevantes de la Knowledge_Base usando búsqueda vectorial antes de generar texto, asegurando que el análisis se ancle en conocimiento institucional histórico.
- **Agent_Orchestrator**: Agente coordinador central que delega tareas a sub-agentes especializados, gestiona el flujo del Decision Pipeline y consolida resultados. No realiza análisis directamente.
- **Auto_Learning_Cycle**: Ciclo formal de retroalimentación donde el Learning Engine propone ajustes a parámetros del sistema (pesos RPF, thresholds de Strategy_Profiles, límites de riesgo) basándose en post-mortems acumulados; los ajustes requieren aprobación humana antes de aplicarse.
- **Event_Bus**: Mecanismo central de mensajería asíncrona (singleton in-memory + historial SQLite).
- **Git_Queue_Worker**: Único proceso autorizado para realizar `git push`. Serializa escrituras al repositorio.
- **Base_Worker**: Clase base de la que heredan todos los Workers. Gestiona RunManifest, telemetría y notificaciones automáticamente.
- **Agent_Base**: Clase base para agentes externos que consumen el IDOS como arnés.
- **Provenance_Entry**: Cadena de evidencia que vincula cada campo de un Assessment o Decision con su fuente y autor.
- **Error_Manager**: Servicio único de gestión y consolidación de errores del sistema.
- **Notification_Center**: Componente que centraliza alertas al usuario por canales (Telegram, Email, Dashboard).
- **Decision_Inbox**: Bandeja de decisiones que agrupa todas las propuestas que requieren intervención humana, ordenadas por prioridad.
- **Paper_Trader**: Componente que simula y registra transacciones de compra/venta.
- **Portfolio_Position**: Estado de ejecución física de una Opportunity aprobada con capital en el mercado.
- **Argentina_Overlay**: Risk Overlay transversal que cuantifica la exposición económica real a Argentina, incluyendo exposición financiera directa, económica indirecta, inmueble, ingresos/negocios locales y obligaciones en pesos.
- **Patrimonio_Dual**: Las dos dimensiones de medición patrimonial que el sistema reporta obligatoriamente: (1) patrimonio en moneda fuerte (USD) y (2) poder adquisitivo argentino estimado.
- **Cartera_Financiera_Liquida**: Activos que pueden valorarse y movilizarse razonablemente. Base de cálculo de los pesos estratégicos de los Cores y del Risk_Budget. Excluye inmuebles, participaciones ilíquidas y pasivos.
- **IPS**: Investment Policy Statement. Documento que formaliza los objetivos patrimoniales, restricciones, horizonte de inversión, capacidad de riesgo y límites del inversor. Es la fuente de verdad de nivel 1 del sistema — prevalece sobre todas las demás capas.
- **Investment_Constitution**: Documento rector que establece principios, restricciones no negociables, autoridad y reglas de gobernanza. Junto con el IPS, constituye la capa superior de la jerarquía de fuentes de verdad.
- **Investor**: Entidad que representa al titular del capital. Atributos: `investor_id`, `objectives`, `constraints`, `risk_capacity`, `liquidity_requirements`, `horizon`.
- **Functional_Role**: Clasificación funcional que el Portfolio_Architect asigna a cada activo. Valores del enum: `Compounder`, `Value_Asymmetry`, `Growth`, `Defensive`, `Inflation_Hedge`, `Crisis_Hedge`, `Liquidity`, `Income`, `Diversifier`, `Tactical`, `Speculative`.
- **Satellite**: Posición que debe justificar su existencia mediante oportunidad, valoración, catalizador, régimen de mercado, asimetría o diversificación específica. No es Satellite simplemente por ser pequeña.
- **Truth_Hierarchy**: Jerarquía de 8 niveles de fuentes de verdad del sistema. Nivel 1 (IPS/Constitution) prevalece sobre niveles inferiores cuando existen conflictos. Los niveles son: 1-Constitution, 2-Portfolio_Architecture, 3-Risk_Audit, 4-Investment_Thesis, 5-Allocation, 6-Decision, 7-Portfolio/Execution, 8-Learning.
- **UNKNOWN**: Valor asignado a variables que no pueden determinarse con evidencia suficiente. Cuando un campo crítico es UNKNOWN, el resultado del sistema es `REVIEW` o `BLOCKED`, nunca una estimación artificial.
- **idos-knowledge**: Directorio de conocimiento objetivo y verificable (company.yml, wikis, datos financieros).
- **idos-journal**: Directorio de conocimiento subjetivo/proceso (Case Files, decisiones, post mortems).
- **idos-core**: Directorio de código, SDK, Workers, pruebas y workflows.
- **idos-config**: Directorio de prompts, reglas operativas, scoring, Strategy_Profiles y perfiles de riesgo.

---

## Requirements

---

### Requirement 1: Ciclo de vida de Opportunity (State Machine)

**User Story:** Como gestor del fondo, quiero que cada oportunidad de inversión avance por un ciclo de vida formal, trazable y consciente de la estrategia que la originó, para que toda decisión de asignación de capital quede auditada, sea reproducible y soporte múltiples estrategias simultáneas sobre el mismo instrumento.

#### Acceptance Criteria

1. THE State_Machine SHALL admitir los siguientes estados para una Opportunity, en el flujo de producción: `DISCOVERED`, `SCREENED`, `PORTFOLIO_FIT`, `UNDER_RESEARCH`, `THESIS_VALIDATED`, `WATCHLIST`, `APPROVED`, `ENTRY_PENDING`, `ACCUMULATING`, `ACTIVE`, `REDUCED`, `OFF`, `CASH_FALLBACK`, `REVIEW`, `BLOCKED`, `EXITED`, `POST_MORTEM`, `ARCHIVED`.
2. THE State_Machine SHALL garantizar que ninguna Opportunity posea más de un estado simultáneo en ningún momento.
3. THE State_Machine SHALL persistir en cada Opportunity los metadatos de estrategia: `strategy_id`, `core`, `sleeve`, `thesis_type`, `entry_policy`, `research_profile`; una Opportunity sin `strategy_id` SHALL interpretarse como estrategia `COMPOUNDER` para compatibilidad hacia atrás.
4. WHEN el Monthly_Universe_Pipeline detecta que el score de un instrumento supera o iguala el `score_threshold` configurado para la estrategia, IF la Opportunity para ese `instrumento + strategy_id` no existe o está en `WATCHLIST`, THEN THE State_Machine SHALL crear la Opportunity en `SCREENED` o promoverla de `WATCHLIST` a `SCREENED`; las Opportunities en cualquier otro estado no se ven afectadas.
5. WHEN el Portfolio_Architect evalúa una Opportunity en `SCREENED` y el GATE 1 pasa, THE State_Machine SHALL transicionar la Opportunity a `PORTFOLIO_FIT` registrando el `core`, `sleeve` y `risk_overlays` asignados.
6. WHEN el DDD_Pipeline procesa una Opportunity en `PORTFOLIO_FIT` o `SCREENED` en modo NORMAL, THE State_Machine SHALL transicionar la Opportunity a `UNDER_RESEARCH` tras la ejecución del `research_protocol` configurado.
7. WHEN el Assessment_Pipeline completa los engines declarados y evalúa los `applicable_gates` de la estrategia, IF los GATE 2 y GATE 3 pasan, THEN THE State_Machine SHALL transicionar la Opportunity de `UNDER_RESEARCH` a `THESIS_VALIDATED`; IF GATE 2 falla, THEN SHALL transicionar a `WATCHLIST`.
8. WHEN el Decision_Orchestrator evalúa los `applicable_gates` restantes y el Decision_Board aprueba, THE State_Machine SHALL transicionar la Opportunity de `THESIS_VALIDATED` a `APPROVED`.
9. WHILE una Opportunity se encuentra en `WATCHLIST`, THE State_Machine SHALL bloquear todo reprocesamiento automático por el DDD_Pipeline; solo el Monthly_Universe_Pipeline puede promoverla si el score recupera el threshold.
10. WHEN una regla detecta señal de salida para una posición activa, THE IDOS SHALL crear una propuesta y mantener sin cambios posición y Opportunity. WHEN el gestor registra una decisión explícita, atribuible y justificada para cerrar la posición, THEN THE State_Machine SHALL transicionar la Opportunity a `EXITED` e iniciar el Post_Mortem_Worker obligatoriamente.
11. IF GATE 0 o GATE 1 fallan durante la evaluación, THEN THE State_Machine SHALL asignar estado `BLOCKED` (no `WATCHLIST`) con registro del gate y motivo específico.
12. THE State_Machine SHALL registrar en SQLite para cada transición: `timestamp`, `worker_name`, `cause`, estado origen y destino, y `strategy_id`.

#### Propiedades de Corrección (Property-Based Testing)

- **Unicidad de estado**: Para toda Opportunity `opp`, en cualquier momento `t`, existe exactamente un estado activo en SQLite. Propiedad de invariante.
- **Deduplicación correcta**: Para una misma empresa `E` y estrategia `S`, en cualquier momento `t`, existe a lo sumo una Opportunity activa (estado anterior a `ARCHIVED`). Dos estrategias distintas `S1` y `S2` sobre la misma empresa `E` pueden coexistir como Opportunities independientes. Propiedad de invariante.
- **Inmutabilidad de historial**: Dado un registro de transición con ID `t`, ninguna operación posterior puede modificar `t.timestamp`, `t.cause` ni `t.from_state`. Propiedad de invariante.
- **Idempotencia de re-research**: Aplicar el modo FORCE del DDD_Pipeline N veces sobre una Opportunity en `UNDER_RESEARCH` produce exactamente el mismo estado (`UNDER_RESEARCH`) con `last_research_at` actualizado. Propiedad de idempotencia: `state(force_n(opp)) == state(force_1(opp)) == UNDER_RESEARCH`.

---

### Requirement 2: Discovery Domain — Scout y Universe Pipeline multi-estrategia

**User Story:** Como gestor del fondo, quiero que el sistema explore automáticamente el universo invertible aplicando el filtro de descubrimiento específico de cada estrategia habilitada, para que cada sleeve del portfolio reciba candidatos con los criterios de selección correctos para su función.

#### Acceptance Criteria

1. THE Scout_Engine SHALL aplicar el `discovery_filter` declarado en el Strategy_Profile de cada estrategia habilitada en `idos-config/strategies.yml`. Los criterios, umbrales, pesos, transformaciones y políticas de datos faltantes SHALL ser configurables y versionados por estrategia; no SHALL estar hardcodeados ni compartir un filtro de inversión global. El Scout SHALL excluir señales e indicadores técnicos de los gates binarios de elegibilidad. Una señal técnica solo podrá contribuir al score cuando el Strategy_Profile de la estrategia la declare con peso y versión explícitos, y se calcule en un motor separado; ScoutEngine no SHALL hardcodear criterios técnicos. MULTIBAGGERS conserva Market Confirmation como componente configurable de su score.
2. THE Monthly_Universe_Pipeline SHALL ejecutarse el día 1 de cada mes vía GitHub Actions `schedule`, SHALL ejecutar los screeners de todas las estrategias habilitadas en `idos-config/strategies/`, y SHALL admitir ejecución manual via `workflow_dispatch`.
2a. THE Monthly_Universe_Pipeline SHALL usar `idos-config/universe/operable.yml` como registro común de elegibilidad de activos (incluidos los que no sean CEDEARs); SHALL intersectar este registro con el universo configurado de cada estrategia, cuando exista, antes de consultar datos, evaluar señales o crear Opportunities. El registro operable SHALL mantenerse según disponibilidad efectiva del broker y no derivarse exclusivamente del listado oficial de CEDEARs.
2b. WHEN un Strategy_Profile define `supported_asset_types`, THE Monthly_Universe_Pipeline SHALL filtrar los instrumentos por esos tipos después de validar su pertenencia al registro operable y antes de consultar fuentes. Para acciones, `equity` SHALL ser el tipo canónico independiente del país y `us_equity` SHALL seguir admitiéndose como alias legado; ambos SHALL coincidir al filtrar una estrategia que soporte acciones. ETFs (`etf`) SHALL permanecer como clase separada. La ejecución manual SHALL admitir hasta cinco tickers, rechazar los que no estén en el registro operable y mantener la ejecución programada sobre el universo completo compatible.
2c. AFTER obtener y validar los datos de un candidato, pero BEFORE ejecutar el filtro específico de Scout de la estrategia, IDOS SHALL aplicar a todas las estrategias el volumen promedio diario mínimo en dólares (USD 100.000). Para acciones (`equity` o el alias legado `us_equity`) SHALL aplicar además capitalización mínima de USD 2.000 millones; ETFs (`etf`) SHALL quedar exentos de filtros de tamaño, capitalización y AUM. El tipo de activo SHALL provenir de `operable.yml`, no de una heurística. La elegibilidad de acciones SHALL ser independiente del país de cotización o domicilio del emisor. Los umbrales SHALL residir en configuración global versionada. Los valores utilizados por los gates SHALL estar ya expresados en USD por el proveedor o corresponder al subyacente USD; IDOS no SHALL convertir desde ARS para decidir elegibilidad. El promedio se SHALL calcular con las observaciones disponibles dentro de la ventana configurada; SHALL NOT exigir una cantidad mínima de ruedas ni una cobertura porcentual. Métricas USD requeridas ausentes o inválidas SHALL dejar el candidato en `PENDING_DATA` con reason codes; SHALL NOT rechazarse por país, cobertura ni falta de conversión ARS, sustituirse por cero ni contarse como aprobadas.
3. WHERE la estrategia es `COMPOUNDER`, THE Scout_Engine SHALL aplicar criterios fundamentales configurados en el Strategy_Profile (por ejemplo, ROIC, FCF y moat indicators) y calcular un score 0–100 basado en calidad del negocio. No SHALL incluir fuerza relativa, tendencia precio-volumen ni otros indicadores técnicos.
4. WHERE la estrategia es `MOMENTUM_ETF`, un motor de señal mensual propio SHALL calcular y rankear el momentum sobre el universo y los parámetros versionados del Strategy_Profile, generar `signal.yml` y asignar `CASH_FALLBACK` si ningún instrumento alcanza los criterios. La fuerza relativa, selección y señal técnica SHALL quedar fuera de Scout_Engine; el Scout no SHALL aplicar indicadores técnicos.
5. WHERE la estrategia es `CREDIT_BOND`, THE Scout_Engine SHALL filtrar usando yield spread, duration y credit rating con criterios y umbrales configurados en el Strategy_Profile.
6. THE `score_threshold` SHALL ser configurable por estrategia en el Strategy_Profile; un instrumento que supera el threshold de su estrategia entra a `SCREENED` para esa estrategia específicamente.
7. WHEN el Monthly_Universe_Pipeline finaliza, THE Monthly_Universe_Pipeline SHALL evaluar el score de todas las Opportunities existentes por estrategia y SHALL aplicar transiciones WATCHLIST/SCREENED respetando el `score_threshold` de cada Strategy_Profile; las Opportunities en `APPROVED` o estados posteriores nunca se modifican automáticamente.
8. IF el Scout_Engine no puede obtener datos de una fuente primaria, THEN THE Scout_Engine SHALL intentar fuentes alternativas (degradación graceful) y SHALL registrar el error en el Error_Manager.
9. WHEN el proceso de Discovery finaliza, THE IDOS SHALL publicar el evento `DiscoveryCompleted` en el Event_Bus con el número de nuevas Opportunities creadas por estrategia.
7. WHEN el Monthly_Universe_Pipeline finaliza, THE Monthly_Universe_Pipeline SHALL evaluar el score de todas las Opportunities existentes por estrategia y SHALL aplicar transiciones WATCHLIST/SCREENED respetando el `score_threshold` de cada Strategy_Profile; las Opportunities en `APPROVED` o estados posteriores SHALL ser excluidas completamente del evaluation pass (no se lee ni evalúa su score, ni siquiera para métricas).
10. THE Scout_Engine SHALL utilizar JEV (`Noul` y `Score`) para puntuar las dimensiones configuradas en el Strategy_Profile, en lugar de un LLM de texto libre; cada evaluación se SHALL basar en el estado numérico trazable del instrumento y producir resultados reproducibles. Una señal técnica como Market Confirmation SHALL calcularse en un motor separado y solo podrá contribuir al score cuando la estrategia la declare explícitamente; no podrá operar como gate binario independiente ni estar hardcodeada en ScoutEngine.

#### Propiedades de Corrección (Property-Based Testing)

- **Routing correcto de discovery_filter**: Para toda Opportunity creada con `strategy_id = X`, el score fue calculado aplicando exactamente el `discovery_filter` declarado en el perfil X, no el de otra estrategia. Propiedad de invariante.
- **Monotonía de creación**: Para cualquier instrumento con score ≥ threshold de la estrategia S en la corrida mensual, después de ejecutar el Monthly_Universe_Pipeline existe exactamente una Opportunity activa para ese instrumento y estrategia (no duplicados). Propiedad de invariante.
- **Corrección del filtro threshold**: Para toda Opportunity promovida a `SCREENED`, `score_at_promotion >= score_threshold` de su estrategia. Para toda Opportunity enviada a `WATCHLIST`, `score_at_demotion < score_threshold`. Propiedad de precondición.

---

### Requirement 3: Research Domain — Protocolos de investigación por estrategia

**User Story:** Como analista del fondo, quiero que el sistema aplique el protocolo de investigación correcto para cada estrategia al analizar un instrumento candidato, para que los artefactos generados sean coherentes con la naturaleza de la oportunidad y no se aplique AOIF completo a señales sistemáticas de momentum.

#### Acceptance Criteria

1. THE Research_Worker SHALL seleccionar el `research_protocol` del Strategy_Profile de la Opportunity y SHALL ejecutar exclusivamente el protocolo declarado; no SHALL aplicar un protocolo genérico independiente de la estrategia.
2. WHERE el `research_protocol` es `FULL_DDD`, THE Research_Worker SHALL ejecutar el protocolo AOIF completo (8 pasos, hipótesis con las 5 preguntas del HMF, condiciones de falsación obligatorias, predicciones cuantitativas) y persistirá `case_file.yml`, `opportunity.yml`, `hypotheses.yml`.
3. WHERE el `research_protocol` es `MOMENTUM_SIGNAL`, THE Research_Worker SHALL calcular la señal de momentum, ejecutar el backtest del universo, generar el ranking y persistir `signal.yml` con: señal cruda, score normalizado, riesgos de señal y condiciones de falsación de la señal (ruptura de tendencia, cambio de régimen); no se requieren hipótesis cualitativas AOIF.
4. WHERE el `research_protocol` es `CREDIT_ANALYSIS`, THE Research_Worker SHALL ejecutar análisis de duration (Macaulay, Modified, Effective), PD, LGD, recovery, credit spread y stress scenarios, y persistirá `credit_analysis.yml` con las métricas crediticias y escenarios de stress.
5. WHERE el `research_protocol` es `FUNDAMENTAL_LITE`, THE Research_Worker SHALL ejecutar un DDD abreviado sin árbol de hipótesis completo, apropiado para posiciones tácticas de Core 4, y persistirá `ddd_lite.yml`.
6. THE Research_Worker SHALL registrar el `research_protocol` utilizado en el `case_file.yml` junto con los artefactos generados.
7. WHERE el `research_protocol` es `FULL_DDD`, THE Hypothesis SHALL formularse respondiendo las cinco preguntas del HMF: ¿Qué creemos?, ¿Por qué?, ¿Qué debería ocurrir si tenemos razón?, ¿Qué hechos demostrarían que estamos equivocados?, ¿Cuándo dejaremos de creerla?; IF una Hypothesis no responde alguna de las cinco preguntas HMF (incluyendo pero no limitado a la ausencia de condición de falsación), THEN THE Research_Worker SHALL rechazar la actualización con error de validación antes de reemplazar el DDD vigente o avanzar a Assessment.
7a. Cada predicción cuantitativa `FULL_DDD` SHALL incluir `fecha_objetivo` en formato ISO `YYYY-MM-DD`, posterior a la fecha de corte de Research; una fecha vencida, inválida o una predicción, falsación o condición de abandono referida a un ejercicio fiscal pasado SHALL causar `hypothesis_validation_failed`, conservar el DDD previo y detener el flujo antes de persistir hipótesis, Assessment o Decision.
8. WHEN el Research_Worker actualiza la Knowledge_Base, THE Research_Worker SHALL nunca sobrescribir registros existentes; SHALL versionar los cambios mediante versionado incremental.
9. THE Research_Worker SHALL utilizar el LLM_Service para tareas de análisis no estructurado (síntesis, generación de hipótesis AOIF); no SHALL crear clientes LLM directamente.
10. WHEN el Research_Worker completa el análisis, THE Research_Worker SHALL publicar el evento `DeepDDCompleted` en el Event_Bus con el `research_protocol` utilizado.
11. THE Research_Worker SHALL ejecutar una búsqueda RAG sobre la Knowledge_Base antes de iniciar el análisis AOIF, recuperando los fragmentos semánticos más relevantes del historial del instrumento (análisis anteriores, hipótesis pasadas, predicciones vs realidad) para anclar el análisis en el conocimiento institucional acumulado y evitar repetir errores documentados en post-mortems anteriores.
12. THE Research_Worker SHALL utilizar Jev (`Choice(PASS/FAIL)` por pregunta HMF) para validar estructuralmente la completitud de cada Hypothesis generada antes de persistirla; Jev verifica que las cinco preguntas HMF están presentes y no vacías; la validación de contenido cualitativo permanece bajo responsabilidad del LLM_Service.

#### Propiedades de Corrección (Property-Based Testing)

- **Correspondencia artefacto-protocolo**: Para toda Opportunity procesada, el artefacto generado (`hypotheses.yml`, `signal.yml`, `credit_analysis.yml` o `ddd_lite.yml`) corresponde exactamente al `research_protocol` declarado en el Strategy_Profile. `research_protocol(opp) → artifact_type(opp)`. Propiedad de invariante.
- **Round-trip de serialización**: Para todo `hypotheses.yml` generado por `FULL_DDD`: `parse(serialize(hypotheses)) == hypotheses`. Los campos obligatorios sobreviven el ciclo completo de escritura y lectura. Propiedad de round-trip (esencial para parsers).
- **Integridad del árbol de hipótesis**: Para toda Hypothesis principal con N hipótesis secundarias, si se serializa y deserializa el árbol, el número y contenido de las hipótesis secundarias se preservan exactamente. Propiedad de round-trip.

---

### Requirement 4: Assessment Engines — Evaluación analítica por Strategy Profile

**User Story:** Como gestor del fondo, quiero que el Assessment Pipeline ejecute únicamente los engines declarados en el Strategy Profile de cada oportunidad y devuelva siempre un schema unificado, para que el Decision_Orchestrator pueda consolidar evaluaciones de estrategias distintas de forma consistente.

#### Acceptance Criteria

1. THE Assessment_Pipeline SHALL ejecutar únicamente los `assessment_engines` listados en el Strategy_Profile de la Opportunity; no SHALL ejecutar los cinco engines por defecto independientemente de la estrategia.
2. WHERE la estrategia es `COMPOUNDER`, THE Assessment_Pipeline SHALL ejecutar: Business_Assessment_Engine (BSP), Valuation_Assessment_Engine, Recovery_Assessment_Engine (MRP), Risk_Assessment_Engine y Portfolio_Assessment_Engine.
3. WHERE la estrategia es `MOMENTUM_ETF`, THE Assessment_Pipeline SHALL ejecutar: Momentum_Score_Engine, Correlation_Engine, Liquidity_Engine y Portfolio_Assessment_Engine.
4. WHERE la estrategia es `DEEP_VALUE`, THE Assessment_Pipeline SHALL ejecutar: Business_Assessment_Engine (BSP simplificado), Distress_Probability_Engine, Recovery_Value_Engine, Risk_Assessment_Engine y Portfolio_Assessment_Engine.
5. WHERE la estrategia es `CREDIT_BOND`, THE Assessment_Pipeline SHALL ejecutar: Duration_Risk_Engine, Credit_Risk_Engine, Inflation_Exposure_Engine, Liquidity_Engine y Portfolio_Assessment_Engine.
6. THE Assessment_Engine SHALL devolver exactamente el schema unificado `{id, engine, version, status, score, confidence, findings, risks, recommendation, evidence, dependencies, generated_at}` independientemente del tipo de engine; ningún campo puede ser null.
7. THE Assessment_Pipeline SHALL calcular el objeto Conviction usando los pesos por engine configurados en el Strategy_Profile; los campos de `conviction.scores` reflejan los engines que aplican a la estrategia.
8. THE Assessment_Pipeline SHALL calcular el Recovery_Index usando la fórmula `Recovery_Index = Probabilidad × Magnitud × Velocidad × Nivel_de_Confianza`; los cuatro factores SHALL calcularse de forma puramente algorítmica.
9. WHEN el Assessment_Pipeline completa la evaluación, THE Assessment_Pipeline SHALL persistir `decision_proposal.yml` y `board_resolution.yml` en el Case File.
10. THE Assessment_Pipeline SHALL ser 100% algorítmico y no SHALL utilizar el LLM_Service en ningún paso.

#### Propiedades de Corrección (Property-Based Testing)

- **Routing correcto de engines**: Para toda Opportunity con `strategy_id = X`, el Assessment_Pipeline ejecuta exactamente los engines declarados en el perfil X (ni más ni menos). Propiedad de invariante.
- **Invariante de schema**: Para todo Assessment generado, el resultado contiene exactamente los campos `{id, engine, version, status, score, confidence, findings, risks, recommendation, evidence, dependencies, generated_at}` y ninguno es null. Propiedad de invariante.
- **Rango de scores**: Para todo Assessment generado, `0 <= score <= 100` y `0 <= conviction.overall <= 100`. Propiedad de invariante.
- **Reproducibilidad del Assessment_Pipeline**: Dado el mismo estado de la Knowledge_Base y las mismas versiones de los engines, ejecutar el Assessment_Pipeline dos veces produce exactamente los mismos scores y el mismo `board_resolution`. Propiedad de idempotencia.

---

### Requirement 5: Decision Domain — Gates del IDE v2.0 y Autorización

**User Story:** Como gestor del fondo, quiero que el Decision_Orchestrator evalúe los Gates del IDE v2.0 aplicables a la estrategia de cada oportunidad y que el Decision_Board autorice formalmente cada transición estratégica, para que ninguna decisión de asignación de capital sea una caja negra y toda posición tenga arquitectura, tesis y riesgo explícitos.

#### Acceptance Criteria

1. THE Decision_Orchestrator SHALL evaluar los `applicable_gates` declarados en el Strategy_Profile de la Opportunity antes de generar una propuesta para el Decision_Board; no todos los Gates aplican a todas las estrategias; IF el Strategy_Profile no declara ningún `applicable_gate`, THEN THE Decision_Orchestrator no está obligado a ejecutar ningún paso de evaluación de gates.
2. THE Decision_Engine SHALL evaluar los siguientes Gates cuando están declarados en `applicable_gates`: GATE 0 (Input/Evidence: fecha de corte, precio, fuentes, calidad de datos, ausencia de contradicciones materiales), GATE 1 (Architecture: Core, Sleeve, función, rango estructural y Risk Overlays definidos por el Portfolio_Architect), GATE 2 (Thesis: tesis, downside, expected value, horizonte, riesgos e invalidación definidos por el Thesis_Engine), GATE 3 (Risk Capacity: RCS, liquidez disponible, drawdown, concentración y estado del portfolio compatibles), GATE 4 (Portfolio Impact: correlación, factores, Argentina_total, duplicación de riesgos, contribución marginal), GATE 5 (Liquidity: proteger reservas de supervivencia, obligaciones próximas y capacidad de maniobra), GATE 6 (Allocation/Competition for Capital: IAS, RCS, Risk_Budget, fuente de financiación, entry_velocity, costo de oportunidad), GATE 7 (Governance: responsable, fecha, acción, límites, condiciones de revisión, plan de ejecución).
2a. GATE 0 SHALL fallar cuando las métricas financieras requeridas carezcan de fuente o fecha de corte válida; una fecha inválida o futura SHALL tratarse como `UNKNOWN`. Una fecha de corte Unix sólo SHALL aceptarse si proviene de metadatos del proveedor y se convierte como segundos UTC con rango válido; su fuente SHALL quedar persistida. El resultado SHALL ser `BLOCKED` o `REVIEW` y no SHALL autorizar la Opportunity.
2b. WHEN dos o más proveedores entregan una métrica numérica, THE DataValidator SHALL comparar la dispersión total (`max - min`) relativa al valor absoluto del promedio con `tolerance_pct`; si supera el umbral, SHALL registrar un único conflicto por métrica con todos los valores de origen. Si el promedio es cero y existe dispersión, SHALL registrar conflicto con `deviation_pct: null`.
3. IF GATE 0 o GATE 1 fallan, THEN THE Decision_Engine SHALL emitir estado `BLOCKED` con el gate y motivo específicos; no deberá emitir `WATCHLIST` en este caso.
4. IF GATE 2 falla, THEN THE Decision_Engine SHALL emitir estado `WATCH`; no habilita posición plena.
5. THE Decision_Engine SHALL poder emitir los siguientes estados de decisión: `APPROVED`, `APPROVED_SMALL`, `WATCH`, `REJECTED`, `HOLD`, `REDUCE`, `EXIT`, `REVIEW`, `BLOCKED`.
6. THE Decision_Board SHALL requerir intervención humana para: aprobar nuevas Opportunities a la Buy_List, autorizar cambios en tesis de inversión y confirmar ejecuciones físicas de transacciones.
7. WHEN el gestor aprueba una Opportunity para la Buy_List pública, THE IDOS SHALL registrar `approved_for_buylist=true`, persistir una entrada trazable en `idos-journal/portfolio/buylist.yml` y mantener la oportunidad en su etapa de Research/Assessment. No SHALL cambiar a `ENTRY_PENDING` ni ejecutar Entry Monitor hasta que se conecte y evalúe el portfolio privado y el gestor confirme el paso de cartera.
8. THE Decision SHALL registrar de forma inmutable: timestamp, `strategy_id`, gates evaluados (resultado PASS/FAIL por gate), authorized_weight, execution_plan, review_date, review_triggers, justificación en Markdown.
9. THE Gates SHALL ser evaluables con los umbrales configurados en `idos-config/rules/` sin necesidad de modificar el código del Decision_Orchestrator.
10. WHEN el Decision_Board genera una autorización de compra, THE IDOS SHALL publicar el evento `BoardApproved` en el Event_Bus.
11. WHEN un campo crítico del contrato de entrada (`ide_input`) no puede determinarse con evidencia suficiente, THE Decision_Engine SHALL asignar el valor `UNKNOWN` o `N/A` a ese campo y SHALL emitir resultado `REVIEW` o `BLOCKED`; THE Decision_Engine no SHALL completar artificialmente un campo UNKNOWN para permitir que el pipeline avance.
12. THE Decision_Engine SHALL evaluar los `applicable_gates` de toda Opportunity como obligación permanente (no condicional) cuando hay gates declarados; las estrategias pueden declarar subconjuntos de los 8 Gates; ambas condiciones —obligatoriedad de evaluación cuando hay gates declarados, y permisividad de subconjuntos por estrategia— son independientes y aplican simultáneamente.
13. THE Decision_Engine SHALL utilizar Jev (`Choice(PASS/FAIL/REVIEW)`) para evaluar GATE 0 (Input/Evidence) y GATE 1 (Architecture), que son verificaciones de completitud del contrato de entrada (`ide_input`); la evaluación de GATE 2 (Thesis) y GATE 4 (Portfolio Impact) puede usar LLM_Service para razonamiento cualitativo cuando sea necesario; GATE 3, GATE 5, GATE 6 y GATE 7 son evaluaciones deterministas sin LLM ni Jev.
14. THE Decision_Orchestrator SHALL implementarse como un Agent_Orchestrator que delega a sub-agentes especializados: Portfolio_Architect_Agent (GATE 1), Thesis_Agent (GATE 2), Risk_Agent (GATE 3 y GATE 4), Allocation_Agent (GATE 6); cada sub-agente mantiene su propia Agent_Memory con historial de decisiones anteriores relevantes.
15. RULE-008 SHALL fallar en autorización cuando la asimetría no provenga de un contrato `bear_bull_v2` validado, una cotización actual válida o fuentes verificables. Research SHALL producir BEAR y BULL como resultados alternativos de una misma tesis para toda estrategia; BASE es opcional y expresa un caso central, no una probabilidad. El Research SHALL pertenecer al perfil de estrategia: fundamental o sistemático.
16. Cada caso SHALL contener `id`, `rationale`, supuestos clave, falsadores y al menos una fuente HTTPS con nombre y fecha no posterior a `as_of_date`. El conjunto SHALL incluir BEAR y BULL una sola vez y podrá incluir BASE una sola vez. `as_of_date` SHALL coincidir con la fecha del análisis y `horizon_date` SHALL ser posterior; moneda SHALL ser ISO 4217. Si `quantification_status=validated`, cada caso SHALL tener precio objetivo positivo y finito, Bear ≤ Bull y, si existe BASE, Bear ≤ Base ≤ Bull. Si no hay evidencia/modelo que defienda rangos de precio, Research SHALL registrar `quantification_status=not_calibrated` y `target_price=null`; el caso cualitativo puede presentarse al Decision Board, pero nunca satisface RULE-008. No se aceptarán `probability_pct` ni retorno esperado hasta que exista un método de probabilidades calibradas validado y versionado; probabilidades de catalizadores independientes o coexistentes SHALL NOT normalizarse para autorizar una Opportunity.
16a. Research y los validadores automáticos SHALL completar la propuesta y comprobar su procedencia antes del Board. No SHALL requerirse revisión humana separada de escenarios antes del Decision Board. El hash del conjunto SHALL quedar ligado al Assessment vigente; durante la única revisión de Decision Board, el gestor podrá confirmar fuentes, fechas y supuestos y aprobar o rechazar el expediente completo.
16a. WHEN Discovery y Research se ejecutan en workflows independientes, THE Opportunity SHALL conservar en `discovery_evidence` una única cotización pública de cierre con fecha, moneda y fuente verificadas. Research SHALL usarla sólo como fallback cuando no exista una cotización equivalente en su fuente local; una cotización ausente o inválida SHALL permanecer `N/D` y SHALL bloquear la validación de escenarios.
17. Para `quantification_status=validated`, Assessment SHALL calcular `bear_return_pct = (bear_target/current_price - 1) * 100` y `bull_return_pct = (bull_target/current_price - 1) * 100`. RULE-008 SHALL comparar el upside Bull con el downside Bear mediante `bull_return_pct / abs(bear_return_pct)` y bloquear si Bear no implica pérdida, Bull no implica retorno positivo, difiere la moneda o falla la validación automática. Para `not_calibrated`, Assessment SHALL registrar que no hay rango y mantener RULE-008 bloqueada. El ratio describe extremos plausibles, no retorno esperado. Una confirmación en Decision Board SHALL comprobar el mismo hash de escenarios que Assessment y SHALL NOT cambiar un gate inválido ni reemplazar evidencia ausente.
18. Un resultado `APPROVE` del motor SHALL ser sólo una propuesta. Discovery, Research y Assessment SHALL operar sin intervención humana y entregar un expediente completo al Decision Board; ésta SHALL ser la primera interacción humana para una Opportunity nueva. Una Opportunity no SHALL entrar en Buy List sin una decisión explícita del gestor con identidad, fecha y justificación ligada al hash de Assessment vigente; para RULE-008, esa misma decisión SHALL registrar confirmación de fuentes y fechas. Ninguna evaluación automática SHALL fabricar una resolución humana. La aprobación a Buy List SHALL quedar separada de cualquier autorización para operar o modificar posiciones privadas.
19. WHEN Research o Assessment generan una versión nueva de la oportunidad, THE IDOS SHALL invalidar su aprobación anterior para Buy List y retirar sólo la entrada asociada a ese `opp_id`; SHALL conservar entradas de otros activos y el registro inmutable de la decisión histórica.
20. THE legacy CLI command `opp-approve` SHALL NOT transition an Opportunity to `APPROVED` or create an approval. It SHALL direct the operator to the current Assessment proposal and attributable manager review flow.
21. THE DDD_Pipeline SHALL allow an explicit manual re-review of exactly one current Buy List opportunity when `FORCE=true` and `REVIEW_BUYLIST=true`; it SHALL match the exact `(ticker, opp_id)`, reject empty/stale selections, and continue excluding every paper portfolio position. After a valid new Research report is persisted, THE IDOS SHALL invalidate the old manager approval immediately, remove only the matching Buy List entry, retain the immutable decision record, and prevent Decision Review from approving the invalidated proposal until Assessment creates a new one.
22. WHILE no authenticated private family-portfolio source is connected, THE PortfolioAssessmentEngine SHALL report `NOT_ASSESSED` with low confidence and a documented neutral placeholder score; it SHALL NOT infer available capacity, diversification benefit or position count from a missing source or paper portfolio state. This status SHALL remain visible in the public pre-portfolio dashboard, and SHALL NOT authorize portfolio entry.
23. THE IDOS SHALL NOT request or depend on human input during Discovery, Research or Assessment for a new Opportunity. Agent workers and deterministic validators SHALL run those stages, preserve provenance and fail closed on invalid or missing evidence; the complete proposal SHALL be presented at Decision Board for the first human interaction.

#### Propiedades de Corrección (Property-Based Testing)

- **Determinismo del Decision_Engine**: Dado el mismo contrato de entrada (ide_input), el mismo estado de portfolio y las mismas versiones de los Strategy_Profiles, el Decision_Engine produce siempre la misma decisión. Propiedad de idempotencia.
- **Exhaustividad de gates aplicables**: Para toda Opportunity que alcanza estado `APPROVED`, existen registros que demuestran que todos los `applicable_gates` de su estrategia pasaron en el momento de la aprobación. Propiedad de invariante de precondición.
- **Inmutabilidad de Decision**: Para todo Decision con ID `d` persistido, ninguna operación posterior puede modificar `d.timestamp`, `d.gates_evaluated` ni `d.justification`. Propiedad de invariante.

---

### Requirement 6: Portfolio Domain — Sizing IDE v2.0 y Gestión de Posiciones

**User Story:** Como gestor del fondo, quiero que el sistema calcule el sizing de posiciones usando el modelo de límites mínimos del IDE v2.0, gestione la entry_policy por estrategia y controle los estados de posición activa, para que la asignación de capital sea sistemática, disciplinada y no mezcle activos de función distinta.

#### Acceptance Criteria

1. THE Allocation_Engine SHALL calcular el peso final de toda posición usando la fórmula: `FINAL_WEIGHT = MIN(Risk_Capacity_Limit, Opportunity_Limit, Portfolio_Limit, Liquidity_Limit, Architecture_Limit)`; un IAS alto no implica posición grande; un RCS alto no obliga a asumir riesgo.
2. THE Entry_Monitor_Worker SHALL aplicar la `entry_policy` declarada en el Strategy_Profile: Wyckoff_Indicator (≥ 45) para `COMPOUNDER`, señal mensual de momentum para `MOMENTUM_ETF`, spread threshold para `CREDIT_BOND`.
3. THE Wyckoff_Indicator SHALL calcularse como score 0–100 con la ponderación: Estructura (40%), Oferta_Demanda (30%), Fuerza_Relativa (20%), Volatilidad (10%); es 100% algorítmico y determinista, sin LLM.
4. THE Entry_Monitor_Worker SHALL clasificar la velocidad de entrada según la `entry_policy`: FAST (tesis clara, liquidez alta, downside conocido, urgencia temporal), GRADUAL (incertidumbre, volatilidad o dependencia de eventos), WAIT (datos insuficientes, margen insuficiente o RCS bajo).
5. THE Portfolio_Domain SHALL asignar a cada activo con posición abierta uno de los siguientes estados: `ACTIVE`, `REDUCED`, `OFF`, `CASH_FALLBACK`; el estado `CASH_FALLBACK` se asigna al sleeve completo cuando ningún activo pasa el filtro de la estrategia.
6. THE Portfolio_Domain SHALL determinar la concentración máxima de posiciones mediante Risk_Audit + Risk_Budget + función de la posición configurados en `idos-config/risk_policy.yml`; no se establece un límite global fijo de 8–15 posiciones; el Risk_Budget disponible y los rangos estructurales de los Cores son los únicos límites vinculantes.
7. THE Risk_Engine SHALL ejecutarse diariamente y SHALL generar alertas cuando el drawdown de una posición supere `max_drawdown_pct` configurado, disparando re-assessment de tesis por el Thesis_Monitor_Worker.
8. WHEN el Thesis_Monitor_Worker detecta que `thesis_active == False`, THE IDOS SHALL invalidar las Hypotheses asociadas, registrar/notificar revisión requerida y crear propuesta `SELL/PENDING_REVIEW`; Opportunity y posición permanecerán sin cambios hasta decisión atribuible del gestor.
9. THE Exit_Engine SHALL clasificar propuestas en cinco tipos: Thesis_Invalidation (propuesta total), Risk_Exit (re-assessment primero; si tesis cambió, propuesta total), Valuation_Exit (propuesta parcial únicamente), Portfolio_Exit (comparación de valor marginal ajustado por riesgo) y Objective_Achieved (propuesta parcial o total). Ninguna propuesta SHALL ejecutar una transacción automáticamente.
10. THE IDOS SHALL exigir decisión humana atribuible y justificada antes de cualquier salida; las señales técnicas por sí solas nunca autorizan una venta.
11. THE Capital_Allocation_Engine SHALL verificar que la liquidez de Core_1 nunca financia compras ofensivas de Core_3 o Core_4; esta regla es no negociable y no puede anularse por configuración.
12. WHEN se ejecuta una transacción de compra, THE Paper_Trader SHALL persistir el `entry_snapshot.yml` con: tesis, assessments, técnicos de entry_policy, catalizadores, riesgos, dominios y fundamentales en el momento de la entrada.
13. WHEN el Portfolio_Domain detecta que un Core supera su rango estructural máximo o que un activo supera su `max_weight`, THE Allocation_Engine SHALL preferir utilizar nuevo capital entrante y efectivo disponible para corregir la desviación antes de vender activos de calidad; la venta de activos como mecanismo de rebalanceo requiere justificación explícita de que no existe alternativa de financiación con nuevo capital o efectivo.
14. THE Thesis_Monitor_Worker SHALL utilizar Jev (`Noul` — probabilidad de que la tesis permanezca válida) para evaluar el estado de cada hipótesis activa ante nuevos eventos; cuando el `Noul` de validez de tesis cae por debajo del umbral configurado, escalará al LLM_Service para análisis cualitativo profundo antes de emitir `thesis_active == False`; este diseño reduce el consumo de tokens LLM en 80–90% para monitoreos rutinarios.

#### Propiedades de Corrección (Property-Based Testing)

- **Invariante de sizing**: Para toda posición activa, `position_weight <= max_weight` configurado en el Strategy_Profile y la suma de pesos de todas las posiciones activas `<= 100%` de la Cartera_Financiera_Liquida. Propiedad de invariante.
- **Idempotencia del Entry_Monitor**: Ejecutar el Entry_Monitor_Worker N veces el mismo día sobre la misma Buy_List sin cambios en datos produce la misma señal (o no-señal). Propiedad de idempotencia.
- **Conservación del capital en liquidación parcial**: Para toda Valuation_Exit o Portfolio_Exit parcial, el peso de la posición después es estrictamente menor que antes, pero mayor que 0. Propiedad de metamorfismo.
- **Integridad del entry_snapshot**: Para todo `entry_snapshot.yml` generado al ejecutar una compra, el parse del archivo produce exactamente los mismos datos usados para tomar la decisión de entrada. Propiedad de round-trip.

---

### Requirement 7: Learning Domain — Post Mortem, Backtesting y Calibración

**User Story:** Como gestor del fondo, quiero que el sistema analice retrospectivamente cada inversión cerrada evaluando calidad de tesis, decisión y asignación de forma independiente, para que el proceso mejore continuamente y el aprendizaje no se reduzca a si la posición ganó o perdió dinero.

#### Acceptance Criteria

1. THE Post_Mortem_Worker SHALL ejecutarse de forma obligatoria para toda Opportunity que transite a `EXITED`, sin posibilidad de ser omitido.
2. THE Post_Mortem_Worker SHALL evaluar por separado y de forma independiente: calidad de la tesis, calidad de la decisión con la información disponible en ese momento, calidad de la asignación de capital, calidad de la ejecución, resultado financiero en moneda fuerte y resultado en poder adquisitivo argentino.
3. WHERE el `research_protocol` fue `FULL_DDD`, THE Post_Mortem_Worker SHALL comparar cada Prediction con el valor real observado antes de clasificarla en: confirmada, parcialmente confirmada o fallida; la comparación (`expected_value_compared`) es precondición para la clasificación.
4. THE Post_Mortem_Worker SHALL evaluar si el retorno de la inversión deriva del cumplimiento de la tesis o de factores externos aleatorios (suerte de mercado).
5. WHEN el Post_Mortem_Worker completa el análisis, THE IDOS SHALL persistir el informe en almacenamiento privado excluido del repositorio público (`private-data/learning/post_mortems/` en ejecución local) y SHALL actualizar el estado de la Opportunity a `POST_MORTEM`. La operación remota requiere almacenamiento privado persistente antes de habilitarse.
6. THE Post_Mortem_Worker SHALL registrar los sesgos detectados, errores de proceso y lecciones aprendidas en formato estructurado usando el schema `{decision_id, outcome, thesis_accuracy, decision_quality, allocation_quality, execution_quality, process_violations, unexpected_events, biases_detected, lesson, rule_or_template_change, recorded_at}`.
7. THE Learning_Domain SHALL proponer ajustes versionados de los pesos del RPF por estrategia a partir de Post_Mortems acumulados. Solo tras aprobación humana, pruebas y despliegue controlado SHALL aplicarlos y registrar `rpf_weights_updated == true` en el log de auditoría.
8. WHEN el Decision_Board aprueba el informe de Post_Mortem, THE State_Machine SHALL transicionar la Opportunity de `POST_MORTEM` a `ARCHIVED`.
9. THE Learning_Domain SHALL proponer ajustes a los umbrales del Wyckoff_Indicator y a los limits de Strategy_Profiles basándose en post-mortems, pero no SHALL aplicarlos sin revisión y aprobación humana.
10. WHEN el Thesis_Monitor_Worker se ejecuta para posiciones activas del portfolio, THE IDOS SHALL calcular y actualizar `last_thesis_assessment_at` después de cada ejecución.
11. THE Post_Mortem_Worker SHALL utilizar Jev (`Choice(THESIS/LUCK/BOTH/UNCLEAR)`) para clasificar el origen del retorno de cada inversión, y `Score` para evaluar la calidad de la tesis, la decisión, la asignación y la ejecución de forma independiente; este output estructurado alimenta directamente el Auto_Learning_Cycle sin post-procesamiento manual.
12. THE Auto_Learning_Cycle SHALL ejecutarse automáticamente cuando se acumulen ≥ 5 nuevos post-mortems desde la última calibración; generará propuestas de ajuste para: (1) pesos de dimensiones del RPF por estrategia, (2) thresholds del Wyckoff_Indicator, (3) límites de position sizing en los Strategy_Profiles; las propuestas son inmutables y auditables; ningún parámetro se modifica sin aprobación explícita del titular.
13. THE Learning_Engine SHALL mantener una Agent_Memory procedimental que persiste los parámetros calibrados históricamente con su timestamp, los post-mortems que los originaron y la razón del ajuste; esta memoria permite reconstruir cómo evolucionaron los parámetros del sistema a lo largo del tiempo.

#### Propiedades de Corrección (Property-Based Testing)

- **Completitud del post mortem**: Para toda Opportunity en estado `ARCHIVED`, existe exactamente un informe de Post_Mortem completado. Propiedad de invariante.
- **Trazabilidad de predicciones**: Para toda Prediction evaluada en un Post_Mortem, el valor real observado puede rastrearse hasta una fuente de datos verificable en la Knowledge_Base. Propiedad de invariante de cadena de evidencia.
- **Convergencia de calibración**: Para el RPF calibrado con al menos 20 Post_Mortems, la probabilidad histórica de rerating para scores > 85 debe ser estadísticamente superior a la de scores < 60. Propiedad de metamorfismo de orden.

---

### Requirement 8: Infraestructura Técnica — Event Bus y Workers

**User Story:** Como desarrollador del sistema, quiero que todos los componentes se comuniquen mediante un Event_Bus asíncrono y que los Workers hereden de Base_Worker, para que el sistema sea desacoplado, testeable y extensible sin modificar el código de Workers existentes al agregar nuevas estrategias.

#### Acceptance Criteria

1. THE Event_Bus SHALL operar como singleton in-memory con historial persistido en SQLite.
2. THE Event_Bus SHALL soportar los eventos del dominio: `DiscoveryCompleted`, `DeepDDCompleted`, `BoardApproved`, `EntryConditionConfirmed`, `QuarterlyResultsParsed`, `ThesisBroken`, `ThesisReassessed`, `PostMortemCompleted`, `CommitRequest`, `StrategySignalGenerated`, `CashFallbackActivated`.
3. THE Base_Worker SHALL gestionar automáticamente: RunManifest, telemetría (via `sdk.telemetry.trace()`), notificaciones al Notification_Center y checkpoint/recovery.
4. THE Base_Worker SHALL clasificar todos los Workers en dos categorías: Data_Workers (deterministas, sin LLM) y AI_Workers (heurísticos, con LLM).
5. WHEN un Worker finaliza, THE Base_Worker SHALL registrar el estado de ejecución en uno de los estados: `SUCCESS`, `PARTIAL_SUCCESS`, `FAILED`, `CANCELLED`.
6. THE Git_Queue_Worker SHALL ser el único proceso autorizado para ejecutar `git push`; todos los Workers SHALL publicar un evento `CommitRequest` al Event_Bus en lugar de escribir directamente.
7. THE Git_Queue_Worker SHALL procesar la cola de `CommitRequest` leyendo la tabla `pending_commits` de SQLite y SHALL agrupar múltiples archivos modificados en un único commit atómico.
8. THE IDOS SHALL organizarse en un único repositorio `idos` con separación lógica de directorios: `idos-core/`, `idos-config/`, `idos-knowledge/`, `idos-journal/`.
9. THE SQLite_Store SHALL activar `PRAGMA foreign_keys=ON` y `PRAGMA journal_mode=WAL`, envolver toda escritura en transacciones con commit/rollback explícito, e implementar índices en todas las columnas de búsqueda frecuente.
10. THE IDOS SDK SHALL exponer una fachada unificada `idos.sdk` con re-exportación de módulos: `idos.data`, `idos.market`, `idos.ai`, `idos.events`, `idos.resilience`, `idos.portfolio`, `idos.telemetry`, `idos.notifications`, `idos.provenance`, `idos.workers`.
11. THE IDOS SDK SHALL ser instalable mediante `pip install -e .` con dependencias en `pyproject.toml`, compatible con Python 3.11+.
12. THE IDOS SHALL implementar los dominios principales (Research, Decision, Portfolio, Learning) como agentes especializados que heredan de `AgentBase`; cada agente mantiene Agent_Memory con sus tres capas (episódica, semántica, procedimental) y puede recuperar contexto histórico relevante antes de ejecutar su tarea.
13. THE Agent_Orchestrator SHALL coordinar el flujo del Decision Pipeline delegando tareas a sub-agentes según el tipo de evento recibido del Event_Bus; el Agent_Orchestrator no ejecuta análisis directamente — solo enruta, consolida resultados y gestiona el ciclo de vida del pipeline.
14. THE Jev_Service SHALL operar como singleton análogo al LLM_Service, configurado en `idos-config/models.yml`; todos los Workers y agentes que necesiten decisiones tipadas (scoring, clasificación, routing, validación) obtendrán el Jev_Service desde el contexto compartido (`config.get("jev_service")`), sin instanciar el cliente directamente.

#### Propiedades de Corrección (Property-Based Testing)

- **Serialización del Event_Bus**: Para todo evento publicado, `deserialize(serialize(event)) == event`. Los campos del evento sobreviven el ciclo completo de persistencia en SQLite. Propiedad de round-trip.
- **Orden de la cola de commits**: Para N eventos `CommitRequest` publicados en orden cronológico, el Git_Queue_Worker los procesa en el mismo orden FIFO. Propiedad de invariante de orden.
- **Idempotencia del Git_Queue_Worker**: Si el Git_Queue_Worker procesa el mismo `CommitRequest` dos veces (por retry), el repositorio Git termina en el mismo estado que si se hubiera procesado una sola vez. Propiedad de idempotencia.

---

### Requirement 9: LLM Service — Acceso a Modelos de Lenguaje

**User Story:** Como desarrollador del sistema, quiero que todos los Workers accedan a los LLMs a través de un servicio centralizado con resiliencia automática, para que los fallos de proveedores no interrumpan el proceso de análisis y los modelos deterministas no paguen el costo de orquestación de IA.

#### Acceptance Criteria

1. THE LLM_Service SHALL operar como singleton con configuración cargada desde `idos-config/models.yml` una única vez.
2. THE LLM_Service SHALL soportar los tipos de tarea de Research: `reasoning` y `analysis` (DDD/AOIF y síntesis de hipótesis) y `classification` (categorización de documentos de Research).
3. THE LLM_Service SHALL gestionar automáticamente: selección de proveedor por `task_type`, rate limiting (RPM y RPD por proveedor), circuit breaker (CLOSED/OPEN/HALF_OPEN) y fallback intra-proveedor de un solo intento al `fallback_model` ante 404, 408, 429 o errores transitorios 5xx; errores de cliente no reintentables no activan el fallback.
4. WHEN un proveedor LLM falla N veces consecutivas (configurable, default 3), THE LLM_Service SHALL activar el circuit breaker y SHALL saltar dicho proveedor por `recovery_timeout` segundos (default 60).
5. THE LLM_Service SHALL implementar retry con exponential backoff: espera inicial 4s, máximo 16s, máximo 5 intentos; IF `Retry-After > 120s`, THEN THE LLM_Service SHALL fallar inmediatamente para forzar failover.
6. THE LLM_Service SHALL registrar telemetría por cada llamada: provider, model, tokens_in, tokens_out, latency_ms, status.
7. THE Workers SHALL obtener el LLM_Service desde el contexto compartido (`config.get("llm_service")`); no SHALL instanciar LLMClient directamente.
8. THE Assessment_Pipeline, THE DecisionBoardWorker, THE Entry_Monitor_Worker, THE Wyckoff_Indicator y THE Post_Mortem_Worker SHALL ser deterministas y no SHALL llamar al LLM_Service. El DecisionBoardWorker SHALL basar estado, recomendación, evaluación de reglas y rationale exclusivamente en resultados deterministas; IF una llamada al LLM_Service ocurre dentro de esos componentes, THEN THE IDOS SHALL permitir la llamada pero SHALL registrarla como `process_violation` en el RunManifest y en el log de auditoría.
9. THE LLM_Service SHALL exponer un método `health()` que retorne el estado de todos los proveedores con: circuit state, RPM restantes, RPD restantes.
10. WHEN un proveedor retorna JSON estructurado inválido, THE LLM_Service SHALL intentar normalización determinista y sin otra llamada al proveedor; IF el resultado no parsea o Research rechaza el contrato de contenido, THEN SHALL fallar de forma cerrada antes de persistir o avanzar etapas.
11. THE IDOS SHALL separar explícitamente las responsabilidades entre LLM_Service y Jev_Service: el LLM_Service se usa en Research para analizar texto libre (AOIF, síntesis de hipótesis y razonamiento cualitativo). Assessment, Decision y Post-Mortem SHALL usar reglas y evidencia deterministas. Jev_Service sólo SHALL adoptarse para scoring, clasificación, routing, validación de completitud o probabilidades de thesis validity después de evaluación en modo sombra y un contrato versionado; un Worker no debe usar LLM_Service donde una decisión tipada y validada sea suficiente.
12. WHEN THE LLM_Service solicita una respuesta estructurada JSON a un proveedor compatible, SHALL solicitar su modo de salida JSON; SHALL unir todas las partes textuales de la respuesta; y SHALL tratar cualquier `finishReason` distinto de `STOP` como respuesta incompleta y fallar de forma cerrada. Un error de parsing SHALL registrar posición y causa sin exponer secretos, y no SHALL persistir resultados parciales.

#### Propiedades de Corrección (Property-Based Testing)

- **Corrección del circuit breaker**: Para un proveedor que falla exactamente `failure_threshold` veces consecutivas, el circuit breaker transiciona exactamente de `CLOSED` a `OPEN`. Para un proveedor que falla `failure_threshold - 1` veces y luego tiene éxito, permanece en `CLOSED`. Propiedad de invariante.
- **Exclusión del proveedor en OPEN**: Mientras un circuit breaker está en estado `OPEN`, ninguna llamada al LLM_Service utiliza ese proveedor. Propiedad de invariante.
- **Round-trip del Self-Healing**: Para un JSON inválido reparable, la normalización determinista debe producir JSON parseable; una salida que no pueda repararse no puede reemplazar Research válido ni avanzar a Assessment.

---

### Requirement 10: Resiliencia y Tolerancia a Fallos

**User Story:** Como operador del sistema, quiero que el IDOS continúe operando ante fallos temporales de infraestructura sin perder conocimiento ni trabajo ya realizado, para que el proceso de inversión sea continuo y autónomo incluso en entornos con conectividad intermitente.

#### Acceptance Criteria

1. THE Base_Worker SHALL implementar una arquitectura de Defensa en Capas: Retry → Failover → Self-Healing → Circuit_Breaker → Graceful_Degradation → Checkpoint → Graceful_Shutdown → Recovery.
2. THE Base_Worker SHALL persistir checkpoints durante procesos largos (Scout, DDD, actualización masiva de wikis) para permitir la reanudación desde el último punto de control sin recomenzar desde cero.
3. WHEN un proceso se interrumpe y existe un checkpoint, THE Base_Worker SHALL reanudar desde el checkpoint en la próxima ejecución y SHALL registrar `resumed_from_checkpoint == true` en el RunManifest.
4. IF una fuente de datos primaria no está disponible, THEN THE Base_Worker SHALL intentar fuentes alternativas (e.g., StockAnalysis → Yahoo Finance → SEC EDGAR → última copia local) y SHALL registrar la degradación en el Error_Manager.
5. THE Error_Manager SHALL ser el único origen de datos para reportes de errores; SHALL persistir errores deduplicados por `fecha + ticker + firma` en `cache/data_errors.json`.
6. THE Error_Manager SHALL consolidar todos los errores del día en UN único issue de GitHub `⚠️ IDOS: errores de datos [fecha]`; errores de severidad `alta` SHALL disparar además notificación inmediata por Telegram.
7. THE Notification_Center SHALL implementar tres niveles: Nivel 1 (Información, solo Dashboard), Nivel 2 (Atención, email/digest diario), Nivel 3 (Acción, Telegram + Email inmediato).
8. THE IDOS SHALL ejecutar Health Checks antes de iniciar cualquier Worker, verificando: conexión Git, acceso SQLite, disponibilidad de proveedores LLM, acceso a fuentes financieras y espacio en disco.
9. IF falla una validación crítica en el Health Check, THEN THE Worker no deberá iniciarse y SHALL notificar al Notification_Center con prioridad alta.
10. THE IDOS SHALL calcular y reportar los KPIs de confiabilidad: Success_Rate (objetivo > 98%), Recovery_Rate (objetivo > 95%), Retry_Success_Rate (objetivo > 80%), Mean_Recovery_Time (objetivo < 10 min).
11. WHEN un proceso finaliza, THE Base_Worker SHALL persistir un RunManifest con: run_id, worker, status, started_at, ended_at, provider_used, fallbacks, checkpoint, files_modified, notifications, errors, git_commit.

#### Propiedades de Corrección (Property-Based Testing)

- **Idempotencia de recovery**: Si un Worker se interrumpe en el punto N de M elementos procesados y se reinicia desde el checkpoint, el resultado final es idéntico al que se habría obtenido sin interrupción. Propiedad de idempotencia de checkpoint.
- **Conservación de conocimiento**: Después de cualquier fallo (Transitorio, Infraestructura, Proveedor LLM, Datos), todo el conocimiento generado antes del fallo puede recuperarse desde Git o SQLite sin pérdida. Propiedad de invariante de durabilidad.
- **Deduplicación de errores**: Si el Error_Manager recibe el mismo error (mismo `fecha + ticker + firma`) N veces, persiste exactamente una entrada en `cache/data_errors.json`. Propiedad de idempotencia.

---

### Requirement 11: Pipelines de CI/CD y Workflows Operativos

**User Story:** Como operador del sistema, quiero que el IDOS ejecute sus procesos automáticamente mediante GitHub Actions en frecuencias definidas y con scripts versionados, para que el ciclo de inversión funcione sin intervención manual continua y el mismo código se ejecute en local y en CI.

#### Acceptance Criteria

1. THE Monthly_Universe_Pipeline SHALL ejecutarse automáticamente el día 1 de cada mes vía GitHub Actions `schedule`, SHALL ejecutar el `discovery_filter` de todas las estrategias habilitadas, y SHALL admitir ejecución manual via `workflow_dispatch`.
1a. THE Monthly_Universe_Pipeline SHALL usar `idos-config/universe/operable.yml` como registro común de elegibilidad de activos, incluidos activos que no sean CEDEARs; cada estrategia SHALL intersectarlo con su universo propio configurado cuando exista, antes de consultar datos o generar Opportunities.
1b. WHEN un Strategy_Profile declara `supported_asset_types`, THE Monthly_Universe_Pipeline SHALL excluir otros tipos antes del fetch; las ejecuciones manuales SHALL poder limitar candidatos a un máximo de cinco instrumentos de `operable.yml` sin cambiar el universo de las ejecuciones programadas.
1c. WHEN el perfil `COMPOUNDER` declara soporte para acciones, THE Universe_Pipeline SHALL aceptar cualquier acción individual de `operable.yml` sin restringir país de cotización o domicilio; el tipo canónico SHALL ser `equity` y `us_equity` SHALL aceptarse como alias legado. ETFs seguirán fuera de COMPOUNDER.
2. THE DDD_Research_Pipeline SHALL ejecutarse el día 2 del mes (modo NORMAL), cada 30 días (modo FORCE), y SHALL admitir `workflow_dispatch` con input `ticker` y `force`, y `repository_dispatch` para `quarterly-results`; WHEN el día 2 y el ciclo FORCE de 30 días coinciden para el mismo ticker, THE DDD_Research_Pipeline SHALL ejecutar ambos modos en la misma ejecución procesando FORCE primero.
2a. THE IDOS SHALL ejecutar Discovery, Research y Assessment mediante
agentes/workers configurados, de forma autónoma y sin solicitar ni requerir
aprobación, confirmación o datos ingresados por el gestor. Los errores, gates
fallidos y evidencia insuficiente SHALL quedar registrados con estado explícito
para completar el expediente y presentarlo en Decision Board.

2b. THE Decision_Board SHALL ser el primer y único checkpoint del flujo de
oportunidades que requiera una acción humana autenticada. SHALL reunir en una
misma revisión la decisión, justificación, identidad y confirmación de fuentes
y fechas contra el paquete vigente. La ausencia de acción humana SHALL mantener
la propuesta pendiente; ningún agente SHALL inferir aprobación.

2c. La finalización autónoma de las etapas previas SHALL NOT crear por sí sola
una aprobación, entrada a Buy_List, posición, orden ni autorización de
operación. Sólo una decisión válida registrada en Decision_Board puede habilitar
la transición posterior definida por la política de entrada.

3. THE Daily_Data_Refresh_Pipeline SHALL ejecutarse de lunes a viernes a las 8:00 UTC y SHALL ejecutar en orden: (1) refresh de datos financieros y benchmark SPY, (2) refresh de Buy_List, (3) Entry_Monitor, (4) Paper_Trader, (5) Risk_Monitor, (6) reporte de errores de datos.
4. THE CI_Pipeline SHALL ejecutar en todo commit a `main`: linting (ruff), tests unitarios (pytest), verificación de tipos (mypy) y validación de schemas YAML de `idos-config/` incluyendo Strategy_Profiles.
5. THE IDOS SHALL usar scripts versionados en `scripts/` en lugar de bloques `python -c` embebidos en los workflows YAML, para garantizar que el mismo código se ejecuta en local y en GitHub Actions.
6. THE DDD_Research_Pipeline SHALL detectar cuando `earnings_date` de un ticker en `idos-config/events/earnings.yml` ha vencido y SHALL disparar un `repository_dispatch` para reprocesar ese ticker en modo FORCE.
7. THE Monthly_Universe_Pipeline SHALL ejecutar el Step 7 Monthly Evaluation, aplicando el `score_threshold` de cada estrategia para ajustar transiciones WATCHLIST/SCREENED; Opportunities en `APPROVED` o estados posteriores nunca se modifican.
8. THE IDOS SHALL publicar automáticamente el Dashboard estático en GitHub Pages al finalizar el DDD_Research_Pipeline.
9. THE Telegram_Bot SHALL ejecutarse en modo único dentro de los workflows GHA para enviar alertas cuando un Worker falla, usando el step `if: failure()`.

---

### Requirement 12: Dashboard e Interfaz de Usuario

**User Story:** Como gestor del fondo, quiero que el IDOS me presente una interfaz clara y priorizada con las acciones relevantes del día, consciente de los Cores y estrategias activas, para que pueda gestionar el fondo de forma eficiente dedicando únicamente el tiempo necesario.

#### Acceptance Criteria

1. THE Dashboard público SHALL organizar el flujo de oportunidades hasta la Buy_List: Watchlist_Widget (top oportunidades por score, con strategy_id visible), Buy_List_Widget (oportunidades con entry_policy, decisión pendiente y condiciones de entrada), Alerts_Widget (riesgos de oportunidades y tesis debilitadas) y Calendar_Widget (próximos earnings y revisiones planificadas).
2. THE Dashboard público SHALL ser estático (HTML/JS generado, sin servidor de aplicaciones) y SHALL poder publicarse en GitHub Pages; SHALL mostrar Research/DDD e hipótesis no aprobadas con estado provisional y procedencia visible para revisión del gestor.
2a. THE Portfolio_Widget SHALL consumir exclusivamente una fuente privada autenticada (por ejemplo, Google Sheets privado); posiciones, tenencias, efectivo, transacciones, Risk Audit y métricas patrimoniales SHALL NOT incluirse en el HTML, JSON, artifacts o commits públicos de GitHub Pages. Si no hay una interfaz privada conectada, el widget SHALL permanecer fuera de Pages.
3. THE Decision_Inbox SHALL agregar todas las propuestas que requieren intervención humana ordenadas por prioridad (Alta, Media, Baja), con gate fallido, strategy_id, acción requerida y límite estimado.
4. THE Dashboard SHALL mostrar la alerta `is_stale` ("Research stale Nd") únicamente para Opportunities en `SCREENED` o `UNDER_RESEARCH` cuando `last_research_at` supera los 30 días.
5. La vista privada del portfolio SHALL mostrar la alerta `is_thesis_stale` ("Tesis sin evaluar Nd") para posiciones activas (`ACCUMULATING`, `ACTIVE`, `REDUCED`, `MONITORING`) cuando `last_thesis_assessment_at` supera los 30 días; esta alerta no se serializa en Pages.
6. THE Dashboard SHALL mostrar tablas con columnas ordenables (clic en encabezado alterna ASC/DESC con indicador ▲/▼) y búsqueda por ticker en vivo sobre la tabla.
7. THE Dashboard SHALL generar una vista pública de detalle de oportunidad con: arquitectura (Core, Sleeve, Risk Overlays), tesis y su estado de aprobación, Research/DDD, hipótesis, procedencia, gates evaluados (PASS/FAIL y detalle persistido), scores provisionales, entry_policy, condiciones de entrada y strategy_id. Cuando exista resultado de RULE-008, SHALL mostrarlo como asimetría provisional junto con el detalle de la regla; si falta en un registro histórico, SHALL indicar que el detalle no fue persistido. La asimetría por sí sola no SHALL autorizar una compra. El impacto patrimonial y los gates dependientes de posiciones se mostrarán como pendientes de datos privados; sus valores reales sólo estarán disponibles en la vista privada.
8. THE Telegram_Bot SHALL soportar los comandos: `/watchlist`, `/dashboard`, `/scout TICKER1,TICKER2`, `/opp-list`, `/position-list`, `/event-log`, `/help`.
9. WHEN un Core supera su rango estructural máximo configurado, la vista privada del portfolio SHALL mostrar una alerta visual; la alerta puede activarse también por otras condiciones definidas en el sistema y no se publica en Pages.
10. THE Notification_Center SHALL enviar un único Digest_Inteligente semanal consolidado en lugar de notificaciones individuales por cada evento de baja prioridad.
11. Cada fila de Buy_List SHALL identificar la Opportunity vinculada y mostrar el estado vigente de su tesis y su próxima fecha de revisión. Una tesis invalidada, vencida, sin oportunidad vinculada o cuya vigencia no pueda verificarse SHALL mostrarse como `requiere revisión` y SHALL NOT presentarse como lista para actuar; la señal de una estrategia sistemática sin agenda de tesis requiere su propia validación.
12. Cada alerta del dashboard SHALL exponer un identificador determinista, tipo, estado activo, severidad, ticker y mensaje. El identificador SHALL mantenerse mientras persista la misma condición y fuente; una actualización SHALL conservar la identidad y reflejar el valor actual. El snapshot SHALL deduplicar alertas repetidas de la misma fuente y condición, y una alerta SHALL dejar de aparecer cuando su condición ya no esté presente.

---

### Requirement 13: Trazabilidad y Provenance

**User Story:** Como auditor del fondo, quiero que toda conclusión analítica pueda rastrearse hasta su fuente de datos original y su gate aprobador, para que el proceso de inversión sea completamente reproducible y auditable en cualquier momento histórico.

#### Acceptance Criteria

1. THE Provenance_Engine SHALL vincular cada campo de un Assessment y de una Decision con su fuente mediante una Provenance_Entry con campos: `id`, `entidad_origen`, `campo_vinculado`, `fuente`, `version`, `timestamp`, `referencias_evidencia`.
2. THE Provenance_Engine SHALL persistir todas las Provenance_Entries en la tabla SQLite `provenance_chain`.
3. WHEN se genera un Assessment, THE Assessment_Engine SHALL enlazar cada `finding` y `recommendation` a la Provenance_Entry correspondiente antes de persistir el resultado.
4. THE IDOS SHALL poder reproducir el estado completo de la Knowledge_Base en cualquier fecha histórica usando el historial de Git.
5. THE Decision SHALL almacenar la versión exacta de la Knowledge_Base utilizada en el momento de la decisión, referenciando el commit de Git correspondiente.
6. THE Backtesting_Engine SHALL poder evaluar si una Decision pasada era correcta usando únicamente la información disponible en la Knowledge_Base en la fecha de esa Decision.
7. THE Provenance_Engine SHALL exponer los métodos: `link(conclusion_id, evidence_id, evidence_type, source, metadata)`, `get_chain(conclusion_id)`, `get_by_evidence(evidence_id)`.

#### Propiedades de Corrección (Property-Based Testing)

- **Completitud de la cadena de provenance**: Para todo Assessment generado, `len(provenance_chain(assessment.id)) >= 1`. Ningún Assessment puede existir sin al menos una Provenance_Entry vinculada. Propiedad de invariante.
- **Round-trip de provenance**: Para toda Provenance_Entry persistida en SQLite, `deserialize(serialize(entry)) == entry`. Propiedad de round-trip.
- **No-pérdida en reconstrucción**: Dado el estado de Git en el commit `C`, reconstruir la Knowledge_Base desde Git produce exactamente el mismo estado que tenía en el momento del commit `C`. Propiedad de round-trip de reconstrucción.

---

### Requirement 14: Principios de Inversión y Reglas No Negociables

**User Story:** Como inversor del fondo, quiero que el sistema codifique los principios filosóficos de inversión como reglas no negociables evaluadas en los Gates, para que ninguna decisión pueda violarlos independientemente del estado del mercado o del atractivo de una oportunidad.

#### Acceptance Criteria

1. IF alguna de las cinco preguntas de la Regla Suprema responde negativamente para una Opportunity `FULL_DDD`, THEN THE Decision_Engine SHALL rechazar dicha Opportunity: (1) ¿Existe un negocio excepcional subyacente?, (2) ¿Hay evidencia trazable de que el consenso del mercado está equivocado?, (3) ¿Existe un catalizador razonable para el rerating?, (4) ¿La expectativa de rentabilidad frente al riesgo es al menos 3:1?, (5) ¿La incorporación mejora la calidad y diversificación del portfolio?
2. THE Decision_Orchestrator SHALL optimizar las decisiones por Valor Esperado (EV = probabilidad × magnitud), no por tasa de aciertos, según el Principio de Expected Value.
3. THE IDOS SHALL clasificar toda afirmación en la Knowledge_Base como `HECHO`, `INFERENCIA` o `HIPÓTESIS`, y SHALL nunca presentar hipótesis como hechos objetivos.
4. THE IDOS SHALL exigir decisión humana atribuible y justificada antes de cualquier salida; señales técnicas por sí solas nunca autorizan una venta.
5. THE IDOS SHALL exigir que toda tesis de inversión `FULL_DDD` tenga condiciones de falsación explícitas antes de ser promovida al Decision_Board; una tesis sin condiciones de falsación es inválida.
6. IF `averaging_down_without_formal_review == true`, THEN THE Decision_Engine SHALL bloquear la operación de averaging down y SHALL registrar `averaging_down_prohibited == true` en el Decision log; la reevaluación formal requerida debe confirmar simultáneamente: tesis sin deterioro, expected value mejorado, riesgo aceptable y capacidad disponible.
7. THE LLM_Service SHALL estar restringido a Research: síntesis de conocimiento no estructurado, generación de hipótesis y análisis AOIF. Assessment, Decision y Post_Mortem SHALL usar reglas y evidencia deterministas. El LLM_Service no SHALL poder superar gates duros del Decision_Orchestrator.
8. THE IDOS SHALL tratar el efectivo como posición estratégica válida; nunca SHALL forzar la inversión del 100% del capital; el resultado `NO_ACTION` o `WAIT` es una salida legítima del Decision_Engine.
9. THE IDOS SHALL separar la función del capital (Core/Sleeve) de la geografía; Argentina es un Risk_Overlay, no un Core; un bono argentino puede ser Core 2 si su función es preservación.
10. THE IDOS SHALL registrar como `process_violation` en el post-mortem toda decisión que no cuente con contrato de entrada completo (`ide_input`) o que haya saltado un gate aplicable.

---

### Requirement 15: Knowledge Lifecycle — Gestión del ciclo de vida del conocimiento

**User Story:** Como analista del fondo, quiero que el conocimiento del sistema evolucione de forma incremental y trazable sin perder información histórica, para que la memoria institucional del fondo sea permanente, recuperable y compatible con búsqueda semántica futura.

#### Acceptance Criteria

1. THE Knowledge_Base SHALL nunca eliminar información histórica; toda actualización SHALL realizarse mediante versionado incremental, no mediante sobrescritura.
2. THE Knowledge_Base SHALL mantener separación estricta entre `idos-knowledge/` (hechos objetivos verificables) e `idos-journal/` (proceso de decisión subjetivo).
3. THE Knowledge_Base SHALL asignar a cada Knowledge_Object los campos de frescura: `freshness`, `confidence`, `last_review`, `owner`, `source_count`, `review_frequency`.
4. THE Knowledge_Base SHALL detectar automáticamente contradicciones entre datos nuevos y afirmaciones existentes y SHALL generar una tarea de revisión obligatoria en el Decision_Inbox.
5. THE Knowledge_Base SHALL implementar Atomic_Knowledge: cada sección wiki es un objeto independiente actualizable sin modificar otros objetos.
6. THE Knowledge_Base SHALL clasificar todo conocimiento siguiendo la arquitectura de capas: Raw_Data → Evidence → Facts → Knowledge_Objects → Wiki → Reasoning → Decision.
7. THE Knowledge_Base SHALL ser completamente legible y procesable por LLMs (formato YAML/Markdown con metadatos estructurados) y SHALL ser compatible con búsqueda vectorial (embeddings) para búsqueda RAG; los embeddings de documentos de la Knowledge_Base SHALL generarse y actualizarse cuando se crea o modifica un Knowledge_Object; `knowledge_llm_readable == true` y `vector_search_compatible == true` son requisitos presentes, no diferidos.
8. WHEN la base de datos SQLite se corrompe o se elimina, THE IDOS SHALL poder reconstruirla completamente a partir de `idos-knowledge/` e `idos-journal/` en Git; IF la reconstrucción falla, THEN THE IDOS SHALL continuar operando en modo degradado (read-only/Git-only) sin bloquear todas las operaciones del sistema.

#### Propiedades de Corrección (Property-Based Testing)

- **Reconstrucción desde Git**: Dado el directorio `idos-knowledge/` e `idos-journal/` en cualquier commit de Git, reconstruir el estado de SQLite produce un conjunto de registros consistente con el contenido de los archivos YAML/Markdown. Propiedad de round-trip de reconstrucción.
- **Inmutabilidad del historial**: Para cualquier Knowledge_Object con versión `v1`, después de crear la versión `v2`, `v1` permanece intacta y accesible. Propiedad de invariante.

---

### Requirement 16: Arquitectura Patrimonial de 4 Cores

**User Story:** Como gestor del patrimonio familiar, quiero que el sistema organice todo activo dentro de una arquitectura de 4 Cores con función explícita asignada por el Portfolio_Architect, para que cada decisión de asignación de capital sea coherente con los objetivos patrimoniales y nunca se mezclen activos de función defensiva con activos de crecimiento ofensivo.

#### Acceptance Criteria

1. THE Portfolio_Architect SHALL asignar a todo activo con posición abierta exactamente un Core de los siguientes: `CORE_1` (función: SURVIVAL/LIQUIDITY/OPTIONALITY, rango estructural 10–25% de la Cartera_Financiera_Liquida), `CORE_2` (función: preservación patrimonial y reducción de fragilidad, rango 15–30%), `CORE_3` (función: crecimiento patrimonial y capitalización de largo plazo, rango 40–60%), `CORE_4` (función: alfa, asimetría y oportunidades especiales, rango 5–20%).
2. WHERE `asset_core_assigned == true`, THE Portfolio_Architect SHALL asignar el Core basándose exclusivamente en la función del capital, no en la geografía del activo; un bono CER puede ser Core_2; una acción argentina puede ser Core_4; el oro puede ser Core_2 o Core_3 según contexto patrimonial.
3. THE Core_3 SHALL subdividirse en los siguientes Sleeves configurables: `Global_Base` (exposición amplia y diversificada), `Systematic_Return` (estrategias sistemáticas como Momentum), `High_Conviction_Long_Term` (compounders de largo plazo); otros Sleeves pueden declararse en `idos-config/strategies/`.
4. THE IDOS SHALL calcular los pesos de los Cores exclusivamente sobre la Cartera_Financiera_Liquida; el inmueble, participaciones ilíquidas y pasivos se incluyen en el patrimonio total para análisis de concentración patrimonial, pero no en el denominador de pesos de Core.
5. IF la suma de pesos de un Core supera su rango estructural máximo configurado, THEN THE Portfolio_Architect SHALL registrar una alerta en el Decision_Inbox y SHALL requerir decisión explícita para mantener la sobreasignación.
6. THE Capital_Allocation_Engine SHALL impedir que la liquidez de Core_1 financie posiciones ofensivas de Core_3 o Core_4; esta restricción es estructural y no puede ser anulada por configuración.
7. WHEN el Portfolio_Architect evalúa un nuevo activo candidato, THE Portfolio_Architect SHALL ejecutar el proceso: (1) identificar función primaria, (2) asignar Core y Sleeve, (3) mapear Risk_Overlays, (4) evaluar solapamiento y contribución de diversificación, (5) determinar rango estructural, y SHALL persistir el output en `portfolio_architecture.yml`.
8. THE Dashboard SHALL mostrar los pesos actuales por Core sobre la Cartera_Financiera_Liquida con indicador visual de rango estructural (dentro/fuera de rango).
9. THE IPS y la Investment_Constitution SHALL constituir la fuente de verdad de nivel 1 del sistema; sus objetivos, restricciones y límites prevalecen sobre los outputs de cualquier engine en caso de conflicto; ningún engine puede sobrescribir la responsabilidad ni los límites establecidos por el nivel superior en la Truth_Hierarchy.
10. THE Portfolio_Architect SHALL asignar a cada activo una `functional_role` del enum definido (`Compounder`, `Value_Asymmetry`, `Growth`, `Defensive`, `Inflation_Hedge`, `Crisis_Hedge`, `Liquidity`, `Income`, `Diversifier`, `Tactical`, `Speculative`); la `functional_role` junto con el Core y el Sleeve constituyen la clasificación funcional completa del activo.
11. THE IDOS SHALL distinguir entre posiciones Core (que sostienen la arquitectura patrimonial de largo plazo y pueden mantenerse aunque desaparezca una tesis táctica concreta) y posiciones Satellite (que requieren justificación continua mediante oportunidad, valoración, catalizador o diversificación específica); toda posición Satellite que pierde su justificación SHALL activar una alerta en el Decision_Inbox.
12. THE IDOS SHALL permitir que un activo pertenezca a Core sin tener una tesis activa en todos los casos (ej. Core_1 cash, Core_2 renta fija defensiva); un activo Satellite sin tesis activa SHALL transicionar a estado `REVIEW` automáticamente.

#### Propiedades de Corrección (Property-Based Testing)

- **Cobertura total de Cores**: Para todo activo con posición activa en el portfolio, tiene asignado exactamente un Core y un Sleeve; no existen posiciones activas sin Core asignado. Propiedad de invariante.
- **Suma de pesos**: La suma de pesos de todos los activos activos sobre la Cartera_Financiera_Liquida es siempre ≤ 100%. La suma de pesos por Core cubre el 100% de los activos asignados. Propiedad de invariante de completitud.
- **Determinismo del Portfolio_Architect**: Dado el mismo activo y el mismo estado patrimonial, el Portfolio_Architect produce siempre el mismo Core, Sleeve y Risk_Overlays. Propiedad de idempotencia.
- **Functional_role obligatorio**: Para todo activo con posición activa en el portfolio, existe exactamente una `functional_role` del enum asignada por el Portfolio_Architect. Propiedad de invariante.
- **Truth_Hierarchy sin conflictos silenciosos**: Cuando un output de un engine de nivel inferior contradice un límite establecido en el IPS (nivel 1), el sistema genera un conflicto explícito registrado en el Decision_Inbox en lugar de resolver silenciosamente a favor del engine. Propiedad de invariante de escalamiento.

---

### Requirement 17: Strategy Catalog — Routing multi-estrategia

**User Story:** Como gestor del portfolio, quiero que el sistema soporte múltiples estrategias de inversión con sus propios protocolos de discovery, research, assessment y entry configurados en archivos YAML, para que pueda gestionar simultáneamente compounders de largo plazo, momentum ETFs sistemáticos, crédito y oportunidades especiales bajo un mismo sistema operativo sin modificar código de Workers.

#### Acceptance Criteria

1. THE Strategy_Catalog SHALL leer los Strategy_Profiles de `idos-config/strategies/{strategy_id}.yml`; cada Strategy_Profile SHALL declarar obligatoriamente los siguientes campos en cualquier momento, independientemente de si el Strategy_Catalog los está leyendo: `strategy_id`, `discovery_filter`, `research_protocol`, `assessment_engines` (lista con pesos), `entry_policy`, `exit_rules`, `applicable_gates`, `core`, `sleeve`, `position_limits`, `score_threshold`, `knowledge_sources` (sección con bibliografía y referentes de la estrategia), `jev_decisions` (mapa de las decisiones del pipeline que usan Jev en lugar de LLM para esa estrategia, con la primitiva Jev utilizada: `Choice`, `Score` o `Noul`).
2. THE Strategy_Catalog SHALL incluir por defecto los siguientes perfiles: `COMPOUNDER` (FULL_DDD, Wyckoff entry, todos los gates), `MOMENTUM_ETF` (MOMENTUM_SIGNAL, señal mensual, gates reducidos), `DEEP_VALUE` (FULL_DDD con engines de distress, gates estándar), `CREDIT_BOND` (CREDIT_ANALYSIS, spread entry, gates de crédito), `DEFENSIVE_ETF` (FUNDAMENTAL_LITE, indicador de tendencia, gates reducidos).
3. THE perfil `COMPOUNDER` SHALL ser el perfil por defecto; toda Opportunity sin `strategy_id` explícito SHALL ser interpretada como COMPOUNDER para garantizar compatibilidad hacia atrás.
4. THE Monthly_Universe_Pipeline SHALL ejecutar el `discovery_filter` de cada estrategia habilitada en el Strategy_Catalog sin modificar el código del Worker; la adición de una nueva estrategia requiere únicamente crear un archivo YAML en `idos-config/strategies/`.
5. THE Research_Worker SHALL seleccionar el `research_protocol` del Strategy_Profile de la Opportunity sin hardcoding; todos los protocolos disponibles (`FULL_DDD`, `MOMENTUM_SIGNAL`, `CREDIT_ANALYSIS`, `FUNDAMENTAL_LITE`) son accesibles por configuración.
6. THE Assessment_Pipeline SHALL ejecutar los `assessment_engines` del Strategy_Profile de la Opportunity; los pesos de los engines para el cálculo del Conviction son los declarados en el Strategy_Profile, no valores globales.
7. THE Decision_Engine SHALL evaluar los `applicable_gates` del Strategy_Profile de la Opportunity; una estrategia puede declarar un subconjunto de los 8 Gates.
8. THE entry_policy del Strategy_Profile SHALL determinar el método de entrada utilizado por el Entry_Monitor_Worker: Wyckoff para COMPOUNDER, señal mensual para MOMENTUM_ETF, spread threshold para CREDIT_BOND.
9. IF el Strategy_Catalog no puede parsear un Strategy_Profile YAML (schema inválido), THEN THE IDOS SHALL reportar el error en la CI_Pipeline y SHALL bloquear la ejecución del pipeline que requiere ese perfil.

10. THE Strategy_Profile SHALL incluir en la sección `knowledge_sources` para cada estrategia: (1) al menos dos referentes intelectuales (`Strategy_Authority`) con nombre del autor, obras principales y el aporte conceptual específico que aplica a la estrategia; (2) al menos dos fuentes bibliográficas adicionales (libros, papers o documentos) con título, autor y relevancia para el Research y Assessment de esa estrategia.

11. THE LLM_Service SHALL recibir el contenido de `knowledge_sources` del Strategy_Profile como parte del contexto del prompt cuando el Research_Worker ejecute tareas de análisis (AOIF, síntesis, generación de hipótesis) para esa estrategia; este contexto ancla el razonamiento del LLM en el marco teórico canónico de la estrategia.

12. THE Strategy_Catalog SHALL incluir en los perfiles por defecto las siguientes referencias canónicas:
    - `COMPOUNDER`: referentes incluyen Warren Buffett ("The Essays of Warren Buffett"), Charlie Munger ("Poor Charlie's Almanack"), Philip Fisher ("Common Stocks and Uncommon Profits"), Terry Smith ("Invest for the Long Term"); fuentes adicionales incluyen cartas anuales de Berkshire Hathaway y Fundsmith.
    - `MOMENTUM_ETF`: referentes incluyen Gary Antonacci ("Dual Momentum Investing"), Meb Faber ("A Quantitative Approach to Tactical Asset Allocation"), Wesley Gray ("Quantitative Momentum"); fuentes adicionales incluyen el paper AQR "Value and Momentum Everywhere" (Asness, Moskowitz, Pedersen).
    - `DEEP_VALUE`: referentes incluyen Benjamin Graham ("Security Analysis", "The Intelligent Investor"), Joel Greenblatt ("The Little Book That Beats the Market"), Seth Klarman ("Margin of Safety"), Walter Schloss; fuentes adicionales incluyen el paper "Deep Value" de Tobias Carlisle.
    - `CREDIT_BOND`: referentes incluyen Howard Marks ("The Most Important Thing", "Mastering the Market Cycle"), Martin Fridson ("Financial Statement Analysis"), Frank Fabozzi ("Fixed Income Mathematics"); fuentes adicionales incluyen el CFA Institute Fixed Income curriculum y los memos de Oaktree Capital.
    - `DEFENSIVE_ETF`: referentes incluyen Harry Browne ("Fail-Safe Investing"), Ray Dalio (All Weather Portfolio), William Bernstein ("The Intelligent Asset Allocator"); fuentes adicionales incluyen los papers de factor investing de Eugene Fama y Kenneth French.

13. WHEN el Research_Worker genera un informe de análisis para una Opportunity, THE Research_Worker SHALL incluir en el artefacto resultante (`hypotheses.yml`, `signal.yml`, `credit_analysis.yml` o `ddd_lite.yml`) una referencia al `strategy_id` y a los `knowledge_sources` utilizados como contexto, de manera que el informe sea trazable hasta su marco teórico canónico.
14. THE `jev_decisions` del Strategy_Profile SHALL declarar al menos las siguientes decisiones tipadas por estrategia: scoring de candidatos (primitiva `Score` o `Noul`), validación estructural de Hypothesis (primitiva `Choice`), evaluación de GATE 0 y GATE 1 (primitiva `Choice`), clasificación del origen del retorno en post-mortem (primitiva `Choice`); cada entrada en `jev_decisions` incluye: `decision_point`, `jev_primitive`, `enum_values` (para `Choice`) o `rubric` (para `Score`) y `fallback_to_llm` (booleano que indica si escala al LLM cuando Jev retorna REVIEW).

#### Propiedades de Corrección (Property-Based Testing)

- **Round-trip del Strategy_Profile**: Para todo Strategy_Profile en YAML: `deserialize(serialize(profile)) == profile`. Todos los campos obligatorios sobreviven el ciclo de lectura y escritura. Propiedad de round-trip (esencial para configuración).
- **Routing correcto completo**: Para toda Opportunity con `strategy_id = X`, las fases de discovery, research, assessment, decision y entry usan exactamente los protocolos declarados en el perfil X; ninguna fase usa protocolos de otro perfil. Propiedad de invariante de routing.
- **Invariante de habilitación**: Si una estrategia `S` está habilitada en `idos-config/strategies/`, el Monthly_Universe_Pipeline ejecuta exactamente su `discovery_filter`; si está deshabilitada, no ejecuta ningún paso de esa estrategia. Propiedad de invariante.
- **Completitud de knowledge_sources**: Para todo Strategy_Profile registrado en el Strategy_Catalog, `len(profile.knowledge_sources.authorities) >= 2` y `len(profile.knowledge_sources.bibliography) >= 2`. Ningún Strategy_Profile puede estar activo sin al menos dos referentes intelectuales y dos fuentes bibliográficas declaradas. Propiedad de invariante.
- **Separación Jev/LLM por decision_point**: Para todo `decision_point` declarado en `jev_decisions` de un Strategy_Profile, el pipeline usa Jev para esa decisión y no invoca el LLM_Service; para todo `decision_point` no declarado en `jev_decisions`, el pipeline no usa Jev. Propiedad de invariante de separación de responsabilidades.

---

### Requirement 18: Argentina Risk Overlay

**User Story:** Como inversor con patrimonio concentrado en Argentina, quiero que el sistema calcule y controle la exposición total a Argentina como un overlay transversal que incluye activos financieros, patrimonio ilíquido e ingresos, para que nunca subestime el riesgo real de dependencia patrimonial argentina y los Gates de decisión la incluyan explícitamente.

#### Acceptance Criteria

1. THE Argentina_Overlay SHALL modelarse como Risk Overlay transversal, no como un Core ni como categoría geográfica de Core; la función del capital determina el Core; Argentina determina el overlay.
2. THE Argentina_Overlay SHALL descomponer la exposición en los siguientes sub-riesgos independientes: `Sovereign_Short_Duration`, `Sovereign_Inflation`, `Corporate_Credit_local`, `ARS_Liquidity`, `Argentina_Equity`; el sistema no trata Argentina como un bloque único.
3. THE Decision_Engine SHALL calcular la exposición Argentina total del activo candidato considerando: (1) exposición financiera directa en cartera, (2) exposición económica indirecta de activos globales con dependencia argentina, (3) inmueble en Argentina (valorado cualitativamente cuando no exista metodología defendible), (4) ingresos y negocios locales, (5) obligaciones en pesos y costos locales.
4. WHEN el Decision_Engine evalúa GATE 4 (Portfolio Impact), THE Decision_Engine SHALL sumar la exposición Argentina del candidato a la exposición Argentina existente en cartera y SHALL verificar el límite configurado en `idos-config/risk_policy.yml`.
5. IF la exposición Argentina total (financiera + patrimonial) supera el límite configurado, THEN GATE 4 SHALL fallar con motivo "Argentina concentration exceeded" y el resultado del Decision_Engine SHALL ser `BLOCKED` o `REJECTED`.
6. THE Risk_Audit SHALL calcular escenarios de stress específicos de Argentina: sovereign spread shock (+100/+300/+500 bps), FX stress, inflación extrema, liquidez ARS y default/restructuring; los escenarios son sensibilidades, no predicciones.
7. THE Portfolio_Architect SHALL mapear los Risk_Overlays de todo activo candidato incluyendo `argentina_direct`, `argentina_indirect` y `argentina_total` antes de asignar el Core.
8. THE Dashboard SHALL mostrar la exposición Argentina total desglosada por sub-riesgo en el Portfolio_Widget.

#### Propiedades de Corrección (Property-Based Testing)

- **Cobertura de exposición**: Para todo activo argentino con posición activa en el portfolio, existe un registro de exposición Argentina desglosado por sub-riesgo (`Sovereign_Short_Duration`, `Sovereign_Inflation`, `Corporate_Credit_local`, `ARS_Liquidity`, `Argentina_Equity`). Propiedad de invariante.
- **Calculabilidad en cualquier momento**: La suma de exposición Argentina financiera directa de todos los activos activos es calculable en cualquier momento desde los datos del portfolio en SQLite sin acceso a Git. Propiedad de invariante de calculabilidad.
- **Consistencia de GATE 4**: Para toda Opportunity que pasó GATE 4, el registro del gate demuestra que `argentina_total_portfolio + argentina_exposure_candidate <= argentina_limit_config` en el momento de la evaluación. Propiedad de invariante de precondición.

---

### Requirement 19: Métrica Dual Patrimonial

**User Story:** Como titular del patrimonio familiar en Argentina, quiero que el sistema reporte simultáneamente el crecimiento en moneda fuerte y el poder adquisitivo argentino en toda revisión periódica y en todo post-mortem, para que pueda tomar decisiones que optimicen ambas dimensiones y detectar cuando una cartera crece en USD pero pierde poder adquisitivo local.

#### Acceptance Criteria

1. THE IDOS SHALL reportar obligatoriamente en toda revisión periódica (mensual y trimestral) dos métricas separadas: (1) variación del patrimonio en moneda fuerte (USD), (2) variación del poder adquisitivo argentino estimado; la ausencia de cualquiera de las dos métricas constituye un reporte incompleto.
2. THE IDOS SHALL calcular el poder adquisitivo argentino considerando: inflación local, tipo de cambio, costos domésticos, vivienda, salud, educación y obligaciones futuras conocidas; los parámetros de cálculo serán configurables en `idos-config/risk_policy.yml`.
3. THE Dashboard SHALL mostrar ambas métricas en el Portfolio_Widget con sus respectivos benchmarks (patrimonio USD vs benchmark global; poder adquisitivo vs inflación local).
4. WHEN una posición genera ganancia en USD pero deteriora el poder adquisitivo argentino estimado, THE IDOS SHALL marcar el trade-off explícitamente en el reporte de la posición y en el Decision_Inbox como alerta `DUAL_METRIC_TRADEOFF`.
5. THE patrimonio total SHALL incluir para análisis de concentración y fragilidad: cartera financiera líquida + inmueble y activos ilíquidos + participaciones empresariales - pasivos relevantes; los pesos de los Cores se calculan exclusivamente sobre la Cartera_Financiera_Liquida.
6. THE Risk_Audit SHALL reportar como mínimo: porcentaje del patrimonio total que es ilíquido, dependencia de ingresos o activos locales como porcentaje del patrimonio total, y exposición Argentina como porcentaje del patrimonio total.
7. WHEN exista una fuente privada de portfolio conectada y un resultado de salida reconciliado, THE Post_Mortem_Worker SHALL registrar el impacto en ambas dimensiones (`financial_pnl_usd`, `purchasing_power_impact_ars`) para alimentar el análisis del Learning_Engine. WHILE esa fuente no exista, las métricas SHALL quedar `NOT_ASSESSED` y no SHALL inferirse ni sustituirse por datos simulados.
8. THE Decision SHALL registrar en el momento de la aprobación el impacto esperado en ambas dimensiones patrimoniales: `expected_usd_impact` (expected value en moneda fuerte) y `expected_ars_purchasing_power_impact` (impacto estimado en poder adquisitivo local).

#### Propiedades de Corrección (Property-Based Testing)

- **Completitud del reporte dual**: Para todo reporte periódico generado por el sistema, existen exactamente dos métricas patrimoniales: variación en USD y variación en poder adquisitivo argentino. Ningún reporte puede generarse con solo una métrica. Propiedad de invariante.
- **Trazabilidad en post-mortem**: Para toda Opportunity `ARCHIVED` con fuente privada conectada y resultado de salida reconciliado, el Post_Mortem registra `financial_pnl_usd` y `purchasing_power_impact_ars`; antes de conectar esa fuente, ambos quedan explícitamente `NOT_ASSESSED`. Propiedad de invariante condicionada por disponibilidad de datos.
- **Consistencia de la Decision**: Para toda Decision con estado `APPROVED`, existen los campos `expected_usd_impact` y `expected_ars_purchasing_power_impact` con valores distintos de null. Propiedad de invariante de completitud del contrato.


---

### Requirement 20: Scout configurable por estrategia

**User Story:** Como gestor, quiero que Scout aplique filtros financieros simples y configurables por estrategia para poder modificar la preselección sin cambiar un motor global ni confundir elegibilidad con convicción.

#### Acceptance Criteria

1. COMPOUNDER aplica margen operativo > 0, FCF > 0 y crecimiento de ingresos > 0; la política tiene versión y cada filtro declara métrica, operador, valor y etiqueta en `idos-config/strategies.yml`.
2. Cap y liquidez USD siguen siendo gates comunes; ETFs no requieren capitalización/AUM y las acciones requieren market cap mínimo USD 2.000 millones; liquidez mínima USD 100.000/día. No hay filtro de país, mínimo de observaciones, cobertura porcentual ni conversión de ARS como gate. Métricas USD ausentes dejan al activo en `PENDING_DATA`.
3. ROIC y moat se evalúan en Research, no bloquean el Scout COMPOUNDER.
4. Métrica requerida ausente, no numérica, no finita o con evidencia fuente contradictoria queda `PENDING_DATA`; el sistema no inventa valores ni promociona el candidato.
5. Filtros cumplidos informan elegibilidad de screening y jamás se copian como convicción, probabilidad o recomendación.
6. El reporte de oportunidad conserva versión de política, valores observados, unidad, moneda/período disponible, proveedor y procedencia de gates de mercado.
7. Discovery público expone las condiciones y estados de los filtros; no presenta el cumplimiento como recomendación de inversión.
