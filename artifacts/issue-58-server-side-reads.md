# Evidencia de lecturas en servidor (#58)

Fecha: 16 de septiembre de 2026

## Decision

Las cuatro lecturas parten de un `$match` por `_id` y devuelven solo el resultado
de dominio solicitado:

- `list_messages()`: `$unwind`, orden estable por `created_at` e indice fisico,
  `$skip` y `$limit`. El segundo `$sort` cierra el pipeline por la diferencia de
  orden documentada por Amazon DocumentDB.
- `read_message()`: `$filter` y `$arrayElemAt` para el primer `message_id` que
  casa.
- `count_messages()`: `$size` sobre `$ifNull(messages, [])`.
- `list_agent_configs()`: `$objectToArray` y `$map` sobre las claves dinamicas de
  `agents`, proyectando solo los cuatro campos publicos.

Se descarto `$slice` para paginas porque corta en orden fisico antes de ordenar y
cambiaria la pagina cuando ese orden difiere de `created_at`. Tambien se descarto
la proyeccion `$elemMatch` sugerida inicialmente: MongoDB 8.2.7 la rechaza sobre
la ruta anidada `agents.<id>.messages` con codigo 31275 (`Cannot use $elemMatch
projection on a nested field`).

Los operadores elegidos figuran como compatibles con DocumentDB 3.6, 4.0, 5.0,
8.0 y/o Elastic en la [matriz oficial de APIs](https://docs.aws.amazon.com/documentdb/latest/devguide/mongo-apis.html).
La repeticion del sort al final se debe a la [diferencia funcional de orden de
resultados](https://docs.aws.amazon.com/documentdb/latest/devguide/functional-differences.html#functional-differences.result-ordering).

## MongoDB 8.2.7 local

Standalone en Docker, PyMongo 4.16, conexion caliente, 5 calentamientos y 30
repeticiones por operacion. Cada mensaje llevaba 512 caracteres. Las cifras son
comparaciones sobre el mismo documento; no estiman una red remota.

### Pagina de 10 mensajes

| Mensajes | Antes p50/p95/p99 | Servidor p50/p95/p99 | Antes BSON | Servidor BSON |
|---:|---:|---:|---:|---:|
| 10 | 0,278 / 0,317 / 0,353 ms | 0,417 / 0,498 / 0,512 ms | 6.800 B | 7.320 B |
| 100 | 0,658 / 1,183 / 1,296 ms | 0,506 / 0,559 / 0,589 ms | 67.641 B | 7.330 B |
| 1.000 | 2,765 / 3,899 / 3,917 ms | 1,163 / 1,256 / 1,265 ms | 677.842 B | 7.340 B |
| 5.000 | 14,322 / 24,385 / 25,457 ms | 4,263 / 4,386 / 4,386 ms | 3.397.842 B | 7.350 B |

Con 5.000 mensajes la respuesta es 462 veces menor. Para diez mensajes el
pipeline tiene un coste fijo ligeramente mayor; desde cien ya gana tambien en
latencia local.

### Otras lecturas, 5.000 mensajes

| Operacion | Antes p50/p95/p99 | Servidor p50/p95/p99 | BSON devuelto |
|---|---:|---:|---:|
| `read_message()` | 13,771 / 15,050 / 15,639 ms | 1,516 / 1,608 / 1,611 ms | 670 B |
| `count_messages()` | 13,410 / 14,891 / 14,918 ms | 1,122 / 1,177 / 1,216 ms | 16 B |
| `list_agent_configs()` | 13,481 / 15,009 / 15,062 ms | 0,519 / 0,580 / 0,583 ms | 118 B |

Ninguna de las tres respuestas contiene una clave `messages`.

### Planes

`explain("executionStats")` sobre los cuatro pipelines dio el mismo acceso al
documento raiz: `PROJECTION_DEFAULT -> IDHACK`, `totalKeysExamined=1` y
`totalDocsExamined=1`. No hay collection scan. Para una pagina
`offset=5, limit=10`, las etapas posteriores recibieron 20 elementos del `$unwind`, dejaron
15 tras el skip y devolvieron 10 tras el limit.

## Amazon DocumentDB 5.0 DEV

Cluster de desarrollo en `eu-west-1`, accedido por tunel SSH al bastion DEV.
Los identificadores de infraestructura viven en el runbook privado del equipo.
PyMongo uso `directConnection=true` por tratarse de un
unico port-forward, con TLS, `retryWrites=false` y
`readPreference=secondaryPreferred`. Las credenciales se consumieron desde
Secrets Manager sin guardarlas en el repositorio ni mostrarlas en la salida.
El procedimiento reutilizable, sin duplicar esos datos privados, queda en
[`docs/development/testing.md`](../docs/development/testing.md#testing-with-the-development-documentdb).

La suite de integracion completa paso contra el motor real:

```text
129 passed, 520 deselected in 216.49s
```

Esto incluye los contratos compartidos, orden cronologico, empates, timestamps
ausentes, primer `message_id` duplicado, paginacion y lecturas inmediatas despues
de escritura.

### Pagina de 10 mensajes

Conexion caliente, 5 calentamientos y 30 repeticiones por operacion. Cada
mensaje llevaba 512 caracteres. La latencia incluye el tunel local--bastion--
DocumentDB; los bytes son el BSON de la respuesta del comando, incluido su
envoltorio. Cada alternativa ejecuto un solo comando.

| Mensajes | Antes p50/p95/p99 | Servidor p50/p95/p99 | Antes BSON | Servidor BSON |
|---:|---:|---:|---:|---:|
| 10 | 49,688 / 50,685 / 56,413 ms | 51,098 / 56,818 / 62,723 ms | 6.782 B | 7.280 B |
| 100 | 97,360 / 107,002 / 123,463 ms | 53,124 / 54,456 / 54,794 ms | 65.733 B | 7.280 B |
| 1.000 | 116,430 / 123,999 / 126,166 ms | 72,360 / 89,403 / 92,910 ms | 656.134 B | 7.280 B |
| 5.000 | 313,749 / 369,818 / 385,455 ms | 162,771 / 189,563 / 194,154 ms | 3.284.134 B | 7.280 B |

Con 5.000 mensajes la respuesta es unas 451 veces menor y la mediana baja un
48 %. Con solo diez mensajes se conserva el pequeno coste fijo observado en
MongoDB local.

### Otras lecturas, 5.000 mensajes

| Operacion | Antes p50/p95/p99 | Servidor p50/p95/p99 | Antes BSON | Servidor BSON |
|---|---:|---:|---:|---:|
| `read_message()` | 197,797 / 219,267 / 251,614 ms | 81,174 / 86,068 / 88,367 ms | 3.284.129 B | 798 B |
| `count_messages()` | 196,534 / 218,264 / 404,521 ms | 68,866 / 77,482 / 87,155 ms | 3.284.129 B | 149 B |
| `list_agent_configs()` | 190,963 / 209,765 / 211,094 ms | 90,467 / 100,781 / 115,907 ms | 3.284.310 B | 284 B |

Ninguna respuesta de servidor contiene el historial completo.

### Planes y preferencia de lectura

`explain("executionStats")` funciono para los cuatro pipelines. DocumentDB
reporto `IXSCAN` en todos ellos. La pagina de 5.000 mensajes con `offset=5` y
`limit=10` mostro las etapas `PROJECTION`, `SUBSCAN`, primer `SORT`,
`LIMIT_SKIP` y `SORT` final: 5.000 elementos alcanzaron el sort, 15 salieron del
skip/limit y 10 del sort final. Las otras tres lecturas devolvieron un unico
resultado de agregacion.

La suite completa uso `directConnection=true`, que hace que PyMongo envie
`primaryPreferred` al servidor aunque el cliente conserve
`SecondaryPreferred`. Para probar el contrato real se repitio una sonda con
`replicaSet=rs0`, resolviendo por el mismo tunel los hostnames privados que
DocumentDB anuncia. Las cuatro lecturas inmediatas despues de una escritura
pasaron y los cuatro comandos `aggregate` llevaron
`$readPreference: {mode: "secondaryPreferred"}`.

El driver confirmo topologia `ReplicaSetWithPrimary`, `setName=rs0`, DocumentDB
`5.0.0` y `maxWireVersion=13`. El cluster DEV solo tiene una instancia;
`isMaster` respondio primaria y no secundaria, y el servidor seleccionado fue
`RSPrimary`. Quedan probados el envio de la preferencia y su fallback a
primaria, pero no es posible medir retraso de replica ni confirmar una lectura
servida fisicamente por una secundaria sin anadir otra instancia al cluster.

Los documentos temporales del benchmark se eliminaron al finalizar y el tunel
SSH se cerro en cada ejecucion.
