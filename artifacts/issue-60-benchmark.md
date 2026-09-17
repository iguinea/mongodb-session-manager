# Evidencia del benchmark reproducible (#60)

Fecha: 17 de septiembre de 2026

## Que se entrega

`benchmarks/`, ejecutable con `uv run python -m benchmarks`, sustituye a
`examples/example_performance.py`. Ejecuta agentes Strands reales contra un
servidor real con un modelo guionizado, y **sale con codigo 1 si un escenario no
puede demostrar que hizo el trabajo** que dice haber medido. Los ficheros de
resultados de las dos ejecuciones de abajo estan versionados:
`artifacts/bench-mongodb-local.json` y `artifacts/bench-documentdb-dev.json`.

La definicion de escenario es la misma en los dos motores: el harness no sabe
con cual habla, registra lo que encontro y deja que el lector decida que es
comparable. `--compare` se niega a restar dos ejecuciones cuyo motor, version,
topologia, preferencia de lectura o compresores difieran.

## Metodologia

Tres pases por celda. El calentamiento llena el pool, la cache del servidor y el
registro de indices, y se reporta aparte. El pase de latencia cuenta comandos sin
serializar nada. El pase de volumen pesa los bytes y **tira sus tiempos**: medir
bytes obliga a recodificar la respuesta dentro del callback del driver, en el
hilo que hace el trabajo, y mezclarlo con la latencia falsearia justo los
escenarios grandes.

Percentiles por rango mas cercano sobre la muestra ordenada: con 30 repeticiones,
un p99 interpolado es un numero que nadie midio. No se reporta ninguna media.

**Corregido despues de publicar (17/09):** ese mismo rango mas cercano hace que
el p99 sea la ultima muestra para cualquier n < 100, y el p95 para n < 20. Las
columnas p99 de este documento son por tanto **la peor de 30 observaciones** (15
en DocumentDB), no una estimacion de cola: son medidas reales, pero las menos
repetibles de la tabla. Se detecto al repetir cuatro veces `turn.tool/h5000` en
DocumentDB: su lag «p99» fue de 1.767, 1.771, 2.836 y 5.754 ms mientras el p95 se
mantuvo entre 1.634 y 1.984. El harness marca ahora esos valores con `*` y
`--repetitions 100` hace que el p99 tenga resolucion. Comparar por p50 y p95.

Salvedades que viajan dentro del propio JSON: los bytes excluyen la cabecera
OP_MSG, son una recodificacion y no bytes de cable, y no reflejan un compresor
negociado. Una sonda de `ping` antes y despues de la matriz detecta que el camino
se haya movido durante la ejecucion.

## MongoDB 8.2.7 local

Standalone en Docker Desktop, macOS arm64, PyMongo 4.18.1, Python 3.12.13,
paquete 0.16.0, lecturas en primario, sin compresor. 5 calentamientos y 30
repeticiones por escenario, mensajes de 512 caracteres. El `ping` quedo en 0,32
ms p50 antes y despues.

| Escenario | p50 | p95 | p99 | Comandos por operacion | Bytes de respuesta |
|---|---:|---:|---:|---:|---:|
| `create` | 1,57 ms | 2,28 ms | 3,32 ms | 7,0 | 329 B |
| `restore` 10 | 1,46 ms | 4,05 ms | 4,26 ms | 3,0 | 8,4 KB |
| `restore` 100 | 3,32 ms | 5,55 ms | 5,94 ms | 3,0 | 76 KB |
| `restore` 1.000 | 7,38 ms | 8,84 ms | 14,22 ms | 4,0 | 753 KB |
| `restore` 5.000 | 31,18 ms | 41,65 ms | 42,89 ms | 4,0 | 3,77 MB |
| `turn.simple` 10 | 1,91 ms | 2,76 ms | 2,82 ms | 6,7 | 32,6 KB |
| `turn.simple` 5.000 | 11,03 ms | 12,13 ms | 12,31 ms | 7,0 | 32,6 KB |
| `turn.tool` 10 | 6,70 ms | 8,86 ms | 9,42 ms | 8,9 | 33,1 KB |
| `turn.tool` 5.000 | 19,18 ms | 20,08 ms | 20,08 ms | 9,0 | 33,1 KB |
| `turn.supervisor` 10 | 7,41 ms | 9,59 ms | 10,08 ms | 15,4 | 65,9 KB |
| `turn.supervisor` 5.000 | 27,90 ms | 30,38 ms | 30,84 ms | 15,5 | 65,9 KB |

