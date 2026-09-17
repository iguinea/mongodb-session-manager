"""Runs the matrix: warm up, measure, weigh, and prove the work happened.

Each scenario runs three passes, for a reason spelled out in `README.md`:
warmups fill the pool and the server cache, the timed pass counts commands
without serialising anything, and the volume pass weighs the traffic with its
timings thrown away.

The client is built here because pymongo only accepts monitoring listeners at
construction time; the probes stay inert until a window opens.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from pymongo import MongoClient

from benchmarks.instruments import (
    CommandProbe,
    CommandTally,
    LoopProbe,
    PoolProbe,
    PoolTally,
    Samples,
    summarize,
)
from benchmarks.invariants import Observation, check, expectation_for
from benchmarks.report import ScenarioResult
from benchmarks.run_context import RunContext
from benchmarks.scenarios import RunPlan, Scenario
from benchmarks.workload import Workload
from mongodb_session_manager.mongodb_session_factory import MongoDBSessionManagerFactory

APPLICATION_NAME = "mongodb-session-manager-benchmark"


def _summary(values: list[float]) -> dict[str, Any] | None:
    return summarize(values).as_dict() if values else None


@dataclass
class Probes:
    """The listeners a client is born with."""

    command: CommandProbe
    pool: PoolProbe

    @classmethod
    def new(cls) -> Probes:
        return cls(command=CommandProbe(), pool=PoolProbe())

    def open(self) -> None:
        self.command.reset()
        self.pool.reset()
        self.command.enabled = True
        self.pool.enabled = True

    def close(self) -> None:
        self.command.enabled = False
        self.pool.enabled = False


def build_client(connection_string: str, probes: Probes, **options: Any) -> MongoClient:
    """A client that reports to the probes. Options override the pool defaults."""
    return MongoClient(
        connection_string,
        event_listeners=[probes.command, probes.pool],
        **options,
    )


class Runner:
    """Drives one matrix against one server."""

    def __init__(
        self,
        *,
        database_name: str,
        collection_name: str,
        run: RunContext,
        plan: RunPlan,
        probes: Probes,
        client: MongoClient,
        baseline_seconds: float = 1.0,
        on_progress: Any = None,
    ) -> None:
        self._database_name = database_name
        self._collection_name = collection_name
        self._run = run
        self._plan = plan
        self._probes = probes
        self._client = client
        self._baseline_seconds = baseline_seconds
        self._on_progress = on_progress or (lambda _message: None)

    async def run(self) -> list[ScenarioResult]:
        results = []
        for scenario in self._plan.scenarios:
            self._on_progress(f"running {scenario.key}")
            results.append(
                await self._run_scenario(scenario, self._client, self._probes)
            )
        return results

    async def _run_scenario(
        self, scenario: Scenario, client: MongoClient, probes: Probes
    ) -> ScenarioResult:
        collection = client[self._database_name][self._collection_name]
        factory = MongoDBSessionManagerFactory(
            client=client,
            database_name=self._database_name,
            collection_name=self._collection_name,
            application_name=APPLICATION_NAME,
        )
        workload = Workload(
            factory,
            collection,
            self._run,
            scenario,
            execution_mode=self._plan.execution_mode,
        )

        workload.prepare()
        messages_before = workload.persisted_messages()
        samples, loop_lag, tally, throughput = await self._timed_passes(
            workload, scenario, probes
        )
        volume = await self._volume_pass(workload, probes)
        messages_after = workload.persisted_messages()

        pool_tally = probes.pool.tally()
        total_passes = (
            self._plan.warmups + self._plan.repetitions + self._plan.volume_repetitions
        )
        measured_operations = max(1, self._plan.repetitions * scenario.concurrency)

        reasons = check(
            expectation_for(scenario, repetitions=total_passes),
            Observation(
                messages_written=messages_after - messages_before,
                commands=tally.commands,
                failures=tally.failures,
                completed_repetitions=total_passes,
                last_messages_have_metrics=workload.last_messages_have_metrics(),
            ),
        )

        return self._result_for(
            scenario,
            samples=samples,
            tally=tally,
            pool_tally=pool_tally,
            volume=volume,
            loop_lag=loop_lag,
            measured_operations=measured_operations,
            throughput=throughput,
            reasons=reasons,
        )

    def _result_for(
        self,
        scenario: Scenario,
        *,
        samples: Samples,
        tally: CommandTally,
        pool_tally: PoolTally,
        volume: dict[str, int],
        loop_lag: dict[str, Any],
        measured_operations: int,
        throughput: dict[str, Any],
        reasons: list[str],
    ) -> ScenarioResult:
        return ScenarioResult(
            scenario=scenario.key,
            operation=scenario.operation,
            history=scenario.history,
            concurrency=scenario.concurrency,
            execution_mode=self._plan.execution_mode,
            latency=samples.summary().as_dict(),
            warmup=samples.warmup_summary().as_dict() if self._plan.warmups else None,
            commands={
                "total": sum(tally.commands.values()),
                "per_operation": sum(tally.commands.values()) / measured_operations,
                "by_name": tally.commands,
            },
            server_ms={
                name: _summary(values) for name, values in tally.server_ms.items()
            },
            bytes=volume,
            pool={
                "wait": _summary(pool_tally.wait_ms),
                "timeouts": pool_tally.timeouts,
                "reasons": pool_tally.reasons,
            },
            loop_lag=loop_lag,
            throughput=throughput,
            errors=tally.failures,
            checks=reasons,
        )

    async def _timed_passes(
        self, workload: Workload, scenario: Scenario, probes: Probes
    ) -> tuple[Samples, dict[str, Any], CommandTally, dict[str, Any]]:
        """Warmups with the probes closed, then the window that gets reported."""
        samples = Samples(warmups=self._plan.warmups * scenario.concurrency)
        for _ in range(self._plan.warmups):
            for latency in await workload.run_repetition():
                samples.record(latency)

        baseline = await LoopProbe().calibrate(self._baseline_seconds)

        probes.open()
        loop_probe = LoopProbe()
        loop = asyncio.get_running_loop()
        async with loop_probe:
            started = loop.time()
            for _ in range(self._plan.repetitions):
                for latency in await workload.run_repetition():
                    samples.record(latency)
            elapsed_seconds = loop.time() - started
        probes.close()

        # Taken before the volume pass resets the counters.
        tally = probes.command.tally()

        loop_lag = {
            "lag": _summary(loop_probe.lag_ms),
            "baseline": baseline.as_dict(),
            "interval_ms": loop_probe.interval_ms,
            "note": (
                "Heartbeat drift on the loop that ran the turns. The baseline is "
                "the machine's own jitter, shown for scale and never subtracted."
            ),
        }
        if not loop_probe.lag_ms:
            # A fast scenario can finish inside one heartbeat. Saying so beats
            # reporting a zero that would read as "the loop was never blocked".
            loop_lag["reason"] = (
                f"the measured window was shorter than the "
                f"{loop_probe.interval_ms:.0f} ms heartbeat; raise --repetitions "
                "to measure lag for this scenario"
            )
        operations = self._plan.repetitions * scenario.concurrency
        throughput = {
            "operations": operations,
            "elapsed_seconds": elapsed_seconds,
            "operations_per_second": (
                operations / elapsed_seconds if elapsed_seconds > 0 else 0.0
            ),
        }
        return samples, loop_lag, tally, throughput

    async def _volume_pass(self, workload: Workload, probes: Probes) -> dict[str, int]:
        """Weighs the traffic, then throws the timings away.

        Re-encoding a reply inside the driver callback costs time on the thread
        doing the work, so this cannot share a pass with the latency numbers.
        """
        if not self._plan.volume_repetitions:
            return {"request": 0, "reply": 0, "repetitions": 0}

        probes.command.reset()
        probes.command.enabled = True
        probes.command.measure_bytes = True
        for _ in range(self._plan.volume_repetitions):
            await workload.run_repetition()
        probes.command.enabled = False
        probes.command.measure_bytes = False

        tally = probes.command.tally()
        per_pass = self._plan.volume_repetitions
        return {
            "request": tally.request_bytes // per_pass,
            "reply": tally.reply_bytes // per_pass,
            "repetitions": per_pass,
        }


def run_matrix(
    *,
    database_name: str,
    collection_name: str,
    run: RunContext,
    plan: RunPlan,
    probes: Probes,
    client: MongoClient,
    baseline_seconds: float = 1.0,
    on_progress: Any = None,
) -> list[ScenarioResult]:
    """Entry point of a run: one event loop for the whole matrix."""
    runner = Runner(
        database_name=database_name,
        collection_name=collection_name,
        run=run,
        plan=plan,
        probes=probes,
        client=client,
        baseline_seconds=baseline_seconds,
        on_progress=on_progress,
    )
    return asyncio.run(runner.run())
