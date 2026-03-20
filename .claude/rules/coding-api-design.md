# Diseno de APIs

## Convenciones REST

- Nombres de recursos consistentes y jerarquicos: `/sessions/{id}/agents/{agentId}`.
- Verbos HTTP semanticos: GET (lectura), POST (creacion), PUT (reemplazo), PATCH (parcial), DELETE.
- Versionado de API en URL: `/api/v1/`.

## Response envelope

Estructura consistente en TODAS las responses:

```json
{
  "success": true,
  "data": {},
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Session ID is required"
  }
}
```

## Status codes HTTP

Usar correctamente: 200 OK, 201 Created, 204 No Content, 400 Bad Request, 401 Unauthorized,
403 Forbidden, 404 Not Found, 409 Conflict, 422 Unprocessable Entity, 429 Too Many Requests,
500 Internal Server Error.

## Paginacion

Obligatoria en TODOS los endpoints de listado:
- Cursor-based o offset/limit.
- Incluir metadata: `total`, `next_cursor`, `has_more`.

## Rate limiting

- Por usuario y por endpoint.
- Headers estandar: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.

## Input validation

- Validar ALL inputs en el boundary con Pydantic models.
- Rechazar temprano con mensajes claros.

## Orden de middleware (FastAPI)

1. CORS
2. Request logging + correlation ID
3. Authentication
4. Authorization
5. Rate limiting
6. Input validation (Pydantic)
7. Business logic (handlers)
8. Response formatting
9. Error handling final
