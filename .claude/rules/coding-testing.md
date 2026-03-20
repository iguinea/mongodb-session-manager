# Testing

## Reglas fundamentales

- Tests como ciudadanos de primera clase: coverage minimo 80%+ en logica de negocio.
- Separar unit tests (rapidos, mockeados) de integration tests (con dependencias reales).
- Ejecutar tests en CI con cada PR/commit.
- Nombres descriptivos: `test_session_save_with_duplicate_id_raises_conflict`.

## Estructura de tests

- Tests en `tests/unit/` y `tests/integration/` (convencion del proyecto).
- Fixtures aisladas: cada test con su propio estado. No compartir estado mutable entre tests.
- No `@pytest.mark.skip` sin razon documentada en CI.

## Orden de verificacion local

Antes de commit, ejecutar siempre en este orden:
1. `ruff format .`
2. `ruff check .`
3. `uv run python -m pytest tests/ -v`

## Regression tests

Regla de oro: reproducir el bug con un test ANTES de fixearlo.
El test debe fallar sin el fix y pasar con el.

## Python especifico

- `pytest` con fixtures y `conftest.py` para compartir setup.
- `@pytest.mark.integration` para tests que requieren MongoDB.
- `MagicMock` y `AsyncMock` para mockear dependencias externas.
- Coverage con `pytest-cov`: `uv run pytest --cov=src tests/`.
- Parametrize para table-driven tests: `@pytest.mark.parametrize`.

## Coverage por componente

| Componente | Minimo |
|-----------|--------|
| Logica de negocio / Services | 80% |
| Handlers / Controllers | 70% |
| Repository / Data Layer | 60% |
| Utilities / Helpers | 80% |
