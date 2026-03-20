# Code Review

Toda cambio de codigo debe pasar revision antes de merge.
Usar dos niveles complementarios: principios y dominio.

> **Prerequisitos**: plugins `code-review-expert` y `staff-reviewers` del marketplace
> claudio-plugins. Sin ellos, hacer revision manual siguiendo los criterios de cada nivel.

## Nivel 1: Principios (code-review-expert)

Revision estructurada de 7 pasos con severidad P0-P3:

- SOLID violations
- Security vulnerabilities
- Dead code detection (verificado con grep)
- Boundary conditions (null, limites, off-by-one)
- Error handling gaps
- Performance issues

```
/code-review
```

| Severidad | Accion |
|-----------|--------|
| P0 Critical | Bloquea merge -- vulnerabilidades, perdida de datos |
| P1 High | Fix antes de merge -- errores logicos, violaciones SOLID |
| P2 Medium | Fix o crear ticket -- code smells |
| P3 Low | Opcional -- estilo, naming |

## Nivel 2: Dominio (staff-reviewers)

Revision por especialidad: backend, frontend, IaC, sistemas, infra, AWS.

```
/review              # Selecciona revisor interactivamente
/parallel-review     # Ejecuta multiples revisores en paralelo
```

## Simplificacion (code-simplifier)

Antes de la revision formal, simplificar el codigo recien escrito:

```
/simplify
```

## Flujo recomendado

1. Terminar implementacion + tests verdes
2. `/simplify` -- simplificar y refactorizar codigo reciente
3. Re-ejecutar tests (deben seguir verdes tras simplificacion)
4. `/code-review` -- gate de principios (P0/P1 bloquean)
5. `/review backend` (o frontend/iac segun aplique) -- gate de dominio
6. Si hay issues: corregir, `/simplify`, y repetir desde paso 3
7. Crear PR solo cuando ambos gates pasen
