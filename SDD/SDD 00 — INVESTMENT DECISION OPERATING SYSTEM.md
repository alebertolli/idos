# SDD 00 — INVESTMENT DECISION OPERATING SYSTEM

## Arquitectura Definitiva

**Versión:** 1.0
**Estado:** Propuesta de congelamiento arquitectónico
**Sistema:** Investment Decision Operating System — IDOS
**Documento:** SDD 00
**Rol:** Documento rector de arquitectura funcional, de decisión y gobernanza.

---

# 1. Propósito

IDOS es un sistema de decisión de inversión cuyo objetivo es transformar:

**capital + objetivos + restricciones + información + oportunidades**

en:

**decisiones de cartera trazables, comparables, auditables y ejecutables.**

El sistema no busca maximizar la cantidad de operaciones ni predecir el mercado.

Busca maximizar el **crecimiento patrimonial de largo plazo ajustado por riesgo de pérdida permanente de capital**, respetando liquidez, restricciones y capacidad de riesgo.

---

# 2. Principios arquitectónicos

## 2.1 Capital como recurso escaso

Toda nueva inversión compite contra:

* posiciones existentes;
* efectivo;
* reducción de riesgo;
* otras oportunidades.

La pregunta central es:

> **¿Cuál es hoy el mejor uso ajustado por riesgo del próximo dólar de capital?**

---

## 2.2 Capital Exposure ≠ Risk Exposure

El peso contable de una posición no determina por sí solo su riesgo.

El sistema debe evaluar:

* exposición económica;
* drivers de riesgo;
* concentración;
* correlación;
* liquidez;
* moneda;
* duración;
* crédito;
* volatilidad;
* riesgo de pérdida permanente;
* escenarios de stress.

---

## 2.3 Arquitectura antes que asignación

Ningún activo recibe capital antes de determinar:

1. función;
2. exposición económica;
3. drivers de riesgo;
4. lugar arquitectónico;
5. rango estructural.

---

## 2.4 Tesis antes que sizing

El Allocation Engine no decide si un activo es una buena inversión.

La tesis determina si existe una oportunidad.

La asignación determina cuánto capital merece.

---

## 2.5 Human in the loop

El sistema:

* analiza;
* estructura;
* contrasta;
* calcula;
* propone;
* alerta.

La autorización estratégica y la ejecución de transacciones permanecen bajo control humano.

---

## 2.6 Evidencia trazable

Toda conclusión relevante debe poder remontarse a:

**dato → fuente → análisis → hipótesis → evaluación → decisión.**

---

## 2.7 No inventar información

Cuando una variable no pueda determinarse con suficiente evidencia:

`UNKNOWN`

o:

`N/A`

Nunca debe completarse artificialmente para permitir que el pipeline avance.

---

# 3. Arquitectura funcional definitiva

La arquitectura queda definida como:

```text
                    INVESTMENT CONSTITUTION
                             │
                             ▼
                    PORTFOLIO ARCHITECT
                             │
             ┌───────────────┼────────────────┐
             ▼               ▼                ▼
       FUNCTION        ECONOMIC EXPOSURE   RISK DRIVERS
             │               │                │
             └───────────────┼────────────────┘
                             ▼
                        RISK AUDIT
                             │
                             ▼
                    INVESTMENT THESIS
                         ENGINE
                             │
                             ▼
                     ALLOCATION ENGINE
                             │
                             ▼
                     DECISION ENGINE
                             │
                             ▼
                         PORTFOLIO
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
         PLAYBOOK                    MONITORING
              │                             │
              └──────────────┬──────────────┘
                             ▼
                      LEARNING ENGINE
```

La secuencia conceptual es obligatoria.

Ningún módulo inferior puede sustituir a uno superior.

---

# 4. Bounded Contexts

IDOS queda dividido en los siguientes bounded contexts.

## BC-01 — Constitution & Governance

Responsabilidad:

* objetivos patrimoniales;
* principios;
* restricciones;
* autoridad;
* reglas de gobernanza;
* límites estratégicos.

Fuente principal:

**Investment Constitution.**

---

## BC-02 — Portfolio Architecture

Responsabilidad:

* clasificación funcional;
* sleeves;
* Core/Satellite;
* exposición económica;
* risk drivers;
* liquidez;
* moneda;
* correlación;
* redundancias;
* rangos estructurales.

Engine:

**Portfolio Architect.**

---

