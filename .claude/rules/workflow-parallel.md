# Parallel Work

Abre de 3 a 5 worktrees a la vez, cada uno con su propia sesion de Claude en paralelo.
Es el mayor impulso de productividad de todos.
(Boris Cherny, creador de Claude Code -- 10 Team Tips, Feb 2026, tip #1)

## Reglas

- **Worktree por tarea**: Cada feature/bugfix en su propio worktree
- **Sesiones nombradas**: Usa `/rename <nombre>` para identificar cada sesion
- **No mezclar contextos**: Cada worktree tiene su propio Claude con contexto limpio
- **Worktree de analisis**: Ten un worktree dedicado solo para leer logs, consultar datos

## Claude Code nativo (recomendado)

Claude Code tiene soporte nativo de worktrees desde Feb 2026:

```bash
# Crear worktree + sesion de Claude en un solo comando
claude --worktree feature/my-feature

# Shorthand
claude -w feature/my-feature

# Combinar con tmux para sesiones persistentes
claude --worktree feature/my-feature --tmux
```

Ventajas del soporte nativo:
- Crea el worktree, la rama y abre Claude automaticamente
- Limpieza automatica del worktree al terminar
- Integrado con tmux para sesiones persistentes

## Alternativa manual

Si necesitas mas control sobre la configuracion del worktree:

```bash
# Crear worktree para nueva feature
git worktree add -b feature/my-feature ../$(basename $PWD)-feature-my-feature main

# Crear worktree para branch existente
git worktree add ../$(basename $PWD)-fix-bug fix/bug-123

# Listar worktrees activos
git worktree list

# Limpiar worktree terminado
git worktree remove ../$(basename $PWD)-feature-done
git worktree prune
```

## Sesiones de Claude Code en worktrees manuales

```bash
# Terminal 1: Feature A
cd ../proyecto-feature-a && claude
> /rename feature-a

# Terminal 2: Feature B
cd ../proyecto-feature-b && claude
> /rename feature-b

# Terminal 3: Analisis (solo lectura)
cd ../proyecto-analysis && claude
> /rename analysis
```
