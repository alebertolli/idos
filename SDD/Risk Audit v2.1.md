# Risk Audit v2.1

## 0. Metadatos

**Estado:** Operativo
**Versión:** 2.1
**Propósito:** Framework de evaluación multidimensional de riesgo de cartera.
**Rol:** Input del Portfolio Architect, Risk Budget y Allocation Engine.

---

# PARTE I — METODOLOGÍA

## 1. Objetivo

El Risk Audit determina el riesgo económico de una cartera distinguiendo entre:

* capital invertido;
* exposición económica;
* riesgo de mercado;
* riesgo de crédito;
* riesgo de liquidez;
* riesgo de pérdida permanente;
* riesgo de concentración;
* riesgo de inflación;
* riesgo de moneda;
* riesgo de duration;
* volatilidad;
* correlación;
* escenarios de stress.

Principio rector:

> **Capital Exposure ≠ Risk Exposure.**

El peso de una posición no constituye por sí mismo una medida suficiente de riesgo.

---

## 2. Relación con Portfolio Architecture

El Risk Audit es una capa transversal.

```text
Portfolio
    ↓
Portfolio Architect
    ↓
Economic Exposure
Risk Drivers
Functional Role
Liquidity
Correlation
Portfolio Overlap
    ↓
Risk Audit
    ↓
Risk Budget
    ↓
Allocation Engine
```

El audit debe evaluar el riesgo del instrumento y su contribución al riesgo agregado de cartera.

---

## 3. Ficha mínima de cada posición

Cada posición debe contener, cuando sea aplicable:

| Dimensión     | Variable                                    |
| ------------- | ------------------------------------------- |
| Capital       | Market Value                                |
| Concentración | Weight                                      |
| Emisor        | Issuer                                      |
| Tipo          | Sovereign / Corporate / Equity / ETF / Cash |
| Moneda        | Currency                                    |
| Vencimiento   | Maturity                                    |
| Duration      | Macaulay / Modified / Effective             |
| Convexidad    | Convexity                                   |
| Crédito       | Rating / PD / LGD / Recovery                |
| Mercado       | Volatility / Beta                           |
| Liquidez      | Volume / Bid-Ask / Depth                    |
| Inflación     | Inflation Exposure                          |
| FX            | Currency Exposure                           |
| Correlación   | Correlation                                 |
| Función       | Functional Role                             |
| Riesgo        | Permanent Loss Risk                         |
| Stress        | Scenario Loss                               |

Cuando una variable no pueda determinarse con datos fiables:

> **UNKNOWN / N/A**

No debe imputarse un valor arbitrario.

---

# 4. Capital Exposure

### Position Weight

```text
Position Weight =
Market Value of Position
/
Total Portfolio Value
```

Debe calcularse también:

* issuer weight;
* instrument weight;
* strategy weight;
* sleeve weight;
* economic-cluster weight.

---

# 5. Economic Exposure

El sistema debe consolidar posiciones que representan el mismo riesgo económico.

Ejemplo:

```text
AO27D Credit
AO27D Optionality
```

deben consolidarse como:

```text
AO27D Economic Exposure
```

para medir concentración de emisor.

La etiqueta estratégica no elimina la exposición común al instrumento.

---

# 6. Market Risk

## 6.1 Duration

Para renta fija:

* Macaulay Duration;
* Modified Duration;
* Effective Duration cuando corresponda.

Aproximación:

```text
ΔP/P ≈ -Duration × ΔYield
```

No debe utilizarse como estimación completa cuando existan:

* opciones;
* estructuras complejas;
* convexidad relevante;
* crédito distressed;
* cambios simultáneos de tasas y spreads.

---

## 6.2 Convexity

Debe incorporarse cuando sea material.

```text
ΔP/P ≈
-Duration × ΔYield
+
0.5 × Convexity × (ΔYield)^2
```

La convexidad de mercado no debe confundirse con convexidad económica.

---

## 6.3 Volatility

Cuando existan datos suficientes:

* 20d;
* 40d;
* 60d;
* 1y;
* anualizada.

Debe diferenciarse:

> **Market Volatility**

de:

> **Permanent Loss Risk**

---

## 6.4 Beta

Para equity/ETF:

* market beta;
* global equity beta;
* sector beta;
* factor beta.

No debe utilizarse beta de equity para renta fija de manera mecánica.

---

# 7. Credit Risk

Cada deuda debe clasificarse por:

### Emisor

* soberano;
* provincial/subsoberano;
* corporativo;
* financiero;
* estructurado.

### Seniority

* secured;
* unsecured;
* senior;
* subordinated;
* guaranteed;
* structurally subordinated.

### Métricas

Cuando estén disponibles:

* rating;
* outlook;
* PD;
* leverage;
* Net Debt / EBITDA;
* interest coverage;
* FCF;
* liquidity;
* maturity wall;
* refinancing needs.

---

# 8. Default / Recovery Risk

Debe distinguirse:

```text
Probability of Default
```

de:

```text
Loss Given Default
```

y:

```text
Expected Loss
```

Conceptualmente:

```text
Expected Loss ≈ PD × LGD
```

Para créditos distressed debe realizarse además un:

> **Recovery Analysis**

que determine:

1. Enterprise Value;
2. deuda senior;
3. deuda garantizada;
4. deuda no garantizada;
5. obligaciones con prioridad;
6. activos disponibles;
7. recovery mínimo;
8. recovery base;
9. recovery optimista.

---

# 9. Liquidity Risk

Evaluar:

* volumen;
* bid/ask;
* profundidad;
* frecuencia de negociación;
* capacidad de liquidación;
* market impact;
* liquidez bajo stress;
* restricciones contractuales.

Clasificación:

```text
High
Medium
Low
Illiquid
```

Principio:

> **Precio observable ≠ liquidez efectiva.**

---

# 10. Currency Risk

Separar:

* moneda nominal;
* moneda de los flujos;
* moneda económica;
* moneda del subyacente.

Debe diferenciarse:

> USD nominal exposure

de:

> USD economic exposure.

---

# 11. Inflation Risk

Evaluar:

* exposición nominal;
* exposición CER;
* inflación implícita;
* duration real;
* sensibilidad a tasas reales.

Debe existir una medida adicional:

> **Real Purchasing Power**

especialmente para patrimonios cuyo objetivo sea preservar poder adquisitivo local.

---

# 12. Argentina Risk Overlay

Argentina no debe tratarse como un único bloque.

Debe descomponerse en:

```text
Argentina Risk
│
├── Sovereign Short Duration
├── Sovereign Inflation
├── Corporate Credit
├── ARS Liquidity
└── Argentina Equity
```

El objetivo es distinguir entre riesgos que comparten país pero no necesariamente tienen la misma sensibilidad económica.

---

# 13. Concentration Risk

Calcular concentración por:

1. posición;
2. emisor;
3. instrumento;
4. sector;
5. país;
6. factor;
7. economic cluster.

La medida más relevante es:

> **Economic Risk Cluster**

y no únicamente el número de posiciones.

---

# 14. Return Stream Analysis

No debe asumirse:

```text
N estrategias = N return streams
```

Distintas estrategias pueden depender del mismo factor.

El análisis debe determinar:

* número de return streams;
* factores compartidos;
* correlación;
* solapamiento económico.

---

# 15. Permanent Loss Risk

Debe evaluarse independientemente de la volatilidad.

Factores:

* default;
* insolvencia;
* subordinación;
* deterioro estructural;
* obsolescencia;
* fraude;
* iliquidez;
* pérdida irreversible de capital.

Clasificación:

```text
Low
Medium
High
Critical
```

---

# 16. Scenario Analysis

Mínimo obligatorio:

### Interest Rate Shock

```text
+100 / +300 / +500 bps
```

### Credit Spread Shock

```text
+100 / +300 / +500 bps
```

### Argentina Stress

Incluye:

* sovereign spread;
* FX;
* inflación;
* liquidez;
* default/restructuring.

### Global Equity Crash

Ejemplo:

```text
Equity -20%
```

### Severe Combined Stress

Combinación de:

* credit;
* equity;
* FX;
* liquidity.

Los escenarios son sensibilidades y no predicciones.

---

# 17. Risk Contribution

Debe distinguir:

```text
Capital Weight
```

de:

```text
Risk Contribution
```

Una aproximación inicial:

```text
Risk Contribution
=
Capital Weight
× Risk Intensity
× Correlation Adjustment
```

La fórmula concreta dependerá del asset class.

---

# 18. Risk Budget

Debe separarse:

```text
Opportunity
Risk Capacity
Available Risk Budget
```

Una oportunidad atractiva no justifica automáticamente una posición grande.

---

# 19. Position Sizing

Regla estructural:

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

El Risk Audit alimenta principalmente:

* Risk Capacity Limit;
* Portfolio Limit;
* Liquidity Limit.

---

# 20. Estado de implementación y validación

Al 2026-10-18, `idos-core/idos/portfolio/audit.py` implementa únicamente el
capital exposure audit: conversión a moneda base con FX aportado en el
snapshot, pesos por posición y agrupaciones conocidas (incluido economic
cluster), reporte de clasificaciones desconocidas y bloqueo de autorización de
asignación. Su salida declara `audit_scope: CAPITAL_EXPOSURE_ONLY`,
`risk_audit_status: NOT_ASSESSED` y enumera los dominios pendientes. El campo
legacy `status` describe sólo la integridad de las clasificaciones de capital;
no significa que Risk Audit v2.1 esté completo.

No se calculan ni infieren duration, convexidad, volatilidad, beta, crédito,
recovery, liquidez efectiva, moneda económica, poder adquisitivo real,
correlaciones, permanent-loss risk, escenarios, contribución de riesgo,
presupuesto ni sizing. Deben permanecer `UNKNOWN / N/A` hasta que el snapshot
aporte inputs con unidad, fuente y fecha, y exista un método versionado
aplicable al tipo de activo. El reporte nunca autoriza operaciones.

La validación actual cubre consolidación determinista de capital y
clasificaciones, rechazo de valores/FX inválidos y CLI con salida separada del
snapshot de entrada. La evaluación multidimensional completa requiere un
contrato versionado de snapshot, fixtures por clase de activo, escenarios y
correlaciones con métodos explícitos, pruebas de integración y revisión del
gestor. No usar cartera simulada como sustituto de la hoja privada familiar.
