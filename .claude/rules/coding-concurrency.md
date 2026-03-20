# Concurrencia y Race Conditions

## Reglas fundamentales

- Toda variable compartida entre hilos/tasks DEBE tener un mecanismo explicito de sincronizacion.
- Preferir paso de mensajes (queues) sobre estado compartido con locks cuando sea viable.
- Si se usa lock: mantener la seccion critica lo mas corta posible.
- Implementar graceful shutdown: capturar senales, completar work in progress y cerrar conexiones ordenadamente.
- En patrones fan-out/fan-in, usar bounded concurrency (worker pools con limite).

## Python async

- `asyncio.gather()` con `return_exceptions=True` para operaciones paralelas.
- Nunca mezclar codigo sincrono bloqueante en event loops sin `run_in_executor`.
- `asyncio.Semaphore` para limitar concurrencia.
- Context managers (`async with`) para lifecycle de recursos.

## Anti-patrones

- Tasks sin lifecycle management (leaks)
- Locks anidados (riesgo de deadlock)
- Usar excepciones para control de flujo en codigo concurrente
- Fire-and-forget sin error handling
