IDOS — Thesis Engine v1
Compounder & Explosive Growth Edition

Versión: 1.0
Estado: Propuesta para incorporar a IDOS v1

1. Objetivo

El Thesis Engine transforma un candidato generado por un Factor Engine en una tesis de inversión estructurada, verificable y monitorizable.

Su foco particular es detectar:

empresas Compounder;
crecimiento sostenible;
capacidad de reinversión;
ventajas competitivas durables;
aceleración del crecimiento;
situaciones donde el mercado pueda estar subestimando la capacidad futura de creación de valor.

La idea central es:

No buscamos predecir cuánto crecerá una empresa. Buscamos identificar qué tiene que ser cierto para que pueda crecer y componer capital durante mucho tiempo.

El Thesis Engine no decide por sí solo cuánto capital asignar ni reemplaza los demás motores de IDOS.

2. Principios fundamentales

El motor se basa en siete principios.

2.1 Simplicidad

La tesis debe poder expresarse en una frase clara.

Si necesitamos varios párrafos para explicar por qué una empresa puede crear valor, probablemente todavía no entendemos suficientemente el mecanismo.

2.2 Separación de responsabilidades
FACTOR ENGINE
      ↓
encuentra oportunidad

THESIS ENGINE
      ↓
explica por qué podría funcionar

El Factor Engine no debe construir la tesis y el Thesis Engine no debe inventar oportunidades.

2.3 Reproducibilidad

Una misma empresa analizada con:

los mismos datos;
la misma fecha;
la misma metodología;

debería producir una evaluación aproximadamente equivalente.

Esto es especialmente importante porque el sistema será ejecutado por agentes.

2.4 Evidencia antes que narrativa

Cada afirmación relevante debe distinguir entre:

HECHO
INFERENCIA
HIPÓTESIS

El agente no debe convertir una narrativa plausible en un hecho.

2.5 Falsabilidad

Toda tesis debe indicar:

¿Qué evidencia demostraría que estamos equivocados?

2.6 La valoración no es el centro

El Thesis Engine no pretende convertirse en un DCF.

La valoración se utiliza para responder:

Si la tesis funciona, ¿el precio actual permite obtener un retorno suficientemente atractivo?

2.7 No agregar complejidad innecesaria

No se incorporan:

scores de 0–100;
múltiples niveles de scoring;
Monte Carlo;
DCF obligatorio;
TAM obligatorio;
probabilidades subjetivas;
veinte KPIs;
múltiples agentes construyendo la misma tesis.
3. Arquitectura

La arquitectura queda:

FACTOR ENGINE
      ↓
CANDIDATE
      ↓
THESIS ENGINE v1
      │
      ├── Thesis Statement
      ├── Why Now
      ├── Compounder Test
      ├── Growth Drivers
      ├── Growth Acceleration
      ├── Management
      ├── Cash Conversion
      └── Catalyst
      ↓
SCENARIO ENGINE
      ↓
MONITORING
      ↓
INVALIDATION
      ↓
DECISION

El Thesis Engine no reemplaza:

Factor Engine;
Scenario Engine;
Invalidation Engine;
Decision Engine;
Portfolio Construction;
Capital Allocation;
Risk Guardian.
4. Thesis Statement

La tesis debe comenzar con una única frase.

Debe responder:

¿Qué creemos?
¿Por qué puede ocurrir?
¿Cuál es el mecanismo económico?

Ejemplo conceptual:

"Creemos que X puede convertirse en un Compounder porque está ganando participación en un mercado de gran tamaño, puede reinvertir a elevados retornos y su ventaja de escala debería reforzarse con el crecimiento."

La tesis no debe ser:

"Es una empresa excelente y creemos que subirá."

Debe explicar el mecanismo económico.

Si el agente no puede formular una tesis clara:

CANDIDATE
   ↓
THESIS UNCLEAR
   ↓
WATCH
5. Why Now

La pregunta obligatoria es:

¿Por qué esta oportunidad existe ahora y no hace cinco años?

Esto evita generar tesis genéricas sobre empresas excelentes.

Posibles razones:

nuevo producto;
nuevo mercado;
cambio tecnológico;
cambio regulatorio;
expansión geográfica;
expansión de capacidad;
transición del modelo de negocio;
aceleración del crecimiento;
expansión de márgenes;
recuperación;
cambio de management;
mejora de asignación de capital;
desapalancamiento;
cambio sectorial;
reconocimiento incompleto por parte del mercado.

