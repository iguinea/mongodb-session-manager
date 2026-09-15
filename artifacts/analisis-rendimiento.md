# Análisis de rendimiento de MongoDB Session Manager

**Fecha:** 15 de septiembre de 2026  
**Alcance:** revisión de código y pruebas contra MongoDB local  
**Objetivo:** identificar mejoras de rendimiento sin modificar la implementación

## Resumen ejecutivo

La aplicación parte de una base razonable: reutiliza conexiones, evita recrear índices para cada manager, conserva en memoria el último `message_id` y combina métricas y configuración en una sola escritura de sincronización.

El principal margen de mejora ya no está en el coste de crear conexiones, sino en dos comportamientos:

1. Cada turno todavía produce un número elevado de viajes a MongoDB.
2. Varias lecturas recuperan arrays o documentos completos, por lo que su coste aumenta con todo el historial aunque el consumidor solo necesite unos pocos campos o mensajes.

En MongoDB local y caliente, un turno representativo con supervisor, subagente y una llamada a herramienta produjo **21 comandos: 15 escrituras y 6 lecturas**. El tiempo total fue de **17,21 ms**. En una base remota, y especialmente donde cada escritura tenga decenas de milisegundos de latencia, el número de round-trips pasa a ser el factor dominante.

La recomendación inmediata es optimizar las proyecciones y la restauración de sesiones, trasladar la paginación al servidor y reducir las sincronizaciones redundantes. Para historiales largos o agentes concurrentes sobre una misma sesión, conviene además separar los mensajes del documento principal.

## Metodología

Se realizaron las siguientes comprobaciones:

- Inspección de los caminos de lectura, escritura, restauración de agentes, pooling, hooks y ejemplos FastAPI.
- Ejecución de **270 pruebas unitarias**, todas superadas en **0,88 s**.
- Ejecución de **37 pruebas de integración** contra `localhost:8550`, todas superadas en **1,07 s**.
- Instrumentación con `CommandListener` de un segundo turno sobre una sesión caliente.
- Prueba sintética de escalabilidad con historiales de 10, 100, 1.000 y 5.000 mensajes.

Los documentos sintéticos se eliminaron al finalizar. No se utilizó AWS ni se modificó código de la aplicación.

## Resultados medidos

### Coste de un turno

Escenario: supervisor que llama a una herramienta, la cual ejecuta un subagente, sobre una sesión ya existente.

| Métrica | Resultado |
| --- | ---: |
| Tiempo local, conexión caliente | 17,21 ms |
| Comandos MongoDB totales | 21 |
| `update` | 15 |
| `find` | 6 |
| `createIndexes` | 0 |

La ausencia de `createIndexes` confirma que el registro de índices por cliente funciona. El siguiente objetivo debe ser reducir escrituras y lecturas del ciclo normal.

### Escalabilidad con el historial

Cada mensaje sintético contenía aproximadamente 512 caracteres de texto.

| Mensajes | Documento | Página de 10 actual | Página con `$slice` | Conteo actual | Conteo en servidor |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 6,5 KB | 0,358 ms | 0,363 ms | 0,384 ms | 0,307 ms |
| 100 | 62,7 KB | 0,536 ms | 0,355 ms | 0,543 ms | 0,373 ms |
| 1.000 | 625,2 KB | 2,614 ms | 0,547 ms | 4,197 ms | 0,867 ms |
| 5.000 | 3.129,1 KB | 14,522 ms | 1,350 ms | 13,283 ms | 1,179 ms |

Con 5.000 mensajes, la implementación actual transfirió aproximadamente **3,1 MB para devolver una página de 10 mensajes**. Una proyección con `$slice` transfirió aproximadamente **6,5 KB**, unas 480 veces menos. La consulta pasó de 14,52 ms a 1,35 ms en local.

`read_session` mostró un patrón similar: con 5.000 mensajes tardó 13,59 ms recuperando el documento completo y 0,47 ms usando una proyección de los campos realmente consumidos.

## Hallazgos y recomendaciones

### P0 — Reducir las lecturas completas durante la restauración

`read_session()` recupera el documento completo, aunque solo usa `session_id`, `session_type`, `created_at` y `updated_at`.