## BC-03 — Risk

Responsabilidad:

* medición del riesgo individual;
* riesgo agregado;
* concentración;
* exposición económica;
* stress;
* liquidity risk;
* permanent-loss risk;
* Risk Capacity Score;
* Risk Budget.

Engine:

**Risk Audit / Risk Budget.**

---

## BC-04 — Investment Thesis

Responsabilidad:

* evaluación del activo;
* hipótesis;
* upside;
* downside;
* expected value;
* asimetría;
* catalizadores;
* horizonte;
* invalidación;
* convicción.

Engine:

**Investment Thesis Engine.**

---

## BC-05 — Capital Allocation

Responsabilidad:

* sizing;
* target;
* minimum;
* maximum;
* capital requerido;
* coste de oportunidad;
* fuente de financiación;
* velocidad de entrada;
* build plan.

Engine:

**Allocation Engine.**

---

## BC-06 — Decision Governance

Responsabilidad:

* integrar outputs;
* detectar contradicciones;
* validar gates;
* producir decisión;
* requerir revisión humana.

Engine:

**Decision Engine / Decision Board.**

---

## BC-07 — Portfolio Execution

Responsabilidad:

* ejecución;
* estados de posiciones;
* entradas;
* aumentos;
* reducción;
* salida;
* rebalanceo;
* seguimiento.

Componentes:

**Playbook + Portfolio State.**

---

## BC-08 — Learning

Responsabilidad:

* evaluar calidad de decisiones;
* comparar tesis vs resultado;
* detectar errores de proceso;
* identificar sesgos;
* recalibrar reglas.

Engine:

**Learning Engine.**

---

# 5. Dominios

## 5.1 Dominio estratégico

Incluye:

* Investor;
* IPS;
* Objectives;
* Constraints;
* Investment Constitution;
* Governance.

---

## 5.2 Dominio de cartera

Incluye:

* Portfolio;
* Position;
* Sleeve;
* Function;
* Economic Exposure;
* Risk Driver;
* Allocation.

---

## 5.3 Dominio de oportunidades

Incluye:

* Opportunity;
* Thesis;
* Catalyst;
* Valuation;
* Invalidation;
* Conviction;
* Decision.

---

## 5.4 Dominio de riesgo

Incluye:

* Risk Assessment;
* Risk Capacity;
* Risk Budget;
* Concentration;
* Stress Scenario;
* Liquidity;
* Exposure.

---

## 5.5 Dominio operativo

Incluye:

* Execution Plan;
* Position State;
* Rebalance;
* Monitoring;
* Review Trigger.

---

## 5.6 Dominio de aprendizaje

Incluye:

* Decision Outcome;
* Decision Quality;
* Thesis Outcome;
* Process Error;
* Learning;
* Calibration.

---

# 6. Capabilities

## Constitution

* definir objetivos;
* definir restricciones;
* definir límites;
* definir autoridad.

## Architecture

* clasificar activos;
* asignar función;
* mapear exposición;
* mapear riesgo;
* detectar redundancia;
* establecer rangos.

## Risk

* medir riesgo;
* consolidar exposiciones;
* stress testing;
* determinar capacidad de riesgo;
* administrar Risk Budget.

## Thesis

* investigar;
* formular hipótesis;
* valorar;
* estimar upside/downside;
* identificar catalizadores;
* definir invalidación;
* determinar atractivo.

## Allocation

* rankear oportunidades;
* determinar tamaño;
* definir target;
* definir max;
* determinar funding;
* definir entry velocity.

## Decision

* validar;
* contrastar;
* bloquear;
* aprobar;
* reducir;
* salir.

## Execution

* ejecutar;
* construir posición;
* mantener;
* congelar;
* reducir;
* cerrar.

## Learning

* evaluar decisiones;
* identificar errores;
* medir calidad;
* recalibrar.

---

# 7. Entidades principales

## Investor

Representa al propietario del capital.

Atributos mínimos:

```yaml
investor_id:
objectives:
constraints:
risk_capacity:
liquidity_requirements:
horizon:
```

---

## Portfolio

Representa la cartera completa.

```yaml
portfolio_id:
valuation_date:
total_value:
financial_assets_value:
cash:
risk_budget:
RCS:
```

---

## Position

Representa una exposición existente.

```yaml
position_id:
asset_id:
issuer:
market_value:
weight:
currency:
function:
sleeve:
economic_exposures:
risk_drivers:
state:
```

