# Observabilidad

## Structured logging

**Obligatorio**: Logs con campos consistentes:

```python
import structlog
logger = structlog.get_logger()
logger.info("session_saved", session_id=session_id, agent_count=len(agents))
logger.error("save_failed", session_id=session_id, error=str(e))
```

## Niveles de log

- `DEBUG`: informacion de desarrollo (desactivado en produccion).
- `INFO`: eventos operacionales normales (session creada, agent sincronizado).
- `WARN`: situaciones inesperadas pero recuperables (retry, fallback).
- `ERROR`: fallos que requieren atencion (query fallida, conexion perdida).

## Correlation ID

Propagado en TODA la cadena de llamadas para trazabilidad end-to-end.
Generarlo en el primer middleware y pasarlo via context/headers.

## Metricas

Monitorizar:
- P50/P95/P99 de latencia por endpoint
- Requests/segundo
- Error rate
- Connection pool utilization

## Alertas

Configurar alarmas en:
- Error rate >1%
- Latencia P99 degradada (>2x baseline)
- Recursos (CPU/memoria) >80% sostenido

## Librerias recomendadas

- `structlog` para structured logging
- `python-json-logger` como alternativa ligera
- OpenTelemetry para distributed tracing

## Anti-patron critico

NUNCA loguear datos sensibles: passwords, tokens, PII, connection strings con credenciales.
