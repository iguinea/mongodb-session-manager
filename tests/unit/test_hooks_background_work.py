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
from tests.conftest import wait_until


def close_stopped_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Close a loop that was stopped while work was still riding it.

    Without cancelling what is left, asyncio prints "Task was destroyed but it
    is pending!" when the loop is collected — noise that says nothing about
    the test.
    """
    for task in asyncio.all_tasks(loop):
        task.cancel()
    loop.run_until_complete(asyncio.sleep(0))
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
        # `handle.result()` returns before the done callback has counted it.
        assert wait_until(lambda: work.stats.completed == 200)


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

    def test_waiting_work_runs_on_the_loop_its_caller_was_on(self, work, server_loop):
        """Waiting does not move the work to somebody else's loop.

        Submitted with no loop of its own, the work belongs on the loop of the
        thread that submitted it. Its turn comes from the callback of the work
        ahead, which runs on *that* work's loop — so resolving the loop then,
        instead of at submit time, would hand it to whichever loop happened to
        finish first.
        """
        release = threading.Event()
        ran_on = []

        async def blocks_the_key() -> None:
            await asyncio.to_thread(release.wait, 5)

        async def note_the_loop() -> None:
            ran_on.append(asyncio.get_running_loop())

        async def submit_from_this_loop() -> None:
            work.submit(note_the_loop(), "updating s1", order_key="s1")

        # The first one rides the reserve loop; the second is submitted from
        # `server_loop`, which is where it must run when its turn comes.
        work.submit(blocks_the_key(), "holding s1", order_key="s1")
        assert wait_until(lambda: work.stats.in_flight == 1)
        asyncio.run_coroutine_threadsafe(submit_from_this_loop(), server_loop).result(
            timeout=5
        )

        release.set()
        assert wait_until(lambda: ran_on == [server_loop])

    def test_every_update_of_a_session_is_delivered_in_order(self, work):
        """A metadata update is a delta, not a state: dropping one loses fields."""
        release = threading.Event()
        delivered = []

        async def blocking() -> None:
            await asyncio.to_thread(release.wait, 5)
            delivered.append("first")

        async def notify(label: str) -> None:
            delivered.append(label)

        work.submit(blocking(), "updating s1", order_key="s1")
        assert wait_until(lambda: work.stats.in_flight == 1)
        work.submit(notify("second"), "updating s1 again", order_key="s1")
        work.submit(notify("third"), "updating s1 once more", order_key="s1")

        assert work.stats.queued == 2
        release.set()

        assert wait_until(lambda: delivered == ["first", "second", "third"])
        assert work.stats.dropped == 0

    def test_a_full_queue_drops_the_oldest_and_says_so(self, caplog):
        """Past that depth the key is stuck; the newest state is worth more."""
        dispatcher = BackgroundWork(max_queued_per_key=2)
        release = threading.Event()
        delivered = []

        async def blocking() -> None:
            await asyncio.to_thread(release.wait, 5)
            delivered.append("first")

        async def notify(label: str) -> None:
            delivered.append(label)

        with caplog.at_level(logging.WARNING):
            dispatcher.submit(blocking(), "updating s1", order_key="s1")
            assert wait_until(lambda: dispatcher.stats.in_flight == 1)
            dispatcher.submit(notify("oldest"), "updating s1 oldest", order_key="s1")
            dispatcher.submit(notify("middle"), "updating s1 middle", order_key="s1")
            dispatcher.submit(notify("newest"), "updating s1 newest", order_key="s1")

            assert dispatcher.stats.queued == 2
            release.set()
            assert wait_until(
                lambda: delivered == ["first", "middle", "newest"], timeout=5
            )

        assert dispatcher.stats.dropped == 1
        assert "2 already waiting for s1" in caplog.text
        assert "oldest" not in delivered
        dispatcher.shutdown(timeout=5.0)

    def test_the_key_is_never_free_between_one_piece_of_work_and_the_next(
        self, work, monkeypatch
    ):
        """Regression (#62): the handover must not open a window.

        Finishing one piece of work and starting the one waiting behind it used
        to happen in two steps. In between, the key looked free, so a third
        submit started at once — and then the older one started too, and could
        be delivered after it.
        """
        from mongodb_session_manager.hooks import background_work

        delivered = []
        release_first = threading.Event()
        handover_reached = threading.Event()
        let_handover_finish = threading.Event()

        original_emit = background_work._Note.emit

        def gated_emit(note):
            # Freeze the moment right after the first one finished.
            if note.message.endswith("first"):
                handover_reached.set()
                assert let_handover_finish.wait(5)
            original_emit(note)

        monkeypatch.setattr(background_work._Note, "emit", gated_emit)

        async def first() -> None:
            await asyncio.to_thread(release_first.wait, 5)
            delivered.append("first")

        async def later(label: str) -> None:
            delivered.append(label)

        work.submit(first(), "delivering first", order_key="s1")
        assert wait_until(lambda: work.stats.in_flight == 1)
        work.submit(later("second"), "delivering second", order_key="s1")

        release_first.set()
        assert handover_reached.wait(timeout=5)
        # The window: another update for the same session arrives now.
        work.submit(later("third"), "delivering third", order_key="s1")
        let_handover_finish.set()

        assert wait_until(lambda: len(delivered) == 3, timeout=5)
        # The third one arrived while the key was changing hands, and still
        # queued behind the second instead of racing it.
        assert delivered == ["first", "second", "third"]
        assert wait_until(lambda: work.stats.in_flight == 0)

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


class TestClosingFromInsideTheLoop:
    """The blocking close cannot wait for work that needs the thread it blocks."""

    def test_shutdown_async_lets_the_loop_finish_its_work(self):
        delivered = []

        async def main() -> None:
            dispatcher = BackgroundWork()

            async def notify() -> None:
                await asyncio.sleep(0.05)
                delivered.append("done")

            dispatcher.submit(notify(), "notifying on this loop")
            report = await dispatcher.shutdown_async(timeout=2.0)

            assert delivered == ["done"]
            assert report.completed == 1
            assert report.cancelled == 0

        asyncio.run(main())

    def test_the_blocking_shutdown_warns_when_it_would_stall_its_own_work(self, caplog):
        async def main() -> None:
            dispatcher = BackgroundWork()

            async def notify() -> None:
                await asyncio.sleep(0.05)

            dispatcher.submit(notify(), "notifying on this loop")
            with caplog.at_level(logging.WARNING):
                dispatcher.shutdown(timeout=0.2)

        asyncio.run(main())

        assert "Use shutdown_async() here" in caplog.text

    def test_a_closed_loop_does_not_abort_the_close(self, caplog):
        """Cancelling through a loop that is gone must not escape."""
        dispatcher = BackgroundWork()
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        started = threading.Event()

        async def notify() -> None:
            started.set()
            await asyncio.sleep(30)

        dispatcher.submit(notify(), "riding a loop that closes", loop=loop)
        assert started.wait(timeout=5)

        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        close_stopped_loop(loop)

        with caplog.at_level(logging.WARNING):
            report = dispatcher.shutdown(timeout=0.3)

        # The close ran to the end and said what happened.
        assert report.in_flight == 0
        assert "Background work closed" in caplog.text


class TestStrandedWork:
    """A loop that goes away must not take a session's key with it."""

    def test_a_dead_loop_does_not_hold_its_key_forever(self, work, caplog):
        """Regression (#62): the done callback of stranded work never runs."""
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()

        async def notify() -> None:
            await asyncio.sleep(30)

        work.submit(notify(), "updating s1", loop=loop, order_key="s1")
        assert wait_until(lambda: work.stats.in_flight == 1)

        # The server loop stops without anybody closing the background work.
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)

        delivered = threading.Event()

        async def notify_again() -> None:
            delivered.set()

        with caplog.at_level(logging.WARNING):
            work.submit(notify_again(), "updating s1 again", loop=loop, order_key="s1")

        # Without the eviction this is dropped for a key that is busy forever.
        assert delivered.wait(timeout=5)
        assert wait_until(lambda: work.stats.in_flight == 0)
        assert work.stats.dropped == 0
        # The stranded notification is accounted for, not just forgotten.
        assert work.stats.cancelled == 1
        assert "updating s1" in caplog.text
        close_stopped_loop(loop)

    def test_stranded_guaranteed_work_is_reported_as_an_error(self, work, caplog):
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()

        async def notify() -> None:
            await asyncio.sleep(30)

        work.submit(
            notify(),
            "sending the feedback notification",
            loop=loop,
            delivery=Delivery.GUARANTEED,
        )
        assert wait_until(lambda: work.stats.in_flight == 1)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)

        async def anything() -> None:
            return None

        with caplog.at_level(logging.WARNING):
            work.submit(anything(), "anything at all", loop=loop)

        errors = [r for r in caplog.records if r.levelname == "ERROR"]
        assert any("sending the feedback notification" in r.message for r in errors)
        close_stopped_loop(loop)


