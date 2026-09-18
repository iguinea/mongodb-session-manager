# Decisión y evidencia: I/O síncrono en flujos async (#61)

Fecha: 17 de septiembre de 2026

## Decisión

El repositorio conserva PyMongo y sus escrituras síncronas. Los callbacks de
sesión que Strands registra (`initialize`, `append_message` y `sync_agent`) son
síncronos; sustituir el driver por uno async no permite hacer `await` dentro de
ese contrato. Tampoco se adopta write-behind: cambiaría las garantías de
read-after-write, el orden del array de mensajes y el `updated_at` raíz que
consumen los visores de sesiones y los runtimes de los consumidores.

La integración no streaming de FastAPI mueve a un worker compartido el camino
síncrono completo: crear el manager, restaurar y construir el agente, invocarlo,
leer las métricas que Strands mantiene en memoria y cerrar el manager. Mover
solo `agent(prompt)` dejaría las lecturas de restauración bloqueando el loop.

Es un workaround de integración, no un cambio de contrato de la librería. En la
versión de Strands resuelta por el lock, `Agent.__call__` crea internamente un
loop aislado para tender el puente a `invoke_async`; eliminar también ese coste
requiere que Strands ofrezca callbacks de sesión async. El streaming permanece
directo hasta que exista un puente con backpressure y cancelación explícitas.

## Medición MongoDB

Los JSON completos son:

- `artifacts/bench-issue61-direct-mongodb.json`
- `artifacts/bench-issue61-thread-mongodb.json`

Ambas ejecuciones usaron MongoDB 8.2.7 local, el mismo proceso y contenedor, un
turno real de supervisor + subagente, 100 mensajes previos, 5 calentamientos, 30
repeticiones de latencia y 3 de volumen. Cada celda probó las escrituras, las
métricas finales y la limpieza de datos. Los comandos por operación permanecen
en 15,5: el modo de ejecución no cambia durabilidad ni trabajo persistido.
Los percentiles de turno miden la invocación; throughput y lag abarcan el camino
repetido completo, incluida la restauración del agente.

| Concurrencia | Modo | p50 | p95 | p99 | Throughput | Lag loop p99 |
|---:|---|---:|---:|---:|---:|---:|
| 1 | directo | 11,87 ms | 18,25 ms | 20,88 ms* | 63,3 op/s | 5,43 ms* |
| 1 | thread | 8,19 ms | 23,69 ms | 27,17 ms* | 58,7 op/s | 2,63 ms* |
| 4 | directo | 18,41 ms | 28,79 ms | 39,16 ms | 128,2 op/s | 19,33 ms* |
| 4 | thread | 13,82 ms | 20,08 ms | 21,73 ms | 204,9 op/s | 1,44 ms* |
| 16 | directo | 68,28 ms | 97,98 ms | 132,21 ms | 139,9 op/s | 101,17 ms* |
| 16 | thread | 58,17 ms | 66,45 ms | 70,89 ms | 206,7 op/s | 4,55 ms |

`*` indica que 30 muestras no resuelven p99 y el valor es el máximo; para el
lag hay aún menos latidos. Se conserva porque es una observación real, pero la
conclusión se apoya también en p50/p95 y throughput.

A concurrencia 16, el worker reduce el lag p99 del loop un **95,5 %** (101,17 →
4,55 ms), aumenta throughput un **47,7 %** (139,9 → 206,7 op/s) y baja p95 un
**32,2 %**. A concurrencia 1 hay un coste de scheduling visible en throughput y
p95; el objetivo no es acelerar un turno aislado, sino impedir que ese turno
bloquee todas las demás peticiones.

## DocumentDB y compatibilidad

No cambia el driver, URI, autenticación, TLS, read preference ni pool: el mismo
PyMongo validado contra DocumentDB por #60 y #92 se ejecuta en otro hilo. La
evidencia directa ya publicada por #60 mostró lag p99 de 429 ms para el turno de
supervisor corto y 1.374 ms con 5.000 mensajes; es precisamente el entorno donde
el aislamiento aporta más valor.

### Medición DocumentDB

Ejecutada contra DocumentDB DEV (`documentdb-or-compatible 5.0.0`, `Single`,
`SecondaryPreferred`) a través del túnel SSH, misma matriz y mismo escenario que
en MongoDB. JSON completos:

- `artifacts/bench-issue61-direct-documentdb.json`
- `artifacts/bench-issue61-thread-documentdb.json`

| Concurrencia | Modo | p50 | p95 | p99 | Throughput | Lag loop p99 |
|---:|---|---:|---:|---:|---:|---:|
| 1 | directo | 776,9 ms | 891,2 ms | 937,9 ms* | 1,0 op/s | 346,7 ms |
| 1 | thread | 792,1 ms | 1.266,5 ms | 2.701,7 ms* | 0,8 op/s | 5,8 ms |
| 4 | directo | 1.869,5 ms | 2.401,4 ms | 2.629,1 ms | 1,4 op/s | 1.384,9 ms |
| 4 | thread | 1.323,0 ms | 1.740,2 ms | 1.986,3 ms | 2,4 op/s | 4,7 ms |
| 16 | directo | 5.430,7 ms | 8.512,9 ms | 9.951,3 ms | 1,6 op/s | 5.509,6 ms |
| 16 | thread | 1.245,8 ms | 2.017,0 ms | 2.059,7 ms | 9,7 op/s | 5,7 ms |

