# TDD Agent Pipeline (Agent Teams)

> EXPERIMENTAL -- Este pipeline depende de Agent Teams, una feature experimental
> de Claude Code. Alto consumo de tokens (~300K+ por ejecucion completa).
> Solo para features grandes con logica de negocio critica.

Pipeline de desarrollo completo orquestado por Agent Teams.
Cada agente tiene un rol aislado para garantizar disciplina TDD real.

## Prerequisitos

- Agent Teams habilitado:
  ```bash
  export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
  ```
- Plugins instalados: code-review-expert, staff-reviewers, dev-tools

## Pipeline

```
SUPERVISOR (Team Lead) -- Orquesta el flujo, media feedback, aprueba merge

  (a) Test Writer       Escribe tests (RED). Deben FALLAR.
       |                Si pasan -> feedback: "test inutil, reescribir"
       v
  (b) Implementer       Codigo minimo para pasar tests (GREEN).
       |                Max 3 ciclos si tests siguen fallando.
       v
  (c) Simplifier        Refactoring sin romper tests (REFACTOR).
       |                Usa el built-in /simplify de Claude Code
       |                Verifica: tests SIGUEN pasando.
       v
  (d)(e)(f) EN PARALELO:
       (d) Quality      code-review-expert (SOLID, dead code, P0-P3)
       (e) Security     dev-tools:qlty-auditor (bandit, trivy, semgrep)
       (f) Domain       staff-reviewers (backend/frontend/iac segun proyecto)
       |
       v                Si P0/P1 -> feedback al Implementer (max 2 ciclos)
  (g) Doc Updater       Actualiza README, CLAUDE.md, CHANGELOG
       |
       v
  READY FOR COMMIT/PR
```

## Safety limits

| Ciclo | Max iteraciones | Si se supera |
|-------|-----------------|--------------|
| Red-Green (a->b) | 3 | STOP, pedir intervencion humana |
| Quality fixes (d/e/f->b) | 2 | STOP, pedir intervencion humana |
| Refactor (c) | 1 | Si rompe tests, revertir |

## Cuando usar este pipeline

- Features nuevas grandes (5+ ficheros, logica de negocio compleja)
- Refactors mayores con cobertura de tests existente
- Cambios criticos donde el coste de un bug supera el coste del pipeline

## Cuando NO usar este pipeline

- Fixes triviales de 1-2 lineas
- Cambios de documentacion
- Actualizacion de dependencias
- Cambios de configuracion
