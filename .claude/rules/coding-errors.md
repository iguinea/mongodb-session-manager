# Error Handling

## Reglas fundamentales

- Tratar errores como valores, no como excepciones inesperadas.
- Anadir contexto al propagar errores: que operacion fallo y por que.
- Definir tipos de error custom para errores de dominio.
- Nunca silenciar errores: loguear o propagar, pero nunca ignorar.
- Implementar degradacion graceful cuando un servicio dependiente falla.

## Python

- Excepciones custom que hereden de una base de la aplicacion.
- Context managers (`async with`) para lifecycle y cleanup.
- `try/except` con tipos especificos, nunca `except Exception` generico sin re-raise.
- Logging con contexto: `logger.error("Failed to save session %s", session_id, exc_info=True)`.
- `finally` para cleanup obligatorio (cerrar conexiones, liberar recursos).

## Anti-patrones

- `except: pass` (silenciar errores)
- `except Exception as e: print(e)` (sin re-raise ni logging apropiado)
- Excepciones para control de flujo normal
- Mensajes de error sin contexto ("Error occurred")
