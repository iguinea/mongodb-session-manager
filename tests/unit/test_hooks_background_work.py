"""The lifecycle of the work the hooks leave running in the background."""

import asyncio
import logging
import subprocess  # nosec B404 - the close of a process is only observable from another
import sys
import textwrap
import threading
import time

import pytest

from mongodb_session_manager.hooks.background_work import (
    _CANCEL_GRACE_SECONDS,
    BackgroundWork,
    Delivery,
)


def wait_until(predicate, timeout: float = 5.0) -> bool:
    """Poll until the predicate holds, so the test never sleeps a fixed time."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.fixture
def work():
    """A dispatcher of its own, closed with the test that used it."""
    dispatcher = BackgroundWork()
    yield dispatcher
    dispatcher.shutdown(timeout=2.0)


@pytest.fixture
def server_loop():
    """An event loop running in a thread of its own, like a server's."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


class TestSharedReserveLoop:
    """Without a loop to dispatch to, the work shares one instead of one each."""

    def test_a_burst_does_not_grow_the_thread_count(self, work):
        done = [threading.Event() for _ in range(50)]

        async def notify(i: int) -> None:
            await asyncio.sleep(0.01)
            done[i].set()

        before = threading.active_count()
        peak = before
        for i in range(50):
            work.submit(notify(i), "probing a burst")
            peak = max(peak, threading.active_count())

        assert wait_until(lambda: all(event.is_set() for event in done))
        # One thread for the reserve loop, plus whatever its executor needs for
        # the blocking calls the hooks make. Never one per event.
        assert peak - before <= 4

    def test_the_handle_carries_the_result(self, work):
        async def notify() -> str:
            return "sent"

        handle = work.submit(notify(), "probing the handle")

        assert handle is not None
        assert handle.result(timeout=5) == "sent"

    def test_a_running_loop_in_the_calling_thread_still_wins(self):
        """Called from inside a loop, the work stays on it — no thread hop."""
        dispatcher = BackgroundWork()
        ran_on = {}

        async def notify() -> None:
            ran_on["loop"] = asyncio.get_running_loop()

        async def main() -> None:
            handle = dispatcher.submit(notify(), "probing the running loop")
            assert isinstance(handle, asyncio.Task)
            await handle
            assert ran_on["loop"] is asyncio.get_running_loop()

        asyncio.run(main())
        dispatcher.shutdown(timeout=2.0)

    def test_an_explicit_loop_still_wins(self, work, server_loop):
        ran_on = {}

        async def notify() -> None:
            ran_on["loop"] = asyncio.get_running_loop()

        handle = work.submit(notify(), "probing the explicit loop", loop=server_loop)

        assert handle is not None
        handle.result(timeout=5)
        assert ran_on["loop"] is server_loop


class TestOverflow:
    """Past the limit the work is refused, and the refusal is visible."""

    def test_work_past_the_limit_is_dropped_and_counted(self, caplog):
        dispatcher = BackgroundWork(max_in_flight=2)
        release = threading.Event()

        async def notify() -> None:
            await asyncio.to_thread(release.wait, 5)

        with caplog.at_level(logging.WARNING):
            accepted = [
                dispatcher.submit(notify(), "filling the limit") for _ in range(2)
            ]
            assert wait_until(lambda: dispatcher.stats.in_flight == 2)
            refused = dispatcher.submit(notify(), "overflowing the limit")

        assert refused is None
        assert dispatcher.stats.dropped == 1
        assert "overflowing the limit" in caplog.text
        assert all(handle is not None for handle in accepted)

        release.set()
        dispatcher.shutdown(timeout=5.0)

    def test_dropped_work_is_closed_not_left_pending(self):
        """A refused coroutine is closed: no 'never awaited' warning escapes."""
        dispatcher = BackgroundWork(max_in_flight=0)

        async def notify() -> None:  # pragma: no cover - never runs
            raise AssertionError("dropped work must not run")

        coro = notify()
        assert dispatcher.submit(coro, "dropping every event") is None
        assert coro.cr_frame is None  # closed

        dispatcher.shutdown(timeout=1.0)

    def test_the_limit_frees_up_as_work_finishes(self, work):
        async def notify() -> None:
            await asyncio.sleep(0)

        for _ in range(200):
            handle = work.submit(notify(), "reusing the budget")
            assert handle is not None
            handle.result(timeout=5)

        assert work.stats.dropped == 0
        assert work.stats.completed == 200


