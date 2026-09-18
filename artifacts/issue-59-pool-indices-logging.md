# Evidencia sobre pool, health checks, índices y logging (#59)

Fecha: 17 de septiembre de 2026

Medido contra **MongoDB 8.2.7** local, un **replica set de 3 nodos** (MongoDB 7 en
Docker) y **Amazon DocumentDB 5.0** DEV (`db.t4g.medium`, eu-west-1) por túnel SSH.
pymongo 4.18.1. Cada apartado termina en una recomendación, y las que valen la pena
están recogidas al final separadas por entorno.

> Este documento es la investigación, escrita antes de tocar nada. Lo que se hizo
> después con ella está en [`features/13_pool_health_indexes_logging/plan.md`](../features/13_pool_health_indexes_logging/plan.md)
> y se publicó en 0.19.0. De los ocho hallazgos, seis se corrigieron; los dos que
> quedan abiertos —retirar el índice `session_id` y migrar los f-strings de
> logging— se explican en «Qué queda fuera» de ese plan.

## Resumen

| # | Hallazgo | Gravedad | Dónde |
|---|---|---|---|
| 1 | Los defaults del pool **pisan la connection string**: `retryWrites=false` en la URI no tiene efecto, y con DocumentDB eso rompe *todas* las escrituras de la librería | Alta | `mongodb_connection_pool.py:71-84` |
| 2 | `minPoolSize=10` y `maxIdleTimeMS=30000` se contradicen: una aplicación **ociosa** abre y cierra 33.596 conexiones al día, por proceso y por nodo | Alta | `mongodb_connection_pool.py:72-74` |
| 3 | El techo de conexiones es `nodos × (maxPoolSize + 2)`, no `maxPoolSize`. Con los defaults, **10 procesos saturan** el cluster DEV | Alta | dimensionamiento |
| 4 | El health check puede bloquear **20 s** un hilo —o el event loop del consumidor— y fuerza el primario | Media | `mongodb_connection_pool.py:138-165` |
| 5 | `_ensure_indexes()` pierde en silencio los índices posteriores al primero que falla, y lo reintenta en cada request | Media | `mongodb_session_repository.py:291-309` |
| 6 | `create_session()` siembra `metadata_fields` como clave literal: `user.name` no casa ni con su índice ni con `update_metadata()` | Media | `mongodb_session_repository.py:397-400` |
| 7 | Los índices cuestan **cero** medible en escritura; el de `session_id` empeora una consulta real y ninguno se usa en `find` con `sort` | Baja | `mongodb_session_repository.py:291-303` |
| 8 | El logging del camino caliente es **volumen**, no latencia: 1.900 B por turno, 0,003 % del tiempo | Baja | 14 llamadas a `logger.info` |

Lo que **no** hay que cambiar, y conviene dejar escrito porque el análisis previo
lo sugería: sustituir `server_info()` por `ping` **no compra latencia** (§4), y
retirar índices **no compra escrituras** (§7).

---

## 1. Los defaults del pool pisan la connection string

`MongoDBConnectionPool.initialize()` construye el cliente así:

```python
merged_kwargs = {**default_kwargs, **kwargs}
instance._client = MongoClient(connection_string, **merged_kwargs)
```

En pymongo **el kwarg del constructor gana a la URI**, siempre. Verificado:

| Cadena | Kwarg | `client.options.retry_writes` |
|---|---|---|
| `?retryWrites=false` | — | `False` |
| `?retryWrites=false` | `retryWrites=True` | **`True`** |

Como `default_kwargs` incluye `retryWrites: True`, quien ponga `retryWrites=false`
en la URI —lo que exige AWS para DocumentDB y lo que documenta este mismo repo en
`docs/development/testing.md:574`— **obtiene `True`**. Y lo mismo vale para
`maxPoolSize`, `minPoolSize`, `maxIdleTimeMS`, `waitQueueTimeoutMS`,
`serverSelectionTimeoutMS`, `connectTimeoutMS`, `socketTimeoutMS` y `retryReads`:
ponerlos en la cadena de conexión no tiene efecto.

### Qué rompe exactamente contra DocumentDB 5.0

No es una advertencia teórica. Con `retryWrites=True`, contra el cluster DEV:

| Operación | `txnNumber` enviado | Resultado |
|---|---|---|
| `insert_one` | sí | ok |
| `update_one` (`$set`) | sí | **`OperationFailure` 301: `Retryable writes are not supported`** |
| `update_one` (`$push`) | sí | **`OperationFailure` 301** |
| `update_one` (upsert) | sí | **`OperationFailure` 301** |
| `delete_many` | no | ok |

DocumentDB acepta el `txnNumber` en `insert` y lo rechaza en `update`. Eso
significa que `create_session()` funciona —es el único `insert_one` de la
librería— y **fallan `create_agent()`, `create_message()`, `update_agent()`,
`update_message()`, `update_metadata()`, `add_feedback()` y el resto**: todas son
`update_one`. El fallo no aparece al conectar: `initialize()` hace `ping`, el ping
va bien, y la sesión se crea. Revienta en el primer mensaje.

Hoy no afecta a producción porque los consumidores conocidos pasan
`retryWrites=False` **también como kwarg**, además de en la URI; uno lo anota en
su código como «Required for DocumentDB compatibility», y otro tiene incluso un
test que lo fija. Es decir: **todos han tropezado con esto y lo han parcheado en
su lado**.

**Recomendación.** Un default solo debe aplicarse si el usuario no expresó ese
parámetro *ni por kwarg ni en la URI*. `pymongo.uri_parser.parse_uri()` devuelve
las opciones de la cadena y permite descartar de `default_kwargs` las que ya
vengan dadas. Es compatible hacia atrás: quien no ponga nada sigue obteniendo los
mismos valores.

## 2. `minPoolSize` y `maxIdleTimeMS` se contradicen

`maxIdleTimeMS` existe para soltar conexiones ociosas; `minPoolSize` para
mantenerlas calientes. Con los dos activos el driver hace las dos cosas, en
bucle. Con los defaults exactos de la librería (`minPoolSize=10`,
`maxIdleTimeMS=30000`) y **sin una sola consulta** en tres minutos:

| Ocioso | Conexiones abiertas | Cerradas | Vivas | Motivo del cierre |
|---:|---:|---:|---:|---|
| 30 s | 20 | 10 | 10 | `idle` |
| 60 s | 30 | 20 | 10 | `idle` |
| 120 s | 50 | 40 | 10 | `idle` |
| 180 s | 70 | 60 | 10 | `idle` |

**1.400 aperturas por hora, 33.596 al día**, por proceso y por nodo del replica
set. El pool repone hasta `minPoolSize` en segundo plano, así que el request no
paga la espera (un `ping` tras la inactividad costó 0,689 ms) — lo paga el
servidor, en handshakes TLS y autenticaciones SCRAM que no pidió nadie. El
`totalCreated` del cluster DEV iba por 123.340.

Lo que cuesta cada una de esas reaperturas, aislado con `minPoolSize=0` y un
cliente nuevo por muestra (incluye descubrimiento de topología, TCP, TLS y
autenticación):

| | Conexión nueva (p50) | Conexión reutilizada (p50) | Sobrecoste |
|---|---:|---:|---:|
| MongoDB 8.2.7 local | 3,05 ms | 0,28 ms | **2,77 ms** |
| DocumentDB 5.0 DEV (por túnel) | 651,75 ms | 48,45 ms | **603,30 ms** |

El túnel SSH infla el número de DocumentDB; dentro de la VPC será bastante menor,
pero el handshake sigue siendo varios RTT y el RTT sigue siendo ~48 ms.

**Recomendación.** Elegir una de las dos políticas, no las dos:

- `minPoolSize=N` con `maxIdleTimeMS=None` (sin expiración): N conexiones calientes,
  cero churn. Es lo que quiere un servidor de larga vida. Ojo: «sin expiración» se
  escribe `None`, no `0` — pymongo rechaza el cero, por kwarg y en la URI
  (`ValueError: maxidletimems must be greater than 0`), y en una connection string
  la única forma de decirlo es no poner la opción.
- `minPoolSize=0` con `maxIdleTimeMS` corto: el pool se vacía en reposo y el
  primer request tras la pausa paga la apertura. Es lo que quiere una Lambda o un
  proceso efímero.

## 3. Dimensionamiento: `maxPoolSize` es por servidor

