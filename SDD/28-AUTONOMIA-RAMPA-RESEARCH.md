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

## Verificación

Pruebas previstas: estado/backoff y límite de cuota; reanudación con cola vacía; persistencia del intento local y continuidad de la cola; preservación del tamaño probado; cuarentena tras tres fallos. Validación E2E en GitHub Actions pendiente de CI y ejecución programada después de integrar el cambio.

## Límites

GitHub Actions cron puede retrasarse y la recuperación opera en la próxima ejecución efectiva; no se garantiza puntualidad horaria. Un proveedor sin cuota puede mantener la cola en espera hasta 24 horas entre reintentos. Los casos en cuarentena necesitan corrección de datos/código para volver a intentarse; quedan persistidos para revisión, sin detener otras oportunidades.
