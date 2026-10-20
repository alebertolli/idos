# Investment Decision Engine (IDE) v2.0

**Documento de arquitectura y gobernanza**  
**Versión:** 2.0  
**Estado:** Consolidado  
**Fecha:** 2026-09-09

> Este documento define un sistema de decisión de inversión. No constituye asesoramiento financiero ni reemplaza la validación de datos, la evaluación fiscal, legal o regulatoria, ni el criterio del titular del patrimonio.

## 1. Propósito

El **Investment Decision Engine (IDE)** transforma una idea, activo o necesidad de cartera en una decisión de capital trazable, compatible con la arquitectura patrimonial y revisable con nueva información.

```text
IDEA / OPORTUNIDAD
        ↓
PORTFOLIO ARCHITECT
        ↓
INVESTMENT THESIS ENGINE
        ↓
ALLOCATION ENGINE
        ↓
DECISION ENGINE
        ↓
EJECUCIÓN / CARTERA
        ↓
LEARNING ENGINE
        ↓
KNOWLEDGE BASE
```

El IDE no busca maximizar la cantidad de operaciones. Busca mejorar la calidad de las decisiones, proteger la supervivencia patrimonial y asignar capital donde su valor marginal ajustado por riesgo sea superior.

## 2. Principios rectores

1. La unidad de decisión es **activo + función + tesis + precio + riesgo + cartera existente**.
2. Un activo bueno no entra automáticamente en cartera: debe competir por capital.
3. La función del capital define el Core; la geografía no lo define.
4. Argentina es un **Risk Overlay transversal**, no un Core.
5. La cartera financiera líquida gobierna la asignación; el patrimonio total gobierna la fragilidad y la concentración patrimonial.
6. Atractivo, capacidad de riesgo y presupuesto de riesgo son variables separadas.
7. Toda tesis debe poder ser refutada mediante condiciones de invalidación.
8. Toda decisión debe tener evidencia, supuestos, límites, responsable y fecha de revisión.
9. La liquidez de supervivencia no financia oportunidades ofensivas.
10. El sistema puede concluir **no hacer nada**.

## 3. Objetivos patrimoniales duales

El IDE mide simultáneamente:

### 3.1 Patrimonio en moneda fuerte

Preservar y aumentar el patrimonio frente a inflación, depreciación monetaria y oportunidades globales.

### 3.2 Poder adquisitivo argentino

Mantener y aumentar la capacidad futura de financiar la vida en Argentina, considerando inflación local, tipo de cambio, costos domésticos, vivienda, salud, educación y obligaciones futuras.

Una cartera puede crecer en USD y perder poder adquisitivo local, o mejorar en términos locales sin fortalecer suficientemente el patrimonio en moneda fuerte. El sistema debe reportar ambas dimensiones y explicitar los trade-offs.

## 4. Dos niveles de patrimonio

### 4.1 Patrimonio total

Incluye:

- cartera financiera líquida;
- inmueble y otros activos ilíquidos;
- participaciones empresariales;
- obligaciones y pasivos relevantes;
- dependencias económicas, geográficas y regulatorias.

Se usa para medir concentración patrimonial, iliquidez, riesgo Argentina, dependencia de una fuente de ingresos y fragilidad total.

### 4.2 Cartera financiera líquida

Incluye activos que pueden valorarse y movilizarse razonablemente para asignación o rebalanceo.

Se usa para:

- pesos estratégicos de los Cores;
- liquidez operativa;
- risk budget;
- rebalanceo;
- financiación de oportunidades.

**Regla:** los pesos de los Cores se calculan sobre la cartera financiera líquida. Los Risk Overlays pueden y deben considerar el patrimonio total.

## 5. Arquitectura funcional de cuatro Cores

Los porcentajes son referencias iniciales de diseño, no objetivos automáticos ni recomendaciones universales. Deben ajustarse a horizonte, obligaciones, liquidez, tolerancia y capacidad de riesgo.