class TestOrderPerKey:
    """Work sharing a key runs one at a time, newest last and oldest never late."""

    def test_work_for_the_same_key_never_overlaps(self, work):
        overlapped = threading.Event()
        running = set()
        lock = threading.Lock()
        order = []

        async def notify(label: str, seconds: float) -> None:
            with lock:
                if running:
                    overlapped.set()
                running.add(label)
            await asyncio.sleep(seconds)
            with lock:
                running.discard(label)
                order.append(label)

        # The slow one first: without the guarantee the fast one would overtake.
        work.submit(notify("first", 0.2), "updating s1", order_key="s1")
        assert wait_until(lambda: work.stats.in_flight == 1)
        work.submit(notify("second", 0.0), "updating s1", order_key="s1")

        assert wait_until(lambda: order == ["first", "second"])
        assert not overlapped.is_set()

    def test_a_newer_update_supersedes_the_one_waiting(self, work, caplog):
        release = threading.Event()
        delivered = []

        async def blocking() -> None:
            await asyncio.to_thread(release.wait, 5)
            delivered.append("first")

        async def notify(label: str) -> None:
            delivered.append(label)

        with caplog.at_level(logging.WARNING):
            work.submit(blocking(), "updating s1", order_key="s1")
            assert wait_until(lambda: work.stats.in_flight == 1)
            work.submit(
                notify("stale"), "updating s1 with a stale state", order_key="s1"
            )
            work.submit(
                notify("latest"), "updating s1 with the latest state", order_key="s1"
            )

            assert work.stats.queued == 1
            release.set()
            assert wait_until(lambda: delivered == ["first", "latest"])

        assert work.stats.dropped == 1
        assert "superseded by newer work for s1" in caplog.text
        # The stale state is never delivered late.
        assert "stale" not in delivered

    def test_different_keys_do_not_wait_for_each_other(self, work):
        started = threading.Barrier(2, timeout=5)

        async def notify() -> None:
            await asyncio.to_thread(started.wait)

        work.submit(notify(), "updating s1", order_key="s1")
        work.submit(notify(), "updating s2", order_key="s2")

        # The barrier only clears if both run at once.
        assert wait_until(lambda: work.stats.completed == 2)

    def test_unkeyed_work_is_not_serialised(self, work):
        started = threading.Barrier(2, timeout=5)

        async def notify() -> None:
            await asyncio.to_thread(started.wait)

        work.submit(notify(), "notifying without a key")
        work.submit(notify(), "notifying without a key")

        assert wait_until(lambda: work.stats.completed == 2)


class TestGuaranteedDelivery:
    """What cannot be produced again is not dropped to respect a limit."""

    def test_guaranteed_work_is_accepted_over_the_limit(self, caplog):
        dispatcher = BackgroundWork(max_in_flight=1)
        release = threading.Event()
        delivered = threading.Event()

        async def blocking() -> None:
            await asyncio.to_thread(release.wait, 5)

        async def notify() -> None:
            delivered.set()

        dispatcher.submit(blocking(), "filling the limit")
        assert wait_until(lambda: dispatcher.stats.in_flight == 1)

        with caplog.at_level(logging.WARNING):
            handle = dispatcher.submit(
                notify(),
                "sending the feedback notification",
                delivery=Delivery.GUARANTEED,
            )

        assert handle is not None
        assert delivered.wait(timeout=5)
        assert dispatcher.stats.dropped == 0
        assert "over the limit" in caplog.text

        release.set()
        dispatcher.shutdown(timeout=5.0)

    def test_best_effort_work_is_dropped_at_that_same_limit(self):
        dispatcher = BackgroundWork(max_in_flight=1)
        release = threading.Event()

        async def blocking() -> None:
            await asyncio.to_thread(release.wait, 5)

        async def notify() -> None:  # pragma: no cover - never runs
            raise AssertionError("dropped work must not run")

        dispatcher.submit(blocking(), "filling the limit")
        assert wait_until(lambda: dispatcher.stats.in_flight == 1)

        assert dispatcher.submit(notify(), "overflowing the limit") is None
        assert dispatcher.stats.dropped == 1

        release.set()
        dispatcher.shutdown(timeout=5.0)


