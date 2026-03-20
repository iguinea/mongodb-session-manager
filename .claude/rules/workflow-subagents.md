# Subagent Strategy

Usa subagentes liberalmente para mantener la ventana de contexto principal limpia y enfocada.
(Boris Cherny, 10 Team Tips, Feb 2026, tip #8)

## Arbol de decision

```
Necesitas que multiples agentes trabajen simultaneamente?
|
+-- NO --> Usa una sesion individual de Claude Code
|
+-- SI --> Las tareas son independientes entre si?
      |
      +-- NO (dependen unas de otras) --> Usa subagents (Tool: Agent)
      |
      +-- SI --> Las tareas modifican ficheros diferentes?
            |
            +-- NO (mismo fichero) --> Usa subagents secuenciales
            |
            +-- SI --> Usa Agent Teams
```

## Cuando usar subagentes

- **Investigacion/exploracion**: Delegar busquedas amplias a un subagente Explore
- **Analisis en paralelo**: Lanzar multiples analisis independientes con run_in_background
- **Proteger contexto**: Offload tareas pesadas para no contaminar la ventana principal
- **Una tarea por subagente**: Dar instrucciones claras y especificas a cada uno

## Cuando usar Agent Teams

- Tareas independientes en ficheros distintos
- Necesitas ver progreso de cada agente (tmux mode)
- Pipeline TDD completo (ver workflow-tdd-pipeline.md)

## Cuando usar sesion individual

- Tareas sencillas y secuenciales
- Debugging interactivo
- Conversacion exploratoria

## Tips

- "Usa subagentes" como instruccion en cualquier peticion donde quieras que
  Claude dedique mas computo al problema
- Delegar tareas individuales a subagentes mantiene el contexto del agente
  principal limpio y enfocado
