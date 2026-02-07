# Guía de Contribución

¡Gracias por tu interés en contribuir a MongoDB Session Manager!

## Proceso de Contribución

1. **Fork** el repositorio
2. **Crea una rama** desde `main`:
   ```bash
   git checkout -b feature/mi-cambio
   ```
3. **Instala dependencias**:
   ```bash
   uv sync
   ```
4. **Haz tus cambios** siguiendo las convenciones del proyecto
5. **Ejecuta lint y tests**:
   ```bash
   uv run ruff check .
   uv run ruff format .
   uv run pytest test_*.py -v
   ```
6. **Commit** con mensaje descriptivo:
   ```bash
   git commit -m "Add: descripción del cambio"
   ```
7. **Push** a tu fork:
   ```bash
   git push origin feature/mi-cambio
   ```
8. **Crea un Pull Request** hacia `main`

## Convenciones

### Branches

| Prefijo | Uso | Ejemplo |
|---------|-----|---------|
| `feature/` | Nueva funcionalidad | `feature/user-auth` |
| `fix/` | Corrección de bug | `fix/login-error` |
| `refactor/` | Refactorización | `refactor/api-client` |
| `docs/` | Documentación | `docs/api-readme` |
| `test/` | Añadir tests | `test/user-service` |
| `chore/` | Mantenimiento | `chore/update-deps` |

### Commits

```
Add:      nueva funcionalidad
Update:   mejora existente
Fix:      corrección de bug
Refactor: sin cambio de comportamiento
Docs:     documentación
Test:     tests
Chore:    mantenimiento
```

## Requisitos Técnicos

- Python >= 3.12.8
- UV como package manager
- Tests requieren MongoDB local (ver README.md)

## Reportar Bugs

Usa la plantilla de [Bug Report](../../issues/new?template=bug_report.yml)

## Proponer Features

Usa la plantilla de [Feature Request](../../issues/new?template=feature_request.yml)