El Why Now no significa necesariamente que exista un catalizador inmediato.

Significa que debe existir una razón concreta para que la situación actual sea diferente de la histórica.

6. Compounder Test

Este es el núcleo de la nueva versión.

Una empresa no es Compounder simplemente porque crezca rápido.

Debe superar cuatro pruebas.

6.1 Growth Runway

Pregunta:

¿Puede crecer durante varios años?

El agente busca evidencia de:

tamaño de mercado;
penetración;
nuevos clientes;
aumento del uso por cliente;
pricing;
nuevos productos;
expansión geográfica;
market share.

El objetivo no es solamente saber cuánto creció.

Es determinar:

¿Cuánto espacio económico queda para seguir creciendo?

6.2 High ROIC

Pregunta:

¿La empresa genera retornos altos sobre el capital?

Preferencia:

ROIC alto
+
ROIC estable o creciente
+
sin dependencia excesiva de deuda

No basta con observar crecimiento del EPS.

Una empresa puede crecer mucho utilizando grandes cantidades de capital y, por tanto, crear menos valor del que aparenta.

7. Reinvestment Runway

Esta es una de las incorporaciones más importantes.

La pregunta no es solamente:

"¿Tiene un ROIC alto?"

Sino:

¿Cuánto capital puede reinvertir la empresa a retornos altos y durante cuánto tiempo?

Conceptualmente:

ROIC alto
+
poca capacidad de reinversión
=
BUEN NEGOCIO

pero:

ROIC alto
+
gran capacidad de reinversión
=
COMPOUNDER

Por lo tanto, el agente debe analizar:

oportunidades de crecimiento;
capacidad de expansión;
necesidad de capital;
retornos incrementales;
capacidad de mantener ROIC;
duración potencial.

Esta distinción evita confundir una empresa de alta calidad con una auténtica máquina de compounding.

8. Durability

Pregunta:

¿Qué impide que un competidor destruya esos retornos?

No basta con escribir:

"Tiene un moat."

El agente debe identificar el mecanismo económico.

Posibles mecanismos:

switching costs;
network effects;
brand;
cost advantage;
scale;
distribution;
installed base;
data;
ecosystem;
regulación;
IP;
estructura de costos;
relaciones con clientes.

La estructura debe ser:

VENTAJA
   ↓
MECANISMO ECONÓMICO
   ↓
PROTECCIÓN
   ↓
ROIC / MARGEN / MARKET SHARE

Por ejemplo:

Mayor escala
      ↓
menor coste unitario
      ↓
precios competitivos
      ↓
más clientes
      ↓
mayor escala

Ese mecanismo es mucho más útil que simplemente etiquetar la empresa como "moat".

9. Clasificación Compounder

No se utiliza un score de 0–100.

Se utiliza una clasificación muy simple:

Growth Runway       YES / NO
High ROIC           YES / NO
Reinvestment Runway YES / NO
Durability          YES / NO

Resultado:

4 YES
→ COMPOUNDER CANDIDATE

3 YES
→ POTENTIAL COMPOUNDER

<3 YES
→ NO COMPOUNDER

Esto es una clasificación de investigación.

No constituye automáticamente una señal de compra.

10. Growth Drivers

El agente identifica máximo tres drivers principales.

Cada driver debe seguir:

DRIVER
   ↓
MECHANISM
   ↓
EVIDENCE

Ejemplos:

Driver 1

Expansión del mercado.

Driver 2

Gains de market share.

Driver 3

Operating leverage.

Otros posibles drivers:

nuevos productos;
expansión geográfica;
aumento de ARPU;
pricing;
mayor utilización;
unit economics;
capacidad;
cross-selling.

La tesis debería poder resumirse:

La empresa puede crecer porque X, Y y Z.

Si necesitamos diez drivers para sostener la tesis, probablemente la tesis no está suficientemente concentrada.

11. Economic Chain

Cuando sea aplicable, el agente debe construir la cadena económica:

MARKET
   ↓
MARKET SHARE
   ↓
REVENUE
   ↓
MARGIN
   ↓
FCF
   ↓
REINVESTMENT
   ↓
VALUE

Pero TAM no es obligatorio.

La cadena debe adaptarse al negocio.

Por ejemplo:

SaaS
Customers × ARPU
Industrial
Units × ASP
Marketplace
Users × Transactions × Take-rate
Banco
Loans × NIM × Credit Quality

El objetivo es identificar:

la cadena causal que transforma crecimiento operativo en creación de valor.

12. Growth Acceleration

El sistema no busca únicamente empresas que crezcan.

Busca también:

GROWTH
+
ACCELERATION

El agente debe revisar:

crecimiento de revenue;
crecimiento de FCF;
expansión de márgenes;
evolución del market share;
unit economics.

Preguntas:

¿Revenue growth está acelerando?

¿FCF growth está acelerando?

¿Los márgenes están expandiéndose?

¿Market share está aumentando?

Estado:

YES
NO
UNCLEAR

Ejemplo:

Revenue:
15% → 22% → 31%

FCF:
18% → 30% → 48%

Margin:
14% → 17% → 21%

Esto sería una señal de especial interés.

Pero:

Acceleration ≠ prueba automática de Compounder.

Es una señal que justifica profundizar.

13. Management

No se crea un Management Score.

El agente solamente evalúa:

Capital Allocation:
GOOD / NEUTRAL / BAD

Integrity / Transparency:
GOOD / CONCERN

Debe revisar evidencia relacionada con:

reinversión;
adquisiciones;
deuda;
buybacks;
emisión de acciones;
incentivos;
comunicación;
consistencia entre discurso y ejecución;
asignación de capital.

El objetivo es detectar si el management:

genera valor

o:

destruye valor

con el capital generado por el negocio.

14. Cash Conversion

Una empresa puede mostrar:

Revenue ↑
EPS ↑

sin necesariamente crear valor económico equivalente.

Por eso el agente debe comprobar:

Earnings
   ↓
Cash

La pregunta es:

¿El crecimiento económico del negocio se convierte en efectivo después del capital necesario para mantener y expandir la capacidad competitiva?

Estado:

HEALTHY
WEAK
UNCLEAR

Especial atención cuando:

EPS crece mucho;
FCF no acompaña;
working capital absorbe caja;
capex aumenta continuamente;
stock-based compensation diluye;
adquisiciones son necesarias para sostener el crecimiento.
15. Catalyst

El Thesis Engine identifica un catalyst principal cuando existe.

Pregunta:

¿Qué puede hacer que el mercado reconozca lo que nosotros estamos viendo?

Ejemplos:

earnings;
nuevo producto;
expansión de capacidad;
margin inflection;
FCF inflection;
gains de market share;
deleveraging;
strategic transition.

No se necesitan cinco o diez catalysts.

Uno principal es suficiente.

Importante:

Una empresa puede ser un excelente Compounder sin tener un catalyst inmediato.

Por eso Catalyst mejora la tesis, pero no debe convertirse en condición universal de calidad empresarial.

16. Valuation / Asymmetry

El Thesis Engine no se convierte en un DCF.

Su pregunta es:

¿El precio actual permite un retorno atractivo si la tesis funciona?

La evaluación utiliza:

BEAR
BASE
BULL

El modelo:

TAM
 ↓
Market Share
 ↓
Revenue
 ↓
FCF
 ↓
Exit Multiple

puede utilizarse cuando sea natural para el negocio.

Pero no es obligatorio.

La finalidad es determinar:

GOOD BUSINESS
+
ATTRACTIVE PRICE
=
ATTRACTIVE OPPORTUNITY

No:

GOOD BUSINESS
=
BUY AT ANY PRICE
17. Scenarios

Los escenarios deben derivarse de los drivers.

Bull

Condiciones favorables:

Growth runway alto
+
share gains
+
margin expansion
+
high reinvestment
Base

Supuesto razonable:

Growth moderado
+
share estable
+
márgenes estables
Bear

Deterioro:

growth slowdown
OR
share loss
OR
margin compression
OR
reinvestment deterioration

No se utilizan probabilidades subjetivas en v1.

18. Invalidation

Esta es una de las reglas centrales:

PRICE FALL
≠
AUTOMATIC INVALIDATION

Una caída de precio no significa necesariamente que la tesis económica haya muerto.

La tesis se invalida cuando se rompe el mecanismo de creación de valor.

Ejemplos:

ROIC
ROIC deteriora estructuralmente
Market share
pérdida material de market share
Growth runway
desaparición del espacio económico para crecer
Incremental returns
caída estructural de retornos sobre nuevo capital
Cash
FCF deja estructuralmente de acompañar earnings
Management
asignación destructiva de capital
Competitive advantage
deterioro de la ventaja competitiva
Catalyst

