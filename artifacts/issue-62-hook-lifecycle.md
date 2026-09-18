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
   paralelo con otro de la misma clave ni lo adelanta. Por clave hay uno en
   vuelo y el resto **espera en cola, en el orden en que se envió** (8 por
   defecto); solo al desbordarse se descarta, la más antigua y en voz alta.
4. **Un cierre que dice qué pasó.** `shutdown_hooks(timeout)` —o
   `shutdown_hooks_async(timeout)` desde dentro de un loop— drena lo que puede,
   cancela el resto y devuelve los contadores.

Política por hook, acordada con el consumidor que los registra en producción:

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
| Ahora, sin llamar a nada | **20/20** | los contadores |
| Ahora, con `shutdown_hooks()` | **20/20** | los contadores |

La política de facto era *pérdida silenciosa no observable*, que no es una
política.

**El gancho importa, y `atexit` era el equivocado.** La primera versión
registraba el cierre con `atexit.register()` y entregaba **1 de 20**: Python
cierra sus thread pools *antes* de ejecutar cualquier `atexit`, y los hooks
hacen su llamada AWS en uno de ellos, así que lo que no había llegado al pool ya
no podía llegar — con un `RuntimeError: cannot schedule new futures…` por cada
una. Se registra ahora con `threading._register_atexit()`, el mismo gancho que
usa `concurrent.futures`, que corre **antes** de ese cierre. Los handlers se
ejecutan en orden inverso de registro, así que el nuestro tiene que registrarse
*después* del suyo: de ahí el `import concurrent.futures.thread` que parece
inútil en `register_close_at_exit()` y no lo es — es lo que registra
`_python_exit`, porque `concurrent.futures` carga sus executors de forma
perezosa. Es API privada, con degradación a `atexit` si un día no está.

Qué cubre y qué no: un proceso que **termina de forma ordenada** (fin de
`main`, `sys.exit`, `SystemExit`) drena ahora sin que nadie llame a nada. Un
`SIGTERM` sin handler no ejecuta *nada* de Python, ni `atexit` ni
`threading._shutdown`, así que ahí sigue haciendo falta un handler que llame a
`shutdown_hooks()` — el caso de un servicio en ECS.

## Lo que encontró la revisión

Cuatro revisiones en paralelo (reutilización, simplificación, eficiencia y
altitud) sobre el diff ya terminado. Los dos hallazgos que cambiaron el
resultado:

**Un loop que muere dejaba una sesión muda para siempre.** Si el loop pasado
por `loop=` se para sin que nadie llame a `shutdown_hooks()` — una recarga de
uvicorn, un lifespan que cierra en otro orden — el trabajo que viajaba en él
queda `PENDING` y su callback no corre nunca: el hueco del límite no se
devuelve y, peor, su `order_key` queda ocupado. Reproducido: tres sesiones
varadas, y a partir de ahí **toda** notificación posterior de esas sesiones se
retenía y se descartaba, con `completed` clavado en 0. Ahora, al detectar que
el loop dado ya no corre, se desaloja lo que quedó atrapado en él, se cuenta
como cancelado y se registra — con nivel de error si era `GUARANTEED`. Cubierto
por `TestStrandedWork`.

**El logging se hacía dentro del lock que comparte todo el proceso.** Medido:
un `logger.error(..., exc_info=…)` cuesta 49 µs, y `_finish()` corre en el hilo
del event loop, así que 64 fallos simultáneos — un endpoint de AWS caído —
formateaban 3,1 ms de tracebacks dentro del lock, en el loop. Las líneas se
componen ahora bajo el lock y se emiten fuera (`_Note`).

## Lo que encontró el gate formal

Sobre el diff ya completo: `/simplify`, revisión de principios y una revisión
adversarial externa (Codex sobre el mismo diff, con sondeos ejecutables). Lo
que cambió el código:

**La clave quedaba libre un instante antes de arrancar su sucesor.** `_finish()`
soltaba el lock, contaba, y solo después arrancaba lo que esperaba. En esa
ventana la clave no era de nadie: un `submit` que cayera ahí arrancaba al
momento, y acto seguido arrancaba también el que esperaba — dos notificaciones
de una sesión en vuelo, y la vieja podía llegar la última, que es justo lo que
el orden existe para impedir. El relevo pasa a ocurrir dentro del lock.

**La política de «gana la última» perdía datos.** El consumidor pidió que una
actualización nueva sustituyera a la que espera, y así estaba implementado. Pero
los hooks de metadata publican *el dict que les pasa el llamante*: un delta, no
el estado completo. Descartar `{"progress": 50}` porque después llega
`{"status": "done"}` pierde `progress` para siempre — ningún mensaje posterior
lo lleva. Pasa a ser una cola FIFO acotada (8 por clave); solo el desbordamiento
descarta, y la más antigua.

**`session_id` a secas colisionaba entre hooks.** Registrar el de SQS y el de
WebSocket a la vez serializaba uno contra otro sin motivo: son destinos
distintos. La clave va prefijada (`sqs:`, `websocket:`).

**El cierre síncrono desde dentro del loop se saboteaba.** `shutdown_hooks()`
bloquea el hilo que lo llama; llamado desde un lifespan de FastAPI, ese hilo es
el del loop en el que viajan las notificaciones, así que el drenaje gastaba su
presupuesto entero sin que ninguna pudiera avanzar y luego las cancelaba. Se
añade `shutdown_hooks_async()`, que es el que hay que usar ahí, y el síncrono
avisa si se le llama así.