class TestShutdown:
    """Closing says what happened to the work that was still in flight."""

    def test_drains_work_that_is_waiting_its_turn(self):
        """Its turn comes during the drain: order is kept, delivery too."""
        dispatcher = BackgroundWork()
        delivered = []

        async def notify(label: str) -> None:
            await asyncio.sleep(0.1)
            delivered.append(label)

        dispatcher.submit(notify("first"), "updating s1", order_key="s1")
        assert wait_until(lambda: dispatcher.stats.in_flight == 1)
        dispatcher.submit(notify("second"), "updating s1", order_key="s1")
        assert dispatcher.stats.queued == 1

        report = dispatcher.shutdown(timeout=5.0)

        assert delivered == ["first", "second"]
        assert report.completed == 2
        assert report.dropped == 0

    def test_closing_takes_no_longer_than_its_timeout(self):
        """The reserve loop must not get a second helping of the budget."""
        dispatcher = BackgroundWork()

        async def notify() -> None:
            await asyncio.sleep(30)

        dispatcher.submit(notify(), "outliving the shutdown")
        assert wait_until(lambda: dispatcher.stats.in_flight == 1)

        started = time.monotonic()
        dispatcher.shutdown(timeout=0.5)
        elapsed = time.monotonic() - started

        # The timeout, plus the grace for the cancellation callbacks.
        assert elapsed < 0.5 + _CANCEL_GRACE_SECONDS + 0.5

    def test_drains_the_work_in_flight(self):
        dispatcher = BackgroundWork()
        delivered = threading.Event()

        async def notify() -> None:
            await asyncio.sleep(0.2)
            delivered.set()

        dispatcher.submit(notify(), "draining on shutdown")
        report = dispatcher.shutdown(timeout=5.0)

        assert delivered.is_set()
        assert report.completed == 1
        assert report.cancelled == 0
        assert report.in_flight == 0

    def test_cancels_what_does_not_finish_in_time(self, caplog):
        dispatcher = BackgroundWork()
        started = threading.Event()

        async def notify() -> None:
            started.set()
            await asyncio.sleep(30)

        with caplog.at_level(logging.WARNING):
            dispatcher.submit(notify(), "outliving the shutdown")
            assert started.wait(timeout=5)
            report = dispatcher.shutdown(timeout=0.2)

        assert report.cancelled == 1
        assert report.completed == 0
        assert "outliving the shutdown" in caplog.text

    def test_work_submitted_after_shutdown_is_refused(self, caplog):
        dispatcher = BackgroundWork()
        dispatcher.shutdown(timeout=1.0)

        async def notify() -> None:  # pragma: no cover - never runs
            raise AssertionError("work after shutdown must not run")

        with caplog.at_level(logging.WARNING):
            assert dispatcher.submit(notify(), "arriving after the shutdown") is None

        assert dispatcher.stats.dropped == 1
        assert "arriving after the shutdown" in caplog.text

    def test_shutting_down_twice_is_harmless(self):
        dispatcher = BackgroundWork()
        dispatcher.shutdown(timeout=1.0)
        report = dispatcher.shutdown(timeout=1.0)

        assert report.in_flight == 0

    def test_drops_work_that_never_got_its_turn(self, caplog):
        dispatcher = BackgroundWork()
        release = threading.Event()

        async def blocking() -> None:
            await asyncio.to_thread(release.wait, 5)

        async def notify() -> None:  # pragma: no cover - never runs
            raise AssertionError("work that never got its turn must not run")

        dispatcher.submit(blocking(), "holding up the key", order_key="s1")
        assert wait_until(lambda: dispatcher.stats.in_flight == 1)
        dispatcher.submit(notify(), "waiting behind it", order_key="s1")
        assert dispatcher.stats.queued == 1

        with caplog.at_level(logging.WARNING):
            report = dispatcher.shutdown(timeout=0.2)

        assert report.queued == 0
        assert "waiting behind it" in caplog.text
        release.set()

    def test_shutdown_without_any_work_is_immediate(self):
        dispatcher = BackgroundWork()

        started = time.perf_counter()
        report = dispatcher.shutdown(timeout=30.0)

        assert time.perf_counter() - started < 1.0
        assert report.dispatched == 0

    def test_drains_work_dispatched_to_an_explicit_loop(self, server_loop):
        dispatcher = BackgroundWork()
        delivered = threading.Event()

        async def notify() -> None:
            await asyncio.sleep(0.2)
            delivered.set()

        dispatcher.submit(notify(), "draining a bound dispatch", loop=server_loop)
        report = dispatcher.shutdown(timeout=5.0)

        assert delivered.is_set()
        assert report.completed == 1


