# Plan: pool, health check, índices y logging (#59)

Aceptado el 17 de septiembre de 2026. Implementado en 0.19.0.

## Objetivo

Llevar a código los hallazgos de la investigación de #59 que tienen arreglo dentro
de la librería. El problema de fondo: el pool tiene opiniones que quien lo usa no
puede contradecir —sus defaults pisan la connection string— y dos de esas
opiniones se contradicen entre sí. Además, la única ventana de observación que
ofrece hace I/O sin timeout y no devuelve las métricas que su único consumidor
conocido le pide.

## Evidencia

Toda en [`artifacts/issue-59-pool-indices-logging.md`](../../artifacts/issue-59-pool-indices-logging.md),
medida contra MongoDB 8.2.7 local, un replica set de 3 nodos y DocumentDB 5.0 DEV.
Los números que mandan en cada decisión:

| Hecho | Medido |
|---|---|
| El kwarg del constructor gana a la URI en pymongo | `?retryWrites=false` + `retryWrites=True` → `True` |
| DocumentDB rechaza el `txnNumber` en `update` | `OperationFailure 301` en `$set`, `$push` y upsert; `insert_one` pasa |
| `minPoolSize` repone lo que `maxIdleTimeMS` expira | 70 aperturas en 180 s ociosos → 33.596/día |
| Coste de reabrir una conexión | 2,77 ms en MongoDB, 603 ms en DocumentDB |
| Techo de conexiones por proceso | `nodos × (maxPoolSize + 2)`; 306 con 3 nodos |
| Techo del cluster DEV (`db.t4g.medium`) | 1.000, por `serverStatus` |
| Health check sin timeout, servidor mudo | 20,04 s |
| `ping` frente a `server_info()` | Indistinguibles: 0,22/0,25 ms local, 48,68/48,56 en DocumentDB |
| Coste del listener CMAP | 3,33 µs por comando, 0,3 % del turno |
| Logging por turno de referencia | 14 `INFO`, 1.900 B; f-string contra `%s`, ~32 ns |
| Coste en escritura de los seis índices | Ninguno: 0,305 → 0,309 ms p50 |

## Decisiones

1. **Un default solo se aplica a lo que nadie nombró.** `_resolve_options()` compara
   contra los kwargs y contra las opciones de la URI (`parse_uri` las normaliza, así
   que `?maxpoolsize=7` casa con `maxPoolSize`). Si el parseo falla —un
   `mongodb+srv://` sin DNS— se aplican todos los defaults con un `warning`, que es
   el comportamiento anterior; el `MongoClient` siguiente dará el error real si la
   URI es de verdad inválida. La clave de identidad del singleton sigue siendo
   `_user_kwargs`: lo que pasó quien llama, no lo resuelto.
2. **El suelo del pool sigue al techo que pida quien configura.** pymongo rechaza un
   `minPoolSize` mayor que `maxPoolSize`, y al dejar de pisar la URI un
   `?maxPoolSize=4` se topaba con nuestro 10. Lo descubrió un test contra el driver
   real, no contra un mock.
3. **`maxIdleTimeMS` a 300.000.** Ni `None` (las conexiones de un pico quedarían
   abiertas hasta que el servidor las cerrara, y el cluster DEV topa en 1.000) ni los
   30.000 de antes. Churn ÷11,7 conservando la liberación.
4. **El health check es un método propio, no un efecto secundario de `get_pool_stats()`.**
   `ping` bajo `pymongo.timeout()`, con la read preference del cliente, devolviendo
   un resultado en vez de lanzar.
5. **La telemetría del pool va en su propio módulo.** `pool_telemetry.py`, interno
   (no se exporta en `__init__.py`, como `field_names.py`). Contadores acumulativos y
   acotados: ninguna muestra se guarda, así que un proceso de semanas ocupa lo mismo
   que al arrancar.
6. **Un `try` por índice**, `application_name` antes que los campos de usuario, y
   distinguir el fallo permanente del transitorio para decidir si se registra la
   clave y no se reintenta en cada request.
7. **El sembrado de `metadata_fields` se construye en `field_names.py`**, que ya es
   donde vive el conocimiento de que un punto separa segmentos, y se precomputa en
   el constructor para que una configuración imposible falle al arrancar.
8. **El nivel del log es contrato**, con tests de `caplog`, como ya se hacía en
   `hooks/`.

## Descartado

- **Retirar el índice `session_id`.** No lo elige ningún `find`, empeora la búsqueda
  por id y en DocumentDB no sirve ni para el `count`, pero es lo único que cubre el
  `count_documents` con regex del SessionViewer en MongoDB. Exige coordinar antes con
  ese consumidor para que busque por `_id`, que vale lo mismo y ya está indexado.
- **Añadir `(application_name, updated_at)`.** El planner lo elige cuando existe,
  pero no mejora nada con la cardinalidad real, y ninguna consulta actual filtra por
  aplicación y ordena por fecha.
- **Migrar los 111 f-strings de logging a `%s`.** Decisión ya tomada en
  `pyproject.toml`, y la medición la respalda: 0,003 % de un turno.
- **Sustituir `server_info()` por `ping` por velocidad.** La hipótesis del análisis
  original; medida, es falsa. El cambio se hace por el timeout y por la read
  preference.
- **Hacer opcional el listener CMAP.** 0,3 % de un turno a cambio de las métricas que
  el consumidor ya intenta leer, y un parámetro menos en la API.

## MongoDB y DocumentDB

Verificado en los dos. Contra DocumentDB 5.0 DEV: la URI con `retryWrites=false` ya
manda (`effective_retry_writes: false`), el camino completo escribe
(`create_session` + `update_metadata`), el sembrado anidado llega donde escribe
`update_metadata`, el health check responde en 92 ms y `get_pool_stats()` devuelve
utilización real. Los 142 tests de integración pasan contra los dos motores.

## Criterios de aceptación

- [x] Una opción puesta en la connection string llega intacta al driver, comprobado
      contra pymongo real y no solo contra un mock.
- [x] `retryWrites=false` en la URI sobrevive, y las escrituras funcionan contra
      DocumentDB.
- [x] Un `maxPoolSize` por debajo del `minPoolSize` por defecto no rompe el arranque.
- [x] `health_check()` respeta el timeout que se le da y nunca lanza.
- [x] `get_pool_stats()` no hace I/O tras la primera llamada y expone utilización.
- [x] Un índice que falla no impide los siguientes, y un fallo permanente no se
      reintenta en cada request.
- [x] `metadata_fields` con punto se siembra donde se indexa, en las dos
      implementaciones del repositorio.
- [x] Un turno no emite nada a `INFO` por mensaje, y sigue siendo trazable en `DEBUG`.
- [x] `ruff`, 767 tests unitarios y 142 de integración en verde en los dos motores.
- [x] El invariante de «cero `createIndexes` dentro de la ventana medida» del harness
      sigue verde.
