# Autonomía de Buy List e invalidación de tesis

**Fecha:** 2026-11-20  
**Estado:** Implementación en rama de revisión  
**Alcance:** autorización de oportunidades en la Buy List pública y retiro cuando la tesis queda invalidada.

## Decisión

Por instrucción del gestor, la aprobación humana deja de ser un paso obligatorio para entrar o salir de Buy List. El sistema admite una oportunidad sólo cuando pasan todas las reglas activas de autorización configuradas, RULE-008 y sus validaciones de fuentes/fechas, y hay precio actual y precio objetivo válidos. Si falta evidencia o una regla falla, la oportunidad queda bloqueada con motivo auditable; no se genera una cola de aprobación humana.

Un consenso de objetivos de analistas es contexto de mercado y no constituye valor intrínseco. No debe mejorar el puntaje de valoración ni llenar `intrinsic_value`; Assessment y Buy List sólo pueden usar un objetivo con base de valuación independiente explícita. Los valores heredados sin esa base no se consideran válidos y se limpian en la siguiente evaluación.

La admisión conserva el estado de Research/Assessment y registra `approved_for_buylist=true`, resolución automática ligada al hash del Assessment y un archivo inmutable en `decisions/`. El máximo sugerido respeta el límite de posición configurado por estrategia. La Buy List sigue siendo una lista pública de seguimiento: no representa sizing de cartera privada, no crea posiciones, no envía órdenes y no opera con broker. La falta de conexión del portfolio privado no se completa con datos supuestos.

Cuando Thesis Monitor confirma `thesis_active=false`, IDOS quita únicamente la entrada del `(ticker, opp_id)` invalidado, marca la aprobación revocada y agrega un registro de auditoría sin sobrescribir decisiones anteriores. La revisión mensual incluye candidatos que están en Buy List aunque todavía no haya una posición. La cadencia sigue el `thesis_review_interval_days` de la estrategia; ante invalidación confirmada, el retiro no espera autorización humana. Una posición existente no se vende ni se cierra por este cambio.

## Impacto y migración

- `assessment_pipeline` convierte el pase completo de reglas en autorización automática incluso cuando el score general está entre 65 y 69 y la etiqueta previa era `PENDING_REVIEW`; el umbral configurado por RULE-005 sigue siendo vinculante.
- `BuyListRefreshWorker` conserva aprobaciones automáticas para perfiles `MANUAL_REVIEW`; Entry Monitor sigue respetando la política de entrada de cada estrategia.
- Oportunidades históricas que quedaron en `PENDING_HUMAN_REVIEW` se reevalúan en grupos acotados de hasta cinco por ejecución normal de Assessment. Se recalculan gates con su expediente guardado y fuentes disponibles; la validación falla de forma segura si la evidencia ya no está vigente.
- No se fuerza un Research nuevo ni se inicia una corrida en producción al cambiar el código.

## Archivos principales

- `idos-core/idos/decision/automatic_buylist.py`: autorización automática, persistencia auditable y revocación idempotente.
- `idos-core/idos/decision/assessment_pipeline.py`: integra la autorización y bloquea sin espera humana si no pasan los gates.
- `idos-core/idos/workers/portfolio/buy_list_refresh_worker.py`: conserva las nuevas admisiones y elimina entradas de tesis invalidadas.
- `idos-core/idos/workers/ai/thesis_monitor_worker.py` y `monthly_reassessment_worker.py`: retiran oportunidades invalidada; el monitor mensual incluye las que sólo están en Buy List.
- `scripts/ddd_assessment.py`: migración acotada de propuestas históricas pendientes.
- `idos-core/idos/site/builder.py`: comunica estados automáticos en dashboard.
- `SDD/requirements.md`, `SDD/5.DOMINIO-Investment Decision Framework (IDF).md`, `SDD/7.DOMINIO-Investment Lifecycle Framework (ILF).md`, `SDD/9.DOMINIO-Investment Playbook & Operating Rules (IPOR).md`.

## Validación

Validación local ejecutada en rama de prueba:

- `python -m pytest -q tests/test_decision/test_automatic_buylist.py tests/test_ai/test_monthly_reassessment.py tests/test_ai/test_thesis_monitor_worker.py tests/test_discovery/test_multibaggers.py tests/test_systematic_lifecycle.py tests/test_workers/test_buy_list_refresh_worker.py`: **47 passed**.
- `python -m compileall -q idos scripts tests`: completó sin errores.
- `git -c core.whitespace=cr-at-eol diff --check`: sin errores.
- La cobertura incluye admisión automática con gates completos, bloqueo al faltar regla, refresh de Buy List, invalidación confirmada con retiro exacto, persistencia de auditoría, conservación de una posición existente, selección mensual de candidatas y dashboard de bloqueos. Se usaron datos sintéticos y providers simulados; no hubo llamadas a modelos, broker, workflows ni escritura en producción.

Límite de esta validación: no se ejecutó un recorrido live contra datos actuales de NVDA ni una corrida completa de Research con proveedores externos. La rama requiere revisión y merge antes de que la migración histórica y el ciclo mensual actúen en producción.

## Límites y reversión

La automatización sólo aplica a Buy List y se limita a los gates deterministas actuales. No convierte reglas fallidas, escenarios cualitativos o datos ausentes en aprobaciones. El retiro de una candidata no constituye recomendación de venta ni transacción. Para revertir el código se revierte el cambio de software; no se borran registros automáticos históricos y las entradas ya revocadas sólo se restauran mediante una evaluación vigente.


## Incidente y corrección — 2026-11-27

El Assessment de TXN del 2026-11-26 usó el objetivo medio de analistas USD 339.66 como `intrinsic_value`. Esto generó una señal de potencial alcista de 25.7%, elevó Valuation a 65 y Conviction a 66; por eso pasaron RULE-005 y los seis gates de autorización. El informe Research, sin embargo, aclaraba que el consenso no prueba valor intrínseco y que no había una valoración fundamental verificable.

La corrección separa el consenso de la valuación, exige una base independiente reconocida antes de aceptar `intrinsic_value` y elimina los objetivos heredados no trazables en la siguiente evaluación. TXN fue retirada de Buy List con una revocación auditable; su aprobación original permanece en el historial. No se modificaron posiciones ni órdenes.

En la ejecución DDD #1186, el job terminó correctamente, pero no procesó candidatos: el log dice que la cola estaba vacía, hubo 0 oportunidades vencidas y no encontró oportunidades elegibles; Assessment indicó que no tenía oportunidades. Es un no-op exitoso, no una corrida que haya completado Research para activos.
