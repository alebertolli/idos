# Corrección del horizonte de escenarios en Research

## Síntoma observado

La ejecución DDD `45846805275` terminó en fallo de calidad después de investigar AAPL y ADI. El informe de `OPP-MB-ADI` contenía `scenario_analysis` estructurado, pero `horizon_date: null`. La validación de escenarios lo rechazó como `horizon_date debe ser una fecha ISO válida`; el candidato se diferió y el paso de continuación horaria no se ejecutó.

El PR de resultados `#865` publicó el resultado parcial. El CI del commit base `dc8f9341284a9539a90ec01a265bb8111cebf32c` pasó, aunque la ejecución DDD citada quedó con conclusión `failure`.

## Cambio propuesto

- Cuando un escenario estructurado omite el horizonte, Research lo completa con una convención explícita de 365 días desde `as_of_date`.
- El informe conserva `horizon_basis: idos_default_365_days`, y la interfaz lo muestra como convención del sistema.
- Las fechas explícitas que no sean válidas siguen siendo rechazadas.
- Los prompts DDD y MULTIBAGGERS describen el mismo criterio para evitar que el modelo lo interprete como evidencia de mercado.
- Si `scenario_analysis` es nulo o carece de una fecha de análisis válida, no se inventa un horizonte y las validaciones existentes se mantienen.

## Validación y seguimiento

La suite remota de CI del PR debe validar los cambios y los tests de normalización. Después de integrar, el flujo DDD de producción debe comprobar que ADI ya no vuelve a la cola por `horizon_date`, que el paso de continuación se ejecuta y que otro candidato de la cola se publica. Esta nota no afirma que esa verificación de producción ya haya ocurrido.

## Hallazgo adicional en producción

La primera corrida sobre el código integrado volvió a diferir E. Su informe decía `as_of_date: 2026-11-01`, aunque la fecha confiable de la ejecución era `2026-11-26` y las seis fuentes citadas también estaban fechadas el 26. El validador rechazó la fecha antigua y todas las fuentes como posteriores a ella. No fue un fallo del proveedor.

El seguimiento ancla `as_of_date` a la fecha ISO confiable de Research y registra `as_of_basis: idos_analysis_date`. Si el horizonte está ausente, el default de 365 días se calcula desde esa fecha confiable. Las fechas de fuente posteriores al análisis y los horizontes explícitos inválidos siguen bloqueados por el validador.

La suite remota y una nueva corrida de producción deben verificar este seguimiento antes de considerarlo cerrado.
