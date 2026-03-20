# Data Contracts -- API Contracts as Source of Truth

El contrato de API/datos es el documento autoritativo. Si frontend y backend discrepan,
el contrato gana. Ningun equipo puede cambiar unilateralmente la estructura de datos
sin actualizar el contrato primero.

## Flujo de modificacion

```
1. PROPONER    Abrir issue/PR con el cambio propuesto al contrato
2. EVALUAR     Clasificar: aditivo (safe) o breaking change?
3. VERSIONAR   Bump version del contrato (semver)
4. COMUNICAR   Notificar a consumidores afectados
5. IMPLEMENTAR Actualizar backend y frontend contra el nuevo contrato
6. VALIDAR     Code review verifica que tipos coinciden con el contrato
```

## Cambios aditivos (safe)

- Anadir campo opcional a un response
- Anadir endpoint nuevo
- Relajar validacion (campo obligatorio -> opcional)
- Anadir nuevo valor a un enum

Bump: **minor** (1.2.0 -> 1.3.0)

## Breaking changes

- Eliminar o renombrar un campo
- Cambiar tipo de un campo
- Hacer un campo opcional -> obligatorio
- Cambiar formato de respuesta
- Eliminar o renombrar endpoint

Bump: **major** (1.2.0 -> 2.0.0)

## Ubicacion canonica

```
docs/contracts/
├── openapi.yaml          # OpenAPI 3.1 spec
├── asyncapi.yaml         # AsyncAPI 3.0 spec (si aplica)
├── CHANGELOG.md          # Historial de cambios del contrato
└── schemas/              # Schemas JSON reutilizables
```
