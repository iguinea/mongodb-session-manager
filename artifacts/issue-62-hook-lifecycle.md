# Decisión y evidencia: ciclo de vida del trabajo asíncrono de los hooks (#62)

Fecha: 17 de septiembre de 2026

## Decisión

El trabajo en segundo plano de los hooks pasa a tener un ciclo de vida propio,
en `hooks/background_work.py`, con cuatro reglas y un cierre explícito:

1. **Un loop de reserva compartido**, no un hilo por evento. Sin loop al que
   despachar, la corrutina va a un único event loop de la librería, en un hilo
   daemon creado la primera vez que hace falta.
2. **Un límite de trabajo en vuelo** (64 por defecto). Superado, el trabajo
   best-effort se descarta: la corrutina se cierra, un WARNING dice qué se
   descartó y un contador lo registra.
3. **Orden por clave donde se pide.** El trabajo con `order_key` no corre en
   paralelo con otro de la misma clave ni lo adelanta. Por clave hay como mucho
   uno en vuelo y uno esperando; uno nuevo sustituye al que esperaba, que se
   descarta en voz alta y **nunca se entrega tarde**.
4. **Un cierre que dice qué pasó.** `shutdown_hooks(timeout)` drena lo que puede,
   cancela el resto y devuelve los contadores.

Política por hook, acordada con el consumidor que los registra en producción
(`genai-mrg-assistant-crm`):

| Hook | Entrega | Orden | Overflow |
|---|---|---|---|
| Metadata WebSocket | best-effort | por `session_id` | descarta el que espera, el último gana |
| Metadata SQS | best-effort | por `session_id` | igual |
| Feedback SNS | **garantizada** | ninguno | se acepta por encima del límite, con WARNING |

La asimetría no es de diseño, es del dominio: una notificación de metadata
refresca una vista y la siguiente escritura la corrige; una de feedback
transporta una queja de cliente que nada vuelve a producir.

**No se añade outbox persistente ni reintentos propios.** Justificación en
"Alternativas descartadas".

## El problema, medido

Reproductor: `uv run python -m benchmarks.hook_burst`. No necesita base de
datos. Compara en el mismo proceso el despacho anterior (`legacy`, reproducido
ahí mismo para que la comparación sea de la misma máquina) con los dos caminos
actuales. Cada evento hace lo que hacen los hooks: `asyncio.to_thread` alrededor
de una llamada bloqueante de 50 ms.

Ráfaga de 200 eventos, MacBook con 16 CPU:

| Camino | Hilos creados | Llamadas simultáneas | Coste del dispatch p50 | Drenaje |
|---|---:|---:|---:|---:|
| `legacy` (antes) | **+403** | 200 | 131,1 µs | 114,0 ms |
| `reserve` (ahora, sin loop) | +21 | 20 | 5,0 µs | 543,5 ms |
| `bound` (ahora, loop conocido) | +21 | 20 | 5,4 µs | 541,7 ms |

Son 403 hilos y no 200 porque cada evento arrancaba su hilo daemon **y** el
`asyncio.to_thread` interno del hook abría otro en el executor de su loop
efímero. Memoria pico medida aparte con `tracemalloc`: 1.832 KB frente a 822 KB.

**El drenaje sube 4,8×** (114 → 543 ms) y es el precio honesto de la decisión:
20 llamadas a la vez en lugar de 200. No es una pérdida real de throughput,
porque las 200 nunca fueron 200: el cliente boto3 cacheado tiene
`max_pool_connections=10`, así que a partir de la décima llamada simultánea los
hilos de más esperaban conexión igual. Y el consumidor real hace 0-3
`update_metadata` por turno, no 200: la cola no se forma.

El techo de 20 llamadas simultáneas no es arbitrario ni configurable aquí: es el
executor por defecto del loop, `min(32, cpu + 4)`.

### Lo que pasaba al cerrar el proceso

20 notificaciones en vuelo, el proceso termina:

| Situación | Entregadas | Rastro |
|---|---:|---|
| Antes, hilo daemon | 0/20 | **ninguno** |
| Antes, loop propio sin cierre ordenado | 0/20 | ninguno |
| Antes, cierre ordenado del loop | 0/20 | 20 × `WARNING Cancelled while …` |
| Ahora, sin llamar a nada | 0/20 | los contadores, vía `atexit` |
| Ahora, con `shutdown_hooks()` | **20/20** | los contadores |

La política de facto era *pérdida silenciosa no observable*, que no es una
política. Ahora el proceso que cierra bien entrega, y el que no cierra bien al
menos lo cuenta.

**`atexit` no salva al que no tiene punto de cierre.** Se probó: Python cierra
sus thread pools *antes* de ejecutar cualquier `atexit`, así que el trabajo que
no había llegado al pool ya no puede llegar (1/20 entregadas y un
`RuntimeError: cannot schedule new futures after interpreter shutdown` por
cada una). El `atexit` se conserva porque deja los contadores en el log, y ese
RuntimeError se degrada a un WARNING legible en vez de un traceback. Para un
proceso sin lifespan — `BedrockAgentCoreApp`, por ejemplo — la única entrega
real es un handler de SIGTERM que llame a `shutdown_hooks()`.

## Requisitos por hook

Los fijó el equipo de `genai-mrg-assistant-crm`, único consumidor con hooks
registrados, sobre sus dos servicios (`virtual-agent`, FastAPI con hooks a nivel
de módulo; `agentcore-agent`, entrypoint síncrono con el hook por petición):

- **Feedback SNS: tiene que llegar.** Alimenta su circuito de quejas de cliente;
  perder una es perder una queja sin rastro, y no hay reconciliación posterior.
  Volumen: uno por conversación como mucho.
- **Metadata WebSocket: la pérdida es tolerable, el desorden no.** Su widget hace
  `Object.assign` puro, sin timestamp ni secuencia
  (`frontend/chat/libs/modules/websocket-handlers.js:165`), y su ruta
  `/crm/start_chat` emite **tres updates de la misma sesión en cascada**. Si el
  segundo pisa al tercero, la vista se queda en un estado intermedio de forma
  permanente. El orden por sesión resuelve un problema real suyo, no teórico.
- **Volumen:** 3 `update_metadata` en `/crm/start_chat`, 0-2 por turno de chat,
  una sesión concurrente por widget. El límite de 64 no lo rozan.
- **Presupuesto de cierre:** 30 s (default de ECS entre SIGTERM y SIGKILL; su
  CDK no fija `stopTimeout`). 5 s de timeout les sobra.

### Una desviación deliberada

Pidieron **backpressure** para el feedback SNS: que `add_feedback()` espere
antes que perder la notificación. No se implementa así. Sus endpoints `async def`
llaman a `add_feedback()` en el propio event loop, y bloquear ahí no retrasa una
petición: congela el servidor. `Delivery.GUARANTEED` consigue lo mismo que les
importa — no se pierde ninguna — aceptándola por encima del límite con un
WARNING. El efecto observable es idéntico; el riesgo, no.

## Credenciales, timeouts y shutdown en AWS

Medido sobre botocore 1.43.95: los clientes se creaban con los defaults —
`connect_timeout=60`, `read_timeout=60`, `retries={'mode': 'legacy'}` (5
intentos) y `max_pool_connections=10`. Una notificación contra un endpoint que no
responde retenía su hilo **minutos**, y el hilo es exactamente el recurso que el
límite de trabajo en vuelo protege.

Los tres hooks pasan a construir sus clientes con
`hooks/aws_client_config.notification_config()`: **3 s de connect, 5 s de read y
3 intentos** en modo `standard`. Peor caso ≈ 24 s con el backoff incluido, por
debajo de los 30 s de gracia de ECS. Está fijado con un test
(`test_the_worst_case_fits_inside_the_shutdown_grace`).

Cuidado con la semántica: el `max_attempts` de botocore cuenta **reintentos**,
no intentos; `max_attempts=3` son 4 intentos. La constante del repo es
`TOTAL_ATTEMPTS` y se traduce restando uno.