El efecto es **mucho más marcado que en MongoDB local**, como anticipaba #60: la
latencia de red amplía la ventana en que el driver síncrono retiene el loop. A
concurrencia 16 el lag p99 cae de 5.509,6 a 5,7 ms (−99,9 %), el throughput se
multiplica por 6,1 (1,6 → 9,7 op/s) y el p50 baja un 77,1 %. A concurrencia 4 el
lag cae de 1.384,9 a 4,7 ms y el p50 un 29,2 %. En el modo `thread` el lag se
mantiene plano (4,7–5,8 ms) en toda la matriz: deja de escalar con la carga, que
es justo lo que se quería.

El coste a concurrencia 1 también es más visible aquí: p50 +2,0 %, throughput
1,0 → 0,8 op/s y una cola peor (p95 891 → 1.266 ms). El p99 de 2.701 ms de esa
celda es el máximo de 30 muestras, no un percentil resuelto, y su baseline idle
fue de 13,3 ms frente a ~1,2 ms en el resto: esa celda tiene ruido y no sostiene
una conclusión por sí sola. La dirección sí es consistente con MongoDB —sin
concurrencia, el salto de thread solo añade scheduling.

Los comandos por operación permanecen en 15,5 en los dos modos y en los dos
motores, y las 21/21 sesiones sintéticas se limpiaron en ambas ejecuciones: el
modo de ejecución no cambia durabilidad ni trabajo persistido.

No cambia el driver, URI, autenticación, TLS, read preference ni pool respecto a
lo validado por #60 y #92: el mismo PyMongo se ejecuta en otro hilo. `pool wait`
p99 se mantuvo en 0,0–0,3 ms y no hubo timeouts, así que el pool compartido
absorbió la concurrencia real que el modo `thread` habilita.

## Cancelación, timeout y cierre

- Una cancelación HTTP no puede interrumpir con seguridad código Python que ya
  corre en un thread. La petición deja de esperar, pero el trabajo termina y el
  `finally` cierra el manager; las pruebas fijan este comportamiento.
- Los límites deben ponerse en el origen: timeouts del modelo y de PyMongo. Un
  `asyncio.wait_for` exterior solo deja de esperar y no revierte escrituras.
- El shutdown graceful drena peticiones antes de que el lifespan cierre la
  factory global. Cada manager de petición se cierra tanto en éxito como error.
- Los errores del worker se propagan al endpoint y conservan la respuesta HTTP
  actual; no se silencian ni se convierten en escrituras diferidas.

## Consulta a los consumidores

Se preguntó a los dos consumidores de la librería si el cambio les afecta. Los
dos respondieron que es transparente —ninguno usa la integración FastAPI— pero
de sus respuestas salen las precondiciones que ahora documenta la guía.

Uno de ellos corre sobre `BedrockAgentCoreApp` con invocación síncrona
bloqueante. Tiene recarga de prompts en caliente cuya
corrección **depende de que el turno bloquee el event loop**: no hay lock sobre
las globales de configuración de sus sub-agentes y lo único que hace segura la
recarga es que no haya ningún `await` dentro del turno, de modo que solo puede
ejecutarse entre turnos. Es el contraejemplo que impide recomendar el patrón
como regla general. Además, el escenario de cancelación de este informe ya es un
bug abierto suyo: el cliente deja de esperar por timeout y el runtime persiste
una respuesta que el usuario nunca vio.

El otro es un servidor fastmcp que solo usa persistencia y metadata, y hoy llama a la librería síncrona
directamente desde el event loop en tools `async`. Es el caso que sí encaja.

De esa consulta salió un hallazgo que no estaba en la investigación: los hooks
despachan por `dispatch_async()`, que ramifica según si hay un loop corriendo en
el thread que llama. Envolver el camino síncrono convierte una task en el loop
en un **daemon thread por evento**, y el dispatch ocurre dentro de
`update_metadata()`, así que no se puede envolver la escritura y dejar el hook
fuera. El análisis y la propuesta de corrección (loop explícito con
`run_coroutine_threadsafe`) quedan en #62, que es donde vive ese trabajo.

Colateral, ya corregido: la corrección del fire-and-forget de esas tasks entró
en v0.10.1 (commit `7a27703`) camuflada en un commit de lint y sin figurar en el
CHANGELOG. Cualquier despliegue por debajo de 0.10.1 con un hook registrado
puede perder notificaciones en silencio.

## Fallback

Para endpoints no streaming se usa el worker compartido. Para streaming se
mantiene `stream_async` directo, se limita el historial restaurado y se escala
con varios workers de servidor. Si el benchmark DocumentDB detectase saturación
del pool, se limita la concurrencia del worker antes de ampliar el pool; no se
crea un cliente MongoDB por petición.