| Core | Función | Referencia | Rango estructural |
|---|---|---:|---:|
| 1. Supervivencia y Liquidez | evitar ventas forzadas y conservar opcionalidad | 15% | 10–25% |
| 2. Preservación Patrimonial | proteger poder adquisitivo y reducir fragilidad | 20% | 15–30% |
| 3. Crecimiento Patrimonial | creación de riqueza real y capitalización | 50% | 40–60% |
| 4. Alfa y Asimetría | oportunidades especiales con upside desproporcionado | 15% | 5–20% |

### Core 1 — Supervivencia y Liquidez

Función: `SURVIVAL`, `LIQUIDITY`, `OPTIONALITY`.

Objetivos:

- cubrir necesidades y contingencias;
- evitar ventas forzadas;
- mantener capacidad de actuar;
- financiar gastos próximos y obligaciones conocidas.

La liquidez crítica tiene prioridad sobre el rendimiento esperado.

### Core 2 — Preservación Patrimonial

Función: preservar poder adquisitivo, reducir fragilidad, diversificar y proteger frente a inflación o crisis.

Puede incluir, según el caso, instrumentos indexados, renta fija defensiva, oro, instrumentos dolarizados de calidad y diversificadores. La pertenencia depende de la función, no de la geografía.

### Core 3 — Crecimiento Patrimonial

Función: capitalización de largo plazo y creación de riqueza real.

Sleeves posibles:

- **Global Base:** exposición amplia y diversificada.
- **Systematic Return:** momentum, trend following u otras estrategias sistemáticas.
- **High Conviction Long-Term:** compounders, transición estructural y empresas de calidad con valoración razonable.

### Core 4 — Alfa y Asimetría

Función: capturar oportunidades especiales, dislocaciones y retornos asimétricos.

Puede incluir deep value, turnarounds, situaciones especiales, oportunidades macro y activos de alto upside.

Se controla principalmente mediante tamaño, límites, diversificación y no dependencia de un único resultado.

## 6. Argentina como Risk Overlay transversal

Cada activo se clasifica en dos dimensiones independientes:

```text
FUNCIÓN DEL CAPITAL (CORE / SLEEVE)
                 +
EXPOSICIÓN ECONÓMICA (RISK OVERLAYS)
```

Por tanto, un bono CER puede pertenecer al Core 2 y tener alta exposición Argentina; una acción argentina puede pertenecer al Core 3 o 4; un ETF global puede pertenecer al Core 3; el oro puede pertenecer al Core 2. La geografía no determina la función.

### 6.1 Exposición Argentina total

Debe considerar, al menos:

```text
EXPOSICIÓN FINANCIERA DIRECTA
+ EXPOSICIÓN ECONÓMICA INDIRECTA
+ INMUEBLE ARGENTINA
+ INGRESOS Y NEGOCIOS LOCALES
+ OBLIGACIONES EN PESOS / COSTOS LOCALES
```

La estimación puede ser cualitativa cuando no exista una metodología defendible de look-through. El objetivo inicial es detectar dependencia patrimonial real, no fabricar una precisión falsa.

### 6.2 Overlays mínimos

- Argentina / geografía;
- moneda;
- inflación;
- tasas de interés;
- ciclo económico;
- crédito y contraparte;
- liquidez;
- concentración;
- correlación;
- factores de estilo;
- riesgo político, regulatorio y fiscal;
- dependencia de una fuente de ingreso.

## 7. Los cinco Skills / Engines

| Módulo | Pregunta | No decide |
|---|---|---|
| Portfolio Architect | ¿Dónde encaja y qué riesgo añade? | no aprueba la compra |
| Investment Thesis Engine | ¿Merece competir por capital? | no fija por sí solo el tamaño |
| Allocation Engine | ¿Cuánto, cuándo y de dónde sale? | no autoriza la ejecución |
| Decision Engine | ¿Se autoriza la acción? | no sustituye la evidencia |
| Learning Engine | ¿Qué aprendimos del proceso? | no reescribe el pasado |

## 8. Contrato común de entrada

Todo flujo debe poder recibir, como mínimo, este contexto:

```yaml
ide_input:
  as_of_date:
  decision_id:
  request_type: NEW_IDEA | REVIEW | REBALANCE | EXIT | EMERGENCY

  asset:
    ticker:
    name:
    asset_type:
    market:
    currency:
    price:
    price_date:
    liquidity_profile:

  patrimony:
    total_net_worth:
    financial_portfolio_value:
    illiquid_assets:
    liabilities:
    income_dependencies:
    required_liquidity:
    liquidity_horizon:

  portfolio:
    current_positions:
    current_weights:
    core_weights:
    sleeve_weights:
    cash:
    risk_budget:
    correlations:
    factor_exposures:
    argentina_exposure:

  constraints:
    horizon:
    objectives:
    tax_or_legal_constraints:
    maximum_drawdown_tolerance:
    forbidden_actions:

  evidence:
    sources:
    source_dates:
    data_quality:
```

Si faltan datos críticos, el resultado debe ser `REVIEW` o `BLOCKED`, nunca una falsa precisión.

## 9. Portfolio Architect v2.0

### 9.1 Rol

Determina la función del activo dentro de la arquitectura patrimonial y los riesgos que añade. No analiza exhaustivamente el negocio, no decide el timing y no autoriza la operación.

### 9.2 Proceso

1. Identificar función primaria: `COMPOUNDER`, `GROWTH`, `VALUE_ASYMMETRY`, `DEFENSIVE`, `INFLATION_HEDGE`, `CRISIS_HEDGE`, `LIQUIDITY`, `INCOME`, `DIVERSIFIER`, `TACTICAL` o `SPECULATIVE`.
2. Asignar Core y, cuando corresponda, Sleeve.
3. Mapear exposiciones económicas: geografía, moneda, inflación, tasas, ciclo, crédito, política y regulación.
4. Estimar Risk Overlays, incluyendo Argentina directa, indirecta y patrimonial.
5. Evaluar solapamiento, contribución de diversificación y límite estructural.

### 9.3 Output contract

```yaml
portfolio_architecture:
  status: PASS | REVIEW | FAIL
  asset:
  functional_role:
  core: CORE_1 | CORE_2 | CORE_3 | CORE_4
  sleeve:

  economic_exposures:
    geography:
    currency:
    inflation:
    interest_rates:
    economic_cycle:
    credit:
    political:
    regulatory:

  risk_overlays:
    argentina_direct:
    argentina_indirect:
    argentina_total:
    liquidity:
    concentration:
    correlation:
    factors:

  portfolio_overlap:
  diversification_contribution:
  structural_weight_range:
    min:
    target:
    max:
  rationale:
  missing_information:
```

## 10. Investment Thesis Engine v2.0

### 10.1 Rol

Determina si existe una oportunidad suficientemente sólida y diferenciada para competir por capital.

### 10.2 Estructura obligatoria

```text
1. Asset / Business
2. Investment Thesis
3. Market Expectation
4. Variant Perception
5. Catalyst
6. Valuation / Price
7. Downside
8. Upside
9. Expected Value
10. Time Horizon
11. Invalidation Conditions
12. Key Risks
13. Evidence Quality
```

La tesis debe separar hechos, inferencias y supuestos. La ausencia de una variante identificable, de un downside razonable o de una invalidación explícita impide un `PASS`.

### 10.3 Escenarios

```yaml
scenarios:
  bear:
    probability:
    value:
    assumptions:
  base:
    probability:
    value:
    assumptions:
  bull:
    probability:
    value:
    assumptions:
```

Las probabilidades deben sumar 100% cuando se utilice un modelo probabilístico. Si no es defendible cuantificar, se debe declarar la limitación.

### 10.4 Output contract

```yaml
investment_thesis:
  status: PASS | WATCH | FAIL | REVIEW
  conviction:
  expected_value:
  asymmetry:
  upside:
  downside:
  catalyst:
  time_horizon:
  invalidation_conditions:
  key_risks:
  evidence:
  evidence_quality:
  conclusion:
```