---

## Asset

Representa el instrumento financiero.

---

## Opportunity

Representa una oportunidad potencial.

Estados:

```text
WATCH
CANDIDATE
ENTRY
BUILD
HOLD
FREEZE
REDUCE
EXIT
CLOSED
```

---

## Thesis

Representa la hipótesis de inversión.

```yaml
thesis_id:
asset:
status:
hypotheses:
expected_value:
upside:
downside:
asymmetry:
catalysts:
horizon:
confidence:
invalidation_conditions:
```

---

## Risk Assessment

Representa la evaluación de riesgo.

---

## Allocation Proposal

Representa la propuesta de capital.

```yaml
status:
action:
current_weight:
initial_weight:
target_weight:
max_weight:
capital_required:
funding:
sizing:
IAS:
RCS:
risk_budget:
portfolio_impact:
opportunity_cost:
execution:
constraints:
```

---

## Decision

Representa la decisión autorizada.

Acciones:

```text
REJECT
WATCH
APPROVE_SMALL
APPROVE_BUILD
HOLD
REDUCE
EXIT
```

---

## Execution Plan

Representa cómo se ejecutará una decisión aprobada.

---

## Learning Record

Representa la evaluación posterior de la decisión.

---

# 8. Clasificación funcional

Todo activo debe recibir una función primaria.

Funciones disponibles:

```text
Compounder
Value / Asymmetry
Growth
Defensive
Inflation Hedge
Crisis Hedge
Liquidity
Income
Diversifier
Tactical
Speculative
```

La clasificación por asset class no reemplaza la clasificación funcional.

---

# 9. Core / Satellite

## Core

Debe sostener la arquitectura patrimonial de largo plazo.

Debe poder mantenerse aunque desaparezca una tesis táctica concreta.

## Satellite

Debe justificar su existencia mediante:

* oportunidad;
* valoración;
* catalizador;
* régimen;
* asimetría;
* diversificación específica.

Una posición no es Satellite simplemente por ser pequeña.

---

# 10. Argentina como dimensión transversal

Aquí se cierra una contradicción existente en documentos anteriores.

**Argentina NO será un Core obligatorio.**

La clasificación correcta es:

```text
Function
+
Economic Exposure
+
Risk Drivers
```

Argentina constituye una **dimensión de exposición económica agregada**.

Ejemplos:

```text
CER
→ Preservation
→ Argentina

Empresa argentina Compounder
→ Growth
→ Argentina

Argentina Deep Value
→ Value / Asymmetry
→ Argentina

ACWI
→ Growth
→ Global

Gold
→ Preservation / Crisis Hedge
→ Global
```

El sistema debe calcular:

**Total Argentina Exposure**

independientemente del sleeve al que pertenezca cada activo.

---

# 11. Risk Model

Risk Audit es transversal a toda la arquitectura.

Debe evaluar:

* market risk;
* credit risk;
* liquidity risk;
* permanent-loss risk;
* concentration;
* inflation;
* currency;
* duration;
* volatility;
* correlation;
* stress scenarios.

Debe distinguir:

```text
Capital Exposure
≠
Economic Exposure
≠
Risk Exposure
```

---

# 12. Risk Capacity y Risk Budget

El sistema utiliza:

**RCS = Risk Capacity Score**

para determinar cuánto riesgo puede absorber la cartera.

El Risk Budget determina cuánto riesgo puede consumir una nueva asignación.

Una oportunidad atractiva no puede superar la capacidad disponible.

---

# 13. Investment Thesis Engine

El Thesis Engine determina:

> **¿Merece esta oportunidad capital?**

Debe producir como mínimo:

* thesis status;
* score/conviction;
* expected value;
* upside;
* downside;
* asymmetry;
* catalyst;
* horizon;
* confidence;
* invalidation conditions.

Una buena empresa no equivale automáticamente a una buena inversión.

La evaluación es:

```text
Asset
+
Thesis
+
Price
+
Risk
+
Portfolio Context
```

---

# 14. IAS

El **Investment Attractiveness Score** representa atractivo relativo.

No representa permiso automático para invertir.

Principio:

> **IAS determina atractivo.**

No sustituye a:

* RCS;
* Risk Budget;
* Architecture;
* Portfolio Impact;
* Liquidity.

---

# 15. Allocation Engine

El Allocation Engine transforma una oportunidad aprobable en una **Allocation Proposal**.