`maxPoolSize` no limita el cliente: limita **el pool que el cliente mantiene
contra cada servidor de la topología**. Medido con un `MongoClient` y un replica
set de 3 nodos, `readPreference=secondaryPreferred`:

| `minPoolSize` | Momento | Conexiones de pool por nodo | Sockets por nodo |
|---:|---|---|---:|
| 10 | en reposo | 10 / 10 / 10 | 12 |
| 10 | tras ráfaga de 30 hilos | 10 / 15 / 15 | 12 / 17 / 17 |
| 0 | en reposo | 1 / 0 / 0 | 3 / 2 / 2 |
| 0 | tras ráfaga de 30 hilos | 1 / 15 / 15 | 3 / 17 / 17 |

Los **2 sockets por nodo** que sobran del pool son de SDAM: el monitor del
servidor y su conexión de medición de RTT. Existen aunque el pool esté vacío, y
no los limita `maxPoolSize`.

De ahí la fórmula:

```
sockets en reposo  = nodos × (minPoolSize + 2)
sockets en el pico = nodos × (maxPoolSize + 2)
```

Con los defaults actuales (`maxPoolSize=100`, `minPoolSize=10`):

| Topología | En reposo | Pico |
|---|---:|---:|
| Un nodo (`directConnection=true`, que es como conectan hoy los consumidores) | 12 | 102 |
| Replica set de 3 nodos | 36 | **306** |

Y el techo del otro lado, preguntado al servidor con `serverStatus`:

| Servidor | `current` | `available` | Techo |
|---|---:|---:|---:|
| DocumentDB DEV `db.t4g.medium` | 151 | 849 | **1.000** |
| MongoDB 8.2.7 local | 3 | 410.137 | sin límite práctico |

**Un solo proceso con los defaults puede reclamar el 10 % del cluster DEV**; diez
procesos —cuatro tareas ECS con dos workers de Uvicorn cada una ya son ocho— lo
agotan. El número a dimensionar no es «cuántas conexiones quiero», sino:

```
procesos × nodos × (maxPoolSize + 2) ≤ techo del cluster
```

Conviene recordar que el pool **no fue el cuello de botella** en ninguna medición
de #60 dentro de un worker async: con un event loop y un driver síncrono las
llamadas se serializan y la cola se ve en el lag del loop. `maxPoolSize` alto no
hace daño por sí mismo mientras nadie lo use; el daño aparece cuando varios
procesos sí lo usan a la vez.

### Espera de checkout con concurrencia creciente

Con hilos reales —donde el pool sí se puede medir, al contrario que en el harness
async de #60— la espera de checkout no mide saturación mientras haya conexiones
calientes: mide **establecimiento**.

MongoDB local, `maxPoolSize=100`, `minPoolSize=10`, escrituras:

| Hilos | Espera p50 | Espera p95 | Espera p99 | Conexiones nuevas |
|---:|---:|---:|---:|---:|
| 1 | 0,0032 ms | 0,0058 ms | 0,0595 ms | 0 |
| 4 | 0,0034 ms | 0,0064 ms | 0,0389 ms | 0 |
| 16 | 0,0037 ms | 0,0052 ms | **5,50 ms** | 6 |
| 64 | 0,0035 ms | 0,0048 ms | **68,01 ms** | 26 |

Con el pool encogido a `maxPoolSize=4` y 64 hilos —saturación de verdad— la
espera p50 sigue siendo 0,0034 ms y el p99 sube a **124,23 ms**. DocumentDB, con
16 hilos y 6 conexiones nuevas: p99 de **602 ms**, el precio de §2.

**Recomendación.** Alertar sobre el **p99** de espera de checkout, nunca sobre la
media ni el p50: un pool saturado no mueve el p50. Y no leer una espera alta como
«falta `maxPoolSize`» sin mirar antes cuántas conexiones se crearon: casi siempre
es `minPoolSize` demasiado bajo, no `maxPoolSize`.

## 4. Health check: `server_info()` frente a `ping`

`server_info()` es `buildInfo` con `ReadPreference.PRIMARY` fijo (fuente de
pymongo). `get_pool_stats()` lo llama en cada invocación.

Medido **entrelazando** las muestras, con el pool ya caliente:

| | `ping` p50 | `server_info` p50 | `hello` p50 |
|---|---:|---:|---:|
| MongoDB 8.2.7 local | 0,22 ms | 0,25 ms | 0,23 ms |
| DocumentDB 5.0 DEV | 48,68 ms | 48,56 ms | 49,36 ms |

**Son indistinguibles.** El coste es el RTT, no el comando. Una primera pasada
midió cada comando en bloques seguidos y dio `ping` 92 ms contra `server_info`
48 ms en DocumentDB; era sesgo de orden — el primer bloque pagaba el llenado del
pool. Queda anotado porque es fácil repetir el error y concluir lo contrario.

Lo que sí cambia:

| | `ping` | `buildInfo` | `hello` |
|---|---:|---:|---:|
| Respuesta en MongoDB | 17 B | **6.289 B** | 292 B |
| Respuesta en DocumentDB | 40 B | 139 B | 673 B |

Y sobre todo, el peor caso. Con `serverSelectionTimeoutMS=5000` y
`socketTimeoutMS=30000`, que son los defaults de la librería:

| Escenario | `server_info()` sin timeout | `ping` con `pymongo.timeout(0.5)` |
|---|---:|---:|
| Servidor inalcanzable (puerto cerrado) | 5,05 s | 0,50 s |
| **Servidor mudo con la conexión ya establecida** | **20,04 s** | 2,01 s (con timeout de 2 s) |

El segundo caso es el realista: un failover, un NAT que descarta el flujo, una
instancia que deja de responder. Se reprodujo con un proxy TCP que deja pasar el
handshake y después enmudece.

### Lo que el consumidor real pide, y lo que recibe

El health check de un visor de sesiones consumidor hace, en esencia:

```python
@app.get("/health", response_model=HealthResponse)
async def health_check():
    collection = app.state.collection
    collection.find_one({}, {"_id": 1})  # pymongo síncrono, en el event loop
    pool_stats = MongoDBConnectionPool.get_pool_stats()  # buildInfo, sin timeout
    return HealthResponse(
        ...,
        connection_pool=ConnectionPoolStats(
            active_connections=pool_stats.get("active_connections"),
            available_connections=pool_stats.get("available_connections"),
            total_connections=pool_stats.get("total_connections"),
        ),
    )
```

Tres observaciones, las tres verificadas:

1. `get_pool_stats()` devuelve `status`, `server_version` y `pool_config`.
   **`active_connections`, `available_connections` y `total_connections` no
   existen**: las tres son `None` en cada respuesta. El único consumidor conocido
   del health check pide exactamente las métricas de utilización que la librería
   no expone.
2. El endpoint es `async def` y hace dos llamadas bloqueantes de pymongo dentro
   del event loop. Con el servidor mudo eso son hasta 20 s con **toda** la
   aplicación parada, no solo el `/health`.
3. La versión del servidor no cambia entre llamadas. Se está pagando un
   `buildInfo` por cada sonda para releerla.

El consumidor no llegó ahí solo. `docs/user-guide/connection-pooling.md:398-417`
enseña exactamente ese patrón — un `@app.get("/health")` declarado `async def` que
llama a `get_pool_stats()` en el propio event loop — y en `:388` sigue
documentando una clave `connection_string` en la respuesta que se retiró
justamente para no exponer credenciales. Las dos cosas convendría arreglarlas
tanto si se toca el health check como si no.

**Recomendación.** Un `health_check(timeout_ms=...)` explícito que use `ping`
—bajo `pymongo.timeout()`, y con la read preference del cliente, no el primario
forzado—, cachee `server_version` de la inicialización, y exponga utilización
real del pool a partir de eventos CMAP (`ConnectionPoolListener`), que es lo que
el consumidor ya intenta leer. El coste de esos eventos es el que ya paga el
harness de #60 sin efecto medible.

## 5. Índices: qué consulta usa cada uno

**Ninguna consulta de la librería usa estos índices.** De las 23 operaciones que
`mongodb_session_repository.py` lanza contra la colección, una es el `insert_one`
de `create_session()` y las otras 22 filtran por `_id`. Los seis índices de
`_ensure_indexes()` existen para consumidores externos, y el consumidor real es
el SessionViewer, un visor de sesiones que consulta la colección directamente:

```python
query["session_id"] = {"$regex": re.escape(session_id), "$options": "i"}
query["metadata.<f>"] = {"$regex": re.escape(value), "$options": "i"}
query["created_at"] = {"$gte": ..., "$lte": ...}
total = collection.count_documents(query)
cursor = collection.find(query).skip(offset).limit(limit).sort("created_at", -1)
```

### `find` con `sort("created_at", -1).limit(20)`

MongoDB 8.2.7, 5.000 sesiones, 110,6 MB, documento medio de 22 KB:

| Consulta | Con índices | Sin índices |
|---|---|---|
| listado por defecto | `IXSCAN created_at_1`, 20 docs, **0,378 ms** | `COLLSCAN`+`SORT`, 5.000 docs, 1,469 ms |
| rango de fechas | `IXSCAN created_at_1`, 20 docs, **0,343 ms** | `COLLSCAN`+`SORT`, 5.000 docs, 2,343 ms |
| `session_id` regex `i` | `IXSCAN created_at_1`, **5.000 docs, 3,589 ms** | `COLLSCAN`+`SORT`, 5.000 docs, **2,100 ms** |
| `metadata` regex `i` | `IXSCAN created_at_1`, 96 docs, **0,412 ms** | `COLLSCAN`+`SORT`, 5.000 docs, 2,612 ms |
| `application_name` exacto + `sort updated_at` | `IXSCAN updated_at_1`, 58 docs, **0,368 ms** | `COLLSCAN`+`SORT`, 5.000 docs, 1,794 ms |

El `sort` con `limit` decide el plan: el planner escoge **siempre** el índice de
la fecha por la que se ordena, porque evita el blocking sort y puede parar a los
20 documentos. `session_id_1`, `application_name_1` y los `metadata.*_1` **no se
eligen en ninguna de estas cinco consultas**. En la de `session_id` el resultado
es peor con índices que sin ellos: escanea las 5.000 claves de `created_at_1`
filtrando por un regex no anclado.

### `count_documents` — el total de la paginación, que no ordena

Aquí sí entran los índices del filtro, y aquí **los dos motores difieren**:

| Consulta | MongoDB 8.2.7 | DocumentDB 5.0 |
|---|---|---|
| `session_id` regex `i` | `IXSCAN session_id_1`, 5.000 claves, **0 documentos**, 1,626 ms (`COLLSCAN` 1,869 ms) | **`COLLSCAN` con índice y sin él** |
| `metadata` regex `i` | `IXSCAN metadata.case_type_1`, 0 documentos, 1,561 ms (`COLLSCAN` 2,355 ms) | **`COLLSCAN` con índice y sin él** |
| `metadata` exacto | `COUNT_SCAN`, 1.001 claves, **0,441 ms** (`COLLSCAN` 1,640 ms) | `IXONLYSCAN`, 48,9 ms (`COLLSCAN` 53,0 ms) |
| `application_name` exacto | `COUNT_SCAN`, 1.668 claves, **0,480 ms** (`COLLSCAN` 1,254 ms) | `IXONLYSCAN`, 49,7 ms (`COLLSCAN` 54,4 ms) |

En MongoDB, con regex el índice sigue sirviendo como índice de cobertura:
`docs_examined = 0` frente a 5.000. La diferencia de latencia local es pequeña
porque los 110 MB caben en caché; lo que el índice evita es **leer los
documentos**, y eso se nota cuando el working set no cabe en RAM o cuando la I/O
se paga, que es el caso de DocumentDB. En DocumentDB, en cambio, el regex
case-insensitive **no usa el índice en absoluto**: solo la igualdad exacta lo
aprovecha.

### Coste de tenerlos

Cuatro colecciones idénticas de 5.000 sesiones, la misma carga de `$push` de
mensaje, 500 muestras **entrelazadas** para que cualquier deriva de la máquina
caiga por igual sobre todas:

| Índices | p50 | p95 | p99 |
|---|---:|---:|---:|
| solo `_id` | 0,305 ms | 0,380 ms | 0,448 ms |
| solo `updated_at` | 0,307 ms | 0,384 ms | 0,487 ms |
| los 5 que no cambian por mensaje | 0,306 ms | 0,380 ms | 0,506 ms |
| los 6 de la librería | 0,309 ms | 0,391 ms | 0,483 ms |