class TestInterpreterShutdown:
    """What the close of the process itself does to work still running."""

    def test_the_interpreter_closing_is_reported_without_a_traceback(
        self, work, caplog
    ):
        """The thread pool closes before our atexit runs; that is not a bug."""

        async def notify() -> None:
            raise RuntimeError("cannot schedule new futures after interpreter shutdown")

        with caplog.at_level(logging.DEBUG):
            handle = work.submit(notify(), "sending a late notification")
            with pytest.raises(RuntimeError):
                handle.result(timeout=5)
            assert wait_until(lambda: "sending a late notification" in caplog.text)

        ours = [
            record
            for record in caplog.records
            if record.name.endswith("background_work")
        ]
        assert [record.levelname for record in ours] == ["WARNING"]
        assert ours[0].exc_info is None
        assert "the process was closing" in caplog.text
        assert work.stats.failed == 1

    def test_a_process_that_closes_drains_its_notifications(self, tmp_path):
        """End to end: a script that dispatches and exits delivers its work."""
        delivered = tmp_path / "delivered.txt"
        script = textwrap.dedent(f"""
            import asyncio
            from pathlib import Path

            from mongodb_session_manager.hooks.utils_async import dispatch_async

            out = Path({str(delivered)!r})

            async def notify(i):
                await asyncio.sleep(0.2)
                with out.open("a") as fh:
                    fh.write(f"{{i}}\\n")

            for i in range(20):
                dispatch_async(notify(i), "notifying before the close")
        """)
        # This interpreter, running a literal written right above it.
        result = subprocess.run(  # nosec B603
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
        )

        assert result.returncode == 0, result.stderr
        assert len(delivered.read_text().splitlines()) == 20


class TestStats:
    """The counters are the observable part of the policy."""

    def test_counts_every_outcome(self, work):
        async def succeeds() -> None:
            return None

        async def fails() -> None:
            raise RuntimeError("boom")

        work.submit(succeeds(), "succeeding").result(timeout=5)
        handle = work.submit(fails(), "failing")
        with pytest.raises(RuntimeError):
            handle.result(timeout=5)

        assert wait_until(lambda: work.stats.completed == 1 and work.stats.failed == 1)
        assert work.stats.dispatched == 2
        assert work.stats.in_flight == 0

    def test_a_failure_is_logged_with_its_context(self, work, caplog):
        async def fails() -> None:
            raise RuntimeError("boom")

        with caplog.at_level(logging.ERROR):
            handle = work.submit(fails(), "sending the failing notification")
            with pytest.raises(RuntimeError):
                handle.result(timeout=5)
            assert wait_until(lambda: "sending the failing notification" in caplog.text)

        assert "boom" in caplog.text
