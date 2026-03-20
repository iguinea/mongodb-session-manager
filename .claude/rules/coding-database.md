# Acceso a Bases de Datos

## Reglas fundamentales

- Usar SIEMPRE connection pooling. Nunca abrir una conexion por query.
- Parametrizar TODAS las queries. Nunca concatenar strings para construir queries.
- Definir indices para campos usados en filtros y ordenacion frecuentes.
- Preferir queries especificas (solo los campos necesarios) sobre consultas completas.
- Usar transacciones para operaciones que deben ser atomicas. Mantener las transacciones cortas.

## MongoDB especifico

- Usar `MongoClient` con connection pooling (`maxPoolSize`, `minPoolSize`).
- Indices compuestos para queries con multiples filtros.
- Projection para devolver solo los campos necesarios.
- Bulk operations (`insert_many`, `update_many`) para operaciones masivas.
- TTL indices para datos con expiracion.
- Evitar documentos > 16MB (limite de BSON).

## Configuracion del pool

Configurar siempre:
- `maxPoolSize` (ajustar a la capacidad del servidor)
- `minPoolSize` (mantener conexiones calientes)
- `maxIdleTimeMS` (evitar conexiones stale)
- `serverSelectionTimeoutMS` (timeout de seleccion de servidor)

## Monitoreo

- Revisar explain plans periodicamente para detectar collection scans.
- Alertar si el pool de conexiones se satura.

## Retry

- Retry con backoff exponencial para errores transitorios de conexion.
- Usar `retryWrites=true` y `retryReads=true` en connection string.