Un turno cuesta los mismos comandos y los mismos bytes con 10 mensajes que con
5.000. Lo que crece es la restauracion que lo precede.

### Concurrencia creciente

`turn.supervisor` con 100 mensajes de historial. Concurrencia = N invocaciones en
vuelo sobre un unico event loop, como N peticiones en un worker de FastAPI.

| Invocaciones simultaneas | p50 | p95 | p99 | Lag del event loop p99 |
|---:|---:|---:|---:|---:|
| 1 | 15,0 ms | 18,9 ms | 30,0 ms | 13,1 ms |
| 4 | 20,6 ms | 33,5 ms | 45,0 ms | 25,9 ms |
| 16 | 62,5 ms | 82,0 ms | 93,6 ms | 64,5 ms |

Los comandos por turno no cambian (15,2 en los tres): es cola, no trabajo extra.

## Amazon DocumentDB 5.0 DEV

Cluster de desarrollo en `eu-west-1`, alcanzado por tunel SSH al bastion DEV; el
repositorio privado de OV conserva los identificadores de infraestructura. TLS,
`directConnection=true`, `retryWrites=false`, `readPreference=secondaryPreferred`
en el cliente. Credenciales consumidas desde Secrets Manager, nunca impresas ni
guardadas. 3 calentamientos y 15 repeticiones. El `ping` quedo en 47,4 ms p50
antes y despues, asi que el tunel no se movio durante la ejecucion.

El driver reporto `documentdb-or-compatible` 5.0.0, `maxWireVersion` 13,
`setName=rs0`. Como en #58, `directConnection=true` hace que PyMongo envie
`primaryPreferred` por el cable aunque el cliente conserve `SecondaryPreferred`.

**La latencia incluye el tunel y no es comparable con la de un servidor local.**
Las dos tablas se leen lado a lado, nunca como un delta.

| Escenario | p50 | p95 | Comandos por operacion | Bytes de respuesta |
|---|---:|---:|---:|---:|
| `create` | 211,0 ms | 268,2 ms | 7,0 | 508 B |
| `restore` 10 | 147,3 ms | 162,4 ms | 3,0 | 8,5 KB |
| `restore` 100 | 198,4 ms | 238,4 ms | 3,0 | 76 KB |
| `restore` 1.000 | 1.449,6 ms | 3.343,1 ms | **12,0** | 754 KB |
| `restore` 5.000 | 5.042,9 ms | 5.200,2 ms | **52,0** | 3,77 MB |
| `turn.simple` 10 | 163,7 ms | 238,7 ms | 6,2 | 34,1 KB |
| `turn.simple` 5.000 | 902,7 ms | 1.196,2 ms | 7,0 | 34,1 KB |
| `turn.tool` 10 | 327,2 ms | 392,6 ms | 8,7 | 33,4 KB |
| `turn.tool` 5.000 | 1.309,9 ms | 2.033,8 ms | 9,0 | 33,4 KB |
| `turn.supervisor` 10 | 668,8 ms | 814,3 ms | 14,7 | 64,6 KB |
| `turn.supervisor` 5.000 | 2.177,0 ms | 3.826,2 ms | 15,0 | 64,6 KB |

### Hallazgo: restaurar en DocumentDB cuesta round-trips, no bytes

El desglose por comando de una restauracion es donde los dos motores dejan de
parecerse:

| Historial | MongoDB local | DocumentDB DEV |
|---:|---|---|
| 10 | 2 `find` + 1 `aggregate` | 2 `find` + 1 `aggregate` |
| 100 | 2 `find` + 1 `aggregate` | 2 `find` + 1 `aggregate` |
| 1.000 | 2 `find` + 1 `aggregate` + **1** `getMore` | 2 `find` + 1 `aggregate` + **9** `getMore` |
| 5.000 | 2 `find` + 1 `aggregate` + **1** `getMore` | 2 `find` + 1 `aggregate` + **49** `getMore` |

MongoDB drena el historial de 5.000 mensajes en un solo `getMore` de 19 ms.
DocumentDB necesita 49, a 94 ms de mediana cada uno: de ahi salen los 5 segundos.
Los bytes transferidos son practicamente identicos (3,77 MB en ambos), asi que
**la diferencia no esta en el volumen sino en el tamano de lote del cursor**.