**No hay coste medible.** Una medición anterior, no entrelazada, dio +11 % en p50
y 3× en p99 para «con índices»; era orden de ejecución. Se anota porque es el
error que llevaría a retirar índices por una razón que no existe.

De los seis, solo `updated_at` cambia de valor en el camino por mensaje —
`created_at`, `session_id`, `application_name` y los `metadata.*` se escriben al
crear la sesión y no se vuelven a tocar—, así que solo él podía costar algo. No
cuesta.

El tamaño sí difiere entre motores: con 5.000 documentos, cada índice ocupa 4 KB
en MongoDB; en DocumentDB, con solo 300 documentos, entre 32 KB y 40 KB. Y
crearlos sobre una colección poblada cuesta 6-8 ms en MongoDB frente a **78-248 ms
en DocumentDB** — dato relevante para §7.

**Recomendación por índice:**

| Índice | Veredicto |
|---|---|
| `created_at` | **Mantener.** Es el único que el planner elige en el listado, y sin él el `sort` es un blocking sort sobre documentos de 22 KB |
| `updated_at` | **Mantener** si alguien ordena por él; ningún consumidor conocido lo hace hoy. No cuesta nada tenerlo, así que retirarlo es opcional y necesita confirmar antes que ningún job de mantenimiento lo use |
| `application_name` | **Mantener.** Gana 2,6× en el `count` por igualdad, en los dos motores |
| `metadata.<campo>` | **Mantener.** Gana 3,7× en el `count` por igualdad y evita leer documentos en el `count` con regex (solo en MongoDB) |
| `session_id` | **Candidato a retirada, coordinado.** No se elige en ningún `find`, empeora la consulta de búsqueda por id, y en DocumentDB no sirve ni para el `count`. Su único uso es el `count` con regex en MongoDB. Antes de retirarlo: el SessionViewer debería buscar por `_id`, que vale lo mismo (`_id == session_id` desde `create_session()`) y ya está indexado |

## 6. El índice compuesto `(application_name, updated_at)`

El planner lo elige cuando existe, en los dos motores: 20 claves y 20 documentos
examinados para filtro por aplicación más `sort` por fecha. Pero **no mejora nada
medible** frente a lo que ya hay: 0,413 ms con el compuesto contra 0,368 ms con
`updated_at_1` a secas.

La razón es la selectividad: con tres aplicaciones, un tercio de la colección casa
con el filtro, y ordenar por `updated_at` y descartar lo que no casa ya llega a 20
resultados tras examinar 58 documentos. El compuesto solo ganaría con muchas
aplicaciones y una minoritaria, donde `updated_at_1` tendría que recorrer media
colección antes de juntar 20 filas de esa aplicación.

**Recomendación. No añadirlo.** No hay hoy ninguna consulta que filtre por
`application_name` y ordene por `updated_at`: el SessionViewer no filtra por
aplicación en absoluto. Añadirlo ahora sería indexar una consulta hipotética. La
regla para cuando aparezca: merece la pena si la aplicación más pequeña es una
fracción pequeña del total, no por el hecho de que la consulta exista.

## 7. `_ensure_indexes()` pierde índices en silencio

Reproducido contra MongoDB 8.2.7 llenando la colección hasta 62 índices —el
límite de MongoDB son 64— y dejando sitio justo para dos de los seis:

```
WARNING  Failed to create indexes: add index fails, too many indexes ...
         key:{ session_id: 1 }, code 67 CannotCreateIndex
```

| | |
|---|---|
| Índices de la librería creados | `created_at_1`, `updated_at_1` |
| `application_name` indexado | **no** |
| `metadata.*` indexados | **no** |
| El constructor lanzó | **no**, solo un `warning` |

Los seis `create_index` están dentro de un único `try`: el tercero falla y se
lleva por delante los tres últimos. El orden actual es
`created_at`, `updated_at`, `session_id`, `metadata.*`, `application_name` —
`application_name` es el último, el más expuesto.

Hay un segundo efecto que la issue no recoge y que es peor a largo plazo: la
clave **no se registra** en `_INDEX_REGISTRY` cuando algo falla (correcto: un
manager posterior debe reintentar). Con el patrón factory, un manager por
request, eso significa **reintentar los seis `createIndexes` en cada request,
para siempre**. En DocumentDB, donde crear un índice cuesta 78-248 ms, ese
reintento es medio segundo por petición.

