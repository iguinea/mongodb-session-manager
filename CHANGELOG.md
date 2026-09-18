# Changelog

## [2026-09-18] PR #109 - Perf: agrupar los mensajes de cada invocación en una escritura (#53) (@iguinea)

- Update: agrupar los mensajes de cada invocación en una escritura (#53)
- Merge remote-tracking branch 'origin/main' into perf-batch-append_mes…

## [2026-09-18] PR #108 - Feat: el tool de metadata nombra las claves que no encontró (#107) (@iguinea)

- Feat: el tool de metadata nombra las claves que no encontró (#107)
- Merge remote-tracking branch 'origin/main' into feature/issue-107-nam…

## [0.23.0] - 2026-09-18

### Changed
- **`manage_metadata("get", keys=[...])` nombra las claves que no encontró** (#107). Devolvía solo las que existen, así que una petición mixta —dos de tres— llegaba al modelo sin ninguna indicación de que la tercera no estaba. No podía distinguir «no existe» de «no la pedí», y por tanto no podía ni reintentar con otro nombre ni concluir que el dato no vive en metadata. Ahora la respuesta añade `. Not found: ['clave']`. Los otros dos casos no cambian: si están todas, la respuesta es la de siempre; si no está ninguna, sigue siendo `No metadata found for keys: [...]`, que ya era inequívoca. Una clave almacenada con valor `null` cuenta como encontrada — es un valor que alguien escribió, no una ausencia

### Notes
- De las tres formas que puede tomar una lectura agrupada, **solo la mixta era muda**: si no hay nada se dice, si está todo es evidente, y si hay algo se devolvía lo que existe y ni una palabra del resto. Es justo la forma que produce un modelo cuando agrupa sus lecturas, y aquella en la que más necesita saberlo
- Cambia el **texto** de una respuesta del tool, que es contrato con el modelo y no con el código: ningún consumidor parsea ese string. Sin cambios de esquema ni migración
- **DocumentDB**: sin operadores ni patrones de consulta nuevos. Se resuelve sobre el documento que la lectura ya trajo, sin round-trips adicionales

## [2026-09-18] PR #106 - Docs: regla de procedencia anonimizada para los repos consumidores (@iguinea)

- Docs: regla de procedencia anonimizada para los repos consumidores

## [2026-09-18] PR #105 - Docs: corregir el alcance del inputSchema mal formado (#47) (@iguinea)

- Docs: corregir el alcance del inputSchema mal formado (#47)
- Docs: retirar de la nota la identificación del consumidor (#47)

## [2026-09-18] PR #104 - Fix: el tool de metadata rompía la petición y no leía lo que escribía (#47) (@iguinea)

- Fix: el tool de metadata rompía la petición y no leía lo que escribía…

## [0.22.0] - 2026-09-17

### Fixed
- **El `inputSchema` del tool de metadata estaba mal formado, y solo funcionaba porque el SDK lo reparaba** (#47). Estaba escrito a mano y se asignaba tal cual a `ToolSpec.inputSchema`, que es una unión etiquetada cuyo único miembro es `json`. **No rompía nada en producción**: `ToolRegistry.validate_tool_spec()` tiene una rama de compatibilidad (`if "json" not in tool_spec["inputSchema"]`) que lo envuelve con `normalize_schema()` antes de que llegue a ningún proveedor — verificado en strands 1.25, 1.30, 1.40, 1.45, 1.50.2 y 1.56. Lo que sí costaba: esa normalización rellena las descripciones que faltan con literales (`{"description": "Property action"}`), así que **el modelo recibía sus tres parámetros descritos como «Property action», «Property metadata» y «Property keys»**, que es justo el hueco de documentación que esta issue venía a tapar. Y la corrección del spec dependía de una rama que existe por compatibilidad hacia atrás y que se puede retirar sin considerarlo breaking. Ahora lo construye Strands desde la firma y el docstring. Un test valida la petición contra el propio modelo de servicio de botocore, sin credenciales ni llamada a AWS: fuera del registro de tools —pasando el `tool_spec` directamente a un proveedor— el schema desnudo sí es rechazado
- **`get` no encontraba lo que `set` acababa de escribir** (#47). Una clave con punto es una ruta en las tres acciones, pero `get` filtraba las claves de primer nivel: el agente que guardaba `user.name` recibía «No metadata found for keys». Ahora se resuelve la ruta sobre el documento que la lectura ya trajo, sin round-trip adicional. `None` y `False` son valores almacenados, no ausencias, y se devuelven como tales

### Changed
- **El docstring del tool es ahora su contrato**, porque es lo que el modelo lee. Antes lo pisaban un `description=` de una línea y el `inputSchema` a mano, así que nada de lo escrito en él llegaba a ninguna parte. Documenta lo que la issue pedía documentar: que una clave con punto actualiza un campo anidado y conserva sus hermanos, y que una clave cuyo valor es un documento **reemplaza** el que hubiera debajo
- **La respuesta de `set` nombra las claves que reemplazaron un documento entero**. Pasar el subdocumento completo es lo natural para un modelo, y callarlo significaba perder los campos hermanos mientras se le decía que había ido bien. Con notación de punto la respuesta no cambia

### Notes
- Sin cambios de esquema ni migración: lo que cambia es el spec del tool y el texto de dos respuestas. `update_metadata()`, `get_metadata()` y `delete_metadata()` se comportan igual
- **DocumentDB**: no se introduce ningún operador ni patrón de consulta nuevo. La resolución de rutas ocurre en Python, sobre el documento ya leído
- Premisa corregida de la issue: proponía documentarlo en el docstring, que era justo lo que no llegaba al modelo
- **Corrección de un diagnóstico propio**: la primera redacción de esta entrada decía que un agente con este tool fallaba en su primera llamada. **Es falso**, y lo desmontó un equipo consumidor que lo registra en un `Agent` en producción, señalando la rama de compatibilidad del registro de tools. El error estaba en cómo se comprobó: el probe pasaba el `tool_spec` directamente a `format_request()`, saltándose el registro por el que pasa todo `Agent`. Un repro que falla convence mucho, y aun así describía un mundo que no existía: había un dato a mano que lo contradecía —ese agente llevaba meses sirviendo— y no se miró hasta que lo puso encima de la mesa quien lo tenía. Ningún consumidor estuvo roto en ningún momento

## [2026-09-17] PR #103 - Feat: strands-agents 1.56 y el BidiAgent por el camino unificado (#69) (@iguinea)

- Feat: strands-agents 1.56 y el BidiAgent por el camino unificado (#69)
- Test: benchmark del bump de strands en MongoDB y DocumentDB (#69)
- Docs: precisar el aviso de hooks y el default de maxIdleTimeMS (#69)
- Merge remote-tracking branch 'origin/main' into actualizar-strands-ag…

## [0.21.0] - 2026-09-17

### Changed
- **Breaking: el suelo de `strands-agents` sube de `>=1.30.0` a `>=1.56.0`** (#69). El lock llevaba clavado en 1.30.0 desde que el PR de dependabot #52 tumbó la suite. Se sube al final del rango, no a un punto intermedio: el CI corre `uv sync --locked`, así que un rango amplio sería una promesa que no se verifica en ningún sitio. **Instalar 0.21.0 obliga a subir el SDK.** Los consumidores conocidos van pineados a versiones anteriores de esta librería y no se ven afectados hasta que decidan subir
- **Breaking: desaparece `MongoDBSessionManager.initialize_bidi_agent()`** (#69). Strands 1.56 borra de su `SessionManager` la familia `initialize_bidi_agent()`/`sync_bidi_agent()`/`append_bidi_message()` y manda los dos tipos de agente por `initialize()` y `sync_agent()`. Nuestro override llamaba a un `super()` que ya no existe. Quien lo llamara era el SDK, no la aplicación; la validación de `agent_id` que aportaba (#79) la sigue dando `initialize()`, que ahora recibe también los `BidiAgent`

### Fixed
- **`sync_agent()` reventaba con un `BidiAgent`** (#69). 1.56 enruta `BidiAgentStopEvent` a `sync_agent()`, y un `BidiAgent` **no tiene** `event_loop_metrics`: pedírselas era un `AttributeError` al cerrar cada sesión bidireccional. Ahora un agente sin event loop sincroniza su estado y su configuración sin métricas, que es lo correcto: no hay ninguna que tomar

### Notes
- **Sin cambios de esquema propios, pero el documento del mensaje gana dos campos del SDK**, dentro de `message` y persistidos tal cual: `tracking_id` (uuid4, en los mensajes que añade el propio SDK; uno que añada a mano el código de la aplicación se guarda sin él, así que para identificar un mensaje sigue estando `storage_id`) y `metadata` con el `usage` y las `metrics` de **ese ciclo**, en cada mensaje `assistant`. Es la atribución por mensaje que #66 no podía dar, y **no cuesta ninguna escritura**: viaja dentro del `$push` de `create_message()`. Es aditivo: ningún campo existente cambia de nombre, tipo ni posición, y no hace falta migrar. No sustituye a `event_loop_metrics`, que sigue siendo el acumulado de la invocación
- **El bump cuesta una escritura por sesión existente, una sola vez.** Strands 1.34 añadió `model_state` al snapshot interno del agente, así que el primer sync tras subir encuentra un contenido distinto del almacenado y lo escribe. Desde el turno siguiente el documento ya lo lleva y la deduplicación por contenido (#67) vuelve a saltarse el sync. Lo fija `tests/unit/test_agent_rewrites.py::TestAgentStoredByAnOlderSdk`
- **El presupuesto de escrituras por turno no se mueve**: remedido con el `CommandListener` de pymongo sobre el mismo escenario de referencia, 8 `update` y 6 lecturas en 1.30 y en 1.56
- **Medido en las dos bases de datos** con `benchmarks/`, mismo código y cambiando solo el SDK. Los **comandos por operación son idénticos** en los siete escenarios y en los dos motores. En **DocumentDB 5.0 dev** la diferencia queda dentro del ruido (de −1,7 % a +1,1 %, salvo `turn.supervisor/h100` con +3,7 %). En **MongoDB local**, donde el round-trip es submilisegundo, asoma el coste de CPU que 1.56 añade por invocación: **+0,24 a +3,19 ms**, que no escala con el historial sino con el número de agentes del turno. Tablas y método en [`artifacts/issue-69-benchmark-strands-1-56.md`](artifacts/issue-69-benchmark-strands-1-56.md)
- El fichero de resultados del benchmark registra ahora `environment.strands_version`, que no guardaba: sin ella dos runs del mismo commit eran indistinguibles. No entra en la clave de comparabilidad, porque cambiar de versión del SDK contra el mismo servidor es justo lo que se quiere medir
- **Límite documentado del orden de hooks**: desde strands 1.45 los hooks tienen prioridad, y los grupos corren en orden ascendente también en los eventos de orden inverso. Un hook de usuario registrado para `AfterInvocationEvent` con `order=HookOrder.SDK_LAST` corre **después** del sync de cierre, así que un mensaje que añada se guarda sin `event_loop_metrics` — las tiene el mensaje del ciclo al que pertenecen. Con la prioridad por defecto sí las recibe. Los dos órdenes quedan fijados en `tests/unit/test_invocation_metrics.py`. No se corrige: mover nuestro sync a `SDK_LAST` dependería del orden de registro dentro del grupo, y hoy ningún consumidor registra hooks de Strands
- **Los tests dejan de congelar el snapshot interno del SDK.** `persisted_agent()` componía a mano el `_internal_state` que escribía 1.30; con 1.56 dejó de coincidir con lo que el SDK produce para un doble, y el turno de referencia pasó de 5 escrituras a 6 sin que nada hubiera cambiado en producción. Ahora el documento se deriva de `SessionAgent.from_agent()`, o sea de lo que persistiría el SDK que haya instalado. El turno de referencia vuelve a **5 escrituras y 0 lecturas**, y el frío a 7. Lo que un doble puede demostrar ahí es el número de round-trips; que la deduplicación de #67 distinga un `_internal_state` que cambia de uno que no lo hace lo prueba `tests/unit/test_agent_rewrites.py`, con un `Agent` de verdad, porque `from_agent()` solo rellena ese campo para un `Agent`
- **DocumentDB**: no se introduce ningún operador ni patrón de consulta nuevo, solo claves adicionales dentro de un subdocumento que ya se escribía entero. **Probado solo contra MongoDB local**
- **SessionViewer del Control Center**: no se ve afectado. Lee `agents.{aid}` y `metadata.{key}` a nivel de sesión y no toca `message.*`; los campos nuevos son claves extra que ignora
- **Convivencia de versiones sobre la misma colección**: un manager anterior lee los mensajes con las claves nuevas y las conserva
## [2026-09-17] PR #102 - Docs: entrada de CHANGELOG para la v0.20.0 (#99) (@iguinea)

- Docs: entrada de CHANGELOG para la v0.20.0 (#99)

## [2026-09-17] PR #101 - Fix: el error de AWS sale del hook y cuenta como fallo (#99) (@iguinea)

- Fix: el error de AWS sale del hook y cuenta como fallo (#99)

## [2026-09-17] PR #100 - Feat: pool que respeta la configuración, health check acotado e índices que no se pierden (#59) (@iguinea)

- Feat: pool que respeta la configuración, health check acotado e índic…

## [0.20.0] - 2026-09-17

### Changed
- **Breaking: los tres hooks bundled dejan salir el error de AWS** (#99). `MetadataSQSHook.on_metadata_change()`, `MetadataWebSocketHook.on_metadata_change()` y `FeedbackSNSHook.on_feedback_add()` capturaban su propio `ClientError`, lo registraban y **retornaban con normalidad**. Ahora lo propagan, y quien lo recoge es `BackgroundWork`, que ya estaba esperándolo. **Solo cambia para quien llame a esas tres corrutinas con `await` directo**; a través de las factorías —`create_metadata_sqs_hook()`, `create_metadata_websocket_hook()`, `create_feedback_sns_hook()`, que es como las usa todo consumidor conocido— no cambia nada observable salvo el log y los contadores. El `except` que lo justificaba —«don't raise to avoid breaking the main operation»— era de cuando la corrutina corría en el camino del llamante; desde 0.17.3 (#95) y 0.18.0 (#62) viaja en segundo plano, así que cuando corre, la escritura en MongoDB ya terminó y ya se devolvió al llamante. No queda operación que romper
- **Un fallo deja un solo registro, y con la sesión dentro.** Antes eran dos y ninguno completo: un `ERROR` del hook, que sabía de qué sesión hablaba, y un `DEBUG` `Finished:` del dispatcher, que no. Ahora lo registra solo el dispatcher, y el `error_context` de las cinco llamadas a `dispatch_async()` lleva el `session_id` — `sending metadata update to SQS for session <id>`, y así las cinco. De propina lo dicen también los `Dropped hook work while…`, `Cancelled while…` y `Accepting guaranteed hook work over the limit…`, que hasta ahora identificaban la operación pero no la sesión
- **`GoneException` sigue sin ser un fallo, pero ya no tapa a sus vecinos.** El `except ClientError` del hook de WebSocket envolvía el método entero y absorbía cualquier código de error, no solo el de la conexión cerrada; ahora envuelve la llamada a `post_to_connection()` y **relanza todo lo que no sea `GoneException`**. Que el cliente haya colgado no es una avería: es como termina una sesión de WebSocket, se registra a `INFO` y cuenta como completada

### Fixed
- **`hooks_background_stats().completed` contaba como entregada una notificación que AWS rechazó** (#99). `BackgroundWork._count_outcome()` solo puede observar si la corrutina terminó o lanzó; con los hooks tragándose su error, una notificación fallida llegaba indistinguible de una buena. Donde más pesaba era en el feedback: se despacha como `Delivery.GUARANTEED` precisamente porque nada vuelve a producir una queja de cliente, y la garantía se quedaba sin la métrica que la haría verificable. Medido con un `AccessDenied` de SQS, el camino completo pasa de un `ERROR` del hook más `{'completed': 1, 'failed': 0}` a una sola línea —`Error sending metadata update to SQS for session sess-smoke-1: An error occurred (AccessDenied)…`, con traza— y `{'completed': 0, 'failed': 1}`
- **El `except ImportError` de los hooks de SQS y SNS era código muerto**: dentro de esos métodos no hay ningún `import`, y el que podía fallar lo hace al construir el hook, donde ya se comprueba

### Notes
- **Sin cambios de esquema ni migración.** Este cambio no toca MongoDB: managers 0.19 y 0.20 conviven sobre la misma colección, y DocumentDB no aplica —nada de esto persiste
- **Lo que `completed` sigue sin poder prometer** es un hook **de tu propiedad** que capture su propio error y retorne: desde el dispatcher es indistinguible de uno que funcionó. Si quieres sus fallos en el contador, déjalos salir — nadie espera a esa corrutina, y el dispatch los registra con su contexto. `docs/api-reference/hooks.md` separa ahora las dos mitades de un hook: el **wrapper**, que corre en el camino del llamante y sí debe contener su error, y la **notificación**, que no
- **Los cinco tests que fijaban el comportamiento anterior están reescritos, no eliminados** — tres a `pytest.raises`, y el de `GoneException` mantiene su contrato y además comprueba que registra a `INFO` sin ningún `ERROR`. `tests/unit/test_hooks_failure_counting.py` cubre el hueco que no cubría nada: hook real, dispatcher real y contadores. Los que existían usan `captured_dispatch`, que cierra la corrutina sin ejecutarla, o la corren suelta; ninguno podía ver qué hacía `BackgroundWork` con el resultado
- Se desprendió del gate de revisión de #62 (0.18.0), que la documentó como limitación conocida antes de arreglarla

## [0.19.0] - 2026-09-17

### Added
- **`MongoDBConnectionPool.health_check(timeout_ms=1000)`** (#59): un `ping` acotado en el tiempo que devuelve `status`, `latency_ms` y `error`, y **nunca lanza**. El timeout es lo que aporta: sin uno, la sonda hereda `serverSelectionTimeoutMS` y `socketTimeoutMS`, y contra un servidor que enmudece con la conexión ya establecida —un failover, un NAT que descarta el flujo— tardó **20,04 s medidos** en rendirse. Eso es un hilo retenido, o un event loop congelado si corre en uno. Hace `ping` y no `server_info()`, pero no por velocidad —son indistinguibles, el coste es el round-trip: 0,22 ms contra 0,25 en MongoDB local, 48,68 contra 48,56 en DocumentDB— sino porque `server_info()` es `buildInfo` clavado a `ReadPreference.PRIMARY`, así que declara enfermo un cluster en failover mientras la aplicación sigue leyendo de un secundario
- **`get_pool_stats()` dice qué está haciendo el pool**, no solo cómo se configuró: `total_connections`, `active_connections`, `available_connections`, `checkout_failures` y `checkout_wait_ms_max`, contados de los eventos CMAP del driver en `pool_telemetry.py`. pymongo no publica ninguna otra forma de saberlo. Las tres primeras son exactamente las claves que el `/health` del SessionViewer lleva pidiendo desde siempre y recibiendo como `None`. Cuesta **3,33 µs por comando**, un 0,3 % de un turno
- **Guía de dimensionamiento** en `docs/user-guide/connection-pooling.md`: `maxPoolSize` es **por servidor**, más dos sockets de SDAM que no acota nadie, así que un proceso contra un replica set de tres nodos llega a `3 × (100 + 2) = 306` conexiones, no 100. Enfrente, un `db.t4g.medium` de DocumentDB admite **1.000** (preguntado con `serverStatus`): diez procesos lo agotan. Con la fórmula, la tabla de emparejamientos `minPoolSize`/`maxIdleTimeMS` por tipo de despliegue y las particularidades de DocumentDB

### Changed
- **Breaking: un default del pool ya no pisa lo que diga la connection string** (#59). pymongo da precedencia al kwarg del constructor sobre la URI, así que los nueve defaults que inyectaba `initialize()` anulaban en silencio lo que se pusiera en la cadena. Ahora un default solo se aplica a la opción que nadie nombró, ni por kwarg ni en la URI. **Quien pusiera una opción en la cadena de conexión y dependiera de que la librería la ignorase, cambia de comportamiento**; para todos los demás no cambia nada. El caso que lo motiva es DocumentDB: exige `retryWrites=false`, el default `retryWrites=True` lo pisaba, y DocumentDB responde `OperationFailure 301: Retryable writes are not supported` a **todo `update_one`** que lleve un `txnNumber`. O sea que `create_session()` funcionaba —es el único `insert_one` de la librería— y fallaban `create_message()`, `update_agent()`, `update_metadata()`, `add_feedback()` y el resto, sin que el `ping` de arranque avisara de nada
- **`maxIdleTimeMS` pasa de 30.000 a 300.000 ms.** Convivía mal con `minPoolSize`: lo que expira el temporizador de inactividad, el mínimo lo vuelve a abrir. Medido con los defaults anteriores y **sin una sola consulta** en tres minutos, el pool cerraba y reabría sus diez conexiones cada 30 segundos indefinidamente — **33.596 aperturas al día, por proceso y por nodo**, cada una con su handshake TLS y su autenticación SCRAM. El request no lo pagaba, porque la reposición va en segundo plano; lo pagaba el servidor. A 5 minutos son 2.880, y las conexiones de un pico se siguen liberando. Cada reapertura cuesta 2,77 ms contra MongoDB y **603 ms contra DocumentDB**
- **El suelo y el techo del pool dejan de contradecirse con quien los configura**: pymongo rechaza un `minPoolSize` mayor que el `maxPoolSize`, y con un `ValueError` que no es `PyMongoError`, así que escapaba de `initialize()` sin contexto. Al dejar de pisar la URI, un `?maxPoolSize=4` se encontraba con nuestro suelo de 10 y el cliente fallaba al construirse; y al revés, un `minPoolSize=200` chocaba con nuestro techo de 100. Ahora la mitad que nadie eligió cede ante la que sí — el despliegue con recursos contados que pide un pool pequeño, y el ocupado que pide 200 conexiones calientes. Si las dos son de quien llama y se contradicen, la decisión es suya y pymongo se lo dice
- **Un kwarg escrito en minúsculas cuenta como nombrar la opción.** pymongo acepta sus keywords sin distinguir mayúsculas, así que `maxpoolsize=5` pasaba **junto** a nuestro `maxPoolSize=100`: el driver resolvía el techo a 5, dejaba el suelo en 10 y rechazaba el par al arrancar. La comparación se hace ahora sobre el nombre en minúsculas, igual que ya se hacía con las opciones de la URI
- **`pool_config` y el log de arranque leen del cliente, no de los kwargs.** Una opción que viene de la cadena de conexión no está en los kwargs, así que reportarla desde ahí habría dicho `None`
- **El camino por mensaje baja a `DEBUG`** (#59). Un turno de referencia emitía **14 registros `INFO` y 1.900 bytes**, ocho de ellos repetidos por cada manager — y con el patrón factory hay un manager por request más uno por sub-agente. Un millón de turnos al mes son 1,9 GB de ingesta solo de esta librería. Pasan a `DEBUG` los de construcción y cierre del repositorio y del manager, `Created message`, `Updated agent` y `Updated message`; siguen en `INFO` los eventos de sesión (`Created session`, `Created agent`, `Added feedback`) y las operaciones explícitas del manager. **Quien filtre por `INFO` deja de ver esos mensajes; siguen estando, un nivel más abajo.** Los f-strings de logging no se migran a formato perezoso: `pyproject.toml` ya decidió que eso merece su propio PR, y la medición lo respalda — son ~32 ns por llamada, el 0,003 % de un turno

### Fixed
- **`_ensure_indexes()` dejaba de crear índices en silencio** (#59). Los seis compartían un único `try`: el primero que fallaba se llevaba por delante a todos los siguientes. Reproducido contra MongoDB 8.2.7 llenando la colección hasta 62 índices —el límite del servidor son 64—: se creaban `created_at` y `updated_at`, `session_id` fallaba con `CannotCreateIndex`, y **`application_name` y todos los `metadata.*` no se intentaban siquiera**, con un `warning` como única señal. Ahora cada índice va en su propio `try`, y `application_name` se crea **antes** que los campos que configura la aplicación, que son los que pueden venir mal
- **Y los reintentaba en cada request para siempre.** Al fallar no se registraba la clave en el registro de índices —correcto para un fallo pasajero—, pero con un manager por request eso significaba seis `createIndexes` fallidos por petición, indefinidamente. Ahora se distingue: un fallo permanente (`CannotCreateIndex`, `Unauthorized`, conflicto de índice) se registra y se avisa; uno transitorio se deja sin registrar para que el siguiente manager lo reintente. Crear un índice cuesta 78-248 ms en DocumentDB
- **`create_session()` sembraba `metadata_fields` donde no estaba el índice** (#59). Con `metadata_fields=["user.name"]` insertaba la clave plana `{"metadata": {"user.name": ""}}`, mientras el índice iba sobre la ruta anidada `metadata.user.name` y `update_metadata({"user.name": ...})` escribía ahí: el valor sembrado no casaba con su propio índice y quedaba una clave que nada volvía a tocar. Ahora se siembra anidado. Para los nombres sin punto no cambia nada, y el doble in-memory —que no sembraba nada, ni aceptaba `metadata_fields`— sigue la misma regla, con el caso en el contrato compartido
- **Un `get_pool_stats()` contra un servidor callado ya no se lleva los contadores.** `server_version` es el único campo que necesita al servidor; si su `buildInfo` agotaba el segundo de timeout, el `except` devolvía `{"status": "error"}` y tiraba también `pool_config` y toda la telemetría CMAP — que se cuenta dentro del proceso y es justo lo que se mira cuando el servidor va mal. Ahora la versión se pide aparte y vuelve como `None`. `status` pasa a decir si el pool está inicializado, no si el servidor responde: para eso está `health_check()`
- **Un cliente que falla su primer `ping` se cierra.** Soltar la referencia no lo cierra: ya está construido, con su hilo monitor por servidor y, con `minPoolSize`, conexiones en camino. pymongo no cierra en `__del__`, avisa — así que un arranque que reintenta contra un MongoDB que aún no está levantado acumulaba uno por intento, y con `maxIdleTimeMS` a 5 minutos cada uno dura diez veces más
- **Dos `metadata_fields` que no pueden coexistir se rechazan al arrancar**: `user` y `user.name` obligarían a que un campo fuera a la vez valor y subdocumento, y uno de los dos se perdía en silencio. Ahora es un `ValueError` al construir la factoría o el repositorio, antes de conectar

### Notes
- **Sin cambios de esquema ni migración**: los documentos existentes se quedan como están, y managers 0.18 y 0.19 conviven sobre la misma colección. Lo único que cambia de forma es el `metadata` de las sesiones **nuevas** cuyo `metadata_fields` lleve un punto, y hacia donde ya apuntaban su índice y sus escrituras. Las claves planas sembradas antes siguen en sus documentos; borrarlas requiere `repo.collection`
- **No afectaba a producción, y por eso conviene decirlo**: los cuatro consumidores conocidos ya pasan `retryWrites=False` **también como kwarg** además de en la URI, que es la forma de sortear el bug. Todos tropezaron con él y lo parchearon en su lado; uno tiene incluso un test que lo fija
- **Ningún índice se retira.** Medido con 5.000 sesiones de 22 KB y 500 muestras entrelazadas, tenerlos cuesta **cero**: 0,305 ms por escritura con solo `_id` contra 0,309 con los seis. `session_id` es el único prescindible —no lo elige ningún `find`, empeora la búsqueda por id (3,589 ms contra 2,100) y en DocumentDB no sirve ni para el `count`—, pero es lo único que cubre el `count_documents` con regex del SessionViewer en MongoDB, así que retirarlo exige antes mover a ese consumidor a buscar por `_id`. Queda anotado en #59
- **Tampoco se añade `(application_name, updated_at)`**: el planner lo elige cuando existe, pero no mejora nada con la cardinalidad real (0,413 ms contra 0,368 con `updated_at` a secas), y hoy ninguna consulta filtra por aplicación y ordena por fecha
- **Los dos motores no coinciden en los planes**: con `sort(created_at).limit(20)` los dos eligen siempre el índice de la fecha del `sort`, nunca el del filtro; pero en el `count_documents` de la paginación, MongoDB usa el índice como cobertura incluso con regex (0 documentos examinados frente a 5.000) y **DocumentDB hace `COLLSCAN` con índice y sin él**, salvo por igualdad exacta
- Evidencia, alternativas descartadas y el método de medición en [`artifacts/issue-59-pool-indices-logging.md`](artifacts/issue-59-pool-indices-logging.md)

## [2026-09-17] PR #98 - Feat: ciclo de vida para el trabajo asíncrono de los hooks (#62) (@iguinea)

- Feat: ciclo de vida para el trabajo asíncrono de los hooks (#62)
- Fix: correcciones del gate de revisión del ciclo de vida de hooks (#62)
- Docs: el caso real que respalda la cola FIFO de metadata (#62)

## [0.18.0] - 2026-09-17

### Added
- **El trabajo en segundo plano de los hooks tiene ciclo de vida** (#62), en `hooks/background_work.py`. Las notificaciones de todos los hooks del proceso comparten un pool acotado con cuatro reglas: un **loop de reserva compartido** en vez de un thread por evento, un **límite de trabajo en vuelo** (64 por defecto), **orden por clave** donde se pide, y un **cierre explícito** que dice qué pasó
- **`shutdown_hooks(timeout=5.0)` y `shutdown_hooks_async(timeout=5.0)`**: drenan las notificaciones en vuelo, cancelan lo que no llega a tiempo, paran el loop de reserva y devuelven los contadores. Llamarlo donde el proceso cierra es la diferencia entre entregar **20 de 20** notificaciones y perder las 20 en silencio, medido. **Desde dentro de un event loop —el lifespan de FastAPI, un handler async— hay que usar la versión `_async`**: la síncrona bloquearía el mismo loop en el que viajan las notificaciones, así que agotaría su presupuesto entero y cancelaría trabajo que podía haber entregado (la síncrona avisa con un WARNING si se la llama así). Fuera de un loop —un handler de SIGTERM, un `main()` síncrono— la síncrona es el cierre de siempre
- **Un cierre ordenado drena aunque nadie llame a nada.** El cierre se registra con `threading._register_atexit()`, que corre **antes** de que Python cierre sus thread pools; `atexit` corre después, demasiado tarde para unos hooks que hacen su llamada AWS precisamente en uno de esos pools (medido: 1 de 20 entregadas con `atexit`, 20 de 20 con el gancho correcto). Un `SIGTERM` sin handler no ejecuta nada de Python, así que ahí sigue haciendo falta el handler
- **`hooks_background_stats()`**: `dispatched / completed / failed / cancelled / dropped / in_flight / queued`, con `as_dict()` para logs y métricas. `dropped` creciendo avisa de que el límite se está tocando
- `order_key=` y `delivery=` en `dispatch_async()`, y `Delivery` exportado, para que un hook propio elija su política

### Changed
- **Sin loop al que despachar, la notificación va a un loop de reserva compartido**, no a un thread daemon con su propio event loop. Medido con `uv run python -m benchmarks.hook_burst`: una ráfaga de 200 eventos pasa de crear **403 hilos a 21**, y lo que paga el llamante por despachar baja de 131,1 a 5,0 µs (p50). Eran 403 y no 200 porque cada evento arrancaba su thread *y* el `asyncio.to_thread` interno del hook abría otro. En contrapartida, drenar esa ráfaga tarda 4,8× más (114 → 543 ms): 20 llamadas a la vez en lugar de 200, que nunca fueron 200 de verdad porque el cliente boto3 tiene un pool HTTP de 10 conexiones
- **`dispatch_async()` devuelve un `Future` también en contexto síncrono**, donde antes devolvía `None`. Ahora hay algo de lo que recoger el resultado en todos los caminos
- **Las notificaciones de metadata (WebSocket y SQS) se serializan por `session_id`**. Dos updates de una misma sesión no corren en paralelo ni se adelantan: el consumidor aplica lo último que llega, así que entregar un estado viejo después de uno nuevo dejaba su vista mal de forma permanente. Sesiones distintas siguen en paralelo, y la clave va prefijada por hook (`sqs:<session_id>`, `websocket:<session_id>`) para que registrar los dos hooks a la vez no los serialice entre sí. Lo que no puede arrancar todavía **espera en cola, en orden** (8 por clave); solo al desbordarse se descarta, la más antigua
- **Las notificaciones de feedback (SNS) no se descartan nunca** (`Delivery.GUARANTEED`): se aceptan por encima del límite, con un WARNING. Transportan una queja de cliente que nada vuelve a producir. No se bloquea al llamante para conseguirlo, porque `add_feedback()` se llama desde rutas `async def` y bloquear ahí congelaría el servidor
- **Los clientes boto3 de los tres hooks se construyen con timeouts acotados**: 3 s de connect, 5 s de read y 2 intentos (`standard`), frente a los defaults de botocore (60 s, 60 s, modo legacy con 5 intentos). Una notificación contra un endpoint que no responde retenía un hilo varios minutos, y el hilo es el recurso que el límite protege. Peor caso **22 s**, por debajo de los 30 s de gracia que da ECS. El presupuesto incluye el backoff máximo que botocore puede insertar, `x-amz-retry-after` incluido (hasta 5 s por reintento en la ruta que activa `AWS_NEW_RETRIES_2026`); con un tercer intento se iba a 37 s y se salía de la gracia. Un test le pregunta esas constantes a botocore, así que una actualización que las mueva falla

### Fixed
- **Un event loop que muere ya no deja una sesión muda para siempre** (#62). Si el loop pasado por `loop=` se paraba sin que nadie llamara a `shutdown_hooks()` —una recarga de uvicorn, un lifespan que cierra en otro orden—, el trabajo que viajaba en él quedaba `PENDING`: su callback no corría nunca, su hueco del límite no se devolvía y su `order_key` quedaba ocupado, con lo que **toda** notificación posterior de esa sesión se retenía y se descartaba. Ahora se desaloja lo que quedó atrapado, se cuenta como cancelado y se registra —como error si era `GUARANTEED`

- **Un `fork()` ya no deja mudo al proceso hijo** (#62). El hijo hereda el objeto entero pero solo el hilo que forkeó: el loop de reserva del padre sobrevive como objeto y sigue diciendo `is_running()`, así que un hijo que se lo creyera aceptaba cada notificación y no entregaba ninguna. Un servidor prefork (gunicorn con `--preload`) que notificara antes de forkear es exactamente ese caso. El dispatcher global se registra con `os.register_at_fork()` y el hijo empieza con loop, locks y contadores propios; el trabajo en vuelo del padre se olvida, porque es del padre y allí sigue

### Notes
- **`completed` cuenta corrutinas que terminan, no notificaciones que AWS aceptó**: los tres hooks capturan su propio error de boto3 y lo registran, así que una notificación fallida vuelve como completada. `dispatched`, `dropped`, `cancelled`, `in_flight` y `queued` sí son de este módulo y dicen exactamente lo que parece
- **Política de overflow, por hook**: metadata descarta con WARNING y contador; feedback no descarta nunca. La asimetría la fijó el consumidor que los registra en producción: perder un refresco de UI lo corrige la siguiente escritura, perder un feedback pierde la queja
- **Por qué la cola de orden es FIFO y no «gana la última»**: el consumidor pidió que una actualización nueva sustituyera a la que esperaba, pero los hooks de metadata publican **el dict que les pasa el llamante**, que es un delta y no el estado completo. Descartar `{"progress": 50}` porque después llega `{"status": "done"}` perdería `progress` para siempre. Se entregan todas, en orden, y solo el desbordamiento de la cola descarta. El propio consumidor lo confirmó al comunicárselo: de los tres pushes en cascada de su ruta, solo el segundo lleva la dirección del cliente que su widget usa para el título del chat, y «gana la última» la habría descartado
- **`Delivery.GUARANTEED` no es un acuse de recibo**: significa que el límite no la descarta. Un proceso que muere, o un cierre que agota su presupuesto, la pierde igual — pero lo registra como error, no como aviso. Lo mismo vale si desborda la cola de su clave de orden: el orden manda sobre la garantía, y el descarte queda registrado
- **MongoDB/DocumentDB: no aplicable**, por decisión explícita. Nada de esto persiste trabajo; la única alternativa que habría tocado la base de datos —un outbox— se descarta por desproporcionada para 0-3 notificaciones por turno
- Evidencia, alternativas descartadas y criterios de aceptación en [`artifacts/issue-62-hook-lifecycle.md`](artifacts/issue-62-hook-lifecycle.md)

## [2026-09-17] PR #97 - Fix: dispatch_async() deja de decidir por el thread llamante (#95) (@iguinea)

- Fix: dispatch_async() deja de decidir por el thread llamante (#95)
- Docs: precisar el alcance del bug de hooks de 0.10.1 (#95)

## [0.17.3] - 2026-09-17

### Fixed
- **`dispatch_async()` ya no decide por el thread que lo llama** (#95). Ramificaba según si había un loop corriendo *en el thread llamante*: desde el loop creaba una task; desde un thread sin loop arrancaba un **thread daemon con su propio event loop por cada evento** de metadata o feedback. El llamante no elegía, heredaba el thread en el que estuviese — y el patrón que recomienda #61 (envolver el camino síncrono en `run_in_threadpool`) activa precisamente esa rama. Ahora el hook lleva su loop y la corrutina se le entrega con `asyncio.run_coroutine_threadsafe()`: ni threads sin límite ni un event loop por evento
- **El fallo de una notificación deja rastro**. Ni la task ni el thread devolvían nada de lo que recoger el error, así que el modo de fallo era una ausencia: el feedback en MongoDB sin su notificación y nada en los logs. El despacho registra ahora el resultado del trabajo terminado (`Error <contexto>: <excepción>` con traza, `Cancelled while <contexto>` si se cancela) y devuelve un handle —`Future` o `Task`— para quien quiera el resultado. Es la base de reintentos y métricas, que siguen siendo de #62

### Added
- **`loop=` en las tres factories de hooks**: `create_feedback_sns_hook()`, `create_metadata_sqs_hook()` y `create_metadata_websocket_hook()`. Sin pasarlo, **capturan el loop que esté corriendo al construirse**, así que crear el hook dentro del lifespan async de FastAPI basta para que la notificación siga viajando por el loop del servidor aunque la escritura ocurra en un worker thread. Sin loop que capturar, el comportamiento es el de siempre: task en el loop del thread llamante, o thread daemon si no hay ninguno
- `capture_loop()` en `hooks/utils_async.py`, para que un hook propio pueda hacer lo mismo

### Notes
- **Precisión sobre el bug de 0.10.1** (la nota retroactiva de más abajo): la notificación expuesta es la que se despachaba **desde un contexto async**, la que iba por `loop.create_task(coro)` sin guardar el handle. La del thread daemon ejecuta `asyncio.run(coro)` hasta el final: malgasta un thread, pero no pierde el envío. Verificado por el equipo del CRM contra su v0.5.0 en producción, donde la ruta expuesta resultó ser la de los `update_metadata()` que hace la **aplicación** desde sus rutas `async def` —los que empujan el tipo de caso al frontend al arrancar la conversación—, no los que hace el agente con el tool
- **El escenario malo no necesitaba el patrón de #61**: `get_metadata_tool()` devuelve un tool **síncrono** (`manage_metadata`), y Strands ejecuta los tools síncronos con `asyncio.to_thread` (`strands/tools/decorator.py:633`). Así que cada `update_metadata` que hace el **agente** —no la aplicación— ya salía sin loop corriendo, y con un hook registrado eso era un thread daemon y un event loop por evento. Confirmado por el equipo del CRM sobre su servidor en producción, cuyas rutas son todas `async def`
- **Compatible hacia atrás**: la firma vieja `dispatch_async(coro, error_context)` sigue funcionando igual, y un hook construido en tiempo de import se comporta exactamente como antes. Quien quiera el arreglo mueve la construcción del hook al lifespan o pasa `loop=asyncio.get_running_loop()`
- El hook nunca fue quien bloqueaba el loop: su llamada boto3 ya va por `asyncio.to_thread`. Lo que bloquea es la escritura PyMongo, y el problema era solo *dónde se despachaba la corrutina*
- Lo que esta versión **no** resuelve: límites, backpressure, política de overflow y cierre limpio del trabajo en segundo plano. El trabajo despachado a un thread daemon sigue muriendo con el proceso; el que va al loop del servidor se drena con él. Sigue en #62
- Propuesta original del equipo de `genai-mrg-sap-mcp`, al analizar el impacto de #61 sobre su servidor

### Fixed (#61, fusionado en el PR #96 sin sección propia)
- **El camino síncrono ya no bloquea el event loop en FastAPI**. El ejemplo no streaming ejecuta el camino síncrono completo en el worker pool compartido —crear el manager, construir el agente (que es donde se restaura la sesión), invocarlo, leer las métricas en memoria y cerrar el manager—, porque envolver solo `agent(prompt)` dejaría las lecturas de restauración bloqueando el loop. Medido con `--execution-mode direct|thread`: a concurrencia 16 el lag p99 del loop baja de 101,2 a 4,6 ms en MongoDB local y de 5.509,6 a 5,7 ms en DocumentDB, donde el throughput se multiplica por 6,1, con los mismos 15,5 comandos por operación en ambos modos
- El repositorio sigue siendo síncrono: Strands registra `initialize`, `append_message` y `sync_agent` como callbacks síncronos. El streaming se mantiene directo hasta que exista un puente con backpressure y cancelación explícitas

## [2026-09-17] PR #96 - Fix: evitar que el camino síncrono bloquee el event loop en FastAPI (#61) (@iguinea)

- Fix: evitar que el camino síncrono bloquee el event loop en FastAPI (…

## [2026-09-17] PR #94 - Fix: la restauración drena el historial en un lote, no en cincuenta (#92) (@iguinea)

- Fix: la restauración drena el historial en un lote, no en cincuenta (…

## [0.17.2] - 2026-09-17

### Fixed
- **Restaurar un historial largo ya no cuesta una decena de round-trips** (#92). `list_messages()` negocia el lote del cursor (`_MESSAGE_BATCH_SIZE`), así que la página se agota dentro del propio `aggregate`. El lote por defecto es de 101 documentos y DocumentDB lo aplica a **todos**, no solo al primero: 5.000 mensajes salían en 49 `getMore` de 94 ms
- Medido con el harness de #60, antes → después, en la misma máquina y sesión. **Amazon DocumentDB 5.0 DEV**: 1.000 mensajes de 1.399 a **335 ms** (12,0 → **3,0** comandos), 5.000 de 5.649 a **525 ms** (52,0 → **3,0**). **MongoDB 8.2.7 local**: 1.000 de 16,24 a **11,13 ms** y 5.000 de 69,77 a **47,26 ms** (4,0 → **3,0** en ambos)

### Notes
- **No se acota el historial restaurado**, la otra palanca que planteaba la issue y que era condicional a que `batchSize` no bastara. Basta. Truncarlo sería un cambio de comportamiento —el modelo vería menos contexto del que pidió la aplicación— y con el `SlidingWindowConversationManager` por defecto el historial **ya está acotado**: sube `removed_message_count`, que `initialize()` pasa como `offset`. Medido con 40 turnos reales: 80 mensajes almacenados, 40 restaurados, 0 `getMore`
- El escenario de la issue es el peor caso, no el común: aparece cuando ese contador se queda en 0 (`NullConversationManager`, una ventana muy grande o una sesión sembrada), que es lo que monta el escenario `restore` del harness
- El lote debe ser **estrictamente** mayor que la página: uno del tamaño exacto devuelve la página con el cursor vivo, porque el servidor no sabe que ha terminado hasta que un lote sale corto
- El techo del diseño sigue siendo el documento de 16 MiB, y es de **escritura**: `create_message()` falla al llegar al límite. A 15,40 MiB la lectura sigue costando un solo `aggregate`
- Sin migración ni cambio de contrato: `batchSize` es un parámetro del cursor. Mismos mensajes, mismo orden, misma forma del documento
- Evidencia completa, barrido de `batchSize` y la alternativa con `$group` descartada, en `artifacts/issue-92-restore-batch-size.md`

## [2026-09-17] PR #93 - Fix: el benchmark ya no llama p99 al máximo de la muestra (#60) (@iguinea)

- Fix: el benchmark ya no llama p99 al máximo de la muestra (#60)

## [0.17.1] - 2026-09-17

### Fixed
- **El benchmark ya no presenta como p99 lo que es el máximo de la muestra** (#60). Los percentiles usan rango más cercano, cuyo p99 cae en la última muestra para cualquier `n < 100`, y el p95 para `n < 20`: con las 30 repeticiones por defecto, el «p99» era la peor observación. Ahora el harness marca esos valores con `*`, los publica en el JSON como `saturated` y explica en el resumen que hace falta `--repetitions 100` para un p99 con resolución
- `docs/architecture/performance.md` y `artifacts/issue-60-benchmark.md` etiquetan sus columnas p99 como «peor de N» en vez de como estimación de cola

### Notes
- Detectado al repetir cuatro veces `turn.tool` con 5.000 mensajes contra DocumentDB 5.0 DEV: su lag «p99» dio 1.767, 1.771, 2.836 y 5.754 ms mientras el p95 se mantuvo entre 1.634 y 1.984 ms. Las medidas eran correctas; la etiqueta prometía una cola que la muestra no resuelve
- No cambia ningún número ya publicado, solo cómo se nombran y se leen

## [2026-09-17] PR #91 - Add: benchmark reproducible para MongoDB y DocumentDB (#60) (@iguinea)

- Add: benchmark reproducible para MongoDB y DocumentDB (#60)
- Refactor: constantes de dominio y aserciones de coma flotante del ben…

## [0.17.0] - 2026-09-17

### Added
- **Benchmark reproducible para MongoDB y DocumentDB** (#60), en `benchmarks/`, ejecutable con `uv run python -m benchmarks`. Ejerce agentes Strands reales con un modelo guionizado y **sale con código 1 si un escenario no puede demostrar que hizo el trabajo** que midió: mensajes persistidos, métricas en el último mensaje (#66), comandos en la ventana, cero `createIndexes` y cero errores
- Matriz de escenarios `create`, `restore`, `turn.simple`, `turn.tool` y `turn.supervisor`, cruzada con historiales de 10, 100, 1.000 y 5.000 mensajes y concurrencia 1, 4 y 16. Por celda: latencia min/p50/p95/p99/max, comandos por nombre y por operación, bytes, espera del pool, lag del event loop y errores
- Tres pases por celda: calentamiento (reportado aparte), latencia (sin serializar nada) y volumen (pesa bytes y descarta sus tiempos, porque recodificar la respuesta dentro del callback del driver falsearía los escenarios grandes)
- Guardarraíles antes de conectar: por encima de 20.000 mensajes sintéticos o concurrencia 8 el run se rechaza sin `--allow-large`, y `--dry-run` imprime la matriz con la base de datos apagada
- Los datos sintéticos se borran por `_id` exacto en un `finally` y en un manejador de SIGINT/SIGTERM, y el recuento de sobrantes viaja en el JSON de resultados. Nunca se elimina una base ni una colección
- `--compare base.json head.json` empareja escenarios por su clave y **se niega a calcular deltas** cuando motor, versión, topología, preferencia de lectura o compresores difieren; en ese caso muestra ambas columnas

### Changed
- `docs/architecture/performance.md` sustituye sus cifras de laboratorio por medidas del harness. Las anteriores procedían de `examples/example_performance.py`, cuyo bucle de operaciones era un `pass`

### Removed
- `examples/example_performance.py`. Sus referencias en README, docs y guías apuntan ahora a `benchmarks/`

### Notes
- Medido en MongoDB 8.2.7 local y en Amazon DocumentDB 5.0 DEV por túnel SSH; evidencia completa en `artifacts/issue-60-benchmark.md` y ficheros de resultados en `artifacts/bench-*.json`
- **Hallazgo para #56**: restaurar 5.000 mensajes cuesta 1 `getMore` y 31 ms en MongoDB local, y **49 `getMore` y 5,04 s en DocumentDB**, transfiriendo los mismos 3,77 MB. La diferencia es el tamaño de lote del cursor, no el volumen
- **Hallazgo para #59**: `_ensure_indexes()` tiene una carrera check-then-act; 16 repositorios creados a la vez sobre un cliente frío envían 64 `createIndexes` en lugar de 4
- La espera de checkout del pool es 0 ms por construcción con un único event loop y un driver síncrono: la sonda se mantiene porque sí mide cuando varios workers comparten cliente

## [2026-09-16] PR #90 - Mover paginación, búsqueda y conteo al servidor (@iguinea)

- Optimize server-side message reads (#58)

## [2026-09-16] PR #89 - Update: reducir lecturas completas al restaurar sesiones (#57) (@iguinea)

- Update: reducir lecturas completas al restaurar sesiones (#57)
- Docs: CHANGELOG y versión 0.16.0 (#57)

## [0.16.0] - 2026-09-16

### Changed
- **Restaurar una sesión ya no transfiere dos veces el historial completo** (#57). `read_session()` proyecta únicamente la cabecera de la sesión y `read_agent()` únicamente `agents.<agent_id>.agent_data`; los mensajes siguen llegando por `list_messages()`, que conserva la paginación y el orden por `created_at`
- La restauración de referencia con 5.000 mensajes baja de **64,24 ms / 13.570 KiB** a **23,96 ms / 4.523 KiB** en MongoDB 8.2.7 local. Los tests de integración inspeccionan los comandos reales enviados al servidor para fijar ambas proyecciones
- `model` y `system_prompt` permanecen dentro de `agent_data`, así que la caché de configuración de Strands conserva su comportamiento

### Notes
- **Sin cambios de esquema ni migración**. La forma pública de las sesiones y agentes restaurados no cambia, y managers 0.15 y 0.16 pueden convivir sobre la misma colección
- Se descartó aplicar `$slice` a `list_messages()`: el repositorio ordena por `created_at` antes de aplicar `offset`, mientras que `$slice` opera sobre el orden físico del array y cambiaría el contrato
- Las proyecciones usan sintaxis compatible con Amazon DocumentDB, pero la latencia y la consistencia sobre réplicas deben validarse en un clúster DocumentDB; las pruebas de esta versión se ejecutaron contra MongoDB 8.2.7

## [2026-09-16] PR #88 - Fix: métricas de la invocación una sola vez, en su último mensaje (#66) (@iguinea)

- Fix: métricas de la invocación una sola vez, en su último mensaje (#66)
- Docs: CHANGELOG y versión 0.15.0 (#66)

## [0.15.0] - 2026-09-16

### Changed
- **Las métricas de una invocación se escriben una sola vez, en su último mensaje** (#66). Strands dispara `MessageAddedEvent` *antes* de acumular el uso y las métricas de la llamada al modelo que produjo el mensaje (`event_loop.py:409-414` en strands 1.30, `:699-703` en 1.56), así que el sync que lanza tras cada mensaje veía las del ciclo anterior. Ahora ese sync no escribe métricas. Las escriben el sync de cierre (`AfterInvocationEvent`) y cualquier llamada explícita a `sync_agent()`. Turno de referencia (supervisor, sub-agente y una tool) contra MongoDB: **10 → 8 updates**. Un agente que llama a N herramientas pasa de 2N+1 escrituras de métricas a 1. En DocumentDB cada una cuesta 40-55 ms
- **Contrato de `event_loop_metrics`**: lo lleva el último mensaje de cada invocación que llega a cerrar. Los mensajes intermedios (`toolUse`, `toolResult`) no lo llevan. Los valores se acumulan durante toda la vida del objeto `Agent`: con la factoría, un `Agent` por petición, son los de esa invocación, y su suma es el total de la sesión
- `register_hooks()` pasa a Strands un registry envuelto (`mongodb_session_manager.sync_origin.MessageAddedTagging`). Los callbacks de `MessageAddedEvent` corren con una etiqueta `ContextVar` y todo lo demás llega al registry sin cambios. Una subclase que sobrescriba `register_hooks()` debe llamar a `super()`

### Fixed
- **Los mensajes intermedios guardaban métricas de un ciclo anterior**. Con una tool, el `toolResult` se llevaba las del primer ciclo, y el mensaje final recibía unas obsoletas que el cierre pisaba un instante después. Con tres tools, el `assistant(tool_use)` del segundo ciclo guardaba `cycle_count=2` junto a los tokens del primero
- **El prompt de un agente reutilizado heredaba las métricas de la invocación anterior**. Con un mismo `Agent` en dos invocaciones, el acumulado ya no vale 0 cuando llega el segundo prompt, y el sync de ese mensaje lo escribía

### Notes
- **Un `sync_agent()` explícito sigue escribiendo las métricas del momento**, desde cualquier hilo. Así una aplicación puede añadirles un valor después de la invocación, como hace OV con el TTFT, y sincronizar
- **Se descartó escribir las métricas solo en `AfterInvocationEvent`** porque rompía justo ese flujo: el TTFT se quedaba en 0. También se descartó una primera versión con una marca por `agent_id`. La revisión adversarial (Codex + OpenCode/GLM 5.3) demostró que se quedaba puesta cuando `create_message` se aplicaba y después lanzaba, y que un sync explícito desde otro hilo la consumía. Detalle en `features/8_invocation_metrics_on_last_message/plan.md`
- **Lo que no arregla**:
  - Una invocación que no llega a su sync de cierre queda sin métricas. Pasa si un hook de usuario lanza en `AfterInvocationEvent` antes que el manager, o si el conversation manager lanza en `apply_management()`, que Strands ejecuta antes del evento. Antes quedaba el snapshot de un ciclo anterior, que tampoco era el total
  - Sin latencia medida sigue sin haber métricas: por ejemplo, un stream cancelado antes de que llegue la metadata del modelo
  - Con strands 1.56, un hook de prioridad `SDK_LAST` que añada un mensaje después del cierre lo deja sin métricas. Se sigue en #69
- **Consumidores**:
  - Control Center: las stats, que leen el último mensaje, y el total del detalle de sesión no cambian. El timeline y la API externa (`timeline[].metrics`) solo mostrarán métricas en el último mensaje de cada invocación
  - OV: `scripts/latencia_tools_dump.py` separa invocaciones cuando baja `latencyMs`. Con datos 0.15 cada punto ya es una invocación
- **Sin cambios de esquema ni migración**, y sin operadores nuevos para DocumentDB: son las mismas escrituras, menos. Los documentos anteriores conservan sus métricas intermedias. Managers 0.14 y 0.15 conviven en la misma colección

## [2026-09-16] PR #87 - Update: no reescribir un agente que no ha cambiado (#67) (@iguinea)

- Update: no reescribir un agente que no ha cambiado (#67)
- Docs: CHANGELOG y versión 0.14.0 (#67)

## [0.14.0] - 2026-09-16

### Changed
- **Un agente que no ha cambiado ya no se reescribe** (#67). Strands llama a `update_agent()` en el primer sync de cada manager, porque aún no tiene versiones con las que comparar, y tras cada tool, porque `_interrupt_state.deactivate()` sube la versión aunque no hubiera ninguna interrupción. En los dos casos el agente trae exactamente lo que ya está guardado. Ahora `update_agent()` compara el `SessionAgent` recibido, sin contar `created_at` ni `updated_at`, con lo que el repositorio leyó, creó o escribió por última vez, y si es idéntico no hace el round-trip. Turno de referencia (supervisor, sub-agente y una tool) contra MongoDB: **13 → 10 updates**. En DocumentDB cada uno cuesta 40-55 ms
- La regla vive en `mongodb_session_manager.agent_content` (`LastPersistedAgents`), y el repositorio de MongoDB y el doble in-memory la aplican en los mismos puntos. El contrato compartido lo comprueba contra las dos implementaciones
- **Contrato público de `update_agent()`**: con contenido idéntico no toca el documento, no refresca ningún `updated_at` y no lanza «Session not found». Con contenido distinto se comporta como antes
- **`agent_data.created_at` y `agent_data.updated_at` solo avanzan cuando cambia el estado del agente**. Antes Strands los regeneraba en cada sync, así que significaban «último sync». `agents.<id>.updated_at` y el `updated_at` raíz siguen avanzando con cada mensaje, y el Session Viewer lee esos

### Fixed
- **Una petición que no cambiaba el agente pisaba lo que otra acababa de guardar**. Cada manager reescribía en su primer sync y tras cada tool el estado que había restaurado, y deshacía en silencio el cambio concurrente de otro manager sobre el mismo agente. Ahora un manager solo escribe cuando su agente ha cambiado. La ventana no se cierra del todo: si los dos lo cambian, gana el último, como antes

### Notes
- **Se compara contenido, no versiones, así que no se pierde ningún cambio**: se persiste con `agent.state.set()`, con un hook que reasigna `agent.state` entero y con un conversation manager que migra su estado al restaurar. Los campos que añada una versión nueva de Strands se comparan igual
- **Se descartó la propuesta original de la issue**, sembrar `_last_synced_internal_state` de Strands en `initialize()`. La revisión adversarial demostró que perdía justo esos dos casos, porque un `AgentState` nuevo nace en la misma versión, y que no ahorraba nada desde strands 1.34.0, que añade `model_state` a esa contabilidad. Detalle en `features/7_skip_unchanged_agent_writes/plan.md`
- **Lo que no ve**: una escritura que no pasa por este repositorio (otro proceso, o `update_agent_fields()` sobre un campo del SDK). Un agente sin cambios no la sobrescribe
- Una escritura que lanza o no casa con ninguna sesión no se da por guardada, y el siguiente sync la reintenta. El repositorio solo recuerda los agentes de la última sesión tocada: la factoría crea uno por manager, y uno reutilizado entre sesiones no acumula estado
- `sync_bidi_agent()` también pasa por `update_agent()`, así que tampoco reescribe un agente bidi sin cambios
- **Sin cambios de esquema ni migración**, y sin operadores nuevos para DocumentDB. Managers 0.13 y 0.14 conviven sobre la misma colección

## [2026-09-16] PR #86 - Fix: validar los nombres que acaban en rutas dot-notation (#79) (@iguinea)

- Fix: validar los nombres que acaban en rutas dot-notation (#79)
- Refactor: nombrar una vez el operador $push (qlty S1192)

## [0.13.0] - 2026-09-16

### Fixed
- **Un `agent_id` con punto borraba el historial del agente en cada petición** (#79). El repositorio guarda cada agente en `agents.<agent_id>` y llega a él con dot notation, así que MongoDB leía `a.b` como la ruta anidada `agents.a.b`: `create_agent()` escribía ahí, pero `read_agent()` buscaba la clave literal y no la encontraba. Strands creaba el agente de nuevo en cada petición y el `$set` reemplazaba sus mensajes por un array vacío. Verificado contra MongoDB 8.2.7 con un manager real: tres peticiones restauraban 0, 0 y 0 mensajes. Ahora el `Agent` falla al construirse con un `ValueError` que explica el motivo
- **Otros nombres que MongoDB lee como sintaxis fallaban con errores opacos o hacían algo inesperado**: un `agent_id` que empieza por `$` se podía escribir pero no leer; uno vacío o con NUL fallaba con errores del servidor o de BSON; la clave de metadata `tags.$[]` reescribía todos los elementos de un array existente (y `delete_metadata()` los ponía a `null`)
- **Un `metadata_fields` inválido dejaba índices sin crear en silencio**: MongoDB rechaza indexar `metadata.$where`, el error se absorbía y se llevaba por delante los índices posteriores, incluido el de `application_name`. Ahora es un error de configuración al construir el repositorio o la factoría

### Changed
- **Breaking: las claves de metadata con un segmento que empieza por `$`** (`$where`, `x.$y`) ya no se aceptan. Antes se guardaban como campo literal, que no se puede indexar
- Una sola regla para todo nombre que acaba en una ruta (`mongodb_session_manager.field_names`): un segmento no está vacío, no empieza por `$` y no contiene NUL; un `agent_id` es un único segmento, así que tampoco lleva `.`. Las claves de metadata, `metadata_fields` y las claves relativas de `update_message_fields()`/`update_agent_fields()` son rutas: `user.name` y `tags.0` siguen funcionando
- `_agent_path()` es el único sitio que construye `agents.<agent_id>`, y `_prefixed()` el único que une claves externas a una ruta, así que la validación va por construcción. Un lote con una clave inválida no escribe nada
- `initialize()` e `initialize_bidi_agent()` validan el `agent_id` antes de llamar a Strands, que registra el id antes de tocar el repositorio: un reintento con el mismo manager da el mismo `ValueError`, no un `SessionException` engañoso
- Los wrappers de `metadata_hook` validan las claves antes de invocar el hook, para que un hook propio no publique una clave que el repositorio va a rechazar

### Notes
- **Los documentos no cambian** y no hay que migrar nada: con nombres válidos se envían exactamente las mismas operaciones, y managers 0.12 y 0.13 conviven sobre la misma colección
- **Un `$` que no inicia el nombre es un dato normal**: `a$b` funciona en todas las operaciones y se sigue aceptando
- **Lo que no arregla**: los documentos que un `agent_id` con punto ya dejó anidados no se limpian; las claves `$…` ya almacenadas siguen ahí y `get_metadata()` las devuelve, pero borrarlas requiere `repo.collection`; los límites del servidor que no son de sintaxis (rutas en conflicto en un mismo lote, más de 100 niveles) siguen llegando como error de MongoDB
- El doble in-memory rechaza lo mismo en el mismo punto, y el contrato lo comprueba contra las dos implementaciones. Queda una divergencia documentada: `tags.0` sobre un array existente
- El presupuesto de escrituras por turno no se mueve

## [2026-09-16] PR #85 - Fix: identidad estable de mensaje para los updates posicionales (#78) (@iguinea)

- Fix: identidad estable de mensaje para los updates posicionales (#78)

## [0.12.0] - 2026-09-16

### Fixed
- **La redacción de Guardrails podía caer en el mensaje equivocado** (#78). `message_id` no identifica un mensaje: Strands lo deriva en memoria (`latest.message_id + 1`) y cada manager restaura su contador desde el último mensaje almacenado, así que dos managers que restauran el mismo agente a la vez calculan el mismo índice y `create_message()` hace `$push` de dos mensajes numerados igual. A partir de ahí el operador posicional `$` actualiza **solo el primero que casa**. Verificado contra MongoDB 8.2.7 con dos managers concurrentes: la redacción del segundo aterrizaba en el mensaje del primero, *y además lo sobrescribía con el contenido del segundo* — se redactaba contenido inocente, se perdía el original y el contenido bloqueado quedaba visible. Lo mismo afectaba al `guardrail_event` de auditoría y a las métricas del turno
- **El evento de auditoría nombraba «el último mensaje», no el que se acababa de redactar**: `redact_latest_message()` volvía a preguntar por el último mensaje después de que la clase padre hubiera redactado. Ahora toma la referencia del mismísimo `SessionMessage` que se redactó, así que el vínculo es cierto por construcción y no por coincidencia

### Added
- **`storage_id`: identidad estable de mensaje**. Un uuid4 que `create_message()` acuña una vez, nunca derivado de nada y nunca reescrito. El mismo valor se adjunta al `SessionMessage` —Strands conserva esa instancia durante todo el turno: la añade, la guarda en `_latest_agent_message` y la devuelve para la redacción—, de modo que cada escritura nombra el mensaje que *este* proceso añadió. `read_message()` y `list_messages()` también lo traen, para un manager restaurado
- **`MessageRef`** (`mongodb_session_manager.MessageRef`): el value object que apunta a un mensaje almacenado. Su método `locator()` contiene la regla entera —identidad si la hay, índice si no—, y tanto el repositorio de MongoDB como el doble in-memory preguntan ahí en vez de decidir cada uno por su cuenta
- El evento de guardarraíl de nivel sesión lleva ahora `storage_id` junto a `message_id`: el índice solo no basta para que un auditor sepa qué mensaje se interceptó

### Changed
- **Breaking: `get_last_message_id()` pasa a ser `get_last_message_ref()`** y devuelve un `MessageRef | None` en lugar de un `int | None`. El `storage_id` viaja con él, así que una escritura construida desde ahí nombra un mensaje y no una posición
- **Breaking: `update_message_fields()` y `record_guardrail_event()`** reciben un `MessageRef` donde antes recibían un `message_id: int`
- El `ValueError` de `update_message()` dice ahora por cuál de los dos campos se buscó (`searched by storage_id=…`). Con un índice duplicado, «mensaje 7 no encontrado» era falso: el 7 estaba ahí; lo que faltaba era la identidad

### Notes
- **No hace falta migrar nada**. Los mensajes almacenados antes de esta versión no tienen `storage_id` y se siguen localizando por `message_id`, exactamente como siempre; la exposición a #78 se extingue por sí sola en cada conversación según sus agentes añaden mensajes nuevos
- **Sigue siendo posible que dos managers generen el mismo `message_id`**: esta versión hace que cada uno escriba sobre su propio mensaje, no impide que el historial acabe con dos mensajes numerados igual. Impedirlo es un problema distinto y queda fuera
- El presupuesto de escrituras por turno no se mueve: mismas 12 lecturas y 8 escrituras que antes, misma proyección `$slice: -1`, mismo `update_one` único para el guardarraíl. El coste del campo es de 49 bytes BSON por mensaje
- `attach_storage_id()` depende de que el `SessionMessage` de Strands acepte un atributo fuera de sus campos. Es un contrato con una SDK ajena, así que está fijado en `tests/unit/test_message_identity.py`: una actualización que lo rompa falla ahí, en vez de desactivar el arreglo en silencio

## [2026-09-16] PR #82 - Refactor: el manager deja de saltarse la interfaz del repositorio (#80) (@iguinea)

- Refactor: primitivo unico de escritura posicional en el repositorio (…
- Add: operaciones de dominio en el repositorio (#80)
- Test: repositorio in-memory y contrato compartido (#80)
- Refactor: el manager habla con el repositorio, no con la coleccion (#80)
- Docs: documentar la interfaz del repositorio y el doble in-memory (#80)
- Refactor: aplicar el gate de simplificacion (#80)
- Fix: cerrar los hallazgos del gate de revision (#80)
- Chore: ajustar el gate de calidad a los ficheros de soporte de tests …

## [0.11.0] - 2026-09-16

### Added
- **El repositorio expone las operaciones que el session manager necesita de verdad**: `update_message_fields()` y `update_agent_fields()` para escribir, más `record_guardrail_event()`, `get_agent_config()`, `list_agent_configs()`, `count_messages()` y `get_last_message_id()`. Las claves que reciben son relativas al mensaje o al agente: quien conoce las rutas de MongoDB es el repositorio
- **`MongoDBSessionManager` acepta `session_repository`**: sirve para sentar un doble en lugar del repositorio de MongoDB, que es lo que hace testeable el manager sin base de datos. **No es un punto de extensión declarado**: el contrato esperado no se publica como `Protocol`, solo existe como casos ejecutables en `tests/support/repository_contract.py`, así que sustituir el almacén es posible pero no está soportado
- **`pop_read_agent_config()` pasa de privado a público** (antes `_pop_read_agent_config()`). El manager lo llama desde `initialize()`, así que era interfaz con nombre de método privado: un repositorio alternativo fallaba con `AttributeError` en la primera petición. Al ser público entra además en la guardia estructural que compara la superficie del doble con la del repositorio real

### Changed
- **El session manager ya no accede a `session_repository.collection`**: lo hacía en ocho métodos, construyendo a mano filtros con dot notation, operadores `$set`/`$push` y leyendo `matched_count`. Contradecía la regla de persistencia del proyecto y el propio diagrama de arquitectura, que nunca dibujó esa arista. Hoy `grep -rn "session_repository.collection" src/` no devuelve nada
- **El mecanismo de escritura posicional deja de estar triplicado**: `update_message()`, las métricas del turno y el evento de guardarraíl construían por separado el mismo filtro `{"_id", "agents.<id>.messages.message_id"}` y el mismo prefijo `agents.<id>.messages.$.`. Ahora viven en un único método privado del repositorio, lo que convierte la identidad de mensaje de #78 en un cambio local en vez de una caza por tres ficheros
- **La regla de que el `GuardrailTrace` completo no viaja al array de sesión** estaba duplicada en el manager, que construía los dos eventos a mano. Ahora el repositorio deriva el evento de sesión a partir del de mensaje

### Notes
- **Sin cambios de comportamiento**: ninguna firma pública cambia y `repo.collection` sigue siendo público y soportado para consultas ad hoc. Los diez tests de `update_message()` pasan sin editar ni uno, que era precisamente el criterio de que el refactor es estructural
- El presupuesto de escrituras por turno no se mueve: `sync_agent()` sigue costando una sola escritura, con la configuración del agente viajando de polizón en la de métricas cuando las hay, y sola cuando no
- Nuevo doble in-memory en `tests/support/`, con 21 casos de contrato que se ejecutan dos veces —contra el doble y contra MongoDB real— para que ambas implementaciones no puedan divergir en silencio
- Tres de esos casos salieron del gate de revisión, y los tres fijan sitios donde el doble era **más amable** que MongoDB: escribir sobre un agente desconocido crea un agente a medias sin array de mensajes (y todo lector debe tolerarlo), `delete_metadata()` trata las claves con puntos como rutas y no como claves planas, y `pop_read_agent_config()` entrega la configuración una sola vez. Un doble que miente no sirve de red
- Si alguna vez llegan métricas sin `message_id`, `sync_agent()` las descarta —no hay dónde escribirlas— pero ahora lo dice con un `logger.error` que las nombra, en lugar de reportar un fallo de filtro que nunca se intentó

## [2026-09-16] PR #81 - Fix: update_message() localiza el mensaje por message_id y deja de borrar campos (#64) (@iguinea)

- Fix: update_message() localiza el mensaje por message_id y deja de bo…

## [0.10.2] - 2026-09-16

### Fixed
- **`update_message()` borraba los campos de extensión del mensaje**: escribía `agents.<id>.messages.<índice>` con el `SessionMessage` entero, y un `$set` sobre la ruta de un subdocumento lo *reemplaza*. Se llevaba por delante `event_loop_metrics`, `guardrail_event` y los contadores legados, que el session manager guarda ahí pero `SessionMessage` no puede transportar. Ahora se escribe un allowlist explícito (`message`, `redact_message`, `updated_at`), cada campo en su propia ruta
- **Cada redacción costaba una lectura del historial completo del agente**: el índice del mensaje se calculaba en el cliente. Ahora se localiza en el servidor por `message_id` con el operador posicional `$`: una escritura, cero lecturas, y el selector deja de depender de que nadie reordene el array
- **`list_messages()` podía dejar un agente permanentemente sin listar**: ordenaba con `x.get("created_at", "")`, así que un mensaje sin ese campo —escrito fuera de `create_message()`— hacía comparar `str` con `datetime` y lanzaba `TypeError`. Hasta ahora lo reparaba de rebote que cada redacción reescribiese `created_at`; al dejar de reescribirlo, nada lo repararía. Los mensajes sin timestamp se ordenan ahora al final como grupo, sin compararse nunca contra un `datetime`

### Changed
- `created_at` ya no se reescribe: un `$set` que no lo nombra lo deja intacto, con su valor y su tipo. Como efecto colateral, un documento legado **sin** `created_at` ya no se rellena de rebote al redactar — crear mensajes sin ese campo no está soportado
- `update_message()` conserva los tres diagnósticos de error (sesión, agente o mensaje ausente). El filtro compuesto no los distingue por sí solo, así que cuando no casa —y solo entonces— se paga una lectura para decir cuál falta: reportar «mensaje no encontrado» con un agente inexistente sería engañoso. El camino feliz sigue siendo una sola escritura y ninguna lectura

### Notes
- Esto **no** hace `update_message()` inmune a la concurrencia. `message_id` no es una clave única —Strands lo deriva en memoria—, así que un id duplicado casa solo con su primera aparición (#78). La condición de carrera que describía #64 no era reproducible con las operaciones actuales del repositorio: el único operador sobre el array es un `$push` al final, que no desplaza los índices ya leídos
- El `guardrail_event` de la propia redacción ya sobrevivía antes de este cambio, porque `_record_guardrail_event()` corre *después* de `redact_latest_message()`. Lo que se recupera es un evento *anterior* del mismo mensaje y las métricas acumuladas del turno

## [2026-09-16] PR #77 - Chore: subir pymongo, uvicorn, pytest-cov, pydantic-settings y strands-agents-tools (@iguinea)

- Chore: subir pymongo, uvicorn, pytest-cov, pydantic-settings y las tools

## [2026-09-16] PR #70 - Chore: aplicar los PRs de dependabot y arreglar los permisos del CI (@iguinea)

- Fix: conceder security-events al job security del CI
- Chore: subir boto3, uvloop, pytest-mock y pytest-asyncio
- Chore: dependabot pasa del ecosistema pip al de uv
- Fix: fijar setup-uv a v10.1.0 (no publica alias de major)

## [2026-09-16] PR #68 - Fix: no borrar la configuración del agente e hidratar su caché desde read_agent() (#65) (@iguinea)

- Docs: plan para hidratar la caché de configuración del agente (#65)
- Fix: update_agent ya no borra la configuración del agente (#65)
- Update: hidratar la caché de configuración del agente desde read_agen…
- Docs: documentar la hidratación y el arreglo de update_agent (#65)
- Refactor: simplificar el traspaso de configuración y sus tests (#65)
- Chore: versión 0.10.1 (#65)

## [0.10.1] - 2026-09-16

### Fixed
- **`update_agent()` wiped the agent config**: it wrote `agents.<id>.agent_data` as a whole document, and a `$set` on a subdocument path *replaces* it — dropping the `model`, `system_prompt` and `prompt_metadata` that the session manager stores there (`SessionAgent` cannot carry them). Each `SessionAgent` field is now written on its own dotted path, so the manager-owned fields survive. Same single `update_one`, no extra reads
- **The reference turn ended with no config at rest**: Strands re-syncs an agent after every tool execution (`_interrupt_state.deactivate()` bumps its internal-state version) and, since 0.10.0, the config cache no longer rewrote the config on that second sync — so any agent that ran a tool finished the turn with `model` and `system_prompt` at `None`. v0.10.0 was never tagged nor published, so no release ever shipped this
- **`prompt_metadata` survives the next request**: the same whole-subdocument write dropped it on the first sync of each request (this one predates 0.10.0)
- **Hook notifications could be lost silently** *(documented retroactively in 0.17.3; the fix shipped here)*: `dispatch_async()` called `loop.create_task(coro)` without keeping the result, and an event loop holds only weak references to its tasks. Since `on_feedback_add()` and `on_metadata_change()` do suspend — both `await asyncio.to_thread(...)` around their boto3 call — the garbage collector could reclaim the task mid-flight. The observable symptom was not an error but an absence: feedbacks and metadata changes persisted in MongoDB with no matching SNS, SQS or WebSocket notification, and nothing in the logs. Strong references are now held in a set each task removes itself from on completion. **Any deployment pinned below 0.10.1 that registers a hook is exposed** — the notification dispatched from an async context, that is; see the precision in 0.17.3. It landed in commit `7a27703` under a lint cleanup (ruff `RUF006`, `asyncio-dangling-task`) and was never listed as a fix, so it could not be found by reading these release notes

### Changed
- **Two fewer writes per turn**: `read_agent()` already fetches `model` and `system_prompt`, so `initialize()` now seeds the agent config cache with what is persisted and the first sync of each request stops rewriting an unchanged system prompt — the largest write of the turn (~14 KB per agent). The reference turn (supervisor + sub-agent, one tool call) goes from 15 to 13 `update` commands and from ~33.7 KB to ~5.9 KB of update payload; 21 → 19 total operations
- **Corrected the documented write breakdown** of the reference turn: measured with a pymongo `CommandListener` it is 6 `$push` + 3 `update_agent` + 4 metrics writes, not the 6 + 8 + 1 documented in 0.10.0

### Notes
- No public API or document schema changes: `_pop_read_agent_config()` is the internal channel between repository and manager, like `_agent_exists()`
- Any narrower `read_agent()` projection (#57) must keep `agent_data.model` and `agent_data.system_prompt`; an integration assert fails loudly if the config starts travelling again

## [2026-09-15] PR #55 - Fix: reducir escrituras por turno (42→21 ops) y corregir read-after-write sobre secundarios (#54) (@iguinea)

- Docs: plan de reduccion de escrituras por turno (#54)
- Fix: reducir escrituras por turno y corregir read-after-write (#54)
- Test: explicar los metodos vacios del CommandListener (#54)
- Chore: arreglar el CI, fijar el ruleset de ruff y limpiar el lint (#54)
- Fix: versionar uv.lock para que el CI sea reproducible (#54)
- Docs: versionar el informe de rendimiento y enlazar el seguimiento (#54)

## [0.10.0] - 2026-09-15

### Changed
- **Half the MongoDB operations per turn**: a turn with a supervisor and a sub-agent went from 42 operations to 21 (21→15 updates, 13→6 finds, 8→0 `createIndexes`). On DocumentDB every write costs 40-55 ms regardless of its size, so this is about the *number* of round-trips, not the bytes
- **Indexes are ensured once per client, not per session manager**: `_ensure_indexes()` ran on every `create_session_manager()`, and pymongo does not cache `create_index` — each call was a round-trip even when the index already existed. Now tracked in a `WeakKeyDictionary` keyed by `MongoClient`, so two clients against different clusters that share database and collection names each get their indexes
- **Agent config is only written when it changes**: `_capture_agent_config()` rewrote the entire system prompt on every `sync_agent()`. Cached per `agent_id`, since one manager can serve several agents in a session
- **Metrics and agent config travel in a single `update_one`**: both target the same document and used to be two separate writes

### Fixed
- **Metrics could be attributed to the wrong message** (silently): `_get_last_message_id()` queried the database milliseconds after `create_message()` pushed the message. On a `secondaryPreferred` cluster a lagging replica returned the previous `message_id`, so the metrics landed on message N-1 — or the filter matched nothing and the update was a no-op, unnoticed because `matched_count` was never checked. The value is now read from `_latest_agent_message`, which the parent class already tracks in memory, with a fallback to the query for restored sessions
- **`update_agent()` could falsify an agent's `created_at`**: it read the timestamp back to rewrite it, another read-after-write. A stale read would replace the original with `now`. The field is now preserved by omission — a `$set` that does not name it leaves it alone
- Sync updates that match no document are now logged instead of disappearing

### Fixed (CI)
- **The `test` job never ran a single test**: it invoked `pytest test_*.py`, a path that stopped existing when tests moved to `tests/`. It failed with "file or directory not found" and, because `build` needed it, nothing was ever built either
- **The `lint` job never linted a single line**: `uv sync` does not install the `dev` group, so ruff was missing and the step died with "Failed to spawn: ruff". Now `uv sync --all-extras`, and ruff is an explicit dev dependency
- **Explicit `[tool.ruff]` ruleset**: there was none, so the lint depended on whatever defaults the installed ruff version happened to carry — a new version added rules and broke CI without anyone touching the code. The ruleset is now pinned in `pyproject.toml`, with every exclusion justified in place
- **`uv.lock` is versioned now**: it was in `.gitignore`, so CI resolved dependencies afresh on every run and was never reproducible. It installed `strands-agents` 1.55.1 while local development used 1.30.0 — the same commit produced different environments. CI now runs `uv sync --locked`, which also fails loudly if someone edits `pyproject.toml` without regenerating the lock
- Cleared the 345 accumulated lint errors and formatted the 36 unformatted files
- `runs-on` now reads from the `CI_RUNS_ON` repository variable, so switching between hosted and self-hosted runners no longer needs a PR
- The MongoDB service in CI waits for a healthcheck before the tests start
- `build` verifies that a wheel *and* an sdist were actually produced, instead of just listing the directory

### Fixed (also caught by the lint pass)
- `dispatch_async()` did not keep a reference to the task it created. The event loop only holds weak references, so a hook could be garbage collected mid-flight and never run
- `send_message()` and `publish_message()` lost the original exception when re-raising, making failures harder to trace
- `publish_message()` declared `message: str | dict = None`, an implicit Optional

### Notes
- No public API or document schema changes
- The root `updated_at` keeps being refreshed on the last write of every turn — two external consumers derive "End" and "Duration" from it. Now pinned by a regression test
- `claude-review` fails for a reason outside this repository: the `CLAUDE_CODE_OAUTH_TOKEN` secret has expired (`API Error: 401`). It needs to be regenerated; no code change fixes it
- Performance analysis of this release in `artifacts/analisis-rendimiento.md`; follow-up work is tracked in #56 (master issue), #64, #65 and #66

## [2026-03-23] PR #46 - Chore: release v0.9.1 (@iguinea)

- Chore: release v0.9.1 — temperature in prompt_metadata
- Merge: resolve CHANGELOG conflict with main

## [0.9.1] - 2026-03-23

### Added
- **Temperature in Prompt Metadata**: Optional `temperature` (float) field in `prompt_metadata` for experimenting with different temperatures on the same prompt version
- Type hint updated from `Dict[str, str]` to `Dict[str, Any]` for `prompt_metadata` parameter

## [2026-03-23] PR #45 - Update: add temperature field to prompt_metadata (@iguinea)

- Update: add temperature field to prompt_metadata
- Fix: use pytest.approx for float comparison in test
- Fix: add temperature to prompt_metadata in Agent Fields doc example

## [2026-03-22] PR #44 - Add: prompt metadata for agent config (v0.9.0) (@iguinea)

- Add: prompt metadata for agent config (v0.9.0)
- Merge: resolve CHANGELOG conflict with main

## [0.9.0] - 2026-03-22

### Added
- **Prompt Metadata**: New `set_prompt_metadata(agent_id, metadata)` method to store prompt lineage (prompt_id, prompt_name, prompt_version, deployment_id, deployment_name) per agent
- **Prompt Metadata in Config**: `get_agent_config()`, `update_agent_config()`, and `list_agents()` now include `prompt_metadata` field
- `prompt_metadata` added to `_AGENT_CONFIG_FIELDS` for proper filtering during SessionAgent reconstruction

## [2026-03-20] PR #43 - Chore: add Spec Kit slash commands (@iguinea)

- Chore: add Spec Kit slash commands

## [2026-03-20] PR #42 - Chore: add workflow guidelines, coding rules, MkDocs, Spec Kit and Agent Teams (@iguinea)

- Chore: add workflow guidelines, coding rules, MkDocs, Spec Kit and Ag…

## [2026-03-19] PR #41 - Chore: remove session_viewer application (@iguinea)

- Chore: remove session_viewer application

## [2026-03-19] PR #40 - Fix: integration test failures (v0.8.1) (@iguinea)

- Fix: integration test failures — MagicMock BSON encoding and teardown…

## [0.8.1] - 2026-03-19

### Fixed
- **Integration Tests**: Fix `bson.errors.InvalidDocument: cannot encode MagicMock` in `test_agent_config_roundtrip` and `test_list_agents` — mock agents now configure `state`, `_interrupt_state`, and `conversation_manager` with serializable values
- **Integration Tests**: Fix teardown `Cannot use MongoClient after close` errors — `cleanup_session` fixture now uses an independent MongoClient for cleanup instead of reusing the manager's closed client

## [2026-03-19] PR #39 - Fix: deadlock, docs audit, broken tests (v0.8.0) (@iguinea)

- Fix: deadlock in connection pool, docs audit, and broken test imports…

## [0.8.0] - 2026-03-19

### Fixed
- **Connection Pool**: Fix deadlock — `Lock` replaced with `RLock` to prevent deadlock when `initialize()` is called with `_instance=None` (lock acquired in `initialize()` then re-acquired in `__new__`)
- **Tests**: Fix broken imports — `_dispatch_async` moved to `utils_async` in v0.7.0 but test imports were not updated
- **Tests**: Fix connection pool fixture — reset `_user_kwargs`/`_resolved_kwargs` instead of non-existent `_client_kwargs`
- **Factory**: Fix inconsistent `collection_name` default in `initialize_global_factory()` — was `"virtualagent_sessions"`, now `"collection_name"` matching all other constructors

### Docs
- **pyproject.toml**: Fix TOML structure — `keywords` and `classifiers` were inside `[[project.authors]]` instead of `[project]`
- **pyproject.toml**: Remove invalid Python 3.11 classifier (requires `>=3.12.8`)
- **pyproject.toml**: Remove duplicate `[dependency-groups] dev` section (conflicting pytest versions)
- **CLAUDE.md**: Fix deprecated camelCase `metadataHook`/`feedbackHook` — replaced with `metadata_hook`/`feedback_hook`
- **CLAUDE.md**: Fix Python version `3.13+` → `3.12+` (matches `requires-python`)
- **README.md**: Fix incorrect `collection_name` default (`"agent_sessions"` → `"collection_name"`)
- **README.md**: Fix test count (`264` → `274`: 243 unit + 31 integration)
- **README.md**: Add missing methods to API table (`get_agent_config`, `update_agent_config`, `list_agents`, `get_message_count`, `get_session_viewer_password`)
- **README.md**: Add missing fields to MongoDB schema (`session_type`, `session_viewer_password`)
- **docs/README.md**: Complete executable examples table (added 5 missing examples)
- **docs/README.md**: Update last modified date
- **examples/README.md**: Remove reference to non-existent `example_stream_async.py`

### Added
- **pyrightconfig.json**: Pyright configuration for venv resolution (fixes `reportMissingImports`)

### Changed
- Version bump to 0.8.0 across `__init__.py`, `pyproject.toml`, `CHANGELOG.md`, `README.md`, `docs/README.md`, `CLAUDE.md`

## [2026-03-19] PR #38 - Chore: fix qlty audit findings (@iguinea)

- Chore: fix qlty audit findings — type annotations and triage rules

## [2026-03-19] PR #37 - Refactor: simplify core modules (v0.7.0) (@iguinea)

- Refactor: simplify core modules — fix bugs, eliminate duplication, im…
- Merge: resolve CHANGELOG.md conflict with origin/main

## [0.7.0] - 2026-03-19

### Refactored — Code Simplification & Quality Improvements
- **Repository**: Fix `__dict__` mutation in `create_agent`, `update_agent`, `create_message`, `update_message` — now uses `.copy()` to avoid modifying caller objects
- **Repository**: Consolidate timestamps with single `now = datetime.now(UTC)` per method (was creating microsecond discrepancies)
- **Repository**: Extract helpers `_parse_iso_datetime`, `_agent_exists`, `_filter_message_data` to eliminate code duplication
- **Repository**: Add `_AGENT_CONFIG_FIELDS` constant (replaces hardcoded `["model", "system_prompt"]`)
- **Repository**: Reduce `list_messages` logging from INFO to DEBUG
- **Connection Pool**: Fix logging bug — labels said `minPoolSize` for `retryWrites`/`retryReads` values
- **Connection Pool**: Thread-safe `initialize` and `close` (now protected by `_lock`)
- **Connection Pool**: Fix stats reporting — store `_resolved_kwargs` (merged defaults) instead of only user kwargs
- **Connection Pool**: Remove credential exposure from `get_pool_stats` (connection_string no longer returned)
- **Connection Pool**: Replace mutable class-level `_client_kwargs = {}` with `Optional[Dict] = None`
- **Manager**: Extract `_MONGO_CLIENT_OPTIONS` as module-level frozenset constant
- **Manager**: Remove pass-through methods `append_message` and `initialize` (just called super)
- **Manager**: Simplify `close()` — remove redundant `hasattr` checks
- **Manager**: Use `MongoDBSessionRepository._agent_exists()` in 3 methods for consistency
- **Manager**: Replace `action_handlers` dict+lambdas with if/elif in metadata tool
- **Factory**: Remove unused `_indexes_created` cache
- **Factory**: Fix inconsistent `or` vs `is not None` parameter fallback
- **Hooks**: Extract shared `dispatch_async` to `hooks/utils_async.py` (was duplicated in 3 files)
- **Hooks**: Fix `datetime.now()` without timezone in SQS and WebSocket hooks → `datetime.now(UTC)`
- **Hooks**: Remove dead code `_SESSION_ID_` replacement in feedback SNS hook
- **Hooks**: Remove dead code `create_metadata_hooks` (plural) in SQS hook
- **Hooks**: Cache boto3 clients per-region in `utils_sns.py` and `utils_sqs.py` (was creating new TCP connection per call)

### Changed
- Version bump to 0.7.0 across `__init__.py`, `pyproject.toml`, `CHANGELOG.md`
- Updated version references in README.md, docs/README.md, CLAUDE.md

## [2026-03-18] PR #36 - Add: enriched guardrail metrics (v0.6.2) (@iguinea)

- Add: enriched guardrail metrics with GuardrailTrace support (v0.6.2)
- Merge: resolve CHANGELOG.md conflict with origin/main

## [0.6.2] - 2026-03-18

### Added
- **Enriched Guardrail Metrics** (Issue #32): `redact_latest_message` now accepts `stop_reason` and `guardrail_trace` kwargs
  - `policies_triggered` summary auto-extracted from GuardrailTrace (contentPolicy, topicPolicy, wordPolicy, sensitiveInformationPolicy, contextualGroundingPolicy)
  - Full `trace` stored at message level; lightweight summary at session level
  - `stop_reason` recorded at both message and session level
  - Backward-compatible: events without new fields remain valid
- **`GUARDRAIL_STOP_REASONS` constant** (`frozenset`) for known stop reasons
- **`_extract_guardrail_summary` helper** for parsing GuardrailTrace into queryable format
- 11 new unit tests for enriched guardrail metrics and summary extraction

### Changed
- Version bump to 0.6.2 across `__init__.py`, `pyproject.toml`, `CHANGELOG.md`
- Updated guardrail auditing documentation with enriched schema and usage examples
- Updated README.md version badge, CLAUDE.md version and schema references

## [2026-03-18] PR #34 - Fix: align guardrail docs message schema (@iguinea)

- Fix: align guardrail-auditing.md message schema with data-model.md

## [2026-03-17] PR #33 - Docs: guardrail auditing guide (v0.6.1) (@iguinea)

- Docs: add guardrail auditing guide and bump version to 0.6.1
- Merge: resolve CHANGELOG.md conflict with origin/main

## [0.6.1] - 2026-03-17

### Added
- **Guardrail Auditing User Guide**: New comprehensive documentation at `docs/user-guide/guardrail-auditing.md` covering automatic recording, manual redaction, custom actions, querying events, and schema reference
- **Documentation index**: Added guardrail auditing to docs/README.md table of contents and quick links

### Changed
- Version bump to 0.6.1 across `__init__.py`, `pyproject.toml`, `CHANGELOG.md`
- Updated `docs/getting-started/basic-concepts.md` to mention guardrail auditing as a core feature
- Updated README.md version badge to 0.6.1
- Updated CLAUDE.md version reference to 0.6.1

## [2026-03-17] PR #31 - Add: guardrail auditing for redact_latest_message (v0.6.0) (@iguinea)

- Add: guardrail auditing for redact_latest_message (v0.6.0)

## [0.6.0] - 2026-03-17

### Added
- **Guardrail Auditing**: `redact_latest_message` now records guardrail events at both message and session level
  - `guardrail_event` field on redacted messages with `action` and `timestamp`
  - `guardrail_events[]` array at session level for centralized audit trail
  - Configurable `action` parameter via kwargs (default: `"BLOCKED"`)
- **`GUARDRAIL_ACTION_BLOCKED` constant** for type-safe guardrail action references
- **`_MESSAGE_EXCLUDED_FIELDS` constant** in repository for centralized field filtering
- **`_get_last_message_id` helper** in session manager for DRY message lookup
- New unit tests: 5 tests for `redact_latest_message` / guardrail events, 4 tests for guardrail filtering in repository
- New integration tests: 2 tests for redact message lifecycle and guardrail_events field creation

### Changed
- **strands-agents dependency**: bumped from `>=1.23.0` to `>=1.30.0`
- `_record_guardrail_event` uses a single MongoDB `update_one` combining `$set` + `$push` (was 2 separate calls + 1 find)
- `_update_last_message_metrics` refactored to use shared `_get_last_message_id` helper
- `read_message` and `list_messages` now use `_MESSAGE_EXCLUDED_FIELDS` constant instead of inline list

### Migration Notes
- **Breaking**: Requires `strands-agents>=1.30.0` — update your dependency
- **Schema**: New `guardrail_events: []` field added to session documents on creation. Existing sessions without this field are unaffected (guardrail events simply won't be recorded for them)
- **No API changes**: All existing code continues to work unchanged

## [2026-02-08] PR #26 - Chore: remove obsolete feature plans, playground chat, and viewer.txt (@iguinea)

- Chore: remove obsolete feature plans, playground chat, and viewer.txt

## [2026-02-08] PR #25 - Chore: qlty audit fixes - code quality and test improvements (@iguinea)

- Chore: configure qlty.toml to eliminate 57 false positives
- Fix: add missing pass statement in empty for loop body
- Refactor: reduce cognitive complexity in 10 functions below threshold
- Refactor: extract TIMEZONE_UTC_SUFFIX constant for duplicated '+00:00…
- Fix: use pytest.approx() for float comparisons in tests
- Refactor: fix JavaScript quality issues in Session Viewer
- Refactor: remove commented-out code blocks
- Fix: move E402 imports to top of file in example_fastapi_streaming.py
- Fix: rename camelCase variables to snake_case (PEP 8)
- Test: restructure and expand test suite from 30 to 253 tests
- Docs: update README.md with current project state
- Chore: fix qlty issues in tests and update triage rules
- Docs: update all documentation to match current project state
- Fix: resolve remaining qlty issues from second audit pass
- Fix: restore accidentally deleted files

## [2026-02-07] PR #14 - Update: migrate Session Viewer with security, rate limiting, and tabbed UI (@iguinea)

- chore: add CI workflow, GitHub docs, and dev philosophy
- Update: migrate Session Viewer with security, rate limiting, and tabb…
- Fix: address qlty issues - non-root Docker user, --no-install-recomme…
- Fix: resolve remaining qlty issues - reduce cognitive complexity, fix…
- Refactor: extract buildToolUsageSpan and simplify buildMetricsHTML to…

All notable changes to the MongoDB Session Manager project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2025-01-28

### Added
- **Application Name Field**: New `application_name` parameter for session categorization
  - Immutable top-level field in MongoDB documents (set only at session creation)
  - Automatic index creation for efficient filtering by application
  - New `get_application_name()` method in `MongoDBSessionManager` (read-only)
  - Supported in all creation patterns:
    - `create_mongodb_session_manager(application_name="my-app")`
    - `MongoDBSessionManager(application_name="my-app")`
    - `MongoDBSessionManagerFactory(application_name="default-app")` with per-session override
    - `initialize_global_factory(application_name="my-app")`
  - New test file: `test_application_name.py` with 15 tests (unit + integration)

### Changed
- **MongoDB Schema**: Extended document structure with `application_name` field at root level
  ```json
  {
    "_id": "session-id",
    "session_id": "session-id",
    "application_name": "my-app",  // NEW
    "session_type": "default",
    ...
  }
  ```

### Documentation
- Updated `README.md` with application_name examples
- Updated `CLAUDE.md` with new schema and usage patterns

### Benefits
- ✅ **Multi-application Support**: Categorize sessions by application for filtering
- ✅ **Session Viewer Integration**: Filter sessions by application in UI
- ✅ **Analytics**: Analyze usage patterns per application
- ✅ **Backward Compatible**: Existing sessions work with `application_name: null`

## [0.4.1] - 2025-01-28

### Changed
- **Updated all dependencies to latest stable versions**:
  - `boto3`: >=1.35.0 → >=1.42.0
  - `fastapi`: >=0.116.1 → >=0.128.0
  - `pydantic-settings`: >=2.11.0 → >=2.12.0
  - `pymongo`: >=4.13.2 → >=4.16.0
  - `strands-agents`: >=1.12.0 → >=1.23.0
  - `strands-agents-tools`: >=0.2.11 → >=0.2.19
  - `uvicorn`: >=0.37.0 → >=0.40.0
  - `uvloop`: >=0.21.0 → >=0.22.0
  - `pytest`: >=7.4.0 → >=8.0.0
  - `pytest-cov`: >=4.1.0 → >=6.0.0
  - `pytest-mock`: >=3.11.0 → >=3.14.0
  - `pytest-asyncio`: >=0.21.0 → >=1.0.0

### Documentation
- Added Testing section to `CLAUDE.md` with MongoDB connection details

## [0.4.0] - 2025-01-28

### Changed
- **Remove python-helpers dependency**: Internalized AWS utilities directly into the package
  - Created `hooks/utils_sqs.py` with `send_message` function
  - `utils_sns.py` was already internalized in previous versions
  - Added `boto3>=1.35.0` as direct dependency
  - Updated import paths in `metadata_sqs_hook.py` and `feedback_sns_hook.py`

### Added
- **GitHub configuration**: Added issue templates, PR template, CODEOWNERS, and dependabot.yml
- **Code quality tooling**: Added `.qlty/` configuration for code quality checks
- **Version management**: Added `.tool-versions` for asdf compatibility

### Fixed
- Removed unused imports across examples and session_viewer modules
- Fixed f-strings without placeholders (converted to regular strings)

### Documentation
- Simplified and updated `CLAUDE.md` with clearer project structure

## [0.3.1] - 2025-11-27

### Fixed
- **manage_metadata Tool Validation Error**: Fixed Pydantic validation error when LLM sends metadata/keys as JSON strings
  - Changed type hints from `Dict[str, Any]` and `List[str]` to `Any` to bypass Strands SDK's strict Pydantic validation
  - Added JSON parsing inside the function to handle both string and native types
  - Error was: `Input should be a valid dictionary [type=dict_type, input_value='{"..."}'`
  - Root cause: LLMs sometimes serialize complex parameters as JSON strings instead of native objects

### Technical Details
- **File**: `src/mongodb_session_manager/mongodb_session_manager.py`
  - Lines 372-376: Changed `metadata: Optional[Dict[str, Any]]` to `metadata: Optional[Any]`
  - Lines 398-410: Added JSON parsing with error handling for both `metadata` and `keys` parameters
- **Backwards Compatible**: Function still accepts native dict/list types as before

## [0.3.0] - 2025-11-27

### Added
- **Comprehensive Metrics Capture**: `sync_agent()` now uses `get_summary()` from Strands SDK for complete metrics extraction
  - **Performance Metrics**:
    - `timeToFirstByteMs`: Time to first byte latency (streaming performance indicator)
  - **Cycle Metrics** (new `cycle_metrics` field):
    - `cycle_count`: Number of event loop cycles executed
    - `total_duration`: Total duration of all cycles (seconds)
    - `average_cycle_time`: Average time per cycle (seconds)
  - **Tool Usage Metrics** (new `tool_usage` field):
    - Per-tool statistics: `call_count`, `success_count`, `error_count`
    - Performance: `total_time`, `average_time`
    - Success rate: `success_rate` (0.0 to 1.0)

### Changed
- **Metrics Extraction Method**: Refactored from direct property access to `agent.event_loop_metrics.get_summary()`
  - More robust and future-proof approach
  - Automatically captures all available metrics from Strands SDK
  - Simplified code structure with centralized metric extraction
- **Session Viewer Frontend**: Enhanced metrics display in timeline
  - Shows cache hit rate percentage with visual indicator (✅ >50%, 📝 ≤50%)
  - Shows Time to First Byte (TTFB) when available
  - Shows cycle count with hover details
  - Shows tool usage summary with per-tool details on hover
  - Improved token display with input/output breakdown on hover

### Technical Details
- **MongoDB Schema**: Extended `event_loop_metrics` structure:
  ```json
  {
    "event_loop_metrics": {
      "accumulated_metrics": {
        "latencyMs": 1500,
        "timeToFirstByteMs": 250
      },
      "accumulated_usage": {
        "inputTokens": 500,
        "outputTokens": 200,
        "totalTokens": 700,
        "cacheReadInputTokens": 450,
        "cacheWriteInputTokens": 50
      },
      "cycle_metrics": {
        "cycle_count": 3,
        "total_duration": 4.5,
        "average_cycle_time": 1.5
      },
      "tool_usage": {
        "search_documents": {
          "call_count": 5,
          "success_count": 4,
          "error_count": 1,
          "total_time": 2.5,
          "average_time": 0.5,
          "success_rate": 0.8
        }
      }
    }
  }
  ```
- **Test Updates**: Comprehensive test suite in `test_cache_metrics.py` covering all new metrics
- **Backwards Compatible**: All new fields use `.get()` with defaults for older data

### Benefits
- ✅ **Tool Performance Analysis**: Identify slow or error-prone tools
- ✅ **Conversation Complexity**: Understand cycle patterns in multi-turn interactions
- ✅ **Streaming Performance**: Monitor time-to-first-byte for UX optimization
- ✅ **Cost Analysis**: Better token tracking including cache efficiency
- ✅ **Debug Support**: Detailed per-message metrics for troubleshooting

### References
- [Strands Agents Metrics Documentation](https://strandsagents.com/latest/documentation/docs/user-guide/observability-evaluation/metrics/)
- [EventLoopMetrics.get_summary()](https://github.com/strands-agents/sdk-python/blob/main/src/strands/telemetry/metrics.py)

## [0.2.8] - 2025-11-27

### Added
- **AWS Bedrock Prompt Caching Metrics**: `sync_agent()` now extracts and stores cache metrics from Strands Agent
  - `cacheReadInputTokens`: Tokens read from cache (cache HIT)
  - `cacheWriteInputTokens`: Tokens written to cache (cache MISS)
  - Uses `.get()` with default 0 for backwards compatibility with older Strands versions
  - Enables Session Viewer to display cache hit/miss rates

### Technical Details
- **File**: `src/mongodb_session_manager/mongodb_session_manager.py:224-230`
  - Added extraction of `cacheReadInputTokens` and `cacheWriteInputTokens` from `agent.event_loop_metrics.accumulated_usage`
  - Updated `update_data` dict to include cache metrics in MongoDB document
- **New Test**: `test_cache_metrics.py`
  - Unit tests for cache metrics extraction
  - Tests for backwards compatibility when cache metrics are not present
  - Tests for cache hit rate calculation

### References
- [AWS Bedrock Prompt Caching](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html)
- [Strands Agents - Bedrock Caching](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/model-providers/amazon-bedrock/#caching)

## [0.2.7] - 2025-10-31

### Added
- **SNS Feedback Hook - Session Password Integration**: Session viewer password now included in SNS feedback notifications
  - `FeedbackSNSHook` now receives `session_manager` instance to retrieve session viewer password
  - Password automatically included in SNS message body for quick session access
  - Enhanced message format: `Password: {session_viewer_password}\n\nSession: {session_id}\n\n{comment}`
  - Enables direct Session Viewer access from feedback notifications
  - Backward compatible: displays "N/A" if session_manager not available

### Changed
- **Feedback Hook Interface**: Enhanced to pass `session_manager` instance to hooks
  - `_apply_feedback_hook()` now passes `session_manager=self` to hook functions
  - `on_feedback_add()` method signature updated to accept `**kwargs` for session_manager
  - `create_feedback_hook()` wrapper updated to forward session_manager parameter
  - Hook wrapper docstrings updated to document new parameter

### Technical Details
- **File**: `src/mongodb_session_manager/mongodb_session_manager.py:416-417`
  - Modified `_apply_feedback_hook()` to include `session_manager=self` in hook call
  - Updated docstring to document session_manager parameter
- **File**: `src/mongodb_session_manager/hooks/feedback_sns_hook.py`
  - Line 229: Updated `on_feedback_add()` signature to accept `**kwargs`
  - Lines 276-277: Added password retrieval from session_manager
  - Lines 403-404, 412-413: Updated wrapper to pass session_manager in both async and sync contexts
  - Updated docstrings to document session_manager parameter

### Use Cases
- Quick access to Session Viewer from SNS notification emails
- Incident response: direct link to problematic sessions with password
- Customer support: immediate session access when negative feedback received
- Debugging: one-click access to session context from alerts

### Example SNS Message Format
```
Subject: [PROD] ⚠️ URGENT: on session user-session-123

Body:
🚨 NEGATIVE FEEDBACK ALERT 🚨
Environment: Production
Session: user-session-123
Timestamp: 2025-10-31T14:20:14Z
---
Password: b5nwmTymyFgs5ubyCRFzbKsEq2UTVXyY

Session: user-session-123

The response was incomplete
```

### Benefits
- ✅ Zero-friction session access from notifications
- ✅ No need to look up passwords separately
- ✅ Faster incident response and debugging
- ✅ Backward compatible with existing hooks
- ✅ Non-breaking change for hook interface

## [0.2.6] - 2025-10-31

### Added
- **Session Viewer Password**: Automatic password generation for session viewer access control
  - New `session_viewer_password` field automatically generated on session creation
  - 32-character alphanumeric password using `secrets.token_urlsafe(24)` for cryptographic security
  - New `get_session_viewer_password()` method in both `MongoDBSessionRepository` and `MongoDBSessionManager`
  - Password stored at document root level (same level as `session_id`, `created_at`, etc.)
  - Backward compatible: legacy sessions without password return `None` with warning log
  - Designed for Session Viewer authentication to control access to sensitive conversation data

### Changed
- **MongoDB Schema**: Extended document structure with `session_viewer_password` field
  - Field added automatically during `create_session()` operation
  - Password persists across session reloads (not regenerated)
  - Updated schema documentation in both `CLAUDE.md` and repository docstrings

### Technical Details
- **File**: `src/mongodb_session_manager/mongodb_session_repository.py`
  - Added `import secrets` for cryptographic random generation
  - Modified `create_session()` to generate and store password
  - Added `get_session_viewer_password()` method with error handling
- **File**: `src/mongodb_session_manager/mongodb_session_manager.py`
  - Added `get_session_viewer_password()` wrapper method
  - Included example usage in docstring
- **Security**: Uses `secrets` module (not `random`) for cryptographically strong passwords
- **Format**: Base64 URL-safe encoding (alphanumeric + `-_` characters)

### Use Cases
- Session Viewer authentication: restrict access to specific sessions
- Shareable session links with password protection
- API access control for session data
- Multi-tenant session isolation

### Example Usage
```python
# Create session (password auto-generated)
session_manager = create_mongodb_session_manager(
    session_id="user-session", connection_string="mongodb://localhost:27017/"
)

# Retrieve password for Session Viewer link
password = session_manager.get_session_viewer_password()
print(
    f"Session Viewer URL: http://localhost:8883?session_id=user-session&password={password}"
)
```

## [0.2.5] - 2025-10-29

### Changed
- **SNS Message Publishing**: Moved `publish_message` function to new `utils_sns` module
  - Refactored for better modularity and code organization
  - Improved management of AWS SNS interactions
  - No breaking changes to existing API

## [0.2.4] - 2025-10-29

### Fixed
- **Python Cache Issue**: Resolved import error with FeedbackSNSHook template parameters
  - Error: `create_feedback_hook() got an unexpected keyword argument 'subject_prefix_good'`
  - Root cause: Stale Python bytecode cache (`__pycache__`) from pre-v0.2.3 versions
  - Solution: Cleared all `__pycache__` directories and `.pyc` files
  - Package reinstallation now works correctly with `uv sync --reinstall`

### Changed
- **Hooks Package Exports**: Updated `/workspace/src/mongodb_session_manager/hooks/__init__.py`
  - Added proper exports for all three hooks: FeedbackSNSHook, MetadataSQSHook, MetadataWebSocketHook
  - Added unique aliases to avoid naming conflicts:
    - `create_metadata_sqs_hook` (for SQS hook)
    - `create_metadata_websocket_hook` (for WebSocket hook)
  - Updated module docstring to document all available hooks
  - Improved conditional imports with proper availability flags

### Technical Details
- All hook implementations were already correct in v0.2.3
- Issue was purely runtime cache-related, not code-related
- Hooks subpackage `__init__.py` now properly exports all hooks with correct function signatures
- Comprehensive tests verify all import paths work correctly

### Benefits
- ✅ FeedbackSNSHook template parameters now work without cache issues
- ✅ All three hooks (SNS, SQS, WebSocket) properly exported from hooks subpackage
- ✅ Improved import path consistency across the package
- ✅ Better developer experience with clear hook availability checks

## [0.2.3] - 2025-10-29

### Added
- **FeedbackSNSHook Message Templates**: Enhanced SNS hook with configurable message prefixes
  - New optional parameters in `FeedbackSNSHook` constructor and `create_feedback_sns_hook()`:
    - `subject_prefix_good`, `subject_prefix_bad`, `subject_prefix_neutral`: Prefix templates for SNS subject lines
    - `body_prefix_good`, `body_prefix_bad`, `body_prefix_neutral`: Prefix templates for SNS message bodies
  - Template variable substitution support with `{session_id}`, `{rating}`, and `{timestamp}`
  - Different prefixes can be configured per feedback type (good/bad/neutral)
  - Prefixes appear in both Subject and Body of SNS messages
  - Fully backward compatible: all prefix parameters are optional
  - Use cases:
    - Environment identification: `[PROD]`, `[STAGING]`, `[DEV]`
    - Priority indicators: `⚠️ URGENT:`, `✅`, `ℹ️`
    - Context injection: Add session details, timestamps, environment info to notifications
  - New example in `examples/example_feedback_hook.py` (Example 7) demonstrating template usage
  - Updated documentation in `CLAUDE.md` and `README.md` with template examples

### Changed
- `FeedbackSNSHook.on_feedback_add()` now applies prefix templates before sending to SNS
- New private method `_apply_template()` handles variable substitution with error handling
- SNS message format now supports optional prefixes while maintaining backward compatibility

### Documentation
- Updated AWS Integration Patterns section in `CLAUDE.md` with template examples
- Updated SNS Feedback Notifications section in `README.md` with advanced usage
- Added comprehensive template usage example in `examples/example_feedback_hook.py`
- Documented template variables: `{session_id}`, `{rating}`, `{timestamp}`
- Added multi-environment pattern example for dev/staging/production setups

## [0.2.0] - 2025-10-22

### Added
- **WebSocket Real-time Updates Hook**: New metadata hook for ultra-low latency push notifications
  - `MetadataWebSocketHook` sends metadata changes directly to WebSocket clients via AWS API Gateway
  - Ultra-low latency compared to polling or SQS patterns (instant push to connected clients)
  - Perfect for real-time UIs: Session Viewer, dashboards, monitoring interfaces, chat applications
  - Automatic handling of disconnected clients (GoneException logged, operation continues)
  - Selective field propagation via `metadata_fields` parameter to minimize bandwidth
  - Non-blocking async operation with support for both async and sync contexts
  - Requires `connection_id` in metadata (typically from API Gateway $connect event)
  - New functions:
    - `create_metadata_websocket_hook()`: Create WebSocket hook with API Gateway endpoint
    - `is_metadata_websocket_hook_available()`: Check if boto3 is available
  - New example: `examples/example_metadata_websocket.py` with comprehensive demos

### Documentation
- Updated `CLAUDE.md` with WebSocket Integration Pattern section
  - Usage examples with connection ID management
  - WebSocket vs SQS comparison and benefits
  - Combined pattern for using both hooks together (WebSocket + SQS)
- Updated `README.md` with WebSocket hook in AWS Integrations section
  - Feature comparison between WebSocket, SQS, and SNS hooks
  - Requirements and AWS permissions (execute-api:ManageConnections)
- Updated Package Exports section in both CLAUDE.md and README.md

### Technical Details
- **File**: `src/mongodb_session_manager/hooks/metadata_websocket_hook.py`
- **Dependencies**: boto3 (already core dependency), botocore for ClientError handling
- **AWS Service**: API Gateway Management API (`apigatewaymanagementapi` client)
- **Message Format**: JSON with event, session_id, operation, metadata, timestamp
- **Error Handling**: GoneException (disconnected clients) logged as INFO, other errors as ERROR
- **Performance**: Direct push to clients, no polling overhead, daemon threads for sync contexts

### Use Cases
- Real-time Session Viewer with instant metadata updates
- Live agent state monitoring in customer dashboards
- Multi-step workflow progress indicators without polling
- Chat interfaces showing agent thinking/processing states
- Multi-user collaboration with synchronized session state

### Benefits vs Alternatives
- **vs SQS Hook**: 10-100x lower latency, ideal for single-client real-time UIs
- **vs Polling**: Eliminates polling overhead, instant updates on state changes
- **Complementary**: Best practice is to use WebSocket (UI) + SQS (backend) together

## [0.1.19] - 2025-10-16

### Added
- **Dynamic Index-Based Filters**: Session Viewer filters now automatically based on MongoDB indexes
  - Backend queries collection indexes (`list_indexes()`) to determine available filters
  - Automatic type detection (string, date, number, boolean, enum) by sampling documents
  - Configurable enum fields via `ENUM_FIELDS_STR` environment variable
  - Type-appropriate UI controls:
    - Enum fields → Dropdown with predefined values
    - Date fields → Date picker
    - Number fields → Number input
    - Boolean fields → True/False dropdown
    - String fields → Text input (default)
  - Performance guarantee: only indexed fields can be filtered (no full collection scans)

### Changed
- **API Response Structure**: `/api/v1/metadata-fields` now returns `FieldInfo` objects with type information
  - **Old format** (v0.1.16-0.1.18):
    ```json
    {
      "fields": ["status", "priority"],
      "sample_values": {"status": ["active", "completed"]}
    }
    ```
  - **New format** (v0.1.19+):
    ```json
    {
      "fields": [
        {"field": "metadata.status", "type": "enum", "values": ["active", "completed"]},
        {"field": "created_at", "type": "date"},
        {"field": "session_id", "type": "string"}
      ]
    }
    ```
- **Frontend Filter Rendering**: Dynamic filter inputs now adapt to field type automatically
- **Backend Version**: FastAPI app version updated to 0.1.19

### Configuration
New environment variables for dynamic filter configuration:
- `ENUM_FIELDS_STR`: Comma-separated list of fields to treat as enum dropdowns
  - Example: `metadata.status,metadata.priority,metadata.case_type`
  - Fields not in this list will use text input (even if they have few unique values)
- `ENUM_MAX_VALUES`: Maximum distinct values for enum detection (default: 50)
  - If a configured enum field has more values than this limit, it falls back to text input

### Implementation Details
- **Backend**: 3 new helper functions in `main.py`:
  - `get_indexed_fields()`: Extracts field names from MongoDB indexes
  - `detect_field_type()`: Samples 100 documents to determine field type
  - `get_enum_values()`: Retrieves distinct values for enum fields
  - `get_metadata_fields()`: Refactored to use index-based approach
- **Frontend**: Major refactor of `renderDynamicFilter()` in `components.js`:
  - Field selector now stores type information in dataset attributes
  - Event listener on field change renders appropriate input control
  - Enum values stored as JSON and parsed dynamically

### Benefits
- ✅ **Automatic**: Filters adapt to existing indexes without code changes
- ✅ **Performant**: Only indexed fields = guaranteed fast queries
- ✅ **Flexible**: Enum configuration via environment variables
- ✅ **Extensible**: Add new filter by creating MongoDB index + optional enum config
- ✅ **Type-safe**: Appropriate UI controls reduce user errors
- ✅ **Maintainable**: No hardcoded filter lists

### Migration Guide
**Backward Compatible**: Frontend continues to work if backend returns old format.

**To Enable Dynamic Filters**:
1. Ensure fields you want to filter have MongoDB indexes:
   ```javascript
   db.sessions.createIndex({"metadata.status": 1});
   db.sessions.createIndex({"metadata.priority": 1});
   db.sessions.createIndex({"created_at": -1});
   ```
2. Configure enum fields in `.env`:
   ```bash
   ENUM_FIELDS_STR=metadata.status,metadata.priority
   ```
3. Restart backend: `cd session_viewer/backend && make dev`
4. Frontend will automatically load new field structure

### Documentation
- Updated `features/3_dynamic_index_filters/plan.md` with complete specification
- Updated `features/3_dynamic_index_filters/progress.md` for tracking
- Updated `session_viewer/backend/.env.example` with new configuration
- See full documentation in feature plan for implementation details

## [0.1.18] - 2025-10-15

### Added
- **Authentication System**: Password protection for Session Viewer application
  - Backend endpoint `POST /api/v1/check_password` for password validation
  - Password stored as `BACKEND_PASSWORD` in `.env` (default: `123456`)
  - SHA-256 password hashing using js-sha256 library for security
  - Frontend modal with elegant dark gradient background and centered logo
  - Header-based authentication (`X-Password`) for all API requests
  - Middleware validates password on every request (except `/health` and `/check_password`)
  - Password stored in memory only (not localStorage) - lost on browser close/refresh
  - Unlimited retry attempts with clear error messages
  - Auto-focus on password input for better UX

- **Resizable Panels**: Drag-to-resize functionality for left panel (Filters + Results)
  - Drag handle between panels with visual hover/dragging states
  - Width constraints: 20% minimum, 70% maximum
  - localStorage persistence for user preference
  - Responsive design: disabled on mobile (stacks vertically)
  - Smooth dragging with cursor change and text selection prevention

- **Interactive JSON Visualization**: Enhanced JSON display using renderjson library
  - Tool calls and results now display as collapsible JSON trees
  - Metadata display with interactive expand/collapse controls
  - "Expand All" / "Collapse All" buttons for metadata section
  - Syntax highlighting with color-coded types (strings, numbers, booleans, keys)
  - Configurable display levels (show 2 levels by default)
  - String truncation for long values (100 chars max)

- **Direct Session Loading**: URL parameter support for quick access
  - Use `?session_id=<ID>` to load session directly on page load
  - Automatic session detail display on initialization
  - Useful for sharing links to specific sessions

- **Favicon**: Added custom SVG favicon for better branding
  - Blue document/list icon matching the application theme
  - Visible in browser tabs and bookmarks

### Changed
- **CORS Configuration**: Set to allow all origins (`*`) for easier development
  - Changed from specific origins to wildcard for development
  - `allow_credentials` set to `False` (required with `allow_origins=["*"]`)
  - Commented for easy production switch back to specific origins

- **Frontend Initialization**: Application only starts after successful authentication
  - SessionViewer and PanelResizer initialized after password validation
  - Clean modal removal from DOM on successful login

- **Layout System**: Changed from CSS Grid to Flexbox for resizable panels
  - Left panel with fixed/adjustable width
  - Right panel flex-grows to fill remaining space
  - Resize handle positioned between panels

### Security
- **Password Hashing**: SHA-256 hash of password travels over network, not plain text
- **No Persistence**: Password not stored in browser (localStorage/sessionStorage)
- **Session-based**: Password required on every page load/refresh
- **Header-based Auth**: All API requests include `X-Password` header with hash
- **Environment Variable**: Password stored in backend `.env` as `BACKEND_PASSWORD`

### Technical Details
- **Modified Files**:
  - Backend: `main.py` (authentication middleware + endpoint), `config.py` (BACKEND_PASSWORD), `.env` (BACKEND_PASSWORD=123456)
  - Frontend: `index.html` (auth modal + resizable layout + renderjson), `viewer.js` (PanelResizer class + URL params + metadata controls)
  - Libraries: Added `js-sha256` (0.9.0) and `renderjson` (1.4.0) via CDN

- **Authentication Flow**:
  1. User opens page → Modal displayed with dark gradient background
  2. User enters password → Frontend hashes with SHA-256
  3. Frontend sends hash to `POST /api/v1/check_password`
  4. Backend validates hash against environment variable
  5. On success: Modal removed, axios configured with header, app initialized
  6. On failure: Error message displayed, retry allowed

- **Panel Resizing**:
  - Mouse events: `mousedown`, `mousemove`, `mouseup`
  - Width calculated as percentage of parent container
  - Body class `resizing` added during drag to prevent text selection
  - localStorage key: `session-viewer-left-panel-width`

### Benefits
- **Security**: Unauthorized users cannot access session data
- **Flexibility**: Resizable panels adapt to user preferences
- **Usability**: Better JSON visualization improves data comprehension
- **Convenience**: Direct session URLs enable easy sharing and bookmarking
- **Branding**: Favicon improves professional appearance

### Configuration
```bash
# Backend .env
BACKEND_PASSWORD=123456  # Change for production
ALLOWED_ORIGINS_STR=*    # For development, specify origins for production
```

### Usage Examples
```bash
# Access with authentication
http://localhost:8883
# Enter password: 123456

# Direct session access
http://localhost:8883?session_id=abc123

# Resize panels
# Drag the vertical handle between left and right panels
```

## [0.1.17] - 2025-10-15

### Added
- **Session Viewer UI Enhancements**: Major improvements to visualization and user experience
  - **Tool Call Visualization**: Display tool calls and results in timeline with color-coded badges
    - 🔧 Blue badges for tool calls with collapsible JSON input parameters
    - ✅ Green badges for successful tool results with collapsible output
    - ❌ Red badges for failed tool results with error details
    - New functions: `parseMessageContent()`, `renderToolUse()`, `renderToolResult()`
    - Professional styling with hover effects and transitions
  - **System Prompt Display**: Full markdown-rendered system prompts in agent summary
    - Click "📝 System Prompt" to expand/collapse full prompt
    - Uses zero-md for professional markdown rendering (code blocks, lists, emphasis)
    - Scrollable area (max 300px) with custom scrollbar
    - No more truncated prompts - see the complete agent configuration
  - **Layout Reorganization**: Improved workflow with new 2-column layout
    - Left column (5/12): Filters + Results stacked vertically
    - Right column (7/12): Session details (wider for better content display)
    - More intuitive flow: filter → see results → explore details
    - Better space utilization on all screen sizes

### Changed
- Session Viewer frontend now uses 2-column layout instead of 3-column
- Agent Summary displays full system prompts with markdown rendering instead of truncated text (was 60 chars)
- Timeline messages now parse and display `toolUse` and `toolResult` content types alongside text
- Results panel height adjusted to `calc(100vh - 600px)` to accommodate filters above

### Fixed
- Tool calls and results were previously rendered as plain text, now properly visualized

### Technical Details
- **Modified Files**:
  - `session_viewer/frontend/components.js`:
    - Lines 121-160: New `parseMessageContent()` function to detect text/toolUse/toolResult
    - Lines 166-222: New tool rendering functions (`renderToolUse`, `renderToolResult`)
    - Lines 228-334: Enhanced `renderTimelineMessage()` with multi-content parsing
    - Lines 427-518: Rewritten `renderAgentSummary()` with zero-md integration
  - `session_viewer/frontend/index.html`:
    - Lines 92-226: CSS styles for tool blocks, badges, and collapsible details
    - Lines 227-273: CSS styles for agent prompt display with custom scrollbar
    - Lines 248-385: Reorganized grid layout structure (3 cols → 2 cols)

### Benefits
- **Better Debugging**: Visual distinction between tool calls, results, and text messages
- **Full Context**: Complete system prompts help understand agent behavior
- **Improved UX**: More intuitive layout reduces eye movement and improves workflow
- **Professional Look**: Color-coded badges and collapsible sections for clean timeline

## [0.1.16] - 2025-10-15

### Added
- **Session Viewer**: Full-featured web application for viewing and analyzing MongoDB sessions
  - **Backend FastAPI API** (`session_viewer/backend/`):
    - 4 REST API endpoints with dynamic filtering and pagination
    - `GET /api/v1/sessions/search` - Search sessions with multiple filters (AND logic)
    - `GET /api/v1/sessions/{id}` - Get complete session with unified timeline
    - `GET /api/v1/metadata-fields` - List available metadata fields dynamically
    - `GET /health` - Health check with connection pool statistics
    - Dynamic MongoDB query builder for metadata filters
    - Unified timeline algorithm (merges multi-agent messages + feedbacks chronologically)
    - Connection pooling integration for high performance
    - CORS configuration for frontend integration
    - Comprehensive error handling and logging
  - **Frontend Web Application** (`session_viewer/frontend/`):
    - Modern UI with Tailwind CSS and vanilla JavaScript (ES6 classes)
    - 3-panel layout: Filters, Results, Session Detail
    - Dynamic filter panel with add/remove metadata filters
    - Session search with session ID, date range, and metadata fields
    - Pagination for search results (configurable page size)
    - Session detail view with expandable metadata
    - Unified chronological timeline for all agents
    - Message rendering with markdown support (marked.js)
    - Feedback indicators inline in timeline (👍/👎)
    - Metrics display (tokens, latency) for assistant messages
    - Agent summary with model and system_prompt configuration
    - Real-time health check indicator
    - Responsive design for desktop, tablet, and mobile
  - **Libraries Used**:
    - Backend: FastAPI, pydantic-settings, uvicorn
    - Frontend: Tailwind CSS (CDN), marked.js, dayjs, axios
  - **Documentation**:
    - Backend README with API documentation and examples
    - Frontend README with architecture and usage guide
    - Feature plan in `features/2_session_viewer/plan.md`
    - Progress tracking in `features/2_session_viewer/progress.md`
    - Makefile commands for both backend and frontend

### Features
- **Dynamic Metadata Filtering**: Users can add any metadata field as a filter at runtime
- **Multi-criteria Search**: Combine session ID, date range, and multiple metadata filters
- **Pagination**: Server-side pagination with configurable page sizes (default 20, max 100)
- **Timeline Unification**: Messages from all agents and feedbacks merged chronologically
- **Markdown Rendering**: Full markdown support in assistant messages
- **Feedback Integration**: User feedbacks displayed at correct chronological position
- **Agent Configuration Display**: Shows model and system_prompt for each agent
- **Health Monitoring**: Real-time backend connectivity status
- **Configurable**: Backend settings via `.env` file

### Architecture
- **Backend**: RESTful API with FastAPI, MongoDB aggregation pipelines, connection pooling
- **Frontend**: OOP JavaScript with classes (APIClient, FilterPanel, ResultsList, SessionDetail, SessionViewer)
- **Communication**: Axios for HTTP requests, JSON data exchange
- **Styling**: Utility-first Tailwind CSS, responsive grid layout
- **Deployment**: Backend on port 8882, Frontend on port 8883

### Files Created
- Backend: `config.py`, `models.py`, `main.py`, `.env.example`, `Makefile`, `README.md`
- Frontend: `index.html`, `viewer.js`, `components.js`, `Makefile`, `README.md`
- Total: 11 new files with 1500+ lines of code

### Usage
```bash
# Backend
cd session_viewer/backend
cp .env.example .env
make run  # or: uv run python main.py

# Frontend
cd session_viewer/frontend
make run  # or: python3 -m http.server 8883

# Access: http://localhost:8883
```

### Benefits
- **Debugging**: Visualize complete conversation flows across multiple agents
- **Analytics**: Analyze session patterns by metadata fields
- **Auditing**: Review historical interactions and feedbacks
- **Troubleshooting**: Identify issues in agent responses and timing
- **User Research**: Understand user behavior and feedback patterns

### Technical Details
- REST API follows OpenAPI 3.0 specification
- MongoDB queries use regex for partial matching (case-insensitive)
- Timeline sorting by `created_at` timestamp (ISO 8601)
- Frontend uses ES6 classes for maintainable OOP architecture
- Components are pure functions for reusability
- Loading and empty states for better UX
- Error handling with user-friendly messages
- CORS enabled for localhost development

## [0.1.15] - 2025-10-15

### Changed
- **Dependency Upgrades**: Updated Strands packages to latest versions for improved stability and features
  - `strands-agents`: 1.0.1 → **1.12.0** (11 minor versions)
  - `strands-agents-tools`: 0.2.1 → **0.2.11** (10 patch versions)

### Fixed
- **SessionMessage Compatibility**: Fixed compatibility with strands-agents 1.12.0+ `SessionMessage` constructor
  - Added filtering for metrics fields (`latency_ms`, `input_tokens`, `output_tokens`) that are no longer accepted as constructor parameters
  - These fields are still stored in MongoDB for analytics but filtered when converting to SessionMessage objects
  - Fixes "SessionMessage.__init__() got an unexpected keyword argument" errors when loading existing sessions
  - Updated both `read_message()` and `list_messages()` methods in `MongoDBSessionRepository`

### Added
- **Documentation Overhaul**: Comprehensive documentation structure with 30+ new files
  - Getting Started guides (installation, quickstart, basic concepts)
  - User guides (session management, connection pooling, factory pattern, metadata, feedback, AWS integrations, async streaming)
  - API reference documentation for all classes and hooks
  - Architecture documentation (overview, design decisions, data model, performance)
  - Development guides (setup, contributing, testing, releasing)
  - Examples and patterns (basic usage, FastAPI integration, metadata patterns, feedback patterns, AWS patterns)
  - FAQ and documentation index at `docs/README.md`
- New `examples/README.md` with quick reference to all example scripts

### Benefits from Strands Upgrades
- **Performance**: Better error handling and improved tool loading mechanisms
- **Features**: New model providers (Gemini), enhanced tool specifications with optional output schemas
- **Observability**: Modern OpenTelemetry v1.37 semantic conventions for better monitoring
- **Stability**: 12 versions worth of bug fixes and improvements across strands-agents
- **Tools**: Access to 10+ new tools (Elasticsearch, Twelve Labs Video, Exa/Tavily search, Bright Data)
- **Compatibility**: Better LiteLLM and model provider support (OpenAI, Bedrock, Anthropic)

### Testing
- ✅ Verified compatibility with `example_calculator_tool.py` (basic agent + tools)
- ✅ Verified compatibility with `example_agent_config.py` (agent configuration persistence)
- ✅ Verified compatibility with `example_metadata_hook.py` (metadata hooks functionality)

## [0.1.14] - 2025-10-15

### Added
- **Agent Configuration Persistence**: Automatic capture and storage of `model` and `system_prompt` fields from agents
  - `sync_agent()` now automatically captures and persists agent configuration (model, system_prompt) to MongoDB
  - New `get_agent_config(agent_id)` method to retrieve agent configuration by ID
  - New `update_agent_config(agent_id, model, system_prompt)` method to modify agent configuration
  - New `list_agents()` method to list all agents in a session with their configurations
  - Agent configuration stored in `agents.{agent_id}.agent_data.model` and `.system_prompt` fields
  - Backward compatible: existing documents without these fields continue to work
- New example file: `examples/example_agent_config.py` demonstrating configuration persistence
- Feature plan documentation in `features/1_agent_config_persistence/`

### Changed
- MongoDB schema extended with `model` and `system_prompt` fields in agent_data
- `sync_agent()` now performs additional update to persist agent configuration

### Benefits
- **Auditing**: Track which model and system prompt were used for each conversation
- **Reproducibility**: Recreate agent behavior by using the same configuration
- **Analytics**: Analyze model usage patterns, costs, and performance
- **Compliance**: Maintain records of system prompts for regulatory purposes

### Technical Details
- Model and system_prompt are captured from the `Agent` object during `sync_agent()`
- Fields are stored using MongoDB `$set` operation with dot notation
- Configuration updates are logged at DEBUG level for observability
- Methods handle missing agents gracefully (return None or empty list)

## [0.1.13] - 2025-01-19

### Changed - BREAKING CHANGE ⚠️
- **FeedbackSNSHook**: Redesigned to support separate SNS topics for different feedback types
  - `create_feedback_sns_hook()` now requires three topic ARNs instead of one:
    - `topic_arn_good`: For positive feedback (rating="up")
    - `topic_arn_bad`: For negative feedback (rating="down")
    - `topic_arn_neutral`: For neutral feedback (rating=None)
  - Messages are automatically routed to the appropriate topic based on rating
  - Message format changed to include session context: `"Session: {session_id}\n\n{comment}"`
  - Removed unused imports (json, datetime) from feedback_sns_hook.py

### Added
- **Optional Topic ARNs**: Topics can be set to `"none"` to disable notifications for specific feedback types
  - Example: `topic_arn_neutral="none"` will skip SNS notifications for neutral feedback
  - Logs informational message when skipping due to "none" value
  - Useful for selectively enabling only good/bad feedback notifications

### Migration Guide
**Before (v0.1.12 and earlier):**
```python
feedback_hook = create_feedback_sns_hook(
    topic_arn="arn:aws:sns:eu-west-1:123456789:feedback-alerts"
)
```

**After (v0.1.13+):**
```python
feedback_hook = create_feedback_sns_hook(
    topic_arn_good="arn:aws:sns:eu-west-1:123456789:feedback-good",
    topic_arn_bad="arn:aws:sns:eu-west-1:123456789:feedback-bad",
    topic_arn_neutral="arn:aws:sns:eu-west-1:123456789:feedback-neutral",
)
```

### Updated
- Documentation updated across all files to reflect new three-topic pattern
- README.md: Updated SNS feedback section with new usage examples
- CLAUDE.md: Updated AWS integration patterns with three-topic routing
- feedback_sns_hook.py: Comprehensive docstring updates with new message format

## [0.1.12] - 2025-01-19

### Changed
- **MetadataSQSHook**: Standardized SQS message format for better event handling
  - Added `event: "metadata_update"` field to message body for consistent event categorization
  - Updated message attributes to use `event` instead of `operation` for better downstream filtering
  - This change improves event processing consistency and aligns with event-driven architecture best practices

## [0.1.11] - 2025-01-19

### Changed
- **MongoDB Connection Pool**: Disabled automatic retry for write operations by setting `retryWrites` to `False`
  - This change improves error handling predictability and prevents potential data inconsistencies
  - Read operations still maintain automatic retries with `retryReads: True`

## [0.1.10] - 2025-01-19

### Fixed
- Fixed import issues in `__init__.py` and `metadata_sqs_hook.py`
- Removed unused import to clean up the codebase
- Enhanced CHANGELOG to reflect import fixes and AWS integration hook additions

## [0.1.9] - 2024-01-27

### Added
- **AWS Integration Hooks**: Optional AWS service integrations for real-time notifications and event propagation
  - `FeedbackSNSHook`: Send feedback notifications to AWS SNS for real-time alerts
  - `MetadataSQSHook`: Propagate metadata changes to AWS SQS for SSE back-propagation
  - Both hooks require `custom_aws` package (python-helpers) as optional dependency
- **Hook Creation Functions**:
  - `create_feedback_sns_hook()`: Create SNS hook with topic ARN
  - `create_metadata_sqs_hook()`: Create SQS hook with queue URL and field filtering
- **Availability Check Functions**:
  - `is_feedback_sns_hook_available()`: Check if SNS hook can be used
  - `is_metadata_sqs_hook_available()`: Check if SQS hook can be used
- **Hooks Package**: New `hooks/` directory containing AWS integration modules
  - Comprehensive docstrings for both hook modules
  - Non-blocking async operation with graceful error handling
  - Support for both async and sync execution contexts

### Updated
- `__init__.py`: Added conditional exports for AWS hooks based on availability
- Documentation updated to include AWS integration patterns
- README.md: Added AWS Integration Hooks section with examples
- CLAUDE.md: Added AWS hooks architecture and usage patterns

### Fixed
- Removed unused `TYPE_CHECKING` import from `__init__.py`
- Fixed missing `List` import in `metadata_sqs_hook.py`

### Technical Details
- SNS hook features:
  - Real-time notifications for feedback events
  - Message attributes for SNS filtering
  - Automatic rating categorization (positive/negative/neutral)
- SQS hook features:
  - Selective field propagation to minimize message size
  - Support for metadata update and delete operations
  - Designed for SSE (Server-Sent Events) back-propagation

## [0.1.8] - 2024-01-26

### Added
- **Feedback System**: New feedback management functionality for storing user ratings and comments
  - `add_feedback()` method in `MongoDBSessionManager` to store feedback with automatic timestamps
  - `get_feedbacks()` method to retrieve all feedback for a session
  - `feedbacks` array field added to MongoDB schema
  - Feedback structure: `{rating: "up"|"down"|null, comment: string, created_at: datetime}`
- **Feedback Hooks**: New `feedbackHook` parameter in `MongoDBSessionManager` constructor
  - `_apply_feedback_hook()` method that wraps the add_feedback method
  - Hook supports "add" action only for intercepting feedback operations
- Comprehensive feedback hook examples:
  - Audit hooks for logging all feedback
  - Validation hooks for ensuring feedback quality
  - Notification hooks for alerting on negative feedback
  - Analytics hooks for collecting feedback metrics
  - Combined hooks for chaining multiple behaviors
- New example file: `examples/example_feedback_hook.py`
- FastAPI integration pattern for receiving feedback from frontend

### Updated
- `MongoDBSessionRepository`: Added `add_feedback()` and `get_feedbacks()` methods
- `MongoDBSessionManagerFactory`: Now passes through feedbackHook parameter
- Documentation updated to include feedback functionality
- README.md: Added comprehensive feedback management section
- CLAUDE.md: Updated with feedback system details

## [0.1.7] - 2024-01-25

### Added
- **Metadata Hooks**: New `metadataHook` parameter in `MongoDBSessionManager` constructor to intercept and enhance metadata operations
- `_apply_metadata_hook()` method that wraps metadata methods (update_metadata, get_metadata, delete_metadata)
- Comprehensive metadata hook examples demonstrating audit, validation, caching, and combined hooks
- New example file: `examples/example_metadata_hook.py`

### Updated
- Documentation updated to include metadata hooks functionality
- README.md and CLAUDE.md now document the hooks feature

## [0.1.6] - 2024-01-24

### Added
- **Metadata Tool**: `get_metadata_tool()` method returns a Strands tool for agents to manage metadata autonomously
- Tool supports three actions: "get", "set/update", and "delete"
- New example files:
  - `examples/example_metadata_tool.py`: Agent using metadata tool autonomously
  - `examples/example_metadata_tool_direct.py`: Direct tool usage patterns

### Updated
- Comprehensive class docstrings for `MongoDBSessionManager` and `MongoDBSessionRepository`

## [0.1.5] - 2024-01-24

### Fixed
- Fixed syntax error in `delete_metadata()` method - corrected dictionary comprehension inside `$unset` operation

### Changed
- **Metadata Updates**: `update_metadata()` now uses MongoDB dot notation for partial updates, preserving existing fields
- Previously metadata updates would replace the entire metadata object

### Added
- New example files:
  - `examples/example_metadata_update.py`: Basic metadata operations
  - `examples/example_metadata_production.py`: Production customer support scenario

## [0.1.4] - 2024-01-23

### Added
- Interactive chat playground with web-based UI
- Real-time streaming support with FastAPI backend
- Playground files:
  - `playground/chat/chat.html`: Web-based chat interface
  - `playground/chat/chat-widget.js`: JavaScript for chat functionality
  - `playground/chat/Makefile`: Easy startup commands

### Updated
- Enhanced streaming examples with better error handling

## [0.1.3] - 2024-01-22

### Added
- Async streaming support with automatic metrics tracking
- `examples/example_stream_async.py`: Demonstrates async streaming with real-time metrics
- `examples/example_fastapi_streaming.py`: FastAPI integration with streaming responses

### Changed
- Improved connection pooling for streaming scenarios
- Better handling of event loop metrics during streaming

## [0.1.2] - 2024-01-21

### Added
- **Factory Pattern**: `MongoDBSessionManagerFactory` for efficient session manager creation
- **Connection Pool Singleton**: `MongoDBConnectionPool` for connection reuse
- Global factory functions:
  - `initialize_global_factory()`
  - `get_global_factory()`
  - `close_global_factory()`
- Performance optimization examples:
  - `examples/example_performance.py`: Benchmarks and comparisons
  - `examples/example_fastapi.py`: FastAPI integration with connection pooling

### Changed
- Session managers can now accept an optional MongoDB client for connection reuse
- Smart connection lifecycle management (owns vs borrowed clients)

### Performance
- Connection overhead reduced from 10-50ms to ~0ms with pooling
- Significant throughput improvement for concurrent requests

## [0.1.1] - 2024-01-20

### Added
- Automatic event loop metrics capture from agents
- Metrics stored in `event_loop_metrics` field of assistant messages
- Token counting (inputTokens, outputTokens, totalTokens)
- Latency measurement in milliseconds

### Changed
- `sync_agent()` now captures metrics from `agent.event_loop_metrics`
- Metrics are attached to the last message in the conversation

## [0.1.0] - 2024-01-15

### Initial Release
- Core MongoDB session persistence for Strands Agents
- Document-based storage with embedded agents and messages
- Full CRUD operations for sessions, agents, and messages
- Session resumption across restarts
- Multiple agents per session support
- Timestamp preservation during updates
- Thread-safe operations
- Comprehensive error handling and logging
- Basic metadata management (create, read operations)
- Example calculator tool demonstration

### Project Structure
- `MongoDBSessionRepository`: Low-level MongoDB operations
- `MongoDBSessionManager`: High-level session management
- `create_mongodb_session_manager()`: Convenience factory function
- UV package manager integration
- Docker Compose setup for local MongoDB

[0.1.17]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.16...v0.1.17
[0.1.16]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.15...v0.1.16
[0.1.15]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.14...v0.1.15
[0.1.14]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.13...v0.1.14
[0.1.13]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.12...v0.1.13
[0.1.12]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.11...v0.1.12
[0.1.11]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.10...v0.1.11
[0.1.10]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.9...v0.1.10
[0.1.9]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.8...v0.1.9
[0.1.8]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/yourusername/mongodb-session-manager/releases/tag/v0.1.0