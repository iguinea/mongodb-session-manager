# Project Documentation -- Docs-as-Code

Mantener documentacion viva dentro del repositorio, junto al codigo.
Cada documento incluye un stamp del commit en el que se genero o actualizo.

## Estructura de docs/

```
docs/
├── index.md                # Pagina principal (overview del proyecto)
├── ARCHITECTURE.md         # Vision general, decisiones de diseno, diagramas
├── API.md                  # Documentacion de API (endpoints, auth, ejemplos)
├── INFRASTRUCTURE.md       # Inventario de infra, IaC, environments
├── RUNBOOK.md              # Operaciones: deploy, rollback, monitoring
├── SETUP.md                # Onboarding: como levantar el proyecto desde cero
├── CHANGELOG.md            # Historial de cambios del proyecto
└── ADR/                    # Architecture Decision Records (MADR)
```

## Git commit stamps

TODOS los documentos en docs/ DEBEN incluir frontmatter YAML con el stamp del commit:

```yaml
---
title: Architecture Overview
last_updated_commit: "abc1234f"
last_updated_at: "2026-03-09T14:30:00Z"
last_updated_by: "claude-code"
---
```

Al actualizar un documento, SIEMPRE actualizar estos campos.

## Cuando actualizar cada documento

| Evento | Documento a actualizar |
|--------|------------------------|
| Nuevo fichero de IaC | `INFRASTRUCTURE.md` |
| Crear/modificar endpoint API | `API.md` |
| Decision arquitectonica significativa | `ADR/NNNN-titulo.md` + `ARCHITECTURE.md` |
| Cambio en flujo de deploy | `RUNBOOK.md` |
| Nueva dependencia o cambio en setup | `SETUP.md` |
| Feature completada o bug fix relevante | `CHANGELOG.md` |

## MkDocs Material -- Navegacion local

```bash
# Instalar (una vez)
uv pip install mkdocs-material

# Servir localmente con live reload
mkdocs serve
# Abrir en navegador: http://127.0.0.1:8000
```

La configuracion `mkdocs.yml` se genera con `/setup-env docs`.
