"""The lifecycle of the work the hooks leave running in the background.

A hook writes first and notifies after: the notification travels on its own and
the caller does not wait for it. That leaves work in flight, and this module is
what bounds it — how much may run at once, where it runs when there is no event
loop to hand it to, in what order, and what happens to whatever is still running
when the process closes.

Four rules, in the order they apply:

1. **One reserve loop, not one thread per event.** Without a loop to dispatch
   to, the work goes to a single event loop of the library's own, running in a
   daemon thread created the first time it is needed.
2. **A bounded number of notifications in flight.** Past the limit, best-effort
   work is refused: the coroutine is closed, a WARNING names what was dropped,
   and a counter records it.
3. **Order where it was asked for.** Work submitted with an `order_key` — the
   session, for the metadata hooks — never runs concurrently with other work
   for that same key, and never overtakes it. At most one piece of work per key
   waits its turn; a newer one replaces the one waiting, because for a metadata
   update the last state is the only one that matters. The replaced work is
   dropped loudly, never delivered late.
4. **A shutdown that says what happened.** `shutdown()` waits for the work in
   flight, cancels what does not make it in time, and returns the counters.

`Delivery.GUARANTEED` opts out of rule 2: feedback notifications carry a
customer complaint, and losing one loses the complaint with no trace. They are
accepted over the limit — loudly — rather than dropped.

A note on cancellation: the bundled hooks make their AWS call with
`asyncio.to_thread`, and cancelling a task blocked on a thread does not
interrupt the call itself — it stops the waiting. Bounding the client's own
timeouts is what bounds that thread.
"""

import asyncio
import logging
import threading
import time
from collections.abc import Coroutine
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum
from functools import partial
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_IN_FLIGHT = 64
DEFAULT_SHUTDOWN_TIMEOUT = 5.0

# How often the shutdown looks at the work still in flight.
_DRAIN_POLL_SECONDS = 0.01
# Grace for the done callbacks of cancelled work to run before reporting.
_CANCEL_GRACE_SECONDS = 1.0

Handle = asyncio.Task | Future


class Delivery(Enum):
    """What the caller is willing to lose.

    BEST_EFFORT: dropped when the work in flight reaches the limit. The next
        write corrects it — a metadata update, a progress refresh.
    GUARANTEED: never dropped. Accepted over the limit, with a WARNING, because
        losing it loses information that nothing else will produce again.
    """

    BEST_EFFORT = "best-effort"
    GUARANTEED = "guaranteed"


@dataclass(frozen=True)
class BackgroundWorkStats:
    """What the background work has done, and what it is doing right now."""

    dispatched: int
    completed: int
    failed: int
    cancelled: int
    dropped: int
    in_flight: int
    queued: int

    def as_dict(self) -> dict[str, int]:
        """Return the counters as a plain dict, for logs and metrics."""
        return {
            "dispatched": self.dispatched,
            "completed": self.completed,
            "failed": self.failed,
            "cancelled": self.cancelled,
            "dropped": self.dropped,
            "in_flight": self.in_flight,
            "queued": self.queued,
        }


@dataclass
class _InFlight:
    """One piece of work: what it was doing, where it runs, under what key."""

    error_context: str
    loop: asyncio.AbstractEventLoop
    order_key: str | None = None
    task: asyncio.Task | None = None


@dataclass
class _Waiting:
    """Work held back so it does not overtake the work ahead of it."""

    coro: Coroutine[Any, Any, Any]
    error_context: str
    loop: asyncio.AbstractEventLoop
    order_key: str


@dataclass
class _Counters:
    dispatched: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    dropped: int = 0


