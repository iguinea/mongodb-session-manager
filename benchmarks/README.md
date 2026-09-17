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

# Issue #61: same workload on the server loop and in worker threads
uv run python -m benchmarks --profile full --execution-mode direct \
  --operation turn.supervisor --history 100 --concurrency 16 \
  --allow-large --json-out /tmp/direct.json
uv run python -m benchmarks --profile full --execution-mode thread \
  --operation turn.supervisor --history 100 --concurrency 16 \
  --allow-large --json-out /tmp/thread.json
uv run python -m benchmarks --compare /tmp/direct.json /tmp/thread.json
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

In the default `--execution-mode direct`, **concurrency N means N invocations in
flight on one event loop**, the way N streaming requests share a FastAPI worker.
pymongo is synchronous, so its calls serialise, and the queue they form is
exactly what the event-loop lag measures. In `--execution-mode thread`, each
complete request path (agent restoration, invocation and manager cleanup) is
sent to asyncio's shared worker pool. That is the non-streaming integration from
issue [#61](https://github.com/iguinea/mongodb-session-manager/issues/61), and it
allows pymongo calls to overlap up to the pool limits.

For every cell: latency `min/p50/p95/p99/max`, throughput over the complete timed
window, MongoDB commands by name and per operation — a read that needs several
round-trips to drain its cursor shows them as `getMore` — bytes in and out,
connection-pool checkout wait, event-loop lag, and errors. There is no latency
mean anywhere: it hides the tail this exists to expose.

For turn scenarios the latency samples cover the invocation itself; throughput
and event-loop lag cover the complete repeated request path, including manager
and agent construction/restoration. Restore scenarios time that construction
directly.

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

- **A percentile marked `*` is the maximum**, not a tail estimate. Percentiles
  use nearest-rank, which puts p99 on rank `ceil(0.99n)` — and that rank *is* `n`
  for every sample below 100, as p95 is below 20. With the default 30
  repetitions the p99 is therefore the worst observation, which is a real
  number but the least repeatable one in the table: measured on one DocumentDB
  scenario, its lag p99 swung between 1.767 and 5.754 ms across four runs while
  its p95 stayed within 10%. Raise `--repetitions` to 100 for a p99 that
  resolves, and read the marked columns as "worst of n" until then.
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
- **Pool wait** reads zero in `direct`, and that is structural, not a bug: one
  event loop driving a synchronous driver never has two checkouts in flight. In
  `thread` it can become non-zero because several workers really can share the
  client at once. The probe therefore distinguishes event-loop queuing from
  connection-pool contention.
- **`thread` is the current Strands workaround, not an async session-manager
  implementation.** `Agent.__call__` bridges back to `invoke_async` with an
  isolated event loop in the installed Strands release. The benchmark includes
  that cost because it measures the integration applications can deploy today.
  Replacing PyMongo with an async driver inside this package is not safe while
  Strands session callbacks remain synchronous.
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