No determina por sí solo si el activo debe comprarse.

### Tres capas de sizing

1. Risk-based.
2. Opportunity-based.
3. Portfolio-based.

El peso final se determina por el límite más restrictivo:

```text
Final Weight =
MIN(
    Risk Capacity Limit,
    Opportunity Limit,
    Portfolio Limit,
    Liquidity Limit,
    Architecture Limit
)
```

---

# 16. Allocation Gates

Antes de asignar capital:

```text
GATE 1 → Architecture
GATE 2 → Thesis
GATE 3 → Risk Capacity
GATE 4 → Portfolio Impact
GATE 5 → Liquidity
```

Un gate crítico fallido implica:

**NO ALLOCATION**

o:

**BLOCKED**

---

# 17. Target / Minimum / Maximum

Cada posición debe poder tener:

```yaml
min_weight:
target_weight:
max_weight:
```

El target es dinámico.

No existe necesariamente un peso correcto permanente.

Conceptualmente:

```text
Target(t) =
f(
 Thesis,
 IAS,
 RCS,
 Portfolio,
 Price,
 Risk,
 Opportunity Cost
)
```

---

# 18. Decision Engine

El Decision Engine es el orquestador final.

No es otro sistema de scoring.

Debe:

1. validar outputs;
2. detectar contradicciones;
3. comprobar gates;
4. verificar gobernanza;
5. producir decisión.

Ejemplo:

```text
Thesis = alta
RCS = baja
Allocation = pequeña
```

La decisión puede ser:

**APPROVE — SMALL**

y no simplemente BUY.

---

# 19. Playbook operativo

Toda decisión aprobada pasa al Playbook.

Estados:

```text
WATCH
CANDIDATE
ENTRY
BUILD
HOLD
FREEZE
REDUCE
EXIT
CLOSED
```

No debe permitirse pasar directamente de:

`WATCH → MAXIMUM POSITION`

sin etapas intermedias.

---

# 20. Technical Overlay

El análisis técnico es transversal.

No constituye una tesis independiente para la mayoría de las estrategias.

### Compounder

Fundamentales dominan.

Deterioro técnico:

→ FREEZE / REDUCE según severidad.

### Value / Special Situation

Deterioro técnico:

→ revisar catalizador y downside.

### Global Base

Deterioro técnico:

→ normalmente no altera la tesis estructural.

### Momentum

La señal técnica/sistemática tiene mayor peso.

---

# 21. Exit Governance

Existen cuatro mecanismos principales.

## Thesis Exit

La hipótesis fundamental se invalida.

Puede implicar:

**EXIT 100%.**

## Valuation Exit

La valoración excede significativamente el valor razonable.

Implica:

**reducción parcial.**

No constituye por sí sola una razón para liquidar 100%.

## Portfolio Exit

Existe una alternativa claramente superior por riesgo/retorno y función patrimonial.

Requiere decisión explícita.

## Risk Exit

El perfil de riesgo se deteriora estructuralmente o se supera un límite crítico.

---

# 22. Rebalanceo

No se utilizará exclusivamente rebalanceo calendario.

Se utilizará:

**Threshold + Event Driven**

Triggers:

```text
Weight > Maximum
Weight < Minimum
Risk Driver exceeds limit
Thesis changes
RCS changes materially
IAS changes materially
New opportunity dominates
```

Preferencia:

> Utilizar nuevo capital y liquidez para corregir desviaciones antes de vender activos buenos innecesariamente.

---

# 23. Contratos entre contextos

Los contextos no deben compartir libremente modelos internos.

La integración se realiza mediante contratos explícitos.

### Portfolio Architect → Risk Audit

```yaml
architecture:
  function:
  sleeve:
  economic_exposures:
  risk_drivers:
  liquidity:
  currency:
  portfolio_overlap:
```

### Portfolio Architect → Thesis

```yaml
architecture:
  function:
  sleeve:
  structural_weight_range:
  economic_exposures:
  risk_drivers:
```

### Thesis → Allocation

```yaml
thesis:
  status:
  score:
  expected_value:
  asymmetry:
  upside:
  downside:
  catalyst:
  horizon:
  confidence:
  invalidation_conditions:
```

### Portfolio → Allocation

```yaml
portfolio:
  total_value:
  current_weight:
  cash:
  required_liquidity:
  RCS:
  risk_budget:
  concentration:
  correlation:
  factor_exposure:
  existing_positions:
  alternative_opportunities:
```

