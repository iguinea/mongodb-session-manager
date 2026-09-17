"""Shared async utilities for hooks.

The dispatch itself lives in `background_work`, which bounds how much of it may
run at once and closes it down on demand. This module is the entry point the
hooks use, on the process-wide instance.
"""

import asyncio
import atexit
import logging
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any

from .background_work import (
    DEFAULT_SHUTDOWN_TIMEOUT,
    BackgroundWork,
    BackgroundWorkStats,
    Delivery,
)

logger = logging.getLogger(__name__)

# How long a process that never called `shutdown_hooks()` waits on its way out.
# Short on purpose: it is a safety net, not the supported way to close.
ATEXIT_TIMEOUT = 2.0

# The background work of every hook in the process. One reserve loop, one
# limit, one close.
_background_work = BackgroundWork()


def _drain_at_exit() -> None:
    """Close the background work if the process never did it itself.

    A last resort, not a guarantee: Python closes its thread pools before any
    atexit runs, so a notification that had not yet reached one cannot be
    delivered from here. What this does give every process is a close that
    ends with the counters in the log instead of in silence.
    """
    stats = _background_work.shutdown(timeout=ATEXIT_TIMEOUT)
    if stats.dispatched:
        logger.info(f"Hook background work closed at exit: {stats.as_dict()}")


atexit.register(_drain_at_exit)


def capture_loop() -> asyncio.AbstractEventLoop | None:
    """Return the event loop running in this thread, or None if there is none."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def dispatch_async(
    coro: Coroutine[Any, Any, Any],
    error_context: str,
    loop: asyncio.AbstractEventLoop | None = None,
    *,
    order_key: str | None = None,
    delivery: Delivery = Delivery.BEST_EFFORT,
) -> asyncio.Task | Future | None:
    """Dispatch a coroutine without blocking the caller.

    Args:
        coro: The coroutine to run.
        error_context: What the coroutine was doing, for the failure log.
        loop: The event loop to run it on. Given one, the dispatch no longer
            depends on which thread calls it: the coroutine is handed to that
            loop with ``asyncio.run_coroutine_threadsafe()``. Hooks built
            inside a running loop capture it, so a call from a worker thread
            (Starlette's ``run_in_threadpool``, say) goes back to the server
            loop instead of a loop of the library's own.
        order_key: Work sharing a key runs one at a time and in order — the
            session id, for the metadata hooks, so two updates of the same
            session cannot arrive swapped. Only the newest waits per key; an
            older one still waiting is dropped rather than delivered late.
        delivery: ``Delivery.GUARANTEED`` for work that nothing will produce
            again, such as a feedback notification: it is accepted over the
            limit instead of dropped.

    Without a usable loop the work goes to a single reserve loop shared by the
    whole process, not to a thread of its own.

    Returns:
        A handle on the work — a ``Task`` or a ``concurrent.futures.Future`` —
        or None when the work was dropped or is waiting its turn. The outcome
        is logged either way; the handle is for callers that want the result.
    """
    return _background_work.submit(
        coro, error_context, loop, order_key=order_key, delivery=delivery
    )


def shutdown_hooks(timeout: float = DEFAULT_SHUTDOWN_TIMEOUT) -> BackgroundWorkStats:
    """Close the background work of the hooks, draining what it can.

    Call it where the process closes down — a FastAPI lifespan, a SIGTERM
    handler — before the event loop goes away. Notifications still in flight
    get `timeout` seconds to finish; whatever is left is cancelled and
    reported. Notifications dispatched afterwards are refused, loudly.

    Args:
        timeout: Seconds to wait for the work in flight before cancelling it.

    Returns:
        The counters as they stand once it is closed.
    """
    return _background_work.shutdown(timeout=timeout)


def hooks_background_stats() -> BackgroundWorkStats:
    """Return the counters of the hooks' background work.

    Useful as a metric or in a health endpoint: `dropped` growing means the
    limit is being hit, `in_flight` staying high means the notifications are
    slower than the events that produce them.
    """
    return _background_work.stats
