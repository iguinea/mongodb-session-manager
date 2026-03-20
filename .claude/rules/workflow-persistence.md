# Database-Agnostic Persistence -- Repository Pattern

La logica de negocio NUNCA depende de una implementacion concreta de base de datos.
Todo acceso a datos se realiza a traves de interfaces (ports). La base de datos es
un detalle de infraestructura que puede cambiar en cualquier momento.

## Reglas

- **Interfaces obligatorias**: Todo acceso a datos pasa por una interfaz/protocolo.
  El dominio importa la interfaz, NUNCA el cliente de DB directamente.
- **Naming**: Interfaz = `XxxRepository`. Implementacion = `PostgresXxxRepository`,
  `MongoXxxRepository`, `InMemoryXxxRepository`.
- **Sin leaky abstractions**: La interfaz NO expone detalles de la DB subyacente.
  Los metodos reflejan operaciones de dominio: `find_by_email`, `save`, `list_active`.
- **Inyeccion de dependencias**: El adaptador concreto se inyecta en tiempo de
  configuracion. Nunca hardcoded.
- **Un repositorio por entidad**: No mezclar queries de distintas entidades.

## Estructura de directorios (Python)

```
src/
├── domain/
│   ├── models/           # Entidades y value objects
│   └── ports/            # Interfaces de repositorios (Protocol)
├── infrastructure/
│   └── persistence/      # Adaptadores concretos
│       ├── mongodb/
│       └── in_memory/
└── config/
    └── dependencies.py   # Wiring: que adaptador usar
```

## Ejemplo Python (Protocol)

```python
# domain/ports/session_repository.py
from typing import Protocol

class SessionRepository(Protocol):
    def find_by_id(self, session_id: str) -> Session | None: ...
    def save(self, session: Session) -> None: ...

# infrastructure/persistence/mongodb/mongo_session_repository.py
class MongoSessionRepository:  # implementa el Protocol implicitamente
    def __init__(self, collection: Collection):
        self._collection = collection

    def find_by_id(self, session_id: str) -> Session | None:
        doc = self._collection.find_one({"session_id": session_id})
        return Session(**doc) if doc else None
```

## Checklist en code review

- [ ] El servicio importa la INTERFAZ, no la implementacion?
- [ ] El repositorio tiene metodos de dominio (no metodos genericos)?
- [ ] El adaptador esta en `infrastructure/persistence/`, no en `domain/`?
- [ ] Existe test con implementacion in-memory o mock?
- [ ] El wiring esta centralizado?