### Allocation → Decision

```yaml
allocation_proposal:
  status:
  action:
  initial_weight:
  target_weight:
  max_weight:
  funding:
  sizing:
  portfolio_impact:
  opportunity_cost:
  execution:
  constraints:
```

---

# 24. Eventos

Los eventos son hechos del sistema, no órdenes implícitas.

Eventos mínimos:

```text
AssetCreated
AssetUpdated
ArchitectureAssessed
RiskAssessed
ThesisCreated
ThesisUpdated
AllocationProposed
DecisionCreated
DecisionApproved
DecisionRejected
PositionOpened
PositionIncreased
PositionFrozen
PositionReduced
PositionExited
ReviewTriggered
RebalanceTriggered
LearningRecordCreated
```

Los eventos deben ser trazables y versionados.

---

# 25. Estados

## Opportunity

```text
WATCH
CANDIDATE
ENTRY
BUILD
HOLD
FREEZE
REDUCE
EXIT
CLOSED
```

## Allocation

```text
PASS
FAIL
BLOCKED
REVIEW
```

## Decision

```text
REJECT
WATCH
APPROVE_SMALL
APPROVE_BUILD
HOLD
REDUCE
EXIT
```

Las transiciones deben estar gobernadas por reglas explícitas.

---

# 26. Fuentes de verdad

Se establece una jerarquía.

## Nivel 1 — Constitution

Fuente de verdad para:

* objetivos;
* restricciones;
* principios;
* autoridad.

## Nivel 2 — Portfolio Architecture

Fuente de verdad para:

* función;
* sleeve;
* exposición;
* arquitectura;
* rangos estructurales.

## Nivel 3 — Risk Audit

Fuente de verdad para:

* riesgo;
* exposición agregada;
* concentración;
* stress;
* capacidad de riesgo.

## Nivel 4 — Investment Thesis

Fuente de verdad para:

* tesis;
* hipótesis;
* valoración;
* upside/downside;
* catalizadores;
* invalidación.

## Nivel 5 — Allocation

Fuente de verdad para:

* sizing;
* target;
* maximum;
* funding;
* entry plan.

## Nivel 6 — Decision

Fuente de verdad para:

* decisión autorizada.

## Nivel 7 — Portfolio

Fuente de verdad para:

* posición realmente existente;
* peso real;
* ejecución.

## Nivel 8 — Learning

Fuente de verdad para:

* evaluación retrospectiva de la calidad de la decisión.

---

# 27. Gobernanza

## Regla 1

Ningún engine puede sobrescribir la responsabilidad de otro.

## Regla 2

El Allocation Engine propone; no ejecuta.

## Regla 3

El Decision Engine autoriza.

## Regla 4

La ejecución requiere control humano.

## Regla 5

Las restricciones de Risk Budget pueden bloquear una asignación.

## Regla 6

La información UNKNOWN no puede transformarse silenciosamente en certeza.

## Regla 7

Toda decisión debe conservar:

* razones;
* riesgos;
* invalidación;
* sizing;
* fecha;
* contexto.

## Regla 8

El resultado financiero posterior no determina por sí solo la calidad de una decisión.

---

# 28. Dependencias permitidas

```text
Constitution
    ↓
Portfolio Architect
    ↓
Risk Audit
    ↓
Thesis Engine
    ↓
Allocation Engine
    ↓
Decision Engine
    ↓
Portfolio / Execution
    ↓
Learning
```

Se permiten consultas hacia abajo cuando sean necesarias para evaluación.

No se permiten dependencias circulares.

Un engine no debe modificar directamente el estado propietario de otro bounded context.

---

# 29. Lo que NO debe hacer cada componente

### Portfolio Architect

No decide compra.

### Risk Audit

No decide qué activo es atractivo.

### Thesis Engine

No determina automáticamente el tamaño.

### Allocation Engine

No decide unilateralmente.

### Decision Engine

No inventa tesis ni riesgos faltantes.

### Playbook

No decide qué comprar.

### Learning Engine

No reescribe retroactivamente una decisión histórica.

---

# 30. Learning Engine

El Learning Engine debe separar:

```text
DECISION QUALITY
≠
INVESTMENT OUTCOME
```

Debe evaluar:

* calidad de tesis;
* calidad del proceso;
* calidad de información;
* sizing;
* ejecución;
* error analítico;
* azar;
* sesgos.

