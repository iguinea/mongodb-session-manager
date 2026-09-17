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
   for that same key, and never overtakes it. The rest waits its turn in a
   queue, in the order it was submitted; only when that queue is full does the
   oldest give way, loudly.
4. **A shutdown that says what happened.** `shutdown()` waits for the work in
   flight, cancels what does not make it in time, and returns the counters.

`Delivery.GUARANTEED` opts out of rule 2, and only of rule 2: feedback
notifications carry a customer complaint, and losing one loses the complaint
with no trace. They are accepted over the limit — loudly — rather than dropped.
A close that runs out of time still cancels them, but never quietly: that is
reported as an error, not as a warning.

A note on cancellation: the bundled hooks make their AWS call with
`asyncio.to_thread`, and cancelling a task blocked on a thread does not
interrupt the call itself — it stops the waiting. Bounding the client's own
timeouts is what bounds that thread.
"""

import asyncio
import atexit
import logging
import threading
import time
from collections import deque
from collections.abc import Coroutine
from concurrent.futures import Future
from dataclasses import asdict, dataclass
from enum import Enum
from functools import partial
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_IN_FLIGHT = 64
DEFAULT_SHUTDOWN_TIMEOUT = 5.0
# How many notifications may wait their turn for one key. Deep enough for the
# bursts seen in practice (three updates in a row on one session), shallow
# enough that a stuck key cannot hoard memory.
DEFAULT_MAX_QUEUED_PER_KEY = 8

# How often the shutdown looks at the work still in flight.
_DRAIN_POLL_SECONDS = 0.01
# Grace for the done callbacks of cancelled work to run before reporting.
_CANCEL_GRACE_SECONDS = 1.0
# The floor of that grace, used when the close has already spent its budget.
_MIN_CANCEL_GRACE_SECONDS = 0.05
# What stopping the reserve loop gets, regardless of the budget left.
_RESERVE_STOP_SECONDS = 1.0

Handle = asyncio.Task | Future


class Delivery(Enum):
    """What the caller is willing to lose when the limit is reached.

    BEST_EFFORT: dropped once the work in flight reaches the limit. The next
        write corrects it — a metadata update, a progress refresh.
    GUARANTEED: never dropped for being over the limit; accepted past it, with
        a WARNING, because losing it loses information nothing produces again.
        It is not a delivery receipt: a process that dies, or a close that runs
        out of time, still loses it — but says so as an error.
    """

    BEST_EFFORT = "best-effort"
    GUARANTEED = "guaranteed"


@dataclass(frozen=True)
class BackgroundWorkStats:
    """What the background work has done, and what it is doing right now.

    `completed` counts coroutines that returned, not notifications AWS took:
    the bundled hooks catch their own errors, so one that fails to publish
    still returns. `dispatched`, `dropped`, `cancelled`, `in_flight` and
    `queued` are this module's own doing and say exactly what they mean.
    """

    dispatched: int
    completed: int
    failed: int
    cancelled: int
    dropped: int
    in_flight: int
    queued: int

    def as_dict(self) -> dict[str, int]:
        """Return the counters as a plain dict, for logs and metrics."""
        return asdict(self)


@dataclass(frozen=True)
class _Note:
    """A line for the log, composed under the lock and emitted outside it.

    Logging is not cheap — a traceback costs tens of microseconds — and this
    lock is shared by every hook in the process, `_finish()` included, which
    runs on the event loop. Formatting a failure inside it would let a stalled
    AWS endpoint stall the loop.
    """

    level: int
    message: str
    exception: BaseException | None = None

    def emit(self) -> None:
        logger.log(self.level, self.message, exc_info=self.exception)


@dataclass
class _InFlight:
    """One piece of work: what it was doing, where it runs, under what key."""

    error_context: str
    loop: asyncio.AbstractEventLoop
    order_key: str | None = None
    delivery: Delivery = Delivery.BEST_EFFORT
    # Both coroutines handed to the loop — the tracking wrapper and the hook's
    # own — kept so they can be closed if that loop dies before running them.
    # Closing the wrapper does not close what it never awaited.
    unstarted: tuple[Coroutine[Any, Any, Any], ...] = ()
    task: asyncio.Task | None = None


@dataclass
class _Waiting:
    """Work held back so it does not overtake the work ahead of it.

    It keeps the loop resolved when it was submitted, which is the caller's:
    its turn arrives from the callback of the work ahead, running on *that*
    work's loop, and resolving it there would hand it to a loop its caller
    never chose. A loop that dies in between is caught at handover, where the
    reserve loop takes over.
    """

    coro: Coroutine[Any, Any, Any]
    error_context: str
    loop: asyncio.AbstractEventLoop
    delivery: Delivery


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

    def reset_after_fork(self) -> None:
        """Forget the inherited loop: the thread running it did not survive.

        Not closed, only dropped. Closing it would run its shutdown against
        file descriptors the parent is still using, and the loop believes it is
        running anyway. The next `get()` starts a loop that belongs to this
        process.
        """
        self._lock = threading.Lock()
        self._loop = None
        self._thread = None

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
        max_queued_per_key: How many notifications may wait their turn for one
            `order_key`. Past it the oldest is dropped, so a key that stops
            draining cannot grow without bound.
    """

    def __init__(
        self,
        max_in_flight: int = DEFAULT_MAX_IN_FLIGHT,
        max_queued_per_key: int = DEFAULT_MAX_QUEUED_PER_KEY,
    ) -> None:
        self._max_in_flight = max_in_flight
        self._max_queued_per_key = max_queued_per_key
        # Reentrant: work that finishes before its callback is attached runs
        # that callback in this very thread, inside `submit()`.
        self._lock = threading.RLock()
        self._in_flight: dict[Handle, _InFlight] = {}
        self._waiting: dict[str, deque[_Waiting]] = {}
        self._counters = _Counters()
        self._closed = False
        self._reserve = _ReserveLoop()

    def reset_after_fork(self) -> None:
        """Start over in a child process, forgetting what the parent left it.

        `os.fork()` copies this object whole but keeps only the forking thread.
        The reserve loop's thread is gone while its loop still answers
        `is_running()`, so a child that trusted it would accept notifications
        and deliver none. A lock another thread held at the fork stays locked
        for good, so it is replaced rather than reused. The work in flight
        belongs to the parent, which is still running it: the child forgets it
        instead of cancelling work it does not own.

        Public because the process-wide instance hands it to
        `os.register_at_fork()`. `_closed` is left alone: a child of a closed
        parent stays closed.
        """
        self._lock = threading.RLock()
        self._reserve.reset_after_fork()
        self._close_unstarted(list(self._in_flight.items()))
        self._in_flight.clear()
        for queue in self._waiting.values():
            for waiting in queue:
                waiting.coro.close()
        self._waiting.clear()
        self._counters = _Counters()

    @property
    def stats(self) -> BackgroundWorkStats:
        """A snapshot of the counters."""
        with self._lock:
            return BackgroundWorkStats(
                **asdict(self._counters),
                in_flight=len(self._in_flight),
                queued=sum(len(queue) for queue in self._waiting.values()),
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
            order_key: Work sharing a key runs one at a time and in order. What
                cannot start yet queues behind it, up to `max_queued_per_key`;
                past that the oldest is dropped, loudly — including guaranteed
                work, which the order guarantee outranks.
            delivery: Whether this work may be dropped for being over the limit.

        Returns:
            A handle on the work, None when it was refused, and None as well
            when it is waiting its turn behind work with the same `order_key`.
            A refusal is always logged and counted.
        """
        notes: list[_Note] = []
        try:
            with self._lock:
                return self._admit(
                    coro, error_context, loop, order_key, delivery, notes
                )
        finally:
            for note in notes:
                note.emit()

    def shutdown(
        self, timeout: float = DEFAULT_SHUTDOWN_TIMEOUT
    ) -> BackgroundWorkStats:
        """Close the background work, draining what it can.

        Waits up to `timeout` for the work in flight — work still waiting its
        turn included, since its turn may well come inside the budget — cancels
        whatever is left, and stops the reserve loop. Work submitted afterwards
        is refused.

        This waits by blocking the calling thread. **Do not call it from an
        event loop that is carrying notifications**: blocking that loop stops
        the very work being waited for, so the drain burns the whole timeout
        and then cancels everything it could have delivered. Inside a loop —
        a FastAPI lifespan, an async signal handler — use `shutdown_async()`.
        Called that way, this logs a warning and drains what it can.

        Args:
            timeout: Seconds to wait for the work in flight before cancelling.
                The budget for the whole close, give or take the short grace
                the cancellations need to be counted.

        Returns:
            The counters as they stand once it is closed.
        """
        deadline = time.monotonic() + timeout
        already_closed = self._begin_close()
        self._warn_if_blocking_its_own_work()

        self._drain(deadline)
        leftovers = self._cancel_what_is_left()
        self._drain(self._grace_deadline(deadline))
        self._close_unstarted(leftovers)
        return self._close_report(already_closed)

    async def shutdown_async(
        self, timeout: float = DEFAULT_SHUTDOWN_TIMEOUT
    ) -> BackgroundWorkStats:
        """Close the background work from inside an event loop.

        Same as `shutdown()`, except that it waits with `await` instead of
        blocking — so the loop keeps running, and notifications riding it can
        actually finish before the deadline.

        Args:
            timeout: Seconds to wait for the work in flight before cancelling.

        Returns:
            The counters as they stand once it is closed.
        """
        deadline = time.monotonic() + timeout
        already_closed = self._begin_close()

        await self._drain_async(deadline)
        leftovers = self._cancel_what_is_left()
        await self._drain_async(self._grace_deadline(deadline))
        self._close_unstarted(leftovers)
        return self._close_report(already_closed)

    def _begin_close(self) -> bool:
        """Stop taking work. Returns whether it was already closed."""
        with self._lock:
            already_closed = self._closed
            self._closed = True
        return already_closed

    def _cancel_what_is_left(self) -> list[tuple[Handle, _InFlight]]:
        """Drop what never got its turn and cancel what did not finish.

        Returns what was cancelled, so the close can tidy up after the grace.
        """
        self._drop_waiting("the background work is closing")
        return self._cancel_leftovers()

    @staticmethod
    def _close_unstarted(leftovers: list[tuple[Handle, _InFlight]]) -> None:
        """Close the coroutines of work that was cancelled before it ran.

        A cancelled task never executes, so `_track()` never awaits the hook's
        coroutine and nothing else will ever close it. Checked after the grace,
        by which point a task that was going to start already has.
        """
        for _, record in leftovers:
            if record.task is not None:
                continue
            for pending in record.unstarted:
                pending.close()

    @staticmethod
    def _grace_deadline(deadline: float) -> float:
        """When to stop waiting for the cancellation callbacks to report.

        Inside the budget if there is any left, and a floor of
        `_MIN_CANCEL_GRACE_SECONDS` if there is not: a close that reported
        numbers taken before its own cancellations landed would be lying.
        """
        now = time.monotonic()
        return min(
            max(deadline, now + _MIN_CANCEL_GRACE_SECONDS),
            now + _CANCEL_GRACE_SECONDS,
        )

    def _close_report(self, already_closed: bool) -> BackgroundWorkStats:
        """Stop the reserve loop and report how the close went."""
        # Its own small budget: by here the timeout may be spent, and a loop
        # left unclosed leaks its thread and its self-pipe.
        self._reserve.stop(timeout=_RESERVE_STOP_SECONDS)

        stats = self.stats
        if not already_closed and (stats.cancelled or stats.in_flight):
            logger.warning(
                f"Background work closed with {stats.cancelled} cancelled and "
                f"{stats.in_flight} still in flight: {stats.as_dict()}"
            )
        return stats

    def _warn_if_blocking_its_own_work(self) -> None:
        """Warn when the blocking close runs on a loop carrying notifications."""
        running = _running_loop()
        if running is None:
            return

        with self._lock:
            stuck = sum(1 for item in self._in_flight.values() if item.loop is running)

        if stuck:
            logger.warning(
                f"shutdown() called from the event loop carrying {stuck} "
                "notifications: blocking it stops the very work being waited "
                "for. Use shutdown_async() here."
            )

    def _admit(
        self,
        coro: Coroutine[Any, Any, Any],
        error_context: str,
        loop: asyncio.AbstractEventLoop | None,
        order_key: str | None,
        delivery: Delivery,
        notes: list[_Note],
    ) -> Handle | None:
        """Decide what happens to this work. Called with the lock held."""
        if self._closed:
            notes.append(
                self._refuse(
                    coro, error_context, "the background work is closed", delivery
                )
            )
            return None

        try:
            # Resolved before anything else, even for work that will only
            # wait, for two reasons. A loop that died strands the work riding
            # it, and that work holds the very key the check below is about to
            # consult. And the resolution belongs to the caller's thread: by
            # the time a waiting turn comes, the thread asking is the one that
            # finished the work ahead.
            target = self._resolve_loop(loop, error_context, notes)
        except Exception as e:
            # The hook already did its write; a broken dispatch must not undo it.
            notes.append(
                _Note(
                    logging.ERROR,
                    f"Error dispatching hook while {error_context}: {e}",
                )
            )
            coro.close()
            return None

        if order_key is not None and self._is_busy(order_key):
            self._hold_back(coro, error_context, target, order_key, delivery, notes)
            return None

        if self._is_full():
            if delivery is Delivery.BEST_EFFORT:
                notes.append(
                    self._refuse(
                        coro,
                        error_context,
                        f"{self._max_in_flight} notifications already in flight",
                        delivery,
                    )
                )
                return None
            notes.append(
                _Note(
                    logging.WARNING,
                    f"Accepting guaranteed hook work over the limit of "
                    f"{self._max_in_flight} while {error_context}",
                )
            )

        return self._start(coro, error_context, target, order_key, delivery, notes)

    def _is_full(self) -> bool:
        return len(self._in_flight) >= self._max_in_flight

    def _is_busy(self, order_key: str) -> bool:
        """Whether work for this key is already running.

        Derived from the work in flight rather than tracked alongside it: one
        source of truth cannot fall out of step with itself.
        """
        return any(item.order_key == order_key for item in self._in_flight.values())

    def _refuse(
        self,
        coro: Coroutine[Any, Any, Any],
        error_context: str,
        reason: str,
        delivery: Delivery,
    ) -> _Note:
        """Drop work that cannot be taken, counted, and say so at its own level."""
        self._counters.dropped += 1
        coro.close()
        level = logging.ERROR if delivery is Delivery.GUARANTEED else logging.WARNING
        return _Note(level, f"Dropped hook work while {error_context}: {reason}")

    def _hold_back(
        self,
        coro: Coroutine[Any, Any, Any],
        error_context: str,
        loop: asyncio.AbstractEventLoop,
        order_key: str,
        delivery: Delivery,
        notes: list[_Note],
    ) -> None:
        """Queue work behind the work already running for its key.

        In order, and without dropping what is already queued. Keeping only the
        newest would be right if each notification carried the whole state, but
        the metadata hooks publish the *dict the caller passed* — a partial
        update. Dropping `{"progress": 50}` because `{"status": "done"}` came
        after it loses `progress` for good: no later message carries it.

        The queue is bounded all the same. Once it is full the oldest goes,
        loudly: past that depth the key is stuck, and the newest state is the
        one worth keeping.
        """
        queue = self._waiting.setdefault(order_key, deque())
        if len(queue) >= self._max_queued_per_key:
            oldest = queue.popleft()
            notes.append(
                self._refuse(
                    oldest.coro,
                    oldest.error_context,
                    f"{self._max_queued_per_key} already waiting for {order_key}",
                    oldest.delivery,
                )
            )

        queue.append(
            _Waiting(
                coro=coro,
                error_context=error_context,
                loop=loop,
                delivery=delivery,
            )
        )

    def _resolve_loop(
        self,
        loop: asyncio.AbstractEventLoop | None,
        error_context: str,
        notes: list[_Note],
    ) -> asyncio.AbstractEventLoop:
        """Pick the loop this work runs on, preferring the one given."""
        if loop is not None:
            if loop.is_running() or loop is _running_loop():
                return loop
            # The loop is gone, and so is every notification that was riding
            # it: their callbacks will never run to free their keys.
            self._evict(loop, notes)
            state = "already closed" if loop.is_closed() else "not running"
            notes.append(
                _Note(
                    logging.WARNING,
                    f"Event loop {state} while {error_context}; "
                    "falling back to the reserve loop",
                )
            )

        return _running_loop() or self._reserve.get()

    def _evict(self, dead_loop: asyncio.AbstractEventLoop, notes: list[_Note]) -> None:
        """Forget work stranded on a loop that stopped without closing us.

        A loop that goes away without `shutdown()` leaves its work `PENDING`
        forever: the done callback never runs, so the budget it holds is never
        returned and its `order_key` stays busy — which would silently drop
        every later notification for that session.
        """
        stranded = [
            (handle, item)
            for handle, item in self._in_flight.items()
            if item.loop is dead_loop and not handle.done()
        ]
        for handle, item in stranded:
            # Cancelling a future whose loop is gone runs its done callback
            # right here; then `_finish()` has already counted and reported it.
            handle.cancel()
            if item.task is None:
                # It never started: the loop died before running it, so nothing
                # else will ever close it.
                for pending in item.unstarted:
                    pending.close()
            if self._in_flight.pop(handle, None) is None:
                continue

            self._counters.cancelled += 1
            level = (
                logging.ERROR
                if item.delivery is Delivery.GUARANTEED
                else logging.WARNING
            )
            notes.append(
                _Note(
                    level,
                    f"Stranded while {item.error_context}: its event loop "
                    "stopped before the notification was delivered",
                )
            )

    def _start(
        self,
        coro: Coroutine[Any, Any, Any],
        error_context: str,
        target: asyncio.AbstractEventLoop,
        order_key: str | None,
        delivery: Delivery,
        notes: list[_Note],
    ) -> Handle | None:
        """Hand the coroutine to its loop and register it as in flight."""
        record = _InFlight(
            error_context=error_context,
            loop=target,
            order_key=order_key,
            delivery=delivery,
        )
        tracked = self._track(coro, record)
        record.unstarted = (tracked, coro)

        handle = self._hand_over(tracked, target, error_context, notes)
        if handle is None:
            # The loop can go away between the check and the handover; the
            # reserve loop is always ours to reach.
            reserve = self._reserve.get()
            if reserve is not target:
                handle = self._hand_over(tracked, reserve, error_context, notes)
                record.loop = reserve

        if handle is None:
            notes.append(
                _Note(logging.ERROR, f"Error dispatching hook while {error_context}")
            )
            tracked.close()
            coro.close()
            return None

        self._counters.dispatched += 1
        self._in_flight[handle] = record
        handle.add_done_callback(partial(self._finish, error_context=error_context))
        return handle

    @staticmethod
    def _hand_over(
        tracked: Coroutine[Any, Any, Any],
        target: asyncio.AbstractEventLoop,
        error_context: str,
        notes: list[_Note],
    ) -> Handle | None:
        """Give the coroutine to a loop, or None if that loop cannot take it."""
        try:
            if target is _running_loop():
                # A loop runs in this very thread: stay on it rather than hop.
                return target.create_task(tracked)
            return asyncio.run_coroutine_threadsafe(tracked, target)
        except Exception as e:
            notes.append(
                _Note(
                    logging.WARNING,
                    f"Could not reach the event loop while {error_context} ({e}); "
                    "falling back to the reserve loop",
                )
            )
            return None

    async def _track(self, coro: Coroutine[Any, Any, Any], record: _InFlight) -> Any:
        """Record the task running this work, so it can be cancelled by name."""
        record.task = asyncio.current_task()
        return await coro

    def _finish(self, handle: Handle, error_context: str) -> None:
        """Count how the work ended and start whatever was waiting for its key.

        The handover happens inside the lock on purpose. Splitting it in two —
        release the lock, then start the next one — left a window in which the
        key belonged to neither: a submit landing there started at once, and
        then the one that had been waiting started too. Two notifications of
        one session in flight, and the older one could arrive last.

        Only the log lines are left outside: `_finish()` runs on the event
        loop, and formatting a traceback there costs more than the bookkeeping.
        """
        notes: list[_Note] = []
        with self._lock:
            record = self._in_flight.pop(handle, None)
            notes.append(self._count_outcome(handle, error_context, record))
            if record is not None and record.order_key is not None:
                self._start_next(record.order_key, notes)

        for note in notes:
            note.emit()

    def _start_next(self, order_key: str, notes: list[_Note]) -> None:
        """Hand the key to the work waiting for it. Called with the lock held."""
        queue = self._waiting.get(order_key)
        if not queue:
            self._waiting.pop(order_key, None)
            return

        waiting = queue.popleft()
        if not queue:
            self._waiting.pop(order_key, None)

        self._start(
            waiting.coro,
            waiting.error_context,
            waiting.loop,
            order_key,
            waiting.delivery,
            notes,
        )

    def _count_outcome(
        self, handle: Handle, error_context: str, record: _InFlight | None
    ) -> _Note:
        """Record the outcome and compose its line. Called with the lock held."""
        delivery = record.delivery if record is not None else Delivery.BEST_EFFORT
        lost_level = (
            logging.ERROR if delivery is Delivery.GUARANTEED else logging.WARNING
        )

        if handle.cancelled():
            self._counters.cancelled += 1
            return _Note(lost_level, f"Cancelled while {error_context}")

        exception = handle.exception()
        if exception is not None:
            self._counters.failed += 1
            if _thread_pool_is_closed(exception):
                # Python closes its thread pools on the way out, and the hooks
                # make their AWS call on one. Not a fault in the hook, and its
                # traceback says nothing.
                return _Note(
                    lost_level,
                    f"Not delivered while {error_context}: the process was closing",
                )
            return _Note(
                logging.ERROR, f"Error {error_context}: {exception}", exception
            )

        self._counters.completed += 1
        # "Finished", not "delivered": all this knows is that the coroutine
        # returned. The bundled hooks catch their own AWS errors and log them,
        # so a failed notification still lands here as completed.
        return _Note(logging.DEBUG, f"Finished: {error_context}")

    def _drain(self, deadline: float) -> None:
        """Wait for the work in flight, and its queue, until the deadline."""
        while time.monotonic() < deadline:
            with self._lock:
                if not self._in_flight and not self._waiting:
                    return
            time.sleep(_DRAIN_POLL_SECONDS)

    async def _drain_async(self, deadline: float) -> None:
        """Wait like `_drain()`, but yielding the loop instead of blocking it."""
        while time.monotonic() < deadline:
            with self._lock:
                if not self._in_flight and not self._waiting:
                    return
            await asyncio.sleep(_DRAIN_POLL_SECONDS)

    def _drop_waiting(self, reason: str) -> None:
        """Drop work that never got its turn, rather than leave it unawaited."""
        notes: list[_Note] = []
        with self._lock:
            waiting = [item for queue in self._waiting.values() for item in queue]
            self._waiting.clear()
            for item in waiting:
                notes.append(
                    self._refuse(item.coro, item.error_context, reason, item.delivery)
                )

        for note in notes:
            note.emit()

    def _cancel_leftovers(self) -> list[tuple[Handle, _InFlight]]:
        """Cancel whatever did not finish, and let its callbacks report."""
        with self._lock:
            leftovers = list(self._in_flight.items())

        for handle, record in leftovers:
            self._cancel_one(handle, record)
        return leftovers

    @staticmethod
    def _cancel_one(handle: Handle, record: _InFlight) -> None:
        """Cancel one piece of work, whatever state its loop is in."""
        if record.task is None:
            handle.cancel()
            return
        try:
            record.loop.call_soon_threadsafe(record.task.cancel)
        except RuntimeError:
            # The loop closed under it. Cancelling the handle is all that is
            # left, and letting this escape would abandon the rest of the close.
            handle.cancel()


def _thread_pool_is_closed(exception: BaseException) -> bool:
    """Whether the work failed because a thread pool would not take it.

    CPython words it two ways — "after shutdown" for a pool closed on purpose,
    "after interpreter shutdown" for the global close — and both mean the same
    to a notification: there is no thread left to make the call on.
    """
    return isinstance(exception, RuntimeError) and "cannot schedule new futures" in str(
        exception
    )


def _running_loop() -> asyncio.AbstractEventLoop | None:
    """The event loop running in the calling thread, if there is one."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def register_close_at_exit(close: Any) -> None:
    """Run `close` on the way out, before Python closes its thread pools.

    `atexit` is too late: by then `concurrent.futures` has already shut its
    pools down, and the hooks make their AWS call on one — a drain from there
    delivers almost nothing (measured: 1 of 20). `threading._register_atexit()`
    is the same hook `concurrent.futures` itself uses, and the handlers run in
    reverse order of registration, so ours must be registered *after* theirs to
    run *before* it.

    Hence the import below, which looks unused and is not: importing
    `concurrent.futures.thread` is what registers `_python_exit`, and
    `concurrent.futures` alone does not — it loads its executors lazily. Drop
    the import and the drain goes back to running too late.

    `threading._register_atexit` is private API, so a Python without it falls
    back to `atexit`, where the close still reports its counters even if it can
    no longer deliver.
    """
    import concurrent.futures.thread  # noqa: F401  registers _python_exit first

    register = getattr(threading, "_register_atexit", None)
    if register is None:  # pragma: no cover - every supported Python has it
        atexit.register(close)
        return
    register(close)