**Un `fork()` dejaba mudo al hijo.** El hijo hereda el objeto entero pero solo
el hilo que forkeó: el loop de reserva sobrevive como objeto y sigue diciendo
`is_running()`. Reproducido en un subproceso: el padre entrega, el hijo acepta
la notificación y no la entrega nunca. Con `os.register_at_fork()` el hijo
empieza con loop, locks y contadores propios.

**El presupuesto de AWS estaba mal calculado.** `BACKOFF_ALLOWANCE_SECONDS = 4`
suponía ~1 s y ~2 s de backoff. Preguntándole a botocore 1.43.95: en la ruta
que activa `AWS_NEW_RETRIES_2026`, una respuesta con `x-amz-retry-after` añade
hasta 5 s **por reintento**, así que con 3 intentos el peor caso eran 37 s — por
encima de los 30 s de gracia de ECS, justo lo que el presupuesto debía
garantizar. Se baja a 2 intentos (22 s) y el cálculo pasa a derivarse de las
constantes de botocore, con un test que se las pregunta y falla si se mueven.

Se anota sin arreglar, por quedar fuera de esta issue: los tres hooks capturan
su propio error de boto3 y retornan, así que `completed` cuenta corrutinas que
terminan, no notificaciones que AWS aceptó. Documentado en el contador y en
`docs/api-reference/hooks.md`.

De la revisión anterior salió el cambio de gancho de cierre descrito arriba, y el
descarte de dos propuestas: sacar el `run_coroutine_threadsafe` fuera del lock
(10,7 µs que no justifican reservar hueco y reindexar, con 0-3 notificaciones
por turno) y sustituir el sondeo del drenaje por un `Event` (~25 ms una vez por
proceso).

## Requisitos por hook

Los fijó el equipo del único consumidor con hooks registrados, sobre sus dos
formas de despliegue (un servicio FastAPI con hooks a nivel de módulo, y un
entrypoint síncrono con el hook por petición):

- **Feedback SNS: tiene que llegar.** Alimenta su circuito de quejas de cliente;
  perder una es perder una queja sin rastro, y no hay reconciliación posterior.
  Volumen: uno por conversación como mucho.
- **Metadata WebSocket: la pérdida es tolerable, el desorden no.** Su widget hace
  `Object.assign` puro, sin timestamp ni secuencia, y la ruta que abre una
  conversación emite **tres updates de la misma sesión en cascada**. Si el
  segundo pisa al tercero, la vista se queda en un estado intermedio de forma
  permanente. El orden por sesión resuelve un problema real suyo, no teórico.
- **Volumen:** 3 `update_metadata` al abrir una conversación, 0-2 por turno de
  chat, una sesión concurrente por widget. El límite de 64 no lo rozan.
- **Presupuesto de cierre:** 30 s (default de ECS entre SIGTERM y SIGKILL; su
  CDK no fija `stopTimeout`). 5 s de timeout les sobra.

### Una desviación deliberada

Pidieron **backpressure** para el feedback SNS: que `add_feedback()` espere
antes que perder la notificación. No se implementa así. Sus endpoints `async def`
llaman a `add_feedback()` en el propio event loop, y bloquear ahí no retrasa una
petición: congela el servidor. `Delivery.GUARANTEED` consigue lo mismo que les
importa — no se pierde ninguna — aceptándola por encima del límite con un
WARNING. El efecto observable es idéntico; el riesgo, no.

### Una segunda desviación, confirmada por ellos

Pidieron también que una actualización nueva **sustituyera** a la que espera. Se
implementó así y el gate lo tumbó por la forma del payload. Al comunicárselo,
confirmaron que el descarte les habría metido un bug concreto: los tres pushes
de esa ruta no son equivalentes.

| Push | Contenido | ¿Delta? |
|---|---|---|
| Primero | dict completo (`customer_*`, `connection_id`, `case_type`) | No |
| Segundo | el anterior enriquecido desde un sistema externo, **único que lleva `customer_address`** | No |
| Tercero | `{case_type, classification_reason, connection_id}` | **Sí** |

Con «gana la última», una colisión entre el segundo y el tercero descartaba el
segundo, y `customer_address` no vuelve a viajar nunca — su widget lo usa para
el título del chat. Habrían cambiado un bug de
orden por uno de pérdida de campos, más difícil de ver. Su propio diagnóstico:
razonaron sobre `case_type`, que sí es idempotente, y generalizaron al resto del
dict.

La lección, para la próxima vez que un consumidor fije una política: **el
requisito lo fija quien consume, pero la forma del payload la fija el código**.
Un «el último estado gana» solo es correcto si cada mensaje lleva el estado
entero, y eso no se pregunta, se comprueba.

## Credenciales, timeouts y shutdown en AWS

Medido sobre botocore 1.43.95: los clientes se creaban con los defaults —
`connect_timeout=60`, `read_timeout=60`, `retries={'mode': 'legacy'}` (5
intentos) y `max_pool_connections=10`. Una notificación contra un endpoint que no
responde retenía su hilo **minutos**, y el hilo es exactamente el recurso que el
límite de trabajo en vuelo protege.

Los tres hooks pasan a construir sus clientes con
`hooks/aws_client_config.notification_config()`: **3 s de connect, 5 s de read y
2 intentos** en modo `standard`. Peor caso 22 s con el backoff incluido, por
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
| **Reintentos propios** | botocore ya reintenta (2 intentos, modo `standard`, con backoff). Un reintento encima duplicaría el tiempo de retención del hilo sin añadir garantía |
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
      `shutdown_hooks()` entrega 20/20 donde antes se perdían 20/20 en silencio,
      y un cierre ordenado sin llamar a nada también, gracias al gancho que
      corre antes que los thread pools. `SIGTERM` sin handler sigue siendo
      muerte inmediata, y está documentado como tal.
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
