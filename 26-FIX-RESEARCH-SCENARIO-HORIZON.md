# Corrección del horizonte de escenarios en Research

## Síntoma observado

La ejecución DDD `45846805275` investigó AAPL y ADI. El informe de `OPP-MB-ADI` contenía `scenario_analysis` estructurado, pero `horizon_date: null`. La validación lo rechazó como `horizon_date debe ser una fecha ISO válida` y difirió ADI. El workflow terminó con `failure`, pero su paso de continuación sí despachó otra corrida. La ejecución `45848516625` completó Research de ASML y dejó pendiente la publicación de esa tanda.

El PR de resultados `#865` publicó el resultado parcial. El CI del commit base `dc8f9341284a9539a90ec01a265bb8111cebf32c` pasó, aunque la ejecución DDD citada quedó con conclusión `failure`.

## Cambio propuesto

- Cuando un escenario estructurado omite el horizonte, Research lo completa con una convención explícita de 365 días desde `as_of_date`.
- El informe conserva `horizon_basis: idos_default_365_days`, y la interfaz lo muestra como convención del sistema.
- Las fechas explícitas que no sean válidas siguen siendo rechazadas.
- Los prompts DDD y MULTIBAGGERS describen el mismo criterio para evitar que el modelo lo interprete como evidencia de mercado.
- Si `scenario_analysis` es nulo o carece de una fecha de análisis válida, no se inventa un horizonte y las validaciones existentes se mantienen.

## Validación y seguimiento

La suite remota de CI del PR debe validar los cambios y los tests de normalización. Después de integrar, el flujo DDD de producción debe comprobar que ADI ya no vuelve a la cola por `horizon_date`, que el paso de continuación se ejecuta y que otro candidato de la cola se publica. Esta nota no afirma que esa verificación de producción ya haya ocurrido.
