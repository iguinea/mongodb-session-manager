# Evidencia del lote del cursor en la restauracion (#92)

Fecha: 17 de septiembre de 2026

## Decision

**Se negocia `batchSize` en la pagina de mensajes. No se acota el historial.**

La issue planteaba dos palancas y una era condicional: *«Negociar `batchSize` en
el pipeline de restauracion si resuelve el coste sin cambiar el contrato. Si no
basta, acotar el historial restaurado con un limite configurable»*. Basta. En
DocumentDB 5.0 la restauracion de 5.000 mensajes pasa de **52 comandos y 5.649 ms
a 3 comandos y 525 ms**, sin tocar el contrato publico de `list_messages()`, ni el
orden cronologico, ni lo que el modelo ve.

Acotar el historial se descarta y **no se implementa**, por tres razones que la
investigacion dejo medidas:

1. Es un cambio de comportamiento, no de rendimiento: el modelo veria menos
   contexto del que la aplicacion pidio.
2. En la configuracion por defecto el historial **ya esta acotado** por el
   conversation manager (ver «Lo que Strands pide en realidad»).
3. Quien escoge `NullConversationManager` escoge historial completo a proposito.
   Truncarlo por debajo seria romperle el contrato en silencio.

## De donde sale el `batchSize` efectivo

El lote por defecto del cursor es de 101 documentos. MongoDB lo aplica solo al
primer lote y llena los siguientes hasta 16 MiB; DocumentDB lo aplica **a todos**,
asi que un historial de 5.000 mensajes sale en ~50 lotes de 100.

Un lote *estrictamente mayor* que el resultado es lo que agota el cursor dentro
del propio `aggregate`. Uno del tamano exacto no basta: el servidor no sabe que
no quedan documentos hasta que un lote sale corto. Medido sobre 1.000 documentos
en MongoDB 8.2.7 local:

| `batchSize` | Comandos |
|---:|---|
| por defecto | `aggregate` + 1 `getMore` |
| 500 | `aggregate` + 2 `getMore` |
| 1.000 | `aggregate` + 1 `getMore` |
| **1.001** | **`aggregate`** |
| 100.000 | `aggregate` |

De ahi la constante `_MESSAGE_BATCH_SIZE = 1_000_000`: por encima de cualquier
numero de mensajes que quepa en un documento de 16 MiB. Pedir mas de lo que cabe
no cuesta nada — el servidor sigue cortando el lote en 16 MiB y entrega un cursor
por el resto.

## Lo que Strands pide en realidad al restaurar

`RepositorySessionManager.initialize()` llama a `list_messages()` **sin `limit`**,
con `offset=agent.conversation_manager.removed_message_count`. El historial
entero, por tanto, solo cuando ese contador es 0.

Con el conversation manager por defecto no lo es. Medido con 40 turnos reales
contra MongoDB local:

| | |
|---|---|
| Mensajes almacenados | 80 |
| `conversation_manager_state` | `{'removed_message_count': 40, ...}` |
| Mensajes restaurados | **40** |
| Comandos de la restauracion | 2 `find` + 1 `aggregate`, **0 `getMore`** |

`SlidingWindowConversationManager(window_size=40)` —el que `Agent` monta si no le
dan otro— recorta el historial tras cada ciclo y sube `removed_message_count`, que
se persiste en `agent_data`. El `offset` crece con el, asi que la restauracion lee
una ventana y no crece con la sesion.

**El escenario de la issue es real pero no es el comun**: aparece cuando ese
contador se queda en 0 —`NullConversationManager`, una ventana muy grande, o una
sesion sembrada— que es exactamente lo que el escenario `restore` del harness de
#60 monta al sembrar los mensajes por `$push`. Mide el peor caso, no el caso por
defecto. Se deja escrito aqui porque cambia como leer sus cifras.

## Que se rompe si la restauracion devuelve una ventana

Nada de esto se ha implementado; se investigo para poder descartarlo con motivo.

- **Redaccion por `storage_id`**: sobrevive. `initialize()` guarda
  `session_messages[-1]` como `_latest_agent_message`, y una ventana por la cola
  contiene ese ultimo mensaje.