Si el catalyst era esencial para la tesis:

catalyst desaparece
Riesgo estructural

Aparece un riesgo que hace incompatible la tesis original.

19. Trigger

El Thesis Engine no inventa el trigger.

El trigger depende del Factor Engine.

Momentum
ranking positivo
+
tendencia positiva
Quality
quality confirmada
+
fundamentales confirmados
+
valoración aceptable
Value
valuation threshold
+
quality threshold
Value / Momentum
valuation atractiva
+
momentum positivo
+
trend positivo

Por tanto:

THESIS
+
TRIGGER
=
ACTIVE OPPORTUNITY

Una buena tesis sin trigger puede quedar:

WATCH
20. Estados de la tesis

El sistema utiliza:

WATCH
ACTIVE
HOLD
WEAKENING
REDUCE
EXIT
INVALIDATED
WATCH

La situación es interesante pero todavía no existe trigger suficiente.

ACTIVE

El trigger se ha cumplido.

HOLD

La tesis y el factor siguen intactos.

WEAKENING

Existe evidencia negativa, pero todavía no suficiente para invalidar.

REDUCE

Existe deterioro material.

EXIT

Se ha cumplido una regla de salida.

INVALIDATED

La hipótesis económica dejó de ser válida.

21. Prioridad de decisión

La jerarquía es:

INVALIDATION
      >
RISK
      >
FACTOR SIGNAL
      >
THESIS
      >
OPPORTUNITY

Esto evita un error importante:

Mantener una inversión simplemente porque el upside teórico sigue siendo enorme.

Si la invalidación es clara:

INVALIDATION
>
UPSIDE
22. Output YAML estándar

El agente debe generar una estructura de salida consistente:

asset:
motor:

thesis:
  statement:
  why_now:
  expected_driver:

evidence:
  factor:
  fundamental:
  market:

compounder:
  growth_runway:
  high_roic:
  reinvestment_runway:
  durability:
  classification:

drivers:
  - driver:
    mechanism:
  - driver:
    mechanism:
  - driver:
    mechanism:

acceleration:
  status:
  evidence:

management:
  capital_allocation:
  integrity:

cash_conversion:
  status:

catalyst:
  event:

scenarios:
  bullish:
    condition:
    confirmation:
    expected_behavior:

  base:
    condition:
    expected_behavior:

  bearish:
    condition:
    invalidation:

risk:
  primary:
  secondary:

invalidation:
  - condition:
  - condition:

decision:

Este formato es deliberadamente pequeño.

23. Asymmetric Compounder

Se agrega una alerta conceptual:

COMPOUNDER
+
ACCELERATION
+
CATALYST
+
VALUATION ACCEPTABLE
=
ASYMMETRIC COMPOUNDER

No significa:

BUY

Significa:

Prioridad alta de investigación.

La situación buscada es aquella donde:

capacidad futura de crecimiento
+
capacidad de reinversión
+
ventaja competitiva

pueden estar subestimadas por el mercado.

24. Weekly Agent Cycle

El ciclo operativo:

UPDATE DATA
      ↓
CHECK SIGNAL
      ↓
CHECK THESIS
      ↓
CHECK COMPOUNDER STATUS
      ↓
CHECK ACCELERATION
      ↓
CHECK SCENARIOS
      ↓
CHECK INVALIDATION
      ↓
SEARCH NEW CANDIDATES
      ↓
GENERATE REPORT

Importante:

Revisión semanal ≠ trading semanal.

El sistema puede actualizarse semanalmente mientras las decisiones de inversión tengan horizontes de meses o años.

25. Agentes
QUALITY_AGENT

Responsabilidades:

evaluar calidad;
analizar evolución fundamental;
detectar Compounders;
detectar mejora;
detectar deterioro.

No decide la cartera.

THESIS_AGENT

Responsabilidades:

construir la tesis;
identificar drivers;
explicar el mecanismo económico;
ejecutar Compounder Test;
evaluar aceleración;
construir escenarios;
identificar riesgos;
definir invalidación;
actualizar la tesis.

Es el agente central del Thesis Engine.

DECISION_AGENT

Consolida:

Factor
+
Thesis
+
Scenarios
+
Risk
+
Invalidation
+
Trigger

Y genera:

NEW
HOLD
WATCH
REDUCE
EXIT

La decisión final sigue separada de la construcción de la tesis.

