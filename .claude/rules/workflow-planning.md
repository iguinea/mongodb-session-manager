# Planning First

Entra en modo plan para CUALQUIER tarea no trivial (3+ pasos o decisiones arquitectonicas).

## Reglas

- **Specs detalladas**: Escribe especificaciones claras antes de delegar trabajo. Cuanto mas
  especifico seas, mejor sera el resultado.
- **Re-planificar si falla**: Si algo se tuerce, STOP inmediato y vuelve a modo plan.
  No sigas empujando. Replantifica.
- **Plan mode para verificacion**: Usa modo plan no solo para construir, sino tambien para
  los pasos de verificacion.
- **Verificar antes de dar por hecho**: Nunca marques una tarea como completa sin demostrar
  que funciona. Ejecuta tests, revisa logs, demuestra correccion.

## Plugin: plan-review

Para tareas complejas, usar el ciclo iterativo de planificacion:

1. `/plan <tarea>` -- Crea un plan detallado con fases, ficheros, criterios de aceptacion
2. `/review` -- Un agente adversarial critica el plan e identifica debilidades
3. Iterar 2-3 ciclos hasta que el reviewer de aprobacion
4. Solo entonces empezar a implementar

## Flujo con multi-model-research (opcional)

Para decisiones arquitectonicas importantes:

1. `/research feature-planning <objetivo>` -- 3 modelos dan perspectiva amplia
2. Alimentar esos hallazgos en `/plan` para crear plan detallado
3. `/review` para validar adversarialmente
