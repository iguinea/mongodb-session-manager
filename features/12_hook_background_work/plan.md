# Plan: ciclo de vida del trabajo asíncrono de los hooks

Issue: [#62](https://github.com/iguinea/mongodb-session-manager/issues/62)

## Objetivo

Dar al trabajo que los hooks dejan corriendo en segundo plano un ciclo de vida
con límites, política de overflow explícita y cierre limpio. #95 resolvió el
*mecanismo* de despacho (a qué loop va la corrutina); aquí se decide *cuánto*
puede correr, *en qué orden* y *qué pasa con lo pendiente* cuando el proceso
termina.

## Evidencia

Reproductor: `uv run python -m benchmarks.hook_burst` (sin base de datos).

- Una ráfaga de 200 eventos sin loop al que despachar creaba **403 hilos** —uno
  daemon por evento más el del `asyncio.to_thread` interno del hook— y lanzaba
  200 llamadas boto3 simultáneas contra un cliente con un pool HTTP de 10
  conexiones. El paralelismo era ficticio; el coste en hilos, no.
- Al cerrar el proceso se perdían **20 de 20** notificaciones en vuelo. Con hilo
  daemon, sin una sola línea de log. La política de facto era pérdida silenciosa
  no observable, que no es una política.
- Los clientes boto3 usaban los defaults de botocore: 60 s de connect, 60 s de
  read, modo de reintentos legacy. Una notificación colgada retenía su hilo
  varios minutos.

El detalle completo, con las tablas de antes y después, está en
[`artifacts/issue-62-hook-lifecycle.md`](../../artifacts/issue-62-hook-lifecycle.md).

## Decisiones

- **Un loop de reserva compartido** (`hooks/background_work.py`) sustituye al
  hilo daemon por evento. 403 → 21 hilos en la misma ráfaga. Como efecto, el
  despacho síncrono devuelve ahora un `Future` donde antes devolvía `None`:
  hay algo de lo que recoger el resultado en todos los caminos.
- **Límite de 64 notificaciones en vuelo**, con descarte explícito (WARNING +
  contador) del trabajo best-effort que lo supere. Nada se encola en silencio.
- **Orden por `session_id` en los hooks de metadata.** No salió de la teoría: el
  consumidor que los usa aplica en su cliente lo último que llega, sin timestamp
  ni secuencia, y tiene una ruta que emite tres updates de la misma sesión en
  cascada. Entregar un estado viejo después de uno nuevo le dejaba la vista mal
  de forma permanente. Por clave hay uno en vuelo y uno esperando; el nuevo
  sustituye al que espera, que se descarta en voz alta y nunca se entrega tarde.
- **`Delivery.GUARANTEED` para el feedback SNS.** Transporta una queja de cliente
  que nada vuelve a producir, así que el límite no lo descarta: lo acepta por
  encima con un WARNING.
- **No se bloquea al llamante para conseguirlo**, aunque el consumidor pidió
  backpressure. Sus rutas llaman a `add_feedback()` desde endpoints `async def`:
  bloquear ahí no retrasa una petición, congela el servidor. El resultado que le
  importa —no perder ninguna— se consigue igual, sin el riesgo.
- **Timeouts acotados** en los tres clientes boto3
  (`hooks/aws_client_config.py`): 3 s connect, 5 s read, 3 intentos. Peor caso
  ≈ 24 s, por debajo de los 30 s de gracia de ECS, fijado con un test.
- **`shutdown_hooks(timeout)`** drena, cancela lo que no llega y devuelve los
  contadores. El trabajo que espera turno **sí** se entrega si su turno llega
  dentro del presupuesto; el timeout es el del cierre entero, no el de cada paso.
- **Se conserva un `atexit`, sabiendo que no es una garantía.** Medido: Python
  cierra sus thread pools antes de ejecutar cualquier `atexit`, y los hooks hacen
  su llamada AWS en uno de ellos (1 de 20 entregadas). Se queda porque deja los
  contadores en el log en vez de silencio, y el `RuntimeError` que eso produce se
  degrada a un WARNING legible.

## Descartado

- **Outbox persistente.** Es la única opción con entrega garantizada de verdad,
  pero añade escrituras al camino que #56 lleva adelgazando, obliga a un
  consumidor aparte y arrastra la dimensión DocumentDB. Desproporcionado para
  0-3 notificaciones por turno con pérdida aceptable en metadata.
- **Executor compartido.** Las corrutinas de los hooks ya hacen `to_thread`
  dentro; el loop de reserva da el mismo techo de hilos sin reescribirlas.
- **Cola acotada con workers.** Con un límite de trabajo en vuelo y descarte
  explícito, una cola solo añade latencia. La única que hace falta es la de
  profundidad 1 por clave, que existe para el orden.
- **Reintentos propios.** botocore ya reintenta; encima duplicarían el tiempo de
  retención del hilo sin añadir garantía.

## MongoDB y DocumentDB

No aplicable, explícitamente: nada de esto persiste trabajo. La única
alternativa que habría tocado la base de datos es el outbox, descartado arriba.

## Criterios de aceptación

- [x] La investigación determina garantías y límites por hook.
- [x] No crece sin límite el número de threads o tareas (403 → 21, techo de 64).
- [x] El proceso termina limpiamente con una política observable (20/20 con
      `shutdown_hooks()`, contadores en el log sin él).
- [x] La dimensión MongoDB/DocumentDB queda marcada como no aplicable, con motivo.