`read_agent()` proyecta `agents.<agent_id>` completo, incluidos todos sus mensajes, aunque únicamente utiliza `agent_data`. Después, `list_messages()` vuelve a recuperar el array de mensajes. En una sesión existente, el mismo historial puede transferirse varias veces antes de procesar el prompt.

Mejoras propuestas:

- Aplicar una proyección mínima en `read_session()`.
- Proyectar únicamente `agents.<agent_id>.agent_data` en `read_agent()`.
- Evaluar una operación especializada de restauración que devuelva agente e historial en una sola lectura.
- Aplicar el `removed_message_count` del conversation manager en MongoDB para no transferir mensajes que serán descartados inmediatamente.

Impacto esperado: alto para sesiones medianas y largas, con riesgo de implementación bajo o medio.

### P0 — Ejecutar paginación, búsqueda y conteo en MongoDB

`list_messages()` descarga todos los mensajes, los ordena en Python y después aplica `offset` y `limit`. Por tanto, la API ofrece paginación funcional, pero no paginación eficiente.

Mejoras propuestas:

- Usar `$slice` cuando exista `limit`.
- Aprovechar el orden de inserción garantizado por `$push`, validando primero la compatibilidad con sesiones antiguas.
- Usar `$elemMatch` para `read_message()`.
- Usar `$size` en servidor o mantener un contador actualizado atómicamente para `get_message_count()`.
- Evitar que `list_agents()` recupere los mensajes de todos los agentes.
- Reemplazar el patrón lectura + búsqueda lineal + actualización por índice de `update_message()` por una actualización posicional basada en `message_id`.

La última mejora reduce una lectura completa y elimina una ventana de carrera que puede afectar a la redacción de mensajes.

### P0 — Reducir el presupuesto de escrituras por turno

El código ya fusiona las métricas y la configuración del agente, pero Strands solicita una sincronización después de cada mensaje y otra al terminar la invocación. El escenario medido sigue produciendo 15 escrituras.

Mejoras propuestas, en este orden:

1. Inicializar la caché de `model` y `system_prompt` con la información ya obtenida por `read_agent()`. Esto evita reescribir una configuración idéntica al comienzo de cada request y podría ahorrar aproximadamente dos escrituras en el escenario medido.
2. Distinguir eventos donde las métricas realmente cambian de mensajes de usuario o `toolResult` que solo repiten el resumen anterior.
3. Revisar llamadas adicionales a `sync_agent()` en las aplicaciones consumidoras.
4. Evaluar batching de creación de mensaje y sincronización únicamente si se conserva la persistencia inmediata, `updated_at` raíz y el estado del conversation manager.

Como referencia interna, el código documenta una latencia de 40–55 ms por escritura en DocumentDB. Con esa cifra, 15 actualizaciones representarían aproximadamente 600–825 ms, sin contar lecturas. Esta estimación debe confirmarse con telemetría del entorno real.

### P0 — Evitar I/O síncrono dentro del event loop

El repositorio utiliza PyMongo síncrono. Strands invoca los callbacks síncronos del session manager directamente desde su flujo async, por lo que cada consulta o escritura bloquea temporalmente el event loop.

El ejemplo FastAPI no streaming también llama a `agent(...)` directamente dentro de un endpoint `async`, bloqueándolo durante toda la invocación del modelo.

Opciones:

- Ejecutar la invocación síncrona completa en un worker thread.
- Diseñar una integración async compatible con el contrato de Strands.
- Desacoplar escrituras no críticas mediante una cola, manteniendo síncronas las que sean necesarias para durabilidad y orden.

Impacto esperado: alto bajo concurrencia, aunque la solución requiere validar cuidadosamente orden, cancelación y consistencia.

### P1 — Separar mensajes del documento principal

El esquema actual guarda la sesión, agentes, mensajes, métricas, feedback y eventos en un único documento. Esto simplifica las operaciones atómicas, pero provoca:

- Crecimiento continuo del documento y riesgo de alcanzar el límite de 16 MB.
- Mayor transferencia y deserialización en cada lectura accidentalmente amplia.
- Contención cuando varios agentes escriben en la misma sesión.
- Paginación y búsqueda limitadas sobre arrays embebidos.

Para sesiones largas, la arquitectura más escalable sería:

- `sessions`: cabecera, metadata, timestamps y resúmenes.
- `agents`: configuración y estado por sesión/agente.
- `messages`: un documento por mensaje, indexado por `(session_id, agent_id, message_id)`.