Una inversión perdedora puede haber sido una buena decisión.

Una inversión ganadora puede haber sido una mala decisión.

---

# 31. Persistencia y trazabilidad

La arquitectura técnica existente establece:

* conocimiento versionado;
* memoria de decisiones;
* contratos estructurados;
* estados persistentes;
* provenance;
* separación entre conocimiento y journal;
* reconstruibilidad.

La implementación técnica detallada permanece subordinada a este SDD.

Este documento define **qué debe hacer el sistema**, no la implementación concreta de cada worker.

---

# 32. Métricas de control

El sistema deberá poder medir como mínimo:

### Portfolio

* retorno;
* drawdown;
* liquidez;
* concentración;
* exposición Argentina;
* exposición por función;
* exposición por factor.

### Decision

* hit rate;
* expected vs realized;
* decision quality;
* thesis accuracy;
* sizing quality.

### Risk

* risk budget utilization;
* concentration;
* stress loss;
* liquidity exposure;
* permanent-loss exposure.

### Process

* decisiones sin tesis;
* decisiones sin invalidación;
* decisiones bloqueadas;
* overrides humanos;
* errores de proceso.

---

# 33. Parámetros que permanecen abiertos

No deben inventarse todavía:

* thresholds definitivos de IAS;
* thresholds definitivos de RCS;
* límites cuantitativos finales por sleeve;
* covariance matrix;
* Expected Shortfall;
* marginal VaR;
* liquidity-adjusted risk;
* límites definitivos de concentración;
* parámetros definitivos de rebalanceo.

Estos parámetros pertenecen a fases de calibración posteriores.

---

# 34. Contradicciones resueltas

## Argentina como Core vs dimensión transversal

Resolución:

**dimensión transversal.**

## Technical Analysis como Core vs Overlay

Resolución:

**Technical Overlay transversal.**

## Portfolio concentrado 8–15 posiciones vs arquitectura multisleeve

Resolución:

La concentración 8–15 no se establece como restricción global en este SDD.

La concentración debe determinarse mediante:

**Risk Audit + Risk Budget + función de la posición.**

## Allocation Engine vs Decision Engine

Resolución:

**Allocation propone. Decision autoriza.**

## Learning Engine

Resolución:

Existe como bounded context, pero su calibración completa queda posterior a la operacionalización de los engines principales.

---

# 35. Arquitectura maestra congelada

```text
                    INVESTMENT CONSTITUTION
                             │
                             ▼
                    PORTFOLIO ARCHITECT
                             │
             ┌───────────────┼────────────────┐
             ▼               ▼                ▼
          FUNCTION       EXPOSURE        RISK DRIVERS
             │               │                │
             └───────────────┼────────────────┘
                             ▼
                        RISK AUDIT
                             │
                             ▼
                    INVESTMENT THESIS
                             │
                             ▼
                     ALLOCATION ENGINE
                             │
                             ▼
                     DECISION ENGINE
                             │
                             ▼
                         PORTFOLIO
                             │
                             ▼
                  PLAYBOOK / MONITORING
                             │
                             ▼
                     LEARNING ENGINE
```

---

# 36. Regla maestra del sistema

La cartera no se gestiona preguntando:

> “¿Qué activo va a subir?”

Se gestiona preguntando:

> **“¿Dónde está hoy el mejor uso ajustado por riesgo del próximo dólar de capital?”**

Y la cadena de decisión queda:

```text
Architecture
→
Risk
→
Thesis
→
Attractiveness
→
Allocation
→
Decision
→
Execution
→
Learning
```

Reglas finales:

**IAS determina atractivo.**

**RCS determina capacidad de riesgo.**

**Risk Budget determina capacidad disponible.**

**Allocation Engine determina tamaño.**

**Decision Engine autoriza.**

**Playbook determina ejecución.**

**Learning Engine evalúa posteriormente la calidad de la decisión.**

---

# 37. Estado del SDD

**SDD 00 v1.0 — Arquitectura funcional definida.**

A partir de este documento, cualquier nuevo módulo debe demostrar:

1. qué bounded context pertenece;
2. qué capability implementa;
3. qué entidad modifica;
4. qué contrato consume;
5. qué contrato produce;
6. qué eventos genera;
7. quién es su fuente de verdad;
8. qué dependencias requiere.

Si no puede responder esas preguntas, no debe incorporarse todavía a la arquitectura.
