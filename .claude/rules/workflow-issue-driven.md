# Issue-Driven Development

Todo trabajo de desarrollo tiene una GitHub Issue como punto de partida.
Si no existe, se crea antes de empezar. Flujo completo:
Issue -> Worktree -> Desarrollo -> Quality Gate -> PR -> Cleanup.

## Phase 0: Issue Proposal

**Antes de implementar cualquier cosa**, verificar si existe una GitHub Issue.

Si el usuario pide implementar algo nuevo y NO hay issue abierta, PREGUNTAR:

```
He detectado que vamos a implementar: [descripcion breve].
No encuentro una GitHub Issue abierta para trackear este trabajo.

1. Si, crea la issue y continuamos
2. No, ya hay una issue (indicame el numero)
3. No hace falta, es algo rapido
```

## Phase 1: Issue Pickup

```bash
gh issue view <N>
```

Analizar: que pide, labels, complejidad. Presentar triage interactivo:

| Respuesta | Accion |
|-----------|--------|
| Directo | Ir a Phase 2 directamente |
| Planificar | Ejecutar ciclo plan-review (#1) antes |
| Mas contexto | Esperar input del usuario |

## Phase 2: Environment Setup

### Naming de rama

| Label / Tipo | Prefijo | Ejemplo |
|-------------|---------|---------|
| `bug` | `fix/` | `fix/issue-123-login-crash` |
| `enhancement` | `feature/` | `feature/issue-45-user-export` |
| `refactor` | `refactor/` | `refactor/issue-67-split-service` |
| `documentation` | `docs/` | `docs/issue-89-api-reference` |

```bash
# Crear worktree (recomendado: Claude Code nativo)
claude -w {prefix}/issue-{N}-{slug}
```

## Phase 3: Desarrollo

Trabajar libremente. Aplicar workflows segun el contexto de la issue:

| Si la issue implica... | Aplicar workflow |
|------------------------|-----------------|
| Correccion de bug | Bugfix (#9) + TDD (#3) |
| Acceso a datos / DB | Persistence Agnostic (#17) |
| Feature compleja | TDD (#3): Red-Green-Refactor |
| Cambio arquitectonico | Planning (#1) + Diagrams (#10) |

## Phase 4: Quality Gate (pre-cierre)

1. `/simplify` -- simplificar codigo
2. `qlty check` o linters del proyecto
3. Ejecutar tests completos
4. Iterar hasta que todo pase limpio

## Phase 5: Commit, PR y cierre

```bash
git push -u origin {branch-name}
gh pr create --title "Feature: descripcion (#N)" --body "Closes #N"
```

**CRITICO**: Incluir `Closes #N` en el body del PR para cierre automatico.

## Phase 6: Cleanup post-merge

```bash
cd /path/to/repo-principal
git pull origin main
git worktree remove /path/to/repo-issue-N
git worktree prune
```