class TestGuaranteedLossIsLouder:
    """What is guaranteed against the limit is still reported when lost."""

    def test_a_cancelled_guaranteed_notification_is_an_error(self, caplog):
        dispatcher = BackgroundWork()
        started = threading.Event()

        async def notify() -> None:
            started.set()
            await asyncio.sleep(30)

        with caplog.at_level(logging.WARNING):
            dispatcher.submit(
                notify(),
                "sending the feedback notification",
                delivery=Delivery.GUARANTEED,
            )
            assert started.wait(timeout=5)
            dispatcher.shutdown(timeout=0.2)

        errors = [r for r in caplog.records if r.levelname == "ERROR"]
        assert any("sending the feedback notification" in r.message for r in errors)

    def test_a_cancelled_best_effort_notification_is_a_warning(self, caplog):
        dispatcher = BackgroundWork()
        started = threading.Event()

        async def notify() -> None:
            started.set()
            await asyncio.sleep(30)

        with caplog.at_level(logging.WARNING):
            dispatcher.submit(notify(), "sending the metadata update")
            assert started.wait(timeout=5)
            dispatcher.shutdown(timeout=0.2)

        ours = [r for r in caplog.records if "sending the metadata update" in r.message]
        assert ours and all(r.levelname == "WARNING" for r in ours)


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
        """End to end: a script that dispatches and exits delivers its work.

        The notification does its blocking call with `asyncio.to_thread`, like
        the bundled hooks. That is the case an `atexit` cannot drain — by then
        the thread pools are closed — and the reason the close is registered
        with `threading._register_atexit()` instead.
        """
        delivered = tmp_path / "delivered.txt"
        script = textwrap.dedent(f"""
            import asyncio
            import time
            from pathlib import Path

            from mongodb_session_manager.hooks.utils_async import dispatch_async

            out = Path({str(delivered)!r})

            def blocking(i):
                time.sleep(0.2)
                with out.open("a") as fh:
                    fh.write(f"{{i}}\\n")

            async def notify(i):
                await asyncio.to_thread(blocking, i)

            for i in range(20):
                dispatch_async(notify(i), "notifying before the close")
        """)
        # This interpreter, running a literal written right above it.
        result = subprocess.run(  # nosec B603
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
        )

        assert result.returncode == 0, result.stderr
        assert len(delivered.read_text().splitlines()) == 20
        assert "cannot schedule new futures" not in result.stderr


