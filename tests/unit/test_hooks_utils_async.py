"""Unit tests for hooks.utils_async.dispatch_async().

The dispatch used to branch on whether a loop was running *in the calling
thread*, so a caller that had been moved to a worker thread silently got a new
daemon thread and a new event loop per event. These tests pin the behaviour
when the loop is given explicitly (#95).
"""

import asyncio
import gc
import logging
import threading
from concurrent.futures import Future
from unittest.mock import MagicMock

import pytest

from mongodb_session_manager.hooks.utils_async import capture_loop, dispatch_async
from tests.conftest import wait_until

# `server_loop` and `wait_until` are shared, in tests/conftest.py.


# ---------------------------------------------------------------------------
# capture_loop
# ---------------------------------------------------------------------------


class TestCaptureLoop:
    def test_returns_the_running_loop(self):
        async def run():
            return capture_loop() is asyncio.get_running_loop()

        assert asyncio.run(run()) is True

    def test_returns_none_without_a_running_loop(self):
        assert capture_loop() is None


# ---------------------------------------------------------------------------
# Explicit loop
# ---------------------------------------------------------------------------


class TestExplicitLoop:
    def test_runs_the_coroutine_on_the_given_loop(self, server_loop):
        ran_on = {}

        async def coro():
            ran_on["loop"] = asyncio.get_running_loop()

        future = dispatch_async(coro(), "test", loop=server_loop)

        assert isinstance(future, Future)
        future.result(timeout=2)
        assert ran_on["loop"] is server_loop

    def test_dispatch_from_worker_thread_creates_no_threads(self, server_loop):
        """Regression: a caller inside run_in_threadpool must not spawn threads."""
        counts: dict[str, int] = {}

        async def coro():
            await asyncio.sleep(0.2)

        def worker():
            # Simulates Starlette's run_in_threadpool: no loop in this thread.
            assert capture_loop() is None
            counts["before"] = threading.active_count()
            futures = [
                dispatch_async(coro(), "test", loop=server_loop) for _ in range(5)
            ]
            # The coroutines are still in flight, so a daemon-thread fallback
            # would still be alive and visible in the count.
            counts["during"] = threading.active_count()
            for future in futures:
                assert isinstance(future, Future)
                future.result(timeout=5)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=10)

        assert not thread.is_alive()
        assert counts["during"] == counts["before"]

    def test_returns_a_future_carrying_the_result(self, server_loop):
        async def coro():
            return 7

        future = dispatch_async(coro(), "test", loop=server_loop)

        assert isinstance(future, Future)
        assert future.result(timeout=2) == 7

    def test_in_flight_work_survives_garbage_collection(self, server_loop):
        """Regression (v0.10.1): the loop only holds weak references."""
        done = threading.Event()

        async def coro():
            await asyncio.sleep(0.05)
            done.set()

        dispatch_async(coro(), "test", loop=server_loop)  # handle discarded
        gc.collect()

        assert done.wait(timeout=2)

    def test_unreachable_loop_falls_back_without_losing_the_coroutine(self, caplog):
        """The loop can close between the check and the handover."""
        unreachable_loop = MagicMock()
        unreachable_loop.is_closed.return_value = False
        unreachable_loop.call_soon_threadsafe.side_effect = RuntimeError(
            "Event loop is closed"
        )
        executed = threading.Event()

        async def coro():
            executed.set()

        with caplog.at_level(logging.WARNING):
            dispatch_async(coro(), "sending metadata to SQS", loop=unreachable_loop)

        assert executed.wait(timeout=2)
        assert any(
            "sending metadata to SQS" in record.message for record in caplog.records
        )

    def test_cancelled_work_is_logged(self, server_loop, caplog):
        async def coro():
            await asyncio.sleep(5)

        with caplog.at_level(logging.WARNING):
            future = dispatch_async(coro(), "sending metadata to SQS", loop=server_loop)
            assert isinstance(future, Future)
            assert future.cancel()

            assert wait_until(
                lambda: any(
                    "Cancelled while sending metadata to SQS" in record.message
                    for record in caplog.records
                )
            )

    def test_closed_loop_falls_back_without_losing_the_coroutine(self, caplog):
        closed_loop = asyncio.new_event_loop()
        closed_loop.close()
        executed = threading.Event()

        async def coro():
            executed.set()

        with caplog.at_level(logging.WARNING):
            dispatch_async(coro(), "sending to WebSocket", loop=closed_loop)

        assert executed.wait(timeout=2)
        assert any(
            "sending to WebSocket" in record.message for record in caplog.records
        )


# ---------------------------------------------------------------------------
# Inherited behaviour when no loop is given
# ---------------------------------------------------------------------------


class TestWithoutExplicitLoop:
    def test_async_context_uses_the_running_loop(self):
        ran_on = {}

        async def coro():
            ran_on["loop"] = asyncio.get_running_loop()

        async def run():
            dispatch_async(coro(), "test")
            await asyncio.sleep(0.05)
            return asyncio.get_running_loop()

        assert asyncio.run(run()) is ran_on["loop"]

    def test_sync_context_uses_the_reserve_loop(self):
        """It used to be a daemon thread per event; now it is one shared loop."""
        executed = threading.Event()

        async def coro():
            executed.set()

        future = dispatch_async(coro(), "test")

        assert isinstance(future, Future)
        assert executed.wait(timeout=2)

    def test_a_sync_burst_does_not_spawn_a_thread_per_event(self):
        """Regression (#62): 200 events used to mean 200 daemon threads."""
        done = [threading.Event() for _ in range(50)]

        async def coro(i: int):
            await asyncio.sleep(0.01)
            done[i].set()

        before = threading.active_count()
        peak = before
        for i in range(50):
            dispatch_async(coro(i), "test")
            peak = max(peak, threading.active_count())

        assert wait_until(lambda: all(event.is_set() for event in done), timeout=5)
        assert peak - before <= 4


# ---------------------------------------------------------------------------
# Failure is observable
# ---------------------------------------------------------------------------


class TestFailureLogging:
    def test_failure_on_explicit_loop_is_logged(self, server_loop, caplog):
        async def coro():
            raise ValueError("boom")

        with caplog.at_level(logging.ERROR):
            future = dispatch_async(coro(), "sending metadata to SQS", loop=server_loop)
            assert isinstance(future, Future)
            with pytest.raises(ValueError):
                future.result(timeout=2)

            assert wait_until(
                lambda: any(
                    "sending metadata to SQS" in record.message
                    and "boom" in record.message
                    for record in caplog.records
                )
            )

    def test_failure_in_running_loop_is_logged(self, caplog):
        async def coro():
            raise ValueError("boom")

        async def run():
            dispatch_async(coro(), "sending metadata to SQS")
            await asyncio.sleep(0.05)

        with caplog.at_level(logging.ERROR):
            asyncio.run(run())

        assert any(
            "sending metadata to SQS" in record.message and "boom" in record.message
            for record in caplog.records
        )

    def test_failure_in_thread_fallback_is_logged(self, caplog):
        async def coro():
            raise ValueError("boom")

        with caplog.at_level(logging.ERROR):
            dispatch_async(coro(), "sending feedback to SNS")

            assert wait_until(
                lambda: any(
                    "sending feedback to SNS" in record.message
                    and "boom" in record.message
                    for record in caplog.records
                )
            )

    def test_a_broken_dispatch_does_not_reach_the_caller(self, caplog):
        """The hook writes first; a dispatch failure must not undo that."""
        # Every way of inspecting it raises, so the test does not depend on
        # which question the dispatch asks first.
        broken_loop = MagicMock()
        broken_loop.is_closed.side_effect = RuntimeError("no loop here")
        broken_loop.is_running.side_effect = RuntimeError("no loop here")

        async def coro():
            return None

        with caplog.at_level(logging.ERROR):
            assert dispatch_async(coro(), "test", loop=broken_loop) is None

        assert any("no loop here" in record.message for record in caplog.records)
