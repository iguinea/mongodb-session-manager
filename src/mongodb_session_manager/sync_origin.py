"""Which of Strands' syncs is running: the one for a message just added, or another.

Strands registers the very same `sync_agent` callback for `MessageAddedEvent` and
for `AfterInvocationEvent`, and neither tells it where it came from. The two are
not alike. `MessageAddedEvent` fires *before* the event loop accumulates the
usage and metrics of the model call that produced the message (strands
`event_loop.py:409-414` in 1.30, `:699-703` in 1.56), so the metrics a sync sees
there belong to the previous cycle. Writing them put a stale snapshot on every
intermediate message and a write that the closing sync overwrote an instant
later (issue #66).

`MessageAddedTagging` wraps the registry the session manager registers its hooks
on, and runs every callback registered for `MessageAddedEvent` with a context
tag set. The tag is a `ContextVar`, not state on the manager: it is restored in
a `finally` even when a callback raises, and a `sync_agent()` called explicitly
from another thread never sees it. Both were real failures of a per-agent flag
(features/8_invocation_metrics_on_last_message/plan.md, section 9).

Wrapping the registry, rather than registering the SDK's callbacks by hand,
keeps whatever a newer SDK registers: only `MessageAddedEvent` callbacks are
touched, and everything else reaches the real registry unchanged.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from strands.hooks import HookRegistry, MessageAddedEvent

_syncing_added_message: ContextVar[bool] = ContextVar(
    "syncing_added_message", default=False
)


def syncing_added_message() -> bool:
    """True while a callback registered for `MessageAddedEvent` is running."""
    return _syncing_added_message.get()


def _tagged(callback: Any) -> Any:
    """Run `callback` with the tag set, restoring it however the call ends.

    Only for synchronous callbacks: a coroutine would run after the tag is
    already restored. Strands' session manager registers synchronous ones, and
    tests/unit/test_sync_origin.py fails if an SDK upgrade changes that.
    """

    def run_tagged(event: Any) -> Any:
        token = _syncing_added_message.set(True)
        try:
            return callback(event)
        finally:
            _syncing_added_message.reset(token)

    return run_tagged


class MessageAddedTagging:
    """A `HookRegistry` whose `MessageAddedEvent` callbacks run tagged."""

    def __init__(self, registry: HookRegistry) -> None:
        self._registry = registry

    def add_callback(
        self, event_type: Any, callback: Any, *args: Any, **kwargs: Any
    ) -> None:
        """Register on the real registry, tagging `MessageAddedEvent` callbacks.

        Extra arguments pass through untouched, such as the `order=` that
        Strands 1.56 accepts.
        """
        if event_type is MessageAddedEvent:
            callback = _tagged(callback)
        self._registry.add_callback(event_type, callback, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._registry, name)
