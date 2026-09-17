"""Shared async utilities for hooks.

The dispatch itself lives in `background_work`, which bounds how much of it may
run at once and closes it down on demand. This module is the entry point the
hooks use, on the process-wide instance.
"""

import asyncio
import logging
import os
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any

from .background_work import (
    DEFAULT_SHUTDOWN_TIMEOUT,
    BackgroundWork,
    BackgroundWorkStats,
    Delivery,
    _running_loop,
    register_close_at_exit,
)

logger = logging.getLogger(__name__)

# How long the drain of a process that never called `shutdown_hooks()` waits.
# Short on purpose: it is a safety net, not the supported way to close.
#
# It bounds the drain, not the exit. Right after it, Python joins the threads of
# its own pools, and cancelling a notification blocked on `asyncio.to_thread`
# stops the waiting without interrupting the AWS call underneath — so the exit
# still lasts as long as that call, which is what `aws_client_config` bounds.
ATEXIT_TIMEOUT = 2.0

# The background work of every hook in the process. One reserve loop, one
# limit, one close.
_background_work = BackgroundWork()


def _drain_at_exit() -> None:
    """Close the background work if the process never did it itself."""
    stats = _background_work.shutdown(timeout=ATEXIT_TIMEOUT)
    if stats.dispatched:
        logger.info(f"Hook background work closed at exit: {stats.as_dict()}")


register_close_at_exit(_drain_at_exit)

# A child of `fork()` inherits this object but none of the threads working it —
# the reserve loop's above all. A prefork server (gunicorn `--preload`) that
# notified before forking would otherwise accept every notification in its
# workers and deliver none.
os.register_at_fork(after_in_child=_background_work.reset_after_fork)


def capture_loop() -> asyncio.AbstractEventLoop | None:
    """Return the event loop running in this thread, or None if there is none."""
    return _running_loop()


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
            session cannot arrive swapped. What cannot start yet waits its turn
            in a queue; on overflow the oldest is dropped, loudly.
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


async def shutdown_hooks_async(
    timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
) -> BackgroundWorkStats:
    """Close the background work from inside an event loop.

    The one to call in a FastAPI lifespan or an async signal handler. The
    blocking `shutdown_hooks()` would stop the very loop the notifications are
    riding, so the drain would spend its whole budget and then cancel work it
    could have delivered.

    Args:
        timeout: Seconds to wait for the work in flight before cancelling it.

    Returns:
        The counters as they stand once it is closed.
    """
    return await _background_work.shutdown_async(timeout=timeout)


def hooks_background_stats() -> BackgroundWorkStats:
    """Return the counters of the hooks' background work.

    Useful as a metric or in a health endpoint: `dropped` growing means the
    limit is being hit, `in_flight` staying high means the notifications are
    slower than the events that produce them.
    """
    return _background_work.stats