Esto no lo cambia #58, que acoto las lecturas *paginadas*: reconstruir un `Agent`
pide todos los mensajes. Es material para una sub-issue de #56 —limitar el
historial que se restaura, o negociar `batchSize`— y ahora es medible.

### Lag del event loop

pymongo es sincrono, `Agent.__call__` envuelve `invoke_async` y el backend de
referencia hace `await stream_async` sobre el loop de FastAPI. Cada llamada al
driver bloquea ese loop y con el al resto de peticiones del worker.

| Escenario | MongoDB local (lag p99) | DocumentDB DEV (lag p99) |
|---|---:|---:|
| `turn.simple` 10 | 3,9 ms | 393,8 ms |
| `turn.supervisor` 10 | 5,3 ms | 429,2 ms |
| `turn.supervisor` 5.000 | 20,4 ms | 1.373,8 ms |
| `turn.tool` 5.000 | 16,9 ms | 1.741,9 ms |

La linea base del loop ocioso (2,1-2,8 ms en esta maquina) se reporta al lado y
**no se resta nunca**. En DocumentDB, un turno sobre una sesion larga deja al
worker sin atender nada durante mas de un segundo.

### Repetibilidad del lag: cuatro ejecuciones de `turn.tool/h5000`

Un «p99» de 5.754 ms en la primera ejecucion motivo repetir el escenario tres
veces mas contra el mismo cluster, con los mismos parametros:

| Ejecucion | n | p50 | p95 | p99 (= max) |
|---|---:|---:|---:|---:|
| 1.ª | 30 | 705,0 ms | 1.752,3 ms | 5.753,8 ms |
| 2.ª | 30 | 523,5 ms | 1.984,1 ms | 2.836,0 ms |
| 3.ª | 30 | 973,0 ms | 1.634,3 ms | 1.767,0 ms |
| 4.ª | 30 | 546,5 ms | 1.699,0 ms | 1.771,7 ms |

El p95 se mantiene entre 1.634 y 1.984 ms —un 10 % de dispersion— mientras el
«p99» va de 1.767 a 5.754. La latencia del turno se comporto igual de bien: p50
entre 1.274 y 1.444 ms en las cuatro. **El pico era una sola muestra**, y la
lectura util del escenario es p50 entre 0,5 y 1 s de bloqueo del loop, con un
p95 alrededor de 1,7-2,0 s.

El `n` de 30 latidos en una ventana de casi dos minutos dice algo por si mismo:
el loop esta bloqueado tan continuamente que el latido de 20 ms apenas consigue
ejecutarse una o dos veces por repeticion.

## Espera del pool: cero, y por que

La espera de checkout salio 0 ms en todos los escenarios. Es estructural: un
unico event loop con un driver sincrono nunca tiene dos checkouts en vuelo. Se
probo un perfil que encogia el pool a 4 conexiones y lo atacaba con 16
invocaciones concurrentes, y siguio siendo 0; se retiro por eso. La sonda se
mantiene porque si mide algo cuando varios workers o hilos comparten cliente,
escenario que este harness no simula.

## Efecto colateral: carrera en el registro de indices

El guardarrail de `createIndexes` dentro de la ventana medida fallo durante el
perfil de saturacion, y al investigarlo aparecio una carrera check-then-act en
`MongoDBSessionRepository._ensure_indexes()`: la consulta al registro y su
escritura estan bajo lock, pero la creacion de indices ocurre entre las dos. Con
16 repositorios creados a la vez sobre un cliente frio se envian **64
`createIndexes` en lugar de 4**.

Reproductor:

```python
with ThreadPoolExecutor(max_workers=16) as ex:
    list(ex.map(lambda _: MongoDBSessionRepository(client=client, ...), range(16)))
# createIndexes enviados: 64
```

No es un fallo de correccion —crear un indice es idempotente— pero en el patron
factory (un manager por request) significa 4xN round-trips desperdiciados en un
arranque en frio concurrente, y en DocumentDB cada uno cuesta 45-100 ms. Queda
fuera del alcance de #60.

## Limpieza

Las dos ejecuciones borraron sus sesiones sinteticas por `_id` exacto: 54/54 en
local y 35/35 en DocumentDB, con 0 sobrantes verificados con una consulta por
prefijo despues del borrado. No se elimino ninguna base ni coleccion.