Credenciales: los clientes se cachean por región desde v0.10.x y la resolución
ocurre en la primera llamada, dentro del hilo del executor. No cambia con esto.

**Cuál de los tres corre riesgo con el nuevo presupuesto.** El consumidor
revisó su reparto de red: tiene VPC endpoints para `sns`, así que el publish va
por PrivateLink y no se acerca a los 5 s ni de lejos. **`execute-api` no está en
esa lista**: el `post_to_connection` del hook de WebSocket sale por NAT a
internet y es el único de los tres que cruza la frontera. No hay medición de su
latencia todavía. Si 5 s de lectura se le quedaran cortos, no es una pérdida
silenciosa: cuenta como `failed`, deja un ERROR con `ReadTimeoutError` y los 3
intentos cubren el fallo transitorio. Subirlo no es gratis — con 10 s de lectura
el peor caso pasa a ~43 s y deja de caber en los 30 s de ECS —, así que se
ajustará con dato si aparece, no antes.

## Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| **Executor compartido** (`ThreadPoolExecutor` global) | Las corrutinas de los hooks ya son async y hacen `to_thread` dentro; un executor obligaría a envolverlas o a reescribirlas en síncrono. El loop de reserva da el mismo techo de hilos sin tocar los hooks |
| **Cola acotada con workers propios** | Es lo que hay, pero sin la cola: con un límite de trabajo en vuelo y descarte explícito, una cola solo añade latencia entre el evento y su entrega. La única cola necesaria es la de profundidad 1 por clave, que existe para el orden, no para el encolado |
| **Outbox persistente en Mongo** | Daría entrega garantizada de verdad, pero añade escrituras por notificación al camino que #56 lleva un mes adelgazando (21 → 8 por turno), obliga a un consumidor aparte y arrastra la dimensión DocumentDB. Para un volumen de 0-3 notificaciones por turno y una pérdida aceptable en metadata, es desproporcionado |
| **Reintentos propios** | botocore ya reintenta (3 intentos, modo `standard`, con backoff). Un reintento encima duplicaría el tiempo de retención del hilo sin añadir garantía |
| **Orden global** | Serializaría sesiones que no tienen nada que ver. El orden se pide por `session_id`, que es donde el consumidor lo necesita |

## MongoDB y DocumentDB

**No aplicable, y por decisión explícita.** Ninguna de las piezas de esta issue
persiste trabajo: el límite, el orden y el cierre viven en memoria del proceso.
La única alternativa que habría tocado la base de datos — el outbox persistente —
se descarta arriba. Si alguna vez se retoma, la investigación de compatibilidad
DocumentDB hay que hacerla entonces, no ahora.

## Criterios de aceptación

- [x] **La investigación determina garantías y límites por hook.** Tabla de
      política arriba, con los requisitos que fijó el consumidor.
- [x] **No crece sin límite el número de threads o tareas.** 403 → 21 hilos en
      una ráfaga de 200; el trabajo en vuelo tiene un techo de 64 y el descarte
      es explícito. Fijado con dos tests de regresión.
- [x] **El proceso termina limpiamente con una política observable.**
      `shutdown_hooks()` entrega 20/20 donde antes se perdían 20/20 en silencio;
      sin él, el `atexit` deja los contadores en el log.
- [x] **Cualquier dependencia de MongoDB/DocumentDB queda probada o marcada como
      no aplicable.** Marcada como no aplicable, con el motivo.

## Reproducir

```bash
# Coste de una ráfaga por camino de dispatch (sin base de datos)
uv run python -m benchmarks.hook_burst
uv run python -m benchmarks.hook_burst --burst 500 --work-ms 20 --path reserve

# Las garantías, como tests
uv run --extra dev python -m pytest tests/unit/test_hooks_background_work.py -v
uv run --extra dev python -m pytest tests/unit/test_hooks_delivery_policy.py -v
uv run --extra dev python -m pytest tests/unit/test_hooks_aws_client_config.py -v
```
