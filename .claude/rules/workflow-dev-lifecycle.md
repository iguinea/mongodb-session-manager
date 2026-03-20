# Development Lifecycle Workflow

> Requiere el plugin `dev-workflow` del marketplace claudio-plugins.

Para features complejas que requieran un flujo E2E completo (desde requisitos
hasta implementacion con tests), usar el plugin `dev-workflow`:

## Comandos
- `/dev-workflow` -- Lanza el workflow completo o una fase especifica (--phase a|b|c|d)
- `/dev-workflow-refine` -- Refina el plan con nuevas transcripciones de reuniones

## Fases
- **Phase A**: Requisitos (transcripciones -> PRD -> plan iterativo)
- **Phase B**: Diseno tecnico (doc-research -> ADRs -> diagramas -> contratos)
- **Phase C**: Implementacion (feature-dev + TDD + Agent Teams + code review)
- **Phase D**: Generacion de rules con validacion del usuario

Cada fase es independiente. Usa `--phase` para empezar en cualquiera.