## 11. Allocation Engine v2.0

### 11.1 Rol

Transforma una oportunidad elegible en una propuesta de asignación compatible con arquitectura, capacidad de riesgo, presupuesto de riesgo, liquidez, concentración y coste de oportunidad.

> El tamaño es una decisión de riesgo y de coste de oportunidad, no una expresión de entusiasmo.

### 11.2 Variables separadas

- **IAS — Investment Attractiveness Score:** ranking relativo de oportunidades.
- **RCS — Risk Capacity Score:** capacidad actual de absorber riesgo.
- **Risk Budget:** riesgo restante disponible después de considerar la cartera existente.

Un IAS alto no implica una posición grande. Un RCS alto no obliga a asumir riesgo.

### 11.3 Motor de sizing

```text
FINAL WEIGHT = MIN(
  RISK CAPACITY LIMIT,
  OPPORTUNITY LIMIT,
  PORTFOLIO LIMIT,
  LIQUIDITY LIMIT,
  ARCHITECTURE LIMIT
)
```

### 11.4 Construcción y financiación

Una posición puede tener `initial_weight`, `target_weight` y `max_weight`. La construcción puede ser `INITIAL → CONFIRMATION → BUILD → TARGET`.

La fuente del capital debe quedar registrada. Orden conceptual de prioridad:

1. exceso de efectivo;
2. asignación de baja prioridad;
3. exposición redundante;
4. posición sobreponderada;
5. tesis debilitada;
6. oportunidad inferior frente a la nueva.

No se vende automáticamente una posición de alta calidad para financiar una oportunidad nueva; debe compararse el valor marginal esperado ajustado por riesgo.

### 11.5 Reglas de entrada y averaging down

- `FAST`: tesis clara, liquidez alta, downside conocido y urgencia temporal.
- `GRADUAL`: incertidumbre, volatilidad o dependencia de eventos.
- `WAIT`: datos insuficientes, margen insuficiente, RCS bajo o coste de oportunidad alto.

Nunca se aumenta una posición solo porque el precio cayó. Para agregar capital deben cumplirse simultáneamente: tesis sin deterioro, expected value mejorado, riesgo aceptable y capacidad disponible.

### 11.6 Output contract

```yaml
allocation_proposal:
  status: PASS | FAIL | BLOCKED | REVIEW
  action: NO_ACTION | INITIATE | ADD | BUILD | HOLD | TRIM | REDUCE | EXIT | ROTATE

  current_weight:
  initial_weight:
  target_weight:
  max_weight:
  capital_required:

  funding:
    source:
    assets_to_reduce:

  sizing:
    risk_capacity_limit:
    opportunity_limit:
    portfolio_limit:
    liquidity_limit:
    architecture_limit:
    final_weight:

  scores:
    IAS:
    RCS:
    risk_budget_status:

  execution:
    entry_velocity: FAST | GRADUAL | WAIT
    build_steps:
  opportunity_cost:
  portfolio_impact:
  constraints:
  rationale:
  review_trigger:
  rebalance_trigger:
```

## 12. Decision Engine v2.0

### 12.1 Rol

Autoriza, rechaza, difiere o modifica una acción después de revisar arquitectura, tesis, allocation y contexto patrimonial.

### 12.2 Gates obligatorios

```text
GATE 0 — Input / Evidence
GATE 1 — Architecture
GATE 2 — Thesis
GATE 3 — Risk Capacity
GATE 4 — Portfolio Impact / Overlays
GATE 5 — Liquidity
GATE 6 — Allocation / Competition for Capital
GATE 7 — Governance / Execution Readiness
```

#### Gate 0 — Input y evidencia

Debe existir fecha de corte, precio, fuentes, calidad de datos y ausencia de contradicciones materiales. Si falla: `REVIEW` o `BLOCKED`.

#### Gate 1 — Architecture

Core, Sleeve, función, rango estructural y Risk Overlays definidos. Si falla: `BLOCKED — NO ALLOCATION`.

#### Gate 2 — Thesis

