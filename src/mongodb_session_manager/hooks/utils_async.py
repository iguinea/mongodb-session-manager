"""Shared async utilities for hooks."""

import asyncio
import logging
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from functools import partial
from typing import Any

logger = logging.getLogger(__name__)

# Strong references to in-flight work. The event loop only keeps weak ones, so
# work that nobody holds can be garbage collected mid-flight and the hook
# would never run. Each handle drops itself from the set when it finishes.
_background_work: set[asyncio.Task | Future] = set()


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
            loop instead of starting a thread per event.

    Without a usable loop the caller's thread decides, as before: a task on the
    loop running in it, or a daemon thread with its own loop if there is none.

    Returns:
        A handle on the work — a ``Task`` or a ``concurrent.futures.Future`` —
        or None when it was dispatched to a daemon thread or not at all. The
        failure is logged either way; the handle is for callers that want the
        result.
    """
    try:
        if loop is not None:
            handle = _dispatch_to_loop(coro, error_context, loop)
            if handle is not None:
                return handle

        running_loop = capture_loop()
        if running_loop is not None:
            return _track(running_loop.create_task(coro), error_context)

        thread = threading.Thread(
            target=_run_in_new_loop, args=(coro, error_context), daemon=True
        )
        thread.start()
        return None
    except Exception as e:
        # The hook already did its write; a failed dispatch must not undo it.
        logger.error(f"Error dispatching hook while {error_context}: {e}")
        coro.close()
        return None


def _dispatch_to_loop(
    coro: Coroutine[Any, Any, Any],
    error_context: str,
    loop: asyncio.AbstractEventLoop,
) -> asyncio.Task | Future | None:
    """Hand the coroutine to a known loop, or None if that loop cannot take it."""
    if loop.is_closed():
        logger.warning(
            f"Event loop already closed while {error_context}; "
            "falling back to the calling thread"
        )
        return None
    try:
        return _track(asyncio.run_coroutine_threadsafe(coro, loop), error_context)
    except RuntimeError as e:
        logger.warning(
            f"Could not reach the event loop while {error_context} ({e}); "
            "falling back to the calling thread"
        )
        return None


def _track(handle: asyncio.Task | Future, error_context: str) -> asyncio.Task | Future:
    """Keep a strong reference to the work and log how it ends."""
    _background_work.add(handle)
    handle.add_done_callback(partial(_log_outcome, error_context=error_context))
    return handle


def _log_outcome(handle: asyncio.Task | Future, error_context: str) -> None:
    """Report the outcome of finished work instead of discarding it."""
    _background_work.discard(handle)
    if handle.cancelled():
        logger.warning(f"Cancelled while {error_context}")
        return
    exception = handle.exception()
    if exception is not None:
        logger.error(f"Error {error_context}: {exception}", exc_info=exception)


def _run_in_new_loop(coro: Coroutine[Any, Any, Any], error_context: str) -> None:
    """Run the coroutine in a loop of its own, in the thread that got it."""
    try:
        asyncio.run(coro)
    except Exception as e:
        logger.error(f"Error {error_context}: {e}", exc_info=e)
