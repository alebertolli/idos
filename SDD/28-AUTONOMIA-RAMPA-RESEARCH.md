# Recuperación autónoma de la rampa Research

## Problema

La rampa DDD podía quedar bloqueada por dos causas operativas: un checkpoint sin pendientes no volvía a descubrir oportunidades y cualquier error de una sola oportunidad pausaba todo el lote. El operador debía iniciar manualmente la siembra o el resume.

## Decisión

- En la ejecución horaria, una cola vacía activa un nuevo escaneo con los filtros actuales de Discovery. Los controles de cartera, Buy List, estrategia y estado siguen aplicándose.
- Los estados heredados `paused` se reanudan en forma automática al último tamaño de lote probado.
- Los límites de cuota del proveedor no repiten llamadas durante el cooldown: se persiste `provider_retry_after` con backoff exponencial de 1, 2, 4… hasta 24 horas. Al vencer, el cron vuelve a procesar la cola.
- Los errores locales de una oportunidad se reintentan hasta tres veces, separados por un día. Tras el tercer intento se guardan en cuarentena con motivo y timestamp; el resto de la cola continúa.
- Una oportunidad completada solo cuenta como trabajo completo cuando ResearchWorker la marca `completed`; si su informe presenta `scenario_validation` distinto de `valid_pending_decision_board`, se trata como error local y no aumenta el lote.
- El lote solo aumenta tras un lote completo sin errores. Los fallos de proveedores nunca suben el tamaño.
- Cola, capacidad, resultados y cuarentena se publican en la rama de resultados para auditoría. La cuarentena no significa Research completado ni habilita Assessment.
- Después de publicar y fusionar cada lote, el workflow vuelve a leer la cola durable de `main` y despacha una única reanudación si queda trabajo vencido y el proveedor está fuera de cooldown. Así los lotes no dependen de que GitHub entregue cada evento `schedule`; la rampa mantiene el límite de tamaño y no inicia una llamada durante espera o pausa.
- El workflow espera tanto el CI de `workflow_dispatch` como todos los checks del PR de resultados y luego lo fusiona directamente. No depende de Auto-merge de GitHub, que requiere reglas de protección de rama; si esa función está deshabilitada en el repositorio, el lote previo se publica pero no arranca el siguiente.
- La reanudación manual (`resume_hourly_ramp`) recupera una rampa pausada y reinicia el tamaño al último lote probado. La continuación automática usa `continue_hourly_ramp`: conserva el siguiente tamaño persistido y evita repetir la evaluación mensual, de modo que la rampa pueda crecer tras cada lote exitoso.
- Las fuentes de cotización entregan `as_of_date` como fecha ISO `YYYY-MM-DD` en cada referencia. El allowlist del validador también incluye sólo URLs financieras cuyo `selected_source` figure en los datos usados por Research. Un timestamp en lugar de fecha o una URL financiera elegida pero no incluida en el allowlist hace que la oportunidad se reintente como `invalid_pending_revision`.
- En la frontera de salida del modelo, los IDs conocidos de escenarios (`BEAR`, `BASE`, `BULL`) se normalizan por mayúsculas/minúsculas y espacios externos antes de validar. Los valores desconocidos siguen fallando cerrados; el validador de contratos permanece estricto.

## Incidente de pérdida de cola (2026-11-19)

El `repository_dispatch` `quarterly-results` (run [44596615424](https://github.com/alebertolli/idos/actions/runs/44596615424)) procesó NVDA correctamente, pero inicializó la cola como vacía porque no era un resume horario. El commit de resultados fusionado por PR #367 reemplazó los 189 pendientes por `pending: []`. Se restauraron los 188 pendientes restantes desde el checkpoint anterior, excluyendo NVDA que ya quedó investigado, en el commit `d06f9ca68f34df1779353d6beeea8306b989d443`. La corrección hace que cualquier ejecución de la rampa cargue la cola existente antes de añadir candidatos de evento y habilita la continuación acotada entre lotes.

## Verificación

Pruebas: estado/backoff y límite de cuota; reanudación con cola vacía; preservación de cola frente a eventos; puerta de despacho para trabajo vencido; persistencia del intento local y continuidad; cuarentena tras tres fallos. Antes de integrar la corrección, el run real de `quarterly-results` demostró que Research puede terminar y aun así perder los pendientes de la cola. Debe verificarse el siguiente resume con la cantidad de candidatos completados y pendientes persistida en `main`.

En `2026-11-19`, el run [44615144605](https://github.com/alebertolli/idos/actions/runs/44615144605) completó dos investigaciones, publicó el PR #382 y pasó CI, pero falló al pedir `gh pr merge --auto`: GitHub indicó que no había reglas de rama protegida para habilitar Auto-merge. El PR se fusionó tras verificar sus checks. La continuación queda corregida para esperar los checks del PR y ejecutar la fusión directa antes del despacho siguiente.

## Incidente de handoff CI (2026-11-20)

Los runs [#44627427454](https://github.com/alebertolli/idos/actions/runs/44627427454) y [#44657883594](https://github.com/alebertolli/idos/actions/runs/44657883594) terminaron con error al consultar el estado de Actions; uno devolvió HTTP 500 desde la API. El run [#44723662253](https://github.com/alebertolli/idos/actions/runs/44723662253) también llegó a publicar resultados y ejecutar el CI completo por `workflow_dispatch`, pero el paso `gh pr checks` informó que no había checks en la rama. Los checks de la ejecución `workflow_dispatch` pasan en el SHA de la rama de resultados; no siempre están asociados al evento `pull_request` y por eso ese comando no es una señal de validación confiable.

La corrección espera el run `workflow_dispatch` recién lanzado con reintentos para errores transitorios de la API, exige `conclusion=success`, `event=workflow_dispatch` y que su `headSha` coincida con el SHA actual del PR; vuelve a comprobar ese SHA antes de fusionar. Un cambio de commit durante CI falla de forma segura. El PR de resultados [#390](https://github.com/alebertolli/idos/pull/390) tiene CI manual exitoso en Python 3.11 y 3.12, pero quedó sin fusionar por el handoff anterior. La próxima ejecución debe demostrar que se publica ese estado y que la continuación vuelve a dispararse.

En el run #44723662253, OpenAI respondió correctamente como proveedor de fallback; Gemini devolvió HTTP 400 y Groq informó cuota agotada (429). Una de las tres oportunidades tuvo `scenario_validation=invalid_pending_revision` y se reprogramó sin pausar el resto. Es un error de calidad por candidato, separado del fallo de publicación. La cola en el checkpoint actual continúa `paused=false`; el lote sólo crece después de un lote enteramente exitoso.

## Límites

GitHub Actions cron puede retrasarse y no se garantiza puntualidad horaria. La continuación automática necesita que la publicación del lote y el CI del PR de resultados terminen; un fallo de CI detiene la cadena hasta la siguiente acción efectiva. Un proveedor sin cuota puede mantener la cola en espera hasta 24 horas entre reintentos. Los casos en cuarentena necesitan corrección de datos/código para volver a intentarse; quedan persistidos para revisión, sin detener otras oportunidades.
