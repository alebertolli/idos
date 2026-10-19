# IDE v2.1 — Addendum de implementación

## Objetivo

Este addendum operacionaliza la arquitectura IDE v2.0 para la cartera declarada, incorporando estado de posición, liquidez de oportunidad, régimen de mercado, correlación, fallback a cash y límites agregados.

## Cambios principales

1. **Core 1 dividido:** supervivencia y oportunidad.
2. **AO27D:** liquidez de oportunidad con riesgo soberano; no reserva pura.
3. **Defensivos condicionales:** GLD, SPY, RSP, DIA y XLU pueden quedar `OFF` si la tendencia es bajista.
4. **Momentum:** universo QQQ, XLE, XLF, XLI, EFA, EEM y GLD; selecciona hasta dos activos el primer día hábil de cada mes.
5. **Cash fallback:** si ningún activo pasa el filtro de momentum, el sleeve queda líquido.
6. **Riesgo agregado:** límites para momentum, táctico, cripto, Core 4, emisores, sectores y Argentina.
7. **Caución tomadora:** deshabilitada por defecto; nunca financia la compra de activos en caída.
8. **CEDEAR:** se separa el riesgo económico del subyacente del riesgo de ejecución local.

## Cartera objetivo inicial

```text
CORE 1 — 25%
  Cash supervivencia/oportunidad       15%
  AO27D oportunidad                    10%

CORE 2 — 35%
  CER corto/medio                     15%
  GLD condicional                      5%
  BRK.B                                5%
  XLU                                  5%
  DIA                                  5%

CORE 3 — 30%
  SPY                                  8%
  RSP                                  4%
  EFA                                  4%
  EEM                                  4%
  Momentum                             6%
  Compounders MSFT/ADP                4%

CORE 4 — 10%
  Swing trading                        5%
  IBIT                                 2%
  Bitcoin                              1%
  Deep value / crédito high risk      2%
```

Estos porcentajes son parámetros iniciales para stress testing, no una autorización automática de compra.

## Transición

La transición recomendada es gradual, en 3–6 meses:

- congelar nuevas compras de GEMSA, DICP y TZX28;
- reducir GEMSA de 23% hacia 0–2%;
- reducir AO27D de 30% hacia 10%;
- reemplazar DICP/TZX28 por CER corto/medio;
- construir CEDEARs globales y defensivos solo cuando pasen los gates;
- mantener aprobación explícita antes de cada operación.

## Estados de decisión

```text
ACTIVE
REDUCED
OFF
CASH_FALLBACK
REVIEW
BLOCKED
```

La ausencia de una posición defensiva no es una falla: puede ser la salida correcta cuando todos los candidatos tienen tendencia y momentum negativos.