Este cambio tiene alto impacto y alto coste. Puede posponerse si el producto limita explícitamente la longitud de las conversaciones y monitoriza el tamaño BSON.

### P1 — Controlar el trabajo en segundo plano de los hooks

En contexto síncrono, `dispatch_async()` crea un thread daemon y un event loop por evento. Los hooks llaman después a `asyncio.to_thread`, pudiendo añadir otro worker. No existe una cola limitada ni backpressure.

Durante las pruebas, tareas SQS siguieron ejecutándose después de finalizar la suite e intentaron resolver credenciales AWS. Esto confirma que el ciclo de vida del trabajo en segundo plano no está completamente controlado.

Mejoras propuestas:

- Executor o cola compartida y acotada.
- Política explícita de overflow y reintentos.
- Método de shutdown que espere o cancele el trabajo pendiente.
- Outbox persistente si la entrega de notificaciones debe ser fiable.

### P2 — Ajustar pooling, health checks, índices y logging

- `maxPoolSize=100` y `minPoolSize=10` se aplican por proceso. Deben dimensionarse considerando workers y réplicas totales, especialmente en Lambda o contenedores pequeños.
- `get_pool_stats()` ejecuta `server_info()` cada vez. Para health checks frecuentes sería preferible cachear la versión y utilizar `ping`, además de métricas CMAP reales para utilización del pool.
- Verificar índices con `explain("executionStats")`. El índice de `session_id` duplica conceptualmente `_id`, mientras que consultas por aplicación y fecha pueden necesitar un índice compuesto como `(application_name, updated_at)`.
- Reducir logs `INFO` del camino por mensaje y usar formato lazy para evitar trabajo e I/O innecesarios.

## Calidad de las mediciones actuales

`examples/example_performance.py` no ejecuta las diez operaciones que contabiliza: el bucle de operaciones contiene `pass`. Sus cifras de throughput no deben emplearse para justificar decisiones de capacidad.

Se recomienda sustituirlo por un benchmark reproducible que incluya:

- Sesión nueva y existente.
- Historiales de 10, 100, 1.000 y 5.000 mensajes.
- Turnos simples y turnos con herramientas/subagentes.
- Concurrencia creciente.
- p50, p95 y p99 por operación y por turno.
- Comandos MongoDB, bytes transmitidos y espera del pool.
- Ejecución separada contra MongoDB local y DocumentDB de desarrollo.

## Hoja de ruta sugerida

### Fase 1 — Bajo riesgo

- Proyecciones mínimas en `read_session()` y `read_agent()`.
- `$slice`, `$elemMatch` y conteo en servidor.
- Evitar mensajes en `list_agents()`.
- Sustituir el benchmark actual por uno real.

### Fase 2 — Menos round-trips

- Hidratar la caché de configuración desde la lectura existente.
- Medir y eliminar sincronizaciones de métricas idénticas.
- Optimizar `update_message()` con actualización posicional.
- Instrumentar p95/p99 y bloqueo del event loop.

### Fase 3 — Escalabilidad estructural

- Validar límites reales de longitud y concurrencia por sesión.
- Separar mensajes y posiblemente agentes en colecciones propias si los datos justifican la migración.
- Introducir una estrategia controlada de trabajo asíncrono para hooks y persistencia no crítica.

## Criterios de éxito propuestos

- Reducir el turno representativo de 15 a **13 o menos escrituras** sin perder métricas ni estado.
- Reducir de 6 a **4 o menos lecturas** en el escenario supervisor/subagente.
- Conseguir que una página de 10 mensajes transfiera datos proporcionales a 10 mensajes, no al historial completo.
- Mantener estable la latencia de lectura al crecer de 100 a 5.000 mensajes, salvo cuando se restaure deliberadamente todo el contexto activo.
- Evitar I/O MongoDB síncrono prolongado en el event loop de FastAPI.
- Disponer de p50, p95 y p99 reales antes y después de cada optimización.

## Conclusión

Las optimizaciones recientes han reducido correctamente la amplificación de escrituras y el coste de creación de managers. El siguiente salto de rendimiento vendrá de recuperar menos datos, ejecutar menos sincronizaciones y evitar bloqueo síncrono bajo concurrencia. La separación de mensajes es la solución estratégica si las sesiones pueden crecer sin un límite pequeño y explícito.
