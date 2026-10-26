# Contratos operativos: oportunidades, horarios y reglas

Estado: adoptado para la implementación. Zona operativa: Argentina (`America/Argentina/Buenos_Aires`, UTC−03:00).

## Identidad y ciclos de oportunidades

Todas las estrategias usan `OPP-{ESTRATEGIA}-{TICKER}-{CICLO}`, con estrategia y ticker en mayúsculas y ciclo de cuatro dígitos. El ciclo es secuencial por combinación de estrategia y ticker, empieza en `0001` y se guarda como `opportunity_cycle` en el registro.

Ejemplos: `OPP-COMPOUNDER-AAPL-0001`, `OPP-MULTIBAGGERS-AAPL-0001` y `OPP-MOMENTUM-ETF-XLF-0012`. El identificador distingue estrategias aunque coincida el ticker.

Una oportunidad activa es idempotente: nuevas ejecuciones actualizan evidencia de Discovery y no generan otro caso ni reinician su decisión. Después de `EXITED`, `POST_MORTEM` o `ARCHIVED` (también `CLOSED`/`REJECTED` legados), el siguiente descubrimiento crea el ciclo siguiente. Un registro legado sin `opportunity_cycle`, incluidos IDs como `OPP-MB-AAPL`, cuenta como ciclo `0001`; por lo tanto, su siguiente caso será `0002`. Los registros terminales se conservan como historial.

## Horarios

GitHub Actions interpreta `schedule.cron` en UTC. Los cron se expresan con el desplazamiento fijo de Argentina, UTC−03:00, y los jobs definen `TZ=America/Argentina/Buenos_Aires` para comandos y fechas de reportes. Los timestamps de observaciones de proveedores que declaran UTC conservan esa referencia original.

| Flujo | Hora local | Cron UTC |
|---|---:|---|
| Monthly Universe | Día 1, 00:00 | `0 3 1 * *` |
| DDD mensual | Día 2, 00:00 | `0 3 2 * *` |
| DDD re-research | Ciclo */30, 06:00 | `0 9 */30 * *` |
| Daily Refresh | Lun–vie, 08:00 | `0 11 * * 1-5` |
| Monthly Rebalance | Día 3, 06:00 | `0 9 3 * *` |
| Board Review | Día 4, 06:00 | `0 9 4 * *` |
| Friday Digest | Viernes, 21:00 | `0 0 * * 6` |

El horario de cron no cambia por horario de verano en Argentina. Si se cambia de zona operativa, actualizar juntos los cron, `TZ`, esta tabla y sus pruebas.

## Explicaciones de reglas fallidas

En el detalle de cada oportunidad, el Dashboard muestra una sección abierta `Motivos de reglas fallidas`. Cada ID fallido aparece con el detalle persistido por Assessment. Si falta, se muestra una explicación base conocida de esa regla; IDs desconocidos indican que la evaluación no guardó detalle específico. Los detalles de reglas superadas permanecen colapsados.

La explicación del fallo informa qué condición no se cumplió; no constituye una recomendación de inversión. Assessment sigue siendo la fuente de los valores y umbrales evaluados.

## Verificación

Las pruebas cubren formato y separación de IDs, avance de ciclo tras registros legados terminales, explicación visible de RULE-005/RULE-008 y conversión de cron a las horas locales enumeradas. La CI del PR valida los flujos y el conjunto de pruebas. No se dispara una ejecución de producción para verificar cambios de calendario.
