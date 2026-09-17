# Plan: benchmark reproducible para MongoDB y DocumentDB

Issue: [#60](https://github.com/iguinea/mongodb-session-manager/issues/60)

## Objetivo

Sustituir `examples/example_performance.py` por un harness mantenible que ejecute
la misma matriz de escenarios contra MongoDB y DocumentDB, exporte resultados
estructurados y falle si no hizo el trabajo que dice haber hecho. Es la base de
medicion comun que la politica de decision de #56 exige a cada sub-issue.

## Evidencia y decision

`examples/example_performance.py` contabilizaba diez operaciones por sesion con
un bucle cuyo cuerpo era `pass` (lineas 87-90). Sus cifras estaban ademas
copiadas en `docs/architecture/performance.md`, que las presentaba como
resultados de laboratorio. Las medidas que si sirvieron (#57 y #58) salieron de
scripts ad-hoc nunca versionados.

Decisiones tomadas al disenar el harness:

- **Paquete `benchmarks/` en la raiz**, ejecutable con `uv run python -m
  benchmarks`. No es instalable: importa `tests.support.scripted_model` para que
  un turno medido y un turno testeado sean el mismo turno.
- **El driver de concurrencia es asyncio, no hilos.** `Agent.__call__` de
  strands-agents 1.30.0 envuelve `invoke_async`, y el backend de referencia
  (`examples/example_fastapi_streaming.py:198`) hace `await stream_async` sobre
  el loop de FastAPI. Las llamadas bloqueantes de pymongo dentro de `sync_agent`
  bloquean ese loop; un `ThreadPoolExecutor` no puede verlo. El *event-loop lag*
  del checklist no solo aplica: es la metrica que mejor describe el riesgo.
- **Tres pases por celda.** Calentamiento (descartado, reportado aparte),
  latencia (cuenta comandos, no serializa nada) y volumen (pesa bytes, tira los
  tiempos). Medir bytes obliga a recodificar la respuesta dentro del callback del
  driver, en el hilo que hace el trabajo: mezclarlo con la latencia falsearia los
  escenarios grandes.
- **Las comprobaciones son suelos, nunca techos.** El presupuesto de comandos por
  turno se queda en `test_write_amplification_integration.py`, que ya lo tiene
  documentado con su historia. Un harness que fallara al reducirse los comandos
  seria un harness que nadie ejecuta dos veces.
- **Se descarto agrupar los `getMore` por `operation_id`.** Medido contra pymongo
  4.18, el driver da un id distinto a cada uno; agruparlos habria reportado un
  numero inventado. Los round-trips se ven por nombre de comando.

## TDD

### RED

1. `test_benchmark_stats.py::test_warmup_samples_are_excluded_from_percentiles`
2. `test_benchmark_scenarios.py::test_large_history_requires_allow_large`
3. `test_benchmark_instruments.py::test_sums_request_and_reply_bytes_per_command`
   y `::test_records_pool_checkout_wait`
4. `test_benchmark_loop_probe.py::test_a_blocked_loop_shows_up_as_lag`
5. `test_benchmark_invariants.py::test_fewer_commands_than_the_previous_run_does_not_fail`
6. `test_benchmark_run_context.py::test_ids_are_deleted_even_when_the_workload_raises`
7. `test_benchmark_compare.py::test_differing_engines_are_reported_as_not_comparable`
8. `tests/integration/test_benchmark_smoke.py::test_a_workload_that_does_no_work_fails_the_run`

### GREEN

`benchmarks/`: `scenarios.py` (matriz y guardarrailes), `instruments.py` (sondas
de comandos, pool y event loop, mas percentiles), `run_context.py` (aislamiento y
limpieza), `workload.py` (el trabajo real), `invariants.py` (contrato de trabajo
hecho), `environment.py` (lo que hace comparable un run), `runner.py`
(orquestacion), `report.py` (JSON, resumen y comparacion), `__main__.py` (CLI).

### REFACTOR Y VERIFICACION

- `ruff format .` y `ruff check .`
- `uv run --extra dev python -m pytest tests/ -v`
- Matriz real contra MongoDB 8.2.7 local y contra DocumentDB 5.0 DEV por el tunel
  SSH, con la evidencia en `artifacts/issue-60-benchmark.md`.

## Criterios de aceptacion

- [x] El benchmark ejecuta trabajo real y falla si no se ejecutan las operaciones
      esperadas (probado en `test_a_workload_that_does_no_work_fails_the_run`).
- [x] La misma definicion de escenario funciona en MongoDB y DocumentDB.
- [x] Los resultados incluyen latencia, comandos y volumen transferido.
- [x] Los datos temporales se eliminan incluso ante errores (`finally` mas
      manejador de SIGINT/SIGTERM, con recuento de sobrantes publicado).
- [x] La ejecucion y sus limites quedan documentados en `benchmarks/README.md`.
