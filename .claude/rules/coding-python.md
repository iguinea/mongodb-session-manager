# Reglas Python

## Version y estilo

- Python 3.12+ (segun .tool-versions del proyecto).
- Syntax moderna: `X | Y` en vez de `Union[X, Y]`, `list[str]` en vez de `List[str]`.
- Ruff como formatter y linter unico.
- Imports ordenados automaticamente: stdlib -> third-party -> local.
- Docstrings como sentencias completas con punto final.
- Dependency injection explicita, no globals.
- UV para gestion de dependencias y lock files.

## Async patterns

- `async def` para operaciones I/O-bound.
- Usar async context managers para lifecycle: `async with client:`.
- `asyncio.gather()` para operaciones paralelas con `return_exceptions=True`.
- Nunca mezclar codigo sincrono bloqueante en event loops sin `run_in_executor`.

## Type hints y validacion

- Type hints completos en TODAS las funciones.
- Pydantic v2 para validacion de datos de entrada/salida.
- `Protocol` para interfaces (duck typing estatico).

## MongoDB (pymongo)

- Connection pooling via `MongoClient` (singleton o pool).
- Parametros de pool: `maxPoolSize`, `minPoolSize`, `maxIdleTimeMS`.
- Projection para devolver solo campos necesarios.
- Indices para queries frecuentes.
- `retryWrites=true` en connection string.

## Testing

Orden obligatorio de verificacion local:
1. `ruff format .`
2. `ruff check .`
3. `uv run python -m pytest tests/ -v`

- Fixtures aisladas con `conftest.py`.
- `@pytest.mark.parametrize` para table-driven tests.
- `MagicMock` y `AsyncMock` para dependencias externas.
- `@pytest.mark.integration` para tests que requieren MongoDB.

## Performance

- List comprehensions sobre loops cuando son legibles.
- Generators para datasets grandes: `yield` en vez de materializar listas.
- `functools.lru_cache` para memoizacion.
- Connection pooling obligatorio.