class _ReserveLoop:
    """One event loop in a daemon thread, shared by every dispatch without one.

    Created the first time something needs it, so a process that never notifies
    never pays for it.
    """

    THREAD_NAME = "mongodb-session-manager-hooks"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def get(self) -> asyncio.AbstractEventLoop:
        """Return the shared loop, starting its thread on first use."""
        with self._lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                thread = threading.Thread(
                    target=self._run, args=(loop,), name=self.THREAD_NAME, daemon=True
                )
                thread.start()
                self._loop, self._thread = loop, thread
            return self._loop

    def stop(self, timeout: float) -> None:
        """Stop the loop and its thread, if they were ever started."""
        with self._lock:
            loop, thread = self._loop, self._thread
            self._loop, self._thread = None, None

        if loop is None or thread is None:
            return

        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=timeout)
        if not thread.is_alive():
            loop.close()

    @staticmethod
    def _run(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()


class BackgroundWork:
    """Bounded background work with an order guarantee and an explicit close.

    Args:
        max_in_flight: How many notifications may run at once. Past it,
            best-effort work is dropped and counted rather than queued without
            end.
    """

    def __init__(self, max_in_flight: int = DEFAULT_MAX_IN_FLIGHT) -> None:
        self._max_in_flight = max_in_flight
        # Reentrant: work that finishes before its callback is attached runs
        # that callback in this very thread, inside `submit()`.
        self._lock = threading.RLock()
        self._in_flight: dict[Handle, _InFlight] = {}
        self._waiting: dict[str, _Waiting] = {}
        self._busy_keys: set[str] = set()
        self._counters = _Counters()
        self._closed = False
        self._reserve = _ReserveLoop()

    @property
    def max_in_flight(self) -> int:
        """The ceiling on best-effort work running at once."""
        return self._max_in_flight

    @property
    def stats(self) -> BackgroundWorkStats:
        """A snapshot of the counters."""
        with self._lock:
            counters = self._counters
            return BackgroundWorkStats(
                dispatched=counters.dispatched,
                completed=counters.completed,
                failed=counters.failed,
                cancelled=counters.cancelled,
                dropped=counters.dropped,
                in_flight=len(self._in_flight),
                queued=len(self._waiting),
            )

    def submit(
        self,
        coro: Coroutine[Any, Any, Any],
        error_context: str,
        loop: asyncio.AbstractEventLoop | None = None,
        *,
        order_key: str | None = None,
        delivery: Delivery = Delivery.BEST_EFFORT,
    ) -> Handle | None:
        """Run a coroutine in the background without blocking the caller.

        Args:
            coro: The coroutine to run.
            error_context: What it was doing, for the logs. It reads inside
                sentences: "Error <error_context>", "Cancelled while
                <error_context>".
            loop: The loop to run it on. Given one, the dispatch does not depend
                on the calling thread. Without one, a loop running in the
                calling thread takes it; failing that, the reserve loop does.
            order_key: Work sharing a key runs one at a time and in order. Only
                the most recent piece of work waits per key; an older one still
                waiting is dropped rather than delivered late.
            delivery: Whether this work may be dropped when the limit is
                reached.

        Returns:
            A handle on the work, None when it was refused, and None as well
            when it is waiting its turn behind work with the same `order_key`.
            A refusal is always logged and counted.
        """
        with self._lock:
            if self._closed:
                return self._refuse(
                    coro, error_context, "the background work is closed"
                )

            try:
                target = self._resolve_loop(loop, error_context)
            except Exception as e:
                # The hook already did its write; a broken dispatch must not
                # undo it.
                logger.error(f"Error dispatching hook while {error_context}: {e}")
                coro.close()
                return None

            if order_key is not None and order_key in self._busy_keys:
                self._hold_back(coro, error_context, target, order_key)
                return None

            if self._is_full() and delivery is Delivery.BEST_EFFORT:
                return self._refuse(
                    coro,
                    error_context,
                    f"{self._max_in_flight} notifications already in flight",
                )

            if self._is_full():
                logger.warning(
                    f"Accepting guaranteed hook work over the limit of "
                    f"{self._max_in_flight} while {error_context}"
                )

            return self._start(coro, error_context, target, order_key)

    def shutdown(
        self, timeout: float = DEFAULT_SHUTDOWN_TIMEOUT
    ) -> BackgroundWorkStats:
        """Close the background work, draining what it can.

        Waits up to `timeout` for the work in flight — work still waiting its
        turn included, since its turn may well come inside the budget — cancels
        whatever is left, and stops the reserve loop. Work submitted afterwards
        is refused.

        Args:
            timeout: Seconds to wait for the work in flight before cancelling.
                It is the budget for the whole close, not for each step of it.

        Returns:
            The counters as they stand once it is closed.
        """
        deadline = time.monotonic() + timeout
        with self._lock:
            already_closed = self._closed
            self._closed = True

        self._drain(deadline)
        self._drop_waiting("the background work is closing")
        self._cancel_leftovers()
        self._reserve.stop(timeout=max(deadline - time.monotonic(), 0.0))

        stats = self.stats
        if not already_closed and (stats.cancelled or stats.in_flight):
            logger.warning(
                f"Background work closed with {stats.cancelled} cancelled and "
                f"{stats.in_flight} still in flight: {stats.as_dict()}"
            )
        return stats

    def _is_full(self) -> bool:
        return len(self._in_flight) >= self._max_in_flight

    def _refuse(
        self,
        coro: Coroutine[Any, Any, Any],
        error_context: str,
        reason: str,
    ) -> None:
        """Drop work that cannot be taken, loudly and counted."""
        self._counters.dropped += 1
        logger.warning(f"Dropped hook work while {error_context}: {reason}")
        coro.close()
        return None

    def _hold_back(
        self,
        coro: Coroutine[Any, Any, Any],
        error_context: str,
        loop: asyncio.AbstractEventLoop,
        order_key: str,
    ) -> None:
        """Keep work behind the work already running for its key."""
        superseded = self._waiting.get(order_key)
        if superseded is not None:
            self._refuse(
                superseded.coro,
                superseded.error_context,
                f"superseded by newer work for {order_key}",
            )

        self._waiting[order_key] = _Waiting(
            coro=coro, error_context=error_context, loop=loop, order_key=order_key
        )

    def _resolve_loop(
        self, loop: asyncio.AbstractEventLoop | None, error_context: str
    ) -> asyncio.AbstractEventLoop:
        """Pick the loop this work runs on, preferring the one given."""
        if loop is not None:
            if loop.is_closed():
                logger.warning(
                    f"Event loop already closed while {error_context}; "
                    "falling back to the reserve loop"
                )
            elif loop.is_running() or loop is _running_loop():
                return loop
            else:
                logger.warning(
                    f"Event loop not running while {error_context}; "
                    "falling back to the reserve loop"
                )

        running = _running_loop()
        if running is not None:
            return running
        return self._reserve.get()

    def _start(
        self,
        coro: Coroutine[Any, Any, Any],
        error_context: str,
        target: asyncio.AbstractEventLoop,
        order_key: str | None,
    ) -> Handle | None:
        """Hand the coroutine to its loop and register it as in flight."""
        record = _InFlight(
            error_context=error_context, loop=target, order_key=order_key
        )
        tracked = self._track(coro, record)

        handle = self._hand_over(tracked, target, error_context)
        if handle is None:
            # The loop can go away between the check and the handover; the
            # reserve loop is always ours to reach.
            reserve = self._reserve.get()
            if reserve is not target:
                handle = self._hand_over(tracked, reserve, error_context)
                record.loop = reserve

        if handle is None:
            logger.error(f"Error dispatching hook while {error_context}")
            tracked.close()
            coro.close()
            return None

        self._counters.dispatched += 1
        self._in_flight[handle] = record
        if order_key is not None:
            self._busy_keys.add(order_key)
        handle.add_done_callback(partial(self._finish, error_context=error_context))
        return handle

    @staticmethod
    def _hand_over(
        tracked: Coroutine[Any, Any, Any],
        target: asyncio.AbstractEventLoop,
        error_context: str,
    ) -> Handle | None:
        """Give the coroutine to a loop, or None if that loop cannot take it."""
        try:
            if target is _running_loop():
                # A loop runs in this very thread: stay on it rather than hop.
                return target.create_task(tracked)
            return asyncio.run_coroutine_threadsafe(tracked, target)
        except Exception as e:
            logger.warning(
                f"Could not reach the event loop while {error_context} ({e}); "
                "falling back to the reserve loop"
            )
            return None

    async def _track(self, coro: Coroutine[Any, Any, Any], record: _InFlight) -> Any:
        """Record the task running this work, so it can be cancelled by name."""
        record.task = asyncio.current_task()
        return await coro

    def _finish(self, handle: Handle, error_context: str) -> None:
        """Count how the work ended, then let its key move on."""
        with self._lock:
            record = self._in_flight.pop(handle, None)
            self._count_outcome(handle, error_context)

            if record is None or record.order_key is None:
                return
            self._busy_keys.discard(record.order_key)
            waiting = self._waiting.pop(record.order_key, None)

        if waiting is not None:
            self._release(waiting)

    def _count_outcome(self, handle: Handle, error_context: str) -> None:
        """Report the outcome instead of discarding it."""
        if handle.cancelled():
            self._counters.cancelled += 1
            logger.warning(f"Cancelled while {error_context}")
            return

        exception = handle.exception()
        if exception is not None:
            self._counters.failed += 1
            if _is_interpreter_closing(exception):
                # Python shuts its thread pools down before any atexit of ours
                # runs, so work that had not reached one cannot get there. It
                # is not a fault in the hook, and its traceback says nothing.
                logger.warning(
                    f"Not delivered while {error_context}: the process was closing"
                )
                return
            logger.error(f"Error {error_context}: {exception}", exc_info=exception)
            return

        self._counters.completed += 1

    def _release(self, waiting: _Waiting) -> None:
        """Start the work that was held back, now that its turn came.

        A close in progress does not stop it: this work was accepted before the
        close and its turn arrived inside the drain. What the close refuses is
        work submitted after it, and `_drop_waiting()` takes care of whatever
        never got a turn in time.
        """
        with self._lock:
            self._start(
                waiting.coro, waiting.error_context, waiting.loop, waiting.order_key
            )

    def _drain(self, deadline: float) -> None:
        """Wait for the work in flight, and its queue, until the deadline."""
        while time.monotonic() < deadline:
            with self._lock:
                if not self._in_flight and not self._waiting:
                    return
            time.sleep(_DRAIN_POLL_SECONDS)

    def _drop_waiting(self, reason: str) -> None:
        """Drop work that never got its turn, rather than leave it unawaited."""
        with self._lock:
            waiting = list(self._waiting.values())
            self._waiting.clear()

        for item in waiting:
            with self._lock:
                self._refuse(item.coro, item.error_context, reason)

    def _cancel_leftovers(self) -> None:
        """Cancel whatever did not finish, and let its callbacks report."""
        with self._lock:
            leftovers = list(self._in_flight.items())

        if not leftovers:
            return

        for handle, record in leftovers:
            if record.task is not None:
                record.loop.call_soon_threadsafe(record.task.cancel)
            else:
                handle.cancel()

        self._drain(deadline=time.monotonic() + _CANCEL_GRACE_SECONDS)


def _is_interpreter_closing(exception: BaseException) -> bool:
    """Whether the work failed because Python itself was shutting down."""
    return isinstance(exception, RuntimeError) and "interpreter shutdown" in str(
        exception
    )


def _running_loop() -> asyncio.AbstractEventLoop | None:
    """The event loop running in the calling thread, if there is one."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None