**Recomendación.** Un `try` por índice, para que el fallo de uno no arrastre a los
demás, y `application_name` antes de los campos de usuario, que son los que puede
definir mal quien configura. Conviene además distinguir el fallo permanente
(`CannotCreateIndex`, permisos) del transitorio: reintentar en cada request algo
que va a fallar siempre no es resiliencia.

## 8. `create_session()` siembra las claves con el punto literal

Con `metadata_fields=["user.name", "plain"]`:

| Momento | `metadata` en el documento |
|---|---|
| tras `create_session()` | `{"user.name": "", "plain": ""}` |
| tras `update_metadata({"user.name": "ana"})` | `{"user.name": "", "plain": "", "user": {"name": "ana"}}` |

Y el índice que se crea es `metadata.user.name_1`, es decir, sobre el **campo
anidado**. O sea: el valor sembrado no casa con su propio índice, y queda una
clave plana `"user.name"` que ningún camino de la librería vuelve a tocar,
conviviendo con el `user.name` anidado donde sí escribe. Los nombres sin punto
(`plain`) no tienen este problema.

Ningún test fija la forma actual: `tests/unit/test_session_repository.py:209-224`
solo usa nombres sin punto. El doble in-memory **no siembra nada** y su
`__init__` ni siquiera acepta `metadata_fields`
(`tests/support/in_memory_session_repository.py:98-103`, `:167-183`), divergencia
que el guard estructural de `test_in_memory_repository.py:55-60` no detecta
porque compara métodos, no comportamiento.

**Recomendación.** Sembrar anidado o dejar de sembrar. Dejar de sembrar es lo más
limpio —un campo vacío no aporta nada que un campo ausente no dé— pero cambia la
forma del documento, así que hay que mirarlo con el SessionViewer: su detección
del tipo de campo muestrea documentos con
`{"$exists": True, "$ne": None}` para decidir el tipo de un campo de filtro, y un
campo que solo existe cuando alguien lo ha escrito cambia lo que ese muestreo ve.
Sea cual sea la decisión, el doble in-memory debería seguirla, y el contrato
compartido probarla en los dos.

## 9. Logging: es volumen, no latencia

Un turno de referencia `turn.supervisor` (supervisor más sub-agente, seis
mensajes), con el nivel en INFO:

| | |
|---|---:|
| Registros de la librería | 25 (14 `INFO`, 11 `DEBUG`) |
| Registros `INFO` | **14** |
| Bytes de esos `INFO` | **1.900 B** |

Los catorce:

```
Using provided MongoDB client                      ×2
Initialized MongoDB session repository - ...       ×2
Initialized Itzulbira session manager for ...      ×2
Created message N for agent ...                    ×6
Skipping close - using shared MongoDB client       ×2
```

Ocho de los catorce son ruido de construcción que se repite por cada manager — y
con el patrón factory hay un manager por request más uno por sub-agente. Solo seis
son eventos de dominio, uno por mensaje. A 1.900 B por turno, un millón de turnos
al mes son **1,9 GB** de ingesta solo de esta librería.

(De paso: `Initialized Itzulbira session manager` nombra a otro producto en una
librería pública.)

El coste de CPU, en cambio, es despreciable, y conviene decirlo con el número
delante para no venderlo como una optimización de latencia. Con el nivel
desactivado:

| Forma | ns por llamada |
|---|---:|
| `logger.info(f"...")` | 88,6 – 99,6 |
| `logger.info("...%s", x)` | 67,8 |
| `if logger.isEnabledFor(...)` + f-string | 41,4 |

La diferencia entre el f-string y el formato perezoso es de ~32 ns. Catorce
llamadas por turno son **0,45 µs**, frente a un turno de 15-20 ms: **0,003 %**.

**Recomendación.** Bajar a `DEBUG` lo que se emite una vez por manager y una vez
por mensaje (`Using provided MongoDB client`, `Initialized MongoDB session
repository`, `Initialized ... session manager`, `Created message`, `Skipping
close`), y dejar en `INFO` lo que es un evento de sesión de verdad
(`Created session`). Sobre el formato perezoso, `pyproject.toml:79-82` ya tomó la
decisión y da la razón correcta: son 111 llamadas, el estilo es consistente, y
migrarlas «merece su propio PR, no ir de polizón en uno de rendimiento». Estos
números la confirman: no es un PR de rendimiento porque no hay rendimiento que
ganar. El que sí vale la pena es el del nivel, que quita 1.900 B por turno de
CloudWatch sin tocar una sola cadena.

