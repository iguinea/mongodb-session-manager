"""Event-loop lag: how long a blocking driver call stalls the server (#60).

This is not a theoretical metric here. `Agent.__call__` wraps `invoke_async`, and
the reference backend awaits `stream_async` straight on the FastAPI loop
(`examples/example_fastapi_streaming.py:198`). pymongo is synchronous, so every
call `sync_agent` makes blocks that loop and every other request on it. A thread
pool driver could not see this at all.

The bounds below are deliberately loose: what is pinned is that a blocked loop is
visible and an idle one is quiet, not a number that depends on the laptop.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from benchmarks.instruments import LoopProbe


class TestLoopProbe:
    @pytest.mark.asyncio
    async def test_a_blocked_loop_shows_up_as_lag(self):
        async with LoopProbe(interval_ms=5) as probe:
            await asyncio.sleep(0.02)
            time.sleep(0.15)  # a blocking driver call, as pymongo makes them
            await asyncio.sleep(0.02)

        assert max(probe.lag_ms) > 100

    @pytest.mark.asyncio
    async def test_an_idle_loop_stays_quiet(self):
        async with LoopProbe(interval_ms=5) as probe:
            await asyncio.sleep(0.1)

        assert probe.lag_ms
        assert max(probe.lag_ms) < 50

    @pytest.mark.asyncio
    async def test_lag_is_never_negative(self):
        async with LoopProbe(interval_ms=5) as probe:
            await asyncio.sleep(0.05)

        assert all(value >= 0 for value in probe.lag_ms)

    @pytest.mark.asyncio
    async def test_the_baseline_is_measured_on_an_empty_loop(self):
        """Reported next to the lag, never subtracted from it: the scheduler's
        own jitter is not something this benchmark gets to explain away."""
        baseline = await LoopProbe(interval_ms=5).calibrate(seconds=0.1)

        assert baseline.n > 1
        assert baseline.p99_ms >= 0

    @pytest.mark.asyncio
    async def test_stopping_twice_is_harmless(self):
        probe = LoopProbe(interval_ms=5)
        async with probe:
            await asyncio.sleep(0.02)

        await probe.stop()

        assert probe.lag_ms
