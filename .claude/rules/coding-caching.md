# Caching

## Arquitectura multi-capa

Application cache (in-memory) -> Redis/Memcached -> CDN -> HTTP cache headers.

## Reglas fundamentales

- **TTL obligatorio** en TODA entrada de cache. Nunca cache infinito.
- **Invalidacion explicita** al mutar datos: invalidar cache tras CREATE, UPDATE, DELETE.
- **Cache key patterns**: `cache:{service}:{resource}:{id}:{version}`.
- **Nunca cachear datos sensibles** (tokens, PII) sin encriptacion.
- **Monitorizar cache hit ratio**: objetivo >80% en produccion.

## Patrones

### Cache-aside
La aplicacion consulta cache primero; si miss, va a BD, guarda en cache y retorna.

### Memoizacion
- Python: `functools.lru_cache` para funciones puras
- `cachetools` para TTL-based caching

## Anti-patrones

- Cache sin TTL (datos stale indefinidamente)
- Mutacion de datos sin invalidar cache
- Cache thundering herd (muchas requests simultaneas al expirar)
- Cachear responses de error sin TTL corto
