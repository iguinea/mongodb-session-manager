# Self-Improvement

Despues de CUALQUIER correccion del usuario, capturar la leccion aprendida.
Iterar estas reglas sin piedad hasta que la tasa de errores baje. (Boris Cherny, 10 Team Tips, Feb 2026, tip #3)

## Donde guardar que

| Tipo de leccion | Donde | Por que |
|-----------------|-------|---------|
| Regla del proyecto (todos deben seguir) | `.claude/rules/` | Compartido via git |
| Correccion personal (mi preferencia) | Memory.md (auto memory) | Personal, no compartido |
| Patron recurrente (3+ veces en Memory) | Promover a `.claude/rules/` | Se ha convertido en regla |

## Flujo tras una correccion

1. El usuario te corrige
2. Preguntate: es una regla del proyecto o una preferencia personal?
3. Si es regla del proyecto: actualiza el fichero `.claude/rules/` relevante
4. Si es preferencia personal: Claude lo guarda automaticamente en auto memory
5. Si no estas seguro: guardalo en auto memory y espera a que se repita

## Mantenimiento periodico

- Ejecutar `/claude-md-improver` periodicamente para auditar y consolidar CLAUDE.md
- Revisar Memory.md al inicio de sesion para lecciones relevantes al proyecto actual
- Si un patron en Memory.md se repite 3+ veces: promocionarlo a `.claude/rules/`
- Si una regla en `.claude/rules/` ya no aplica: eliminarla

## Estructura recomendada de CLAUDE.md

Mantener CLAUDE.md por debajo de 200 lineas. Usar `.claude/rules/` para el detalle:

```
CLAUDE.md (< 200 lineas)
  - Descripcion del proyecto
  - Comandos de build/test/deploy
  - Resumen de convenciones
  - Referencia: "Ver .claude/rules/ para guias detalladas"

.claude/rules/ (sin limite)
  - workflow-*.md (estas guias)
  - coding-*.md
  - testing.md
  - security.md
```