---

## Recomendaciones por entorno

### MongoDB autogestionado o Atlas, servidor de larga vida (FastAPI, ECS)

- `maxPoolSize` según `procesos × nodos × (maxPoolSize + 2) ≤ techo del cluster`.
- `minPoolSize` a lo que se quiera caliente, y `maxIdleTimeMS=None` para no reciclarlo.
- `retryWrites=true`, `retryReads=true`.
- Health check con `ping` bajo timeout explícito, versión cacheada.
- Índices: los seis actuales no molestan. `session_id` es el único prescindible, y
  solo tras mover al SessionViewer a buscar por `_id`.

### Amazon DocumentDB

- **`retryWrites=False` como kwarg explícito**, no solo en la URI, hasta que los
  defaults dejen de pisarla. Sin eso no escribe nada salvo la creación de sesión.
- `minPoolSize` generoso y `maxIdleTimeMS=None`: cada reapertura cuesta cientos de
  milisegundos, y el techo del cluster (1.000 en `db.t4g.medium`) se agota antes
  que en MongoDB.
- Sin `directConnection=true`, el driver descubre todos los nodos del cluster y
  multiplica el pool por ellos. Contarlos.
- El `count` con regex no usa índices: si el SessionViewer se vuelve lento en
  DocumentDB, no es por falta de índices.
- Crear un índice cuesta 78-248 ms: importa cuando `_ensure_indexes()` reintenta.

### Lambda o procesos efímeros

- `minPoolSize=0`, `maxPoolSize` pequeño: con invocaciones concurrentes, cada
  contenedor es un proceso más multiplicando contra el techo del cluster.
- El primer request de cada contenedor frío paga la apertura (2,8 ms en MongoDB,
  cientos de ms en DocumentDB). Ese es el coste, y es inevitable.

---

## Cómo reproducir

Las sondas son scripts de un solo uso; no se han añadido al repositorio para no
arrastrar mantenimiento por algo que no se ejecutará de nuevo. Lo que cada una
hace está descrito arriba con detalle suficiente para reescribirla, y las piezas
reutilizables ya existen:

- Espera de pool y censo de conexiones: `pymongo.monitoring.ConnectionPoolListener`
  sobre los eventos `connection_created`, `connection_closed` y
  `connection_checked_out` (`event.duration` llega en **segundos** y es opcional).
  El harness tiene una versión reducida en `benchmarks/instruments.py:292-344`.
- Turno de referencia para el conteo de logs: `benchmarks.workload.Workload` con un
  `Scenario("turn.supervisor", history=10, concurrency=1)`.
- Planes: `db.command("explain", {...}, verbosity="executionStats")`. DocumentDB
  responde con etapas propias (`SUBSCAN`, `IXONLYSCAN`, `LIMIT_SKIP`) y sin
  `totalDocsExamined`.
- Túnel a DocumentDB DEV: `docs/development/testing.md:520-600`.

Tres trampas metodológicas que costaron una medición cada una:

1. **Entrelazar siempre.** Medir cada variante en un bloque seguido hace que el
   primer bloque pague el calentamiento del pool: dio un `ping` el doble de lento
   que `server_info`, y un +11 % de escritura por índices que no existe.
2. **El p50 no ve la saturación del pool.** Con `maxPoolSize=4` y 64 hilos el p50
   de espera seguía en 3,4 µs mientras el p99 estaba en 124 ms.
3. **Una espera de checkout alta no es un pool pequeño.** Casi siempre es una
   conexión que se estaba abriendo. Contar `connection_created` antes de concluir.

## Limpieza

Todas las bases de datos creadas por estas sondas (`issue59_probe`,
`issue59_index_probe`, `issue59_write_probe`, `issue59_logging_probe`,
`issue59_findings`, `issue59_rs`) se borraron al terminar, en MongoDB local y en
DocumentDB DEV. El replica set de Docker se eliminó, el túnel SSH se cerró por su
socket de control y las credenciales temporales se borraron del disco. No se tocó
ninguna colección de datos reales ni ningún security group.