class TestForkedProcess:
    """A child of `fork()` inherits the object but not the threads running it."""

    def test_a_child_notifies_on_a_loop_of_its_own(self, tmp_path):
        """The parent's reserve loop is a thread the child does not have.

        Its loop object survives the fork and still claims to be running, so a
        child that took it at face value would accept the notification, hand it
        to nothing, and deliver it never. A prefork server (gunicorn with
        `--preload`) is exactly that child.
        """
        delivered = tmp_path / "delivered.txt"
        script = textwrap.dedent(f"""
            import os
            import sys
            from pathlib import Path

            from mongodb_session_manager.hooks.utils_async import (
                dispatch_async,
                shutdown_hooks,
            )

            out = Path({str(delivered)!r})

            async def notify(who):
                with out.open("a") as fh:
                    fh.write(f"{{who}}\\n")

            # Starts the reserve loop and its thread, in the parent.
            dispatch_async(notify("parent"), "notifying from the parent").result(5)

            if os.fork() == 0:
                handle = dispatch_async(notify("child"), "notifying from the child")
                try:
                    handle.result(timeout=5)
                finally:
                    shutdown_hooks(timeout=2)
                os._exit(0)

            os.wait()
        """)
        # This interpreter, running a literal written right above it.
        result = subprocess.run(  # nosec B603
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
        )

        assert result.returncode == 0, result.stderr
        assert sorted(delivered.read_text().split()) == ["child", "parent"]

    def test_a_child_does_not_inherit_the_parents_counters(self, tmp_path):
        """What the parent dispatched is the parent's; the child starts at zero."""
        counters = tmp_path / "counters.txt"
        script = textwrap.dedent(f"""
            import os
            from pathlib import Path

            from mongodb_session_manager.hooks.utils_async import (
                dispatch_async,
                hooks_background_stats,
            )

            async def notify():
                return None

            dispatch_async(notify(), "notifying from the parent").result(5)

            if os.fork() == 0:
                Path({str(counters)!r}).write_text(str(hooks_background_stats()))
                os._exit(0)

            os.wait()
        """)
        result = subprocess.run(  # nosec B603
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
        )

        assert result.returncode == 0, result.stderr
        assert "dispatched=0" in counters.read_text()


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