26. Fundamentos intelectuales incorporados

La versión incorpora principios asociados a inversores reconocidos en Compounders.

Inversor	Concepto incorporado
Warren Buffett	ROIC, reinversión, asignación de capital, owner earnings
Charlie Munger	calidad económica, ventaja competitiva, duración del compounding
Philip Fisher	growth runway, competencia, management, innovación
Terry Smith	alto ROIC + crecimiento mediante reinversión + resiliencia
Nick Sleep	economías de escala compartidas y mecanismos auto-reforzados

La intención no es copiar mecánicamente sus carteras.

Se incorporan principios económicos.

27. Qué NO incorporar

Para proteger la simplicidad del sistema:

No
score 0–100;
DCF obligatorio;
TAM obligatorio;
probabilidades subjetivas;
Monte Carlo;
múltiples agentes de tesis;
20+ KPIs;
múltiples indicadores técnicos;
predicción de precio;
estimaciones arbitrarias de crecimiento;
PEG como regla universal;
P/E universal;
moat score;
ranking compuesto de Compounders;
más de tres growth drivers;
múltiples catalysts principales.

La razón es evitar:

COMPLEJIDAD
+
FALSA PRECISIÓN
+
OVERFITTING CONCEPTUAL
28. Regla central del Compounder

La regla más importante del motor es:

Una empresa no es Compounder porque crezca rápido. Es Compounder si puede reinvertir una parte significativa de sus beneficios durante mucho tiempo a retornos altos y proteger esos retornos mediante una ventaja competitiva durable.

Esto permite diferenciar:

Caso A
Revenue +50%
ROIC ↓

Puede ser una mala inversión.

Caso B
Revenue +20%
ROIC 30%
Reinvestment runway 10 años
Moat ↑
FCF ↑

Puede convertirse en un extraordinario Compounder.

29. Compatibilidad con IDOS

El Thesis Engine v1 no modifica:

Portfolio Construction;
Capital Allocation;
Risk Guardian;
Factor Engines;
Scenario Engine;
Decision Engine.

Su función es exclusivamente:

OPPORTUNITY
      ↓
ECONOMIC HYPOTHESIS
      ↓
COMPOUNDER TEST
      ↓
SCENARIOS
      ↓
MONITORING
      ↓
INVALIDATION

El output es:

una tesis de inversión estructurada, no una recomendación automática de compra.

30. Principio final del sistema

El Thesis Engine no intenta predecir el futuro.

Busca situaciones donde:

existe evidencia favorable;
existe un mecanismo económico comprensible;
existe runway para crecer;
existe capacidad de reinversión;
los retornos pueden defenderse;
existen señales de aceleración cuando corresponda;
la valoración deja margen para una asimetría atractiva;
sabemos qué evidencia demostraría que estamos equivocados.

La pregunta central del motor queda:

No "¿cuánto subirá la acción?", sino "¿qué mecanismo económico puede hacer que esta empresa cree mucho más valor durante los próximos años y qué evidencia demostrará que estamos equivocados?"

Arquitectura final resumida
                 FACTOR ENGINE
                       │
                       ▼
                  CANDIDATE
                       │
                       ▼
             ┌───────────────────┐
             │  THESIS ENGINE v1 │
             ├───────────────────┤
             │ Thesis            │
             │ Why Now           │
             │ Compounder Test   │
             │  • Growth Runway  │
             │  • High ROIC      │
             │  • Reinvestment   │
             │  • Durability     │
             │ Growth Drivers    │
             │ Acceleration      │
             │ Management        │
             │ Cash Conversion   │
             │ Catalyst          │
             └─────────┬─────────┘
                       │
                       ▼
               SCENARIO ENGINE
                       │
                       ▼
                  MONITORING
                       │
                       ▼
                 INVALIDATION
                       │
                       ▼
                DECISION ENGINE
                       │
             ┌─────────┼─────────┐
             ▼         ▼         ▼
            NEW       HOLD      EXIT

En esencia, el Thesis Engine v1 queda deliberadamente pequeño: toma una oportunidad detectada por un factor y obliga al sistema a demostrar por qué puede convertirse en un Compounder, cuál es el mecanismo de crecimiento, si ese crecimiento está acelerando, qué puede hacer que el mercado lo reconozca y qué evidencia demostraría que la tesis dejó de ser válida. Esa es la pieza que faltaba para conectar los motores de factores con una tesis fundamental realmente automatizable