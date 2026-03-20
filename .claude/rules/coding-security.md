# Seguridad

## Reglas criticas

- **Secrets**: NUNCA hardcodear API keys, tokens, o credenciales. Usar variables de entorno o secret managers.
- **Injection**: queries parametrizadas SIEMPRE. Nunca concatenar strings para queries.
- **XSS**: sanitizar output en HTML. Usar Content Security Policy headers.
- **CORS**: whitelist explicito de origenes. Nunca `Access-Control-Allow-Origin: *` en produccion.
- **Auth en toda mutacion**: verificar autenticacion Y autorizacion en cada endpoint de escritura.

## Dependencias

Auditoria regular. Ejecutar en CI:
- `pip audit`
- `uv run safety check` (si safety esta instalado)

Actualizar dependencias con vulnerabilidades conocidas promptly.

## Mass assignment

Whitelist explicito de campos aceptados en payloads (Pydantic models). Nunca pasar request body directo al ORM/driver.

## Headers de seguridad

Incluir siempre en responses HTTP:
- `Strict-Transport-Security` (HSTS)
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`

## Principios

- **Menor privilegio**: en BD, crear roles con permisos minimos necesarios.
- **Logging de seguridad**: registrar intentos de auth fallidos, accesos no autorizados.
- **Variables de entorno tipadas** con validacion al arrancar la app.
- Nunca loguear datos sensibles: passwords, tokens, PII.
