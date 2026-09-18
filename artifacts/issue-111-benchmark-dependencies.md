# Benchmark de la separación de dependencias y el lock actualizado (#111)

Fecha: 18 de septiembre de 2026

## Conclusión

**El cambio no toca el tráfico contra la base de datos ni el coste en proceso.
Ningún escenario empeora de forma que se distinga del ruido, en ninguno de los
dos motores.**

- **Comandos por operación, reparto por comando y bytes: idénticos** en los 7
  escenarios y en los dos motores. Es lo esperable: no cambia código de la
  librería y `pymongo` sigue en 4.18.1.
- **MongoDB local: sin regresión.** La mejor p50 del head queda entre −0,4 % y
  −7,5 %, con los rangos de las tres pasadas solapados. Es el motor que delata el
  coste de CPU dentro del proceso —fue donde asomó el del bump de strands en
  #69—, y aquí no aparece ninguno.
- **DocumentDB dev: dentro del ruido.** De −0,8 % a +0,4 % en cinco escenarios.
  `turn.supervisor` sale +3,4 % (h10) y +1,6 % (h100) en la mejor p50, pero los
  rangos se solapan —en h10 una pasada de la base es más lenta que las dos del
  head— y su p95 **baja** (610 → 597 ms y 609 → 599 ms). Si el lock nuevo costara
  CPU en el turno del supervisor, se vería antes en MongoDB local, donde ese
  escenario sale un 1,8 % y un 2,5 % más rápido.

## Cómo se midió

`benchmarks/`, perfil smoke (7 escenarios), **con la misma librería en las dos
columnas y cambiando solo el conjunto de dependencias**:

- **base**: un worktree de `main` (`4fd6a9e`) con su `uv.lock` — `mcp` 1.26.0,
  `starlette` 0.50.0, `cryptography` 46.0.4, `fastapi` 0.128.0.
- **head**: esta rama — `mcp` 2.1.1, `starlette` 1.6.0, `cryptography` 50.0.1, y
  `fastapi`, `uvicorn`, `uvloop` y `strands-agents-tools` fuera del runtime.

En los dos, `strands-agents` 1.56.0 y `pymongo` 4.18.1.

```bash
# desde cada worktree, intercalando base y head
uv run --no-sync python -m benchmarks --repetitions 100 --json-out ...  # MongoDB
uv run --no-sync python -m benchmarks --json-out ...                    # DocumentDB
```

- **MongoDB local**: 8.2.7 en Docker, `localhost:8550`. Tres pasadas por lado,
  **intercaladas**, 100 repeticiones.
- **DocumentDB dev**: 5.0.0, eu-west-1, por el túnel SSH del bastion. Una pasada
  de calentamiento descartada —la primera sale con la caché fría— y después dos
  por lado intercaladas, con 30 repeticiones.

Las tablas usan la **mejor p50 de cada lado**, como en #69: con Docker y un túnel
de por medio la cola es del entorno, y el mínimo es el estadístico menos
contaminado. El rango da la dispersión entre pasadas.

## MongoDB 8.2.7 local

| Escenario | cmd/op | bytes/op | base p50 | head p50 | Delta | Rango base | Rango head |
|---|---:|---:|---:|---:|---:|---|---|
| `create/h0/c1` | 6,00 | 6.048 | 1,36 ms | 1,34 ms | −1,1 % | 1,36-1,58 | 1,34-1,50 |
| `restore/h10/c1` | 3,00 | 3.208 | 1,43 ms | 1,32 ms | −7,5 % | 1,43-1,56 | 1,32-1,73 |
| `turn.simple/h10/c1` | 5,90 | 13.544 | 2,21 ms | 2,13 ms | −3,6 % | 2,21-2,30 | 2,13-2,38 |
| `turn.supervisor/h10/c1` | 11,83 | 27.683 | 8,40 ms | 8,25 ms | −1,8 % | 8,40-8,55 | 8,25-8,44 |
| `restore/h100/c1` | 3,00 | 25.755 | 1,99 ms | 1,84 ms | −7,3 % | 1,99-2,13 | 1,84-2,37 |
| `turn.simple/h100/c1` | 6,00 | 13.547 | 2,28 ms | 2,27 ms | −0,4 % | 2,28-2,43 | 2,27-2,35 |
| `turn.supervisor/h100/c1` | 11,85 | 27.689 | 8,68 ms | 8,47 ms | −2,5 % | 8,68-8,88 | 8,47-8,85 |

## DocumentDB 5.0.0 dev

| Escenario | cmd/op | bytes/op | base p50 | head p50 | Delta | Rango base | Rango head |
|---|---:|---:|---:|---:|---:|---|---|
| `create/h0/c1` | 6,00 | 6.114 | 156,4 ms | 156,9 ms | +0,4 % | 156,4-157,6 | 156,9-160,0 |
| `restore/h10/c1` | 3,00 | 3.298 | 148,2 ms | 147,3 ms | −0,6 % | 148,2-151,4 | 147,3-147,9 |
| `turn.simple/h10/c1` | 5,67 | 13.657 | 161,5 ms | 160,9 ms | −0,4 % | 161,5-162,0 | 160,9-162,2 |
| `turn.supervisor/h10/c1` | 11,43 | 27.909 | 517,2 ms | 534,7 ms | +3,4 % | 517,2-538,7 | 534,7-537,4 |
| `restore/h100/c1` | 3,00 | 25.845 | 194,9 ms | 194,9 ms | −0,0 % | 194,9-195,5 | 194,9-195,1 |
| `turn.simple/h100/c1` | 6,00 | 13.660 | 171,9 ms | 170,5 ms | −0,8 % | 171,9-173,4 | 170,5-171,0 |
| `turn.supervisor/h100/c1` | 11,50 | 27.915 | 541,4 ms | 550,1 ms | +1,6 % | 541,4-558,9 | 550,1-555,8 |

**No se calcula delta entre motores**, y el harness se niega a hacerlo: la
latencia de DocumentDB está dominada por el túnel. Las dos tablas se leen por
separado.

## Lo que el benchmark verifica además de cronometrar

En las once pasadas: `every scenario proved the work it measured`, y
`cleanup: 114/114 synthetic sessions deleted` en MongoDB y `44/44` en
DocumentDB. Ninguna sesión sintética quedó atrás en ninguno de los dos motores.

## Ficheros

- `artifacts/bench-issue111-mongodb-{base,head}-{1,2,3}.json`
- `artifacts/bench-issue111-documentdb-{base,head}-{1,2}.json`

Para comparar una pareja:

```bash
uv run python -m benchmarks --compare \
  artifacts/bench-issue111-documentdb-base-1.json \
  artifacts/bench-issue111-documentdb-head-1.json
```
