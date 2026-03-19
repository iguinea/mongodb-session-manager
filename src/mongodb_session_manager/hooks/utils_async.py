"""Shared async utilities for hooks."""

import asyncio
import logging
import threading

logger = logging.getLogger(__name__)


def dispatch_async(coro, error_context: str) -> None:
    """Dispatch an async coroutine in the current event loop or a new thread.

    In async contexts, creates a task in the running loop.
    In sync contexts, spawns a daemon thread to avoid blocking.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        thread = threading.Thread(target=asyncio.run, args=(coro,), daemon=True)
        thread.start()
    except Exception as e:
        logger.error(f"Error {error_context}: {e}")
