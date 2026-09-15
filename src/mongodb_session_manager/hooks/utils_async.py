"""Shared async utilities for hooks."""

import asyncio
import logging
import threading

logger = logging.getLogger(__name__)

# Strong references to in-flight tasks. The event loop only keeps weak ones, so
# a task that nobody holds can be garbage collected mid-flight and the hook
# would never run. Each task drops itself from the set when it finishes.
_background_tasks: set[asyncio.Task] = set()


def dispatch_async(coro, error_context: str) -> None:
    """Dispatch an async coroutine in the current event loop or a new thread.

    In async contexts, creates a task in the running loop.
    In sync contexts, spawns a daemon thread to avoid blocking.
    """
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    except RuntimeError:
        thread = threading.Thread(target=asyncio.run, args=(coro,), daemon=True)
        thread.start()
    except Exception as e:
        logger.error(f"Error {error_context}: {e}")
