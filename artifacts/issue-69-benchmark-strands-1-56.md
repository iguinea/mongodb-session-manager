# Benchmark del bump de strands, 1.30.0 → 1.56.0 (#69)

Fecha: 17 de septiembre de 2026

## Conclusión

**El bump no cambia el tráfico contra la base de datos y no se nota en
DocumentDB. Cuesta CPU dentro del proceso, y eso solo se ve contra un MongoDB
local, donde el round-trip es submilisegundo.**

- **Comandos por operación: idénticos**, escenario a escenario y motor a motor,
  con el mismo reparto `find`/`aggregate`/`update`. El presupuesto de escrituras
  de #54, #65, #66 y #67 sigue intacto.
- **DocumentDB dev: dentro del ruido.** De −1,7 % a +1,1 % en seis de los siete
  escenarios. El séptimo, `turn.supervisor/h100`, sube un +3,7 % (768 → 796 ms).
- **MongoDB local: entre +0,24 y +3,19 ms por operación.** En porcentaje suena
  mucho (+22 % a +78 %) porque la base es de 1-9 ms; en valor absoluto es un
  coste fijo por invocación y por agente.

No hay nada que corregir en la librería: el coste está en el SDK, que en 1.56
hace más trabajo por turno (genera `tracking_id`, compone `message.metadata`,
resuelve prioridades de hooks con `bisect`, copia `model_state`).

## Cómo se midió

`benchmarks/`, perfil smoke (7 escenarios, 1.014 mensajes sintéticos), con el
**mismo código de la librería** en las dos columnas y cambiando solo el SDK:

```bash
uv run python -m benchmarks --repetitions 100 --json-out ...              # 1.56.0
uv run --with 'strands-agents==1.30.0' python -m benchmarks ... # 1.30.0
```

Aislar así la variable es lo que hace comparables las dos columnas: misma rama,
mismo `pyproject.toml`, mismo servidor, mismo proceso. El fichero de resultados
registra ahora `strands_version`, que no guardaba (se añade en este PR): sin él
dos runs del mismo commit eran indistinguibles.

- **MongoDB local**: 8.2.7 en Docker, `localhost:8550`. Tres runs por versión,
  **intercalados** (1.56, 1.30, 1.56, 1.30, …), 100 repeticiones.
- **DocumentDB dev**: 5.0.0 (`maxWireVersion` 13), eu-west-1, por el túnel SSH
  del bastion. Dos runs por versión, 30 repeticiones — allí cada escritura
  cuesta 40-55 ms y la matriz se mantiene pequeña a propósito.

Las tablas usan el **mejor p50 de cada versión**, no la media: con Docker y un
túnel de por medio la cola es del entorno, y el mínimo es el estadístico menos
contaminado. Los tres runs de MongoDB coinciden en la dirección en 7 de 7
escenarios, que es la señal; la dispersión dentro de cada versión es del ruido
de la máquina.

## MongoDB 8.2.7 local

| Escenario | cmd/op | 1.30.0 | 1.56.0 | Delta | Absoluto |
|---|---:|---:|---:|---:|---:|
| `create/h0/c1` | 7,00 | 1,28 ms | 2,13 ms | +67 % | +0,85 ms |
| `restore/h10/c1` | 3,00 | 1,12 ms | 1,37 ms | +22 % | +0,24 ms |
| `turn.simple/h10/c1` | 6,90 | 1,87 ms | 3,31 ms | +78 % | +1,45 ms |
| `turn.supervisor/h10/c1` | 15,83 | 8,23 ms | 11,41 ms | +39 % | +3,19 ms |
| `restore/h100/c1` | 3,00 | 1,91 ms | 2,43 ms | +27 % | +0,52 ms |
| `turn.simple/h100/c1` | 7,00 | 2,08 ms | 2,95 ms | +42 % | +0,87 ms |
| `turn.supervisor/h100/c1` | 15,85 | 9,11 ms | 11,11 ms | +22 % | +2,00 ms |

El sobrecoste **no escala con el historial**: `restore/h10` y `restore/h100`
suman +0,24 y +0,52 ms, y `turn.simple` lo mismo con 10 y con 100 mensajes
previos. Escala con el **número de agentes**: `turn.supervisor`, que monta dos
managers y dos agentes, paga +2 a +3 ms, aproximadamente el doble de
`turn.simple`. Es coste por invocación, no por dato.

El `event-loop lag` p99 sube en la misma proporción (5,1 → 12,7 ms en
`turn.simple/h10`), que es la lectura que importa para el backend de referencia:
lo que un turno bloquea a las demás peticiones que comparten el loop.

## DocumentDB 5.0.0 dev

| Escenario | cmd/op | 1.30.0 | 1.56.0 | Delta |
|---|---:|---:|---:|---:|
| `create/h0/c1` | 7,00 | 216,5 ms | 216,2 ms | −0,2 % |
| `restore/h10/c1` | 3,00 | 149,3 ms | 148,9 ms | −0,3 % |
| `turn.simple/h10/c1` | 6,67 | 220,0 ms | 222,5 ms | +1,1 % |
| `turn.supervisor/h10/c1` | 15,43 | 772,5 ms | 776,1 ms | +0,5 % |
| `restore/h100/c1` | 3,00 | 198,7 ms | 195,3 ms | −1,7 % |
| `turn.simple/h100/c1` | 7,00 | 234,4 ms | 231,7 ms | −1,2 % |
| `turn.supervisor/h100/c1` | 15,50 | 768,1 ms | 796,3 ms | +3,7 % |

Tres escenarios salen **más rápidos** con 1.56, lo que sitúa el ruido de la
medición en torno al ±1,5 %: por debajo de eso no se puede afirmar nada. El
único que asoma es `turn.supervisor/h100`, con +28 ms sobre 768; los dos runs de
1.56 (796,3 y 824,2 ms) quedan por encima de los dos de 1.30 (768,1 y 771,2),
así que probablemente sea real y de la misma naturaleza que en MongoDB —dos
agentes, dos veces el coste fijo—, solo que aquí es el 3,7 % de un turno que ya
dura 0,8 s.

**No se calcula delta entre motores**, y el harness se niega a hacerlo: la
latencia de DocumentDB está dominada por el túnel. Las dos tablas se leen por
separado.

## Lo que el benchmark verifica además de cronometrar

Cada escenario tiene que demostrar lo que midió o el run sale con código
distinto de cero. En las cuatro pasadas: `every scenario proved the work it
measured` y `cleanup: 44/44 synthetic sessions deleted` (114/114 en las de 100
repeticiones). Ninguna sesión sintética quedó atrás en ninguno de los dos
motores.

## Ficheros

- `artifacts/bench-issue69-mongodb-strands130.json`
- `artifacts/bench-issue69-mongodb-strands156.json`
- `artifacts/bench-issue69-documentdb-strands130.json`
- `artifacts/bench-issue69-documentdb-strands156.json`

Para releerlos:

```bash
uv run python -m benchmarks --compare \
  artifacts/bench-issue69-mongodb-strands130.json \
  artifacts/bench-issue69-mongodb-strands156.json
```