Tesis, downside, expected value, horizonte, riesgos e invalidación definidos. `WATCH` no habilita una posición plena.

#### Gate 3 — Risk Capacity

RCS, liquidez disponible, drawdown, concentración y estado del portfolio compatibles con el tamaño propuesto.

#### Gate 4 — Portfolio Impact

Evaluar correlación, factores, geografía, moneda, Argentina total, duplicación de riesgos y contribución marginal.

#### Gate 5 — Liquidity

Proteger reservas de supervivencia, obligaciones próximas y capacidad de maniobra. La liquidez crítica nunca se compromete por una oportunidad ofensiva.

#### Gate 6 — Allocation

La asignación debe respetar el mínimo de límites independientes y explicar fuente de financiación, velocidad de entrada y coste de oportunidad.

#### Gate 7 — Gobernanza

La decisión debe registrar responsable, fecha, acción, peso, límites, condiciones de revisión, autorización requerida y plan de ejecución.

### 12.3 Decision output

```yaml
decision:
  decision_id:
  status: APPROVED | APPROVED_SMALL | WATCH | REJECTED | HOLD | REDUCE | EXIT | REVIEW | BLOCKED
  action:
  gates:
    input_evidence:
    architecture:
    thesis:
    risk_capacity:
    portfolio_impact:
    liquidity:
    allocation:
    governance:
  authorized_weight:
  authorized_capital:
  execution_plan:
  review_date:
  review_triggers:
  rationale:
  approver:
  timestamp:
```

El Decision Engine autoriza; no ejecuta automáticamente operaciones externas salvo que exista una integración explícita, límites preautorizados y una política de ejecución aprobada.

## 13. Lifecycle de una inversión

```text
DISCOVERED
    ↓
PORTFOLIO_FIT
    ↓
UNDER_RESEARCH
    ↓
THESIS_VALIDATED
    ↓
ALLOCATION_PROPOSAL
    ↓
DECISION
    ├── REJECTED / WATCH / BLOCKED
    └── APPROVED
             ↓
       ENTRY_PENDING
             ↓
       ACCUMULATING
             ↓
       HOLDING / MONITORING
        ├── REVIEW
        ├── TRIM / REDUCE
        └── EXITED
             ↓
       POST_MORTEM
             ↓
       KNOWLEDGE_BASE
```

Cada transición debe registrar fecha, motivo, evidencia nueva y quién la autorizó. No se salta directamente de una idea a una posición plena sin pasar por arquitectura, tesis, allocation y decisión.

## 14. Monitoring y triggers

El seguimiento debe combinar umbrales y eventos, no solo calendario.

Triggers de revisión:

- peso por encima de `max_weight` o por debajo de `min_weight`;
- cambio material en tesis, catalizador o invalidación;
- deterioro de liquidez o solvencia;
- cambio relevante en RCS o risk budget;
- variación material en IAS relativo;
- aumento de exposición Argentina, moneda, factor o correlación;
- nueva oportunidad con mejor valor marginal ajustado por riesgo;
- cambio de objetivos, horizonte, obligaciones o situación patrimonial.

## 15. Learning Engine v2.0

Se activa ante salida, invalidación, revisión mayor, error de proceso o cambio relevante de hipótesis.

Evalúa por separado:

- calidad de la tesis;
- calidad de la decisión con la información disponible;
- calidad de la asignación;
- calidad de la ejecución;
- resultado financiero;
- resultado patrimonial dual;
- cumplimiento de reglas;
- sesgos y errores de proceso.

Pregunta principal:

> ¿Fue una buena decisión con la información disponible en ese momento?

No debe juzgarse únicamente por si la posición ganó o perdió dinero.

```yaml
post_mortem:
  decision_id:
  outcome:
  thesis_accuracy:
  decision_quality:
  allocation_quality:
  execution_quality:
  process_violations:
  unexpected_events:
  biases_detected:
  lesson:
  rule_or_template_change:
  recorded_at:
```

## 16. Métricas del sistema

### 16.1 Métricas patrimoniales

- patrimonio total en moneda fuerte;
- cartera financiera líquida en moneda fuerte;
- poder adquisitivo argentino estimado;
- crecimiento real y nominal;
- liquidez por horizonte;
- drawdown y tiempo de recuperación;
- exposición Argentina total;
- concentración por activo, emisor, Core, Sleeve, moneda, geografía y factor;
- porcentaje de patrimonio ilíquido;
- dependencia de ingresos o activos locales.

### 16.2 Métricas de decisión

- porcentaje de decisiones con contrato completo;
- tiempo desde descubrimiento hasta decisión;
- porcentaje de ideas rechazadas por falta de fit;
- cumplimiento de límites y gates;
- diferencia entre peso inicial, target y peso realizado;
- frecuencia de averaging down no justificado;
- rotación y coste de oportunidad;
- calidad de pronósticos y calibración de probabilidades;
- resultados por Core y Sleeve;
- errores de tesis versus errores de sizing o ejecución.

### 16.3 Métrica dual mínima

Toda revisión periódica debe responder:

```text
¿El patrimonio mejoró en moneda fuerte?
¿El poder adquisitivo argentino mejoró?
¿A qué coste de liquidez, volatilidad y concentración?
```

## 17. Reglas de gobernanza

1. El sistema conserva un registro inmutable o versionado de decisiones y revisiones.
2. Las fuentes y fechas de datos se registran junto con cada conclusión.
3. Los supuestos se separan de los hechos observados.
4. Los límites de Core, Sleeve y posición requieren revisión explícita para ser superados.
5. Toda salida total se clasifica por motivo: invalidación, riesgo, objetivo alcanzado, liquidez, oportunidad superior u objetivo patrimonial.
6. Una salida por oportunidad superior requiere comparar valor marginal esperado ajustado por riesgo.
7. No se permite aumentar riesgo agregado durante una emergencia de liquidez sin autorización explícita.
8. Los cambios en objetivos, obligaciones, horizonte o patrimonio reinician la revisión arquitectónica.
9. El sistema puede emitir `NO_ACTION`, `WATCH` o `WAIT` sin penalización por inactividad.
10. El aprendizaje puede modificar plantillas, límites o reglas, pero no alterar retrospectivamente el registro original.

## 18. Separación de responsabilidades

```text
PORTFOLIO ARCHITECT
  clasifica función y riesgo estructural

THESIS ENGINE
  evalúa oportunidad y falsabilidad

ALLOCATION ENGINE
  propone tamaño, velocidad y financiación

DECISION ENGINE
  aplica gates y autoriza / rechaza

EJECUCIÓN
  implementa dentro de límites autorizados

LEARNING ENGINE
  evalúa proceso y actualiza conocimiento
```

Ningún módulo debe aprobarse a sí mismo. El componente que propone una asignación no es el único que la autoriza.

## 19. Ejemplo de flujo resumido

```text
1. Se detecta una oportunidad.
2. Portfolio Architect confirma Core 3, Sleeve definido y overlays.
3. Thesis Engine valida variante, valoración, downside y invalidación.
4. Allocation Engine calcula IAS, RCS, risk budget y límites independientes.
5. Se propone una entrada gradual con fuente de capital explícita.
6. Decision Engine ejecuta los siete gates.
7. Si se aprueba, se registra el plan y los triggers.
8. La cartera se monitorea por umbrales y eventos.
9. Ante salida o invalidación, Learning Engine realiza post-mortem.
```

## 20. Estado de la arquitectura

El cambio fundamental de IDE v2.0 es:

```text
ANTES
La geografía podía mezclarse con la organización de los Cores.

AHORA
Los Cores se definen exclusivamente por función.
Argentina y las demás exposiciones económicas se modelan como Risk Overlays.
```

La arquitectura queda consolidada cuando cada oportunidad puede recorrer el flujo completo con contratos, gates, límites, trazabilidad, lifecycle y aprendizaje posterior. Las ponderaciones de referencia deben tratarse como parámetros revisables, no como verdades permanentes.

