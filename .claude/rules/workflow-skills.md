# Skills & Automation

Si haces algo mas de una vez al dia, conviertelo en una skill o comando.
(Boris Cherny, 10 Team Tips, Feb 2026, tip #4)

## Reglas

- **Deteccion de repeticion**: Si detectas que ejecutas la misma secuencia de acciones
  por segunda vez en el dia, pregunta: "He notado que repites este patron.
  Quieres que lo convierta en un skill?"
- **Si el usuario acepta**: Inicia el wizard /create para crear el skill
- **Skills en git**: Siempre commitear skills al repositorio para reutilizar

## Que convertir en skill

| Patron repetitivo | Skill candidato |
|-------------------|-----------------|
| Sincronizar contexto de Slack/GDrive/GitHub | skill personalizado |
| Ejecutar bateria de checks pre-PR | `/pre-pr-check` |
| Generar boilerplate de un tipo de componente | `/scaffold <tipo>` |
| Consultar metricas de una base de datos | `/query <db>` |
| Limpiar tech debt al final de sesion | `/techdebt` |

## Wizard de creacion

```
/create skill    # Wizard interactivo para crear una skill nueva
/create agent    # Wizard para crear un agente
/create hooks    # Wizard para configurar hooks
```