- **Metricas del ultimo mensaje (#66)**: sobreviven por lo mismo.
- **`removed_message_count`**: **no** sobrevive. El `offset` es del conversation
  manager; una ventana que ademas recorte por la cabeza le miente sobre cuantos
  mensajes se quitaron, y el siguiente turno acumula el error.
- **Pares `toolUse`/`toolResult`**: Strands ya lo contempla —
  `_fix_broken_tool_use()` descarta un `toolResult` huerfano al inicio *«when
  messages are truncated due to pagination limits»*— pero pagar una perdida de
  contexto que el propio SDK considera un roto no es un intercambio que haga falta
  aceptar cuando `batchSize` resuelve el coste sin perder nada.
- **Session Viewer**: no le afecta, lee el documento por su cuenta.

## El techo real: 16 MiB, y es de escritura

Se lleno una sesion con mensajes de 16 KB hasta romperla, en MongoDB 8.2.7 local:

```
write stopped at 1000 messages: WriteError: Plan executor error during update ::
caused by :: Resulting document after update is larger than 16777216
document size now: 15.40 MiB with 1000 messages stored
list_messages read 1000 messages with cmds={'aggregate': 1}
```

El limite lo impone `create_message()`, no la lectura: el `$push` falla cuando el
documento de sesion llega a 16 MiB. A 15,40 MiB la lectura sigue costando **un
solo `aggregate`**, asi que el lote negociado aguanta hasta el techo. Que ese
techo exista es lo que hace segura la constante: ningun array de mensajes puede
contener mas entradas de las que quepan en 16 MiB.

## Mediciones

Harness de #60 (`uv run python -m benchmarks --operation restore`), escenario
`restore`, concurrencia 1. **Las dos tablas se leen lado a lado, nunca como un
delta**: la latencia de DocumentDB incluye el tunel SSH.

Las dos columnas de cada tabla se midieron **en la misma sesion y en la misma
maquina**, alternando una sola linea de `list_messages()`. Las cifras de
`artifacts/bench-*.json` (#60) no sirven de linea base: esta maquina estaba mas
cargada hoy y su `restore/h5000` costaba 69,8 ms donde aquel dia costo 31,2.

### MongoDB 8.2.7 local

Standalone en Docker Desktop, macOS arm64, topologia `Single`, lecturas en
`Primary()`, sin compresor. 5 calentamientos y 30 repeticiones.

| Historial | Antes p50 | Despues p50 | Comandos antes | Comandos despues |
|---:|---:|---:|---:|---:|
| 10 | 3,20 ms | 3,00 ms | 3,0 | 3,0 |
| 100 | 3,47 ms | 4,39 ms | 3,0 | 3,0 |
| 1.000 | 16,24 ms | **11,13 ms** | 4,0 | **3,0** |
| 5.000 | 69,77 ms | **47,26 ms** | 4,0 | **3,0** |

### Amazon DocumentDB 5.0 DEV

Cluster de desarrollo en `eu-west-1` por tunel SSH al bastion DEV, TLS,
`directConnection=true`, `retryWrites=false`, cliente en
`readPreference=secondaryPreferred`, topologia `Single`, motor reportado
`documentdb-or-compatible 5.0.0`. 3 calentamientos y 15 repeticiones.

| Historial | Antes p50 | Despues p50 | Comandos antes | Comandos despues |
|---:|---:|---:|---:|---:|
| 10 | 172,0 ms | 147,4 ms | 3,0 | 3,0 |
| 100 | 217,8 ms | 309,4 ms | 3,0 | 3,0 |
| 1.000 | 1.399,4 ms | **335,3 ms** | **12,0** | **3,0** |
| 5.000 | 5.649,4 ms | **524,6 ms** | **52,0** | **3,0** |

Los bytes de respuesta son identicos en las cuatro celdas y en los dos motores
(3,77 MB para 5.000 mensajes), que es lo que ya decia #60: **el coste estaba en
los round-trips, no en el volumen**.

Las filas de 10 y 100 mensajes no cambian de comandos —ya cabian en un lote— y su
movimiento en las dos direcciones (−14,3 % en h10, +42,1 % en h100 sobre
DocumentDB; −6,2 % y +26,5 % en local) es **dispersion del tunel y de la maquina,
no un efecto del cambio**. Con n=15 el p50 de un cluster compartido al otro lado
de un tunel se mueve asi. Lo que si es senal es la columna de comandos.

Los cuatro ficheros de resultados estan versionados y llevan dentro su motor,
version, topologia y preferencia de lectura: `artifacts/bench-issue92-{base,head}-{mongodb,docdb}.json`.

## Efecto sobre las sesiones existentes

Ninguno que requiera accion. `batchSize` es un parametro del cursor, no del
documento: no cambia como se escribe ni como se almacena nada, no hay migracion,
y una sesion escrita por cualquier version anterior se lee igual. Tampoco cambia
lo que `list_messages()` devuelve —los mismos mensajes, en el mismo orden— asi
que ningun consumidor de la libreria ni el Session Viewer necesitan enterarse.
Solo cambia cuantos viajes hace el driver para traerlos.

## Alternativa considerada y descartada

Plegar el pipeline con `$group`/`$push` para que el cursor lleve **un** documento
con todo el array. Medido, funciona y da las mismas cifras (327 ms contra 303 ms
del `batchSize` en DocumentDB con 5.000 mensajes, ambos con un `aggregate`), pero:

- Cambia el pipeline y con el las garantias de orden, que en DocumentDB dependen
  de que el `$sort` sea la ultima etapa. Habria que apoyarse en la regla —tambien
  documentada— de que desde DocumentDB 4.0 `$push` respeta el `$sort` anterior.
- Convierte el resultado en un unico documento, y un unico documento **si** tiene
  que caber en 16 MiB. Una sesion al borde del techo pasaria de leerse en dos
  lotes a no leerse.

`batchSize` no toca el pipeline, no toca el orden y degrada bien: si un dia el
resultado no cupiera en un lote, el servidor entrega un cursor por el resto.

## Limpieza

Las cuatro ejecuciones del harness borraron sus sesiones sinteticas por `_id`
exacto (4/4 cada una). Las sondas de investigacion escribieron en la coleccion
`probe92` de la base `benchmark_mongodb_session_manager` y borraron por `_id`,
verificando 0 sobrantes. No se elimino ninguna base ni coleccion, ni se modifico
ningun security group: el bastion DEV ya era alcanzable.
