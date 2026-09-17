"""The #61 benchmark compares blocking and worker-thread execution."""

from __future__ import annotations

import asyncio
import time

import pytest

from benchmarks.instruments import LoopProbe
from benchmarks.scenarios import Scenario
from benchmarks.workload import Workload


class FakeAgent:
    async def invoke_async(self, _prompt: str) -> None:
        time.sleep(0.12)

    def __call__(self, _prompt: str) -> None:
        time.sleep(0.12)


class FakeManager:
    def close(self) -> None: ...


class FakeRun:
    def session_id(self, key: str, slot: int) -> str:
        return f"{key}-{slot}"


def workload(mode: str) -> Workload:
    instance = Workload(
        factory=None,
        collection=None,
        run=FakeRun(),
        scenario=Scenario("turn.simple", history=0),
        execution_mode=mode,
    )
    instance._session_ids = ["session-1"]
    instance._build_agent = lambda _session_id: (FakeAgent(), FakeManager())
    return instance


async def observed_lag(instance: Workload) -> list[float]:
    async with LoopProbe(interval_ms=5) as probe:
        # Let the heartbeat schedule its first deadline before the workload.
        await asyncio.sleep(0.02)
        await instance.run_repetition()
        await asyncio.sleep(0.02)
    return probe.lag_ms


class TestExecutionModes:
    @pytest.mark.asyncio
    async def test_direct_mode_exposes_blocking_as_loop_lag(self) -> None:
        lag = await observed_lag(workload("direct"))

        assert max(lag) > 75

    @pytest.mark.asyncio
    async def test_thread_mode_keeps_the_measuring_loop_responsive(self) -> None:
        lag = await observed_lag(workload("thread"))

        assert max(lag) < 50
