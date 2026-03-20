# Multi-model Research

Para decisiones tecnicas importantes, investigar con multiples modelos de IA
para obtener perspectivas diversas y reducir sesgos.

> **Prerequisito**: plugin `multi-model-research` del marketplace claudio-plugins
> + Codex CLI y/o Gemini CLI con API keys.

## Cuando usar

- Evaluacion de tecnologias (Kafka vs SQS, PostgreSQL vs DynamoDB)
- Decisiones arquitectonicas (monolito vs microservicios)
- Feasibility analysis de nuevas features
- Code analysis profundo del codebase
- Validacion de planes de implementacion

## Como usar

```
/research <objetivo>
```

Tipos de investigacion:
- **feasibility** -- Viabilidad, blockers, soluciones existentes
- **technical** -- Evaluacion tecnologica, benchmarks, best practices
- **feature-planning** -- Diseno arquitectonico, fases, estimacion
- **code-analysis** -- Calidad, issues, mejoras, metricas

## Validar planes con research

Despues de crear un plan con `/plan`, pasar por multi-model research:

1. `/plan <tarea>` -- Crear plan detallado
2. `/research feature-planning "Validar el plan de <tarea>"` -- 3 modelos opinan
3. Si hay divergencias: incorporar feedback y refinar con `/plan`
4. `/review` -- Validacion adversarial final

## Output

Genera workspace `.research/<timestamp>/` con:
- Hallazgos individuales de cada modelo
- SYNTHESIS.md con matriz de consenso (UNANIME / MAYORIA / DIVIDIDO / UNICO)
- Recomendaciones priorizadas
