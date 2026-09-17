# Benchmark harness

Reproducible measurement of MongoDB Session Manager against **MongoDB** and
**Amazon DocumentDB**, with the same scenario definitions on both (issue
[#60](https://github.com/iguinea/mongodb-session-manager/issues/60)).

It replaces `examples/example_performance.py`, which reported throughput for a
loop whose body was `pass`.

```bash
# Smoke profile: a few minutes, no permission needed
export MONGODB_CONNECTION_STRING="mongodb://<user>:<pass>@localhost:8550/"
uv run python -m benchmarks

# See what a run would do without connecting
uv run python -m benchmarks --profile full --dry-run

# The full matrix of the issue, with results on disk
uv run python -m benchmarks --profile full --allow-large \
  --json-out artifacts/bench-$(date +%Y%m%d).json
```

Exit codes: `0` the run proved its work · `1` a scenario did not, or synthetic
data was left behind · `2` the run was refused before it started.

## What it measures

| Operation | What it exercises |
|---|---|
| `create` | New session: first manager and first turn, including the initial config write |
| `restore` | Manager and `Agent` over an existing session: `read_session` + `read_agent` + `list_messages` |
| `turn.simple` | One text invocation on a warm session |
| `turn.tool` | One invocation that calls a local tool |
| `turn.supervisor` | Supervisor and sub-agent, each with its own manager |

Crossed with history sizes (10, 100, 1.000, 5.000 previous messages) and
concurrency (1, 4, 16 simultaneous invocations).

**Concurrency N means N invocations in flight on one event loop**, the way N
requests share a FastAPI worker — not N parallel driver calls. pymongo is
synchronous, so those serialise, and the queue they form is exactly what the
event-loop lag measures.

For every cell: latency `min/p50/p95/p99/max`, MongoDB commands by name and per
operation — a read that needs several round-trips to drain its cursor shows them
as `getMore` — bytes in and out, connection-pool checkout wait, event-loop lag, and errors.
There is no mean anywhere: it hides the tail this exists to expose.

## Three passes per cell, and why

1. **Warmup** (`--warmups`, default 5) — fills the pool, the server cache and the
   index registry. Reported separately, never mixed into the percentiles.
2. **Latency** (`--repetitions`, default 30) — counts commands and their
   server-side duration without serialising anything.
3. **Volume** (`--volume-repetitions`, default 3) — weighs the traffic, and
   throws its timings away. Measuring bytes means re-encoding the reply inside
   the driver's callback, on the thread doing the work; sharing a pass with the
   latency numbers would inflate exactly the largest scenarios.

## Reading the numbers honestly

- **Bytes** are re-encoded from the decoded reply. They exclude the OP_MSG
  header and do **not** reflect a negotiated compressor — which is why the
  results file records the compressors in use.
- **Event-loop lag** is heartbeat drift on the loop that ran the turns. It
  matters because `Agent.__call__` wraps `invoke_async` and the reference
  backend awaits `stream_async` straight on the FastAPI loop, so every blocking
  pymongo call inside `sync_agent` stalls every other request sharing it. A
  window shorter than one heartbeat reports `null` and says so, rather than a
  zero that would read as "never blocked". The idle-loop baseline is printed
  beside it and is **never subtracted**: it is the machine's own jitter.
- **Pool wait** reads zero here, and that is structural, not a bug: one event
  loop driving a synchronous driver never has two checkouts in flight. A profile
  that saturated a four-connection pool with sixteen concurrent invocations was
  tried and removed — it still waited 0 ms. The probe stays because it does
  measure something real once several workers or threads share a client, which
  this harness does not simulate.
- **A `ping` probe** runs before and after the matrix. If it drifts, something
  outside the benchmark changed and the run is not comparable.

## It fails when the work did not happen

Every scenario must prove what it did, or the run exits non-zero:

- the messages persisted match what the script generates, re-read from the document;
- the last message of each agent carries `event_loop_metrics`, so the invocation closed;
- commands reached the server, with a write per turn and a read per restore;
- no `createIndexes` inside the measured window — the sample is warm, not cold;
- no failed commands, and every repetition completed.

These are floors, never ceilings. The **budget** of commands per turn is not
checked here: it lives in `tests/integration/test_write_amplification_integration.py`,
which owns it along with the history of how it got there. A harness that failed
when a sub-issue of [#56](https://github.com/iguinea/mongodb-session-manager/issues/56)
reduced commands would be a harness nobody runs twice.

## Guardrails

The cost is computed before anything connects. A run above **20.000 synthetic
messages** or **concurrency 8** is refused unless `--allow-large` is passed, and
the refusal says what it stopped. `--dry-run` prints the matrix and its cost with
the database down.

## Synthetic data

Every session is named `bench-<run_id>-<scenario>-<slot>`, registered, and
deleted by its exact id when the run ends — through a `finally` and through a
SIGINT/SIGTERM handler, because a `finally` does not survive a signal. Nothing is
ever dropped: the default database `benchmark_mongodb_session_manager` sits next
to real ones. After teardown the harness counts what is still named after the
run and publishes that number in the results; `--keep-data` keeps them on
purpose and prints their ids.

## Comparing a branch before and after

```bash
git switch main
uv run python -m benchmarks --json-out /tmp/base.json

git switch my-optimisation
uv run python -m benchmarks --json-out /tmp/head.json

uv run python -m benchmarks --compare /tmp/base.json /tmp/head.json
```

Scenarios are paired by their key (`operation/history/concurrency`). If the two
runs disagree on engine, server version, topology, read preference or
compressors, **no delta is computed**: both columns are printed with the field
that differs. That is also the rule for MongoDB versus DocumentDB — side by side,
never a delta, because there the latency is dominated by the tunnel.

## Against the development DocumentDB

Export `MONGODB_CONNECTION_STRING` through the SSH tunnel exactly as described in
[`docs/development/testing.md`](../docs/development/testing.md#testing-with-the-development-documentdb),
then run the same command. Nothing in this package knows which engine it is
talking to; it records what it found and lets the reader decide what is
comparable. Keep the matrix small there: every write costs 40-55 ms.

## Notes

This package is intentionally **not installable**. It imports
`tests.support.scripted_model`, so a benchmark turn and a tested turn are the
same turn, and it must therefore run from the repository root
(`uv run python -m benchmarks`).
