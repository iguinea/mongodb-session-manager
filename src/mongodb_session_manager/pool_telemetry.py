"""What the connection pool is doing, counted from the driver's own events.

pymongo does not expose the state of a pool: no public API says how many
connections exist or how many are checked out right now. The only way to know is
to listen to the CMAP events it publishes, and it only delivers them to a
listener registered when the client is built (issue #59).

Worth counting because the numbers answer questions the configuration cannot:

- `total_connections` against `maxPoolSize` says whether the pool is near its
  ceiling. The ceiling that matters is per server, so a replica set of three
  nodes holds up to three times this figure.
- `active_connections` is the concurrency the process is really reaching, which
  in an async server with a synchronous driver is usually far below what the
  number of requests would suggest.
- `checkout_wait_ms_max` is the one that separates a saturated pool from a slow
  server. It stays near zero while the pool has warm connections and jumps when
  it has to open one -- measured at 603 ms against DocumentDB.

The counters are cumulative and bounded: no sample is kept, so a process that
runs for weeks holds the same handful of integers it started with.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from pymongo import monitoring


@dataclass(frozen=True)
class PoolSnapshot:
    """The pool as it was when `snapshot()` was called.

    `checkout_wait_ms_max` is the worst wait seen since the pool was created,
    not a recent one: it answers "did this ever queue?", which is the question
    an operator asks after a latency spike has already happened.
    """

    total_connections: int
    active_connections: int
    available_connections: int
    checkout_failures: int
    checkout_wait_ms_max: float

    def as_dict(self) -> dict[str, Any]:
        """The shape that goes into `get_pool_stats()` and into a log line."""
        return {
            "total_connections": self.total_connections,
            "active_connections": self.active_connections,
            "available_connections": self.available_connections,
            "checkout_failures": self.checkout_failures,
            "checkout_wait_ms_max": self.checkout_wait_ms_max,
        }


class PoolTelemetry(monitoring.ConnectionPoolListener):
    """Counts the CMAP events that describe pool utilisation.

    Every method of the interface is implemented, including the ones that count
    nothing: pymongo calls all of them, and one that is missing costs a logged
    traceback per event.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._opened = 0
        self._closed = 0
        self._checked_out = 0
        self._checked_in = 0
        self._checkout_failures = 0
        self._checkout_wait_ms_max = 0.0

    def snapshot(self) -> PoolSnapshot:
        """Read every counter at once, so they describe the same instant."""
        with self._lock:
            total = self._opened - self._closed
            active = self._checked_out - self._checked_in
            return PoolSnapshot(
                total_connections=total,
                active_connections=active,
                # A checkout can be seen before its connection_created while the
                # pool is filling, and a negative count would read as a bug in
                # whatever dashboard shows it.
                available_connections=max(0, total - active),
                checkout_failures=self._checkout_failures,
                checkout_wait_ms_max=self._checkout_wait_ms_max,
            )

    # -- Events that move a counter ------------------------------------------

    def connection_created(self, event: Any) -> None:
        with self._lock:
            self._opened += 1

    def connection_closed(self, event: Any) -> None:
        with self._lock:
            self._closed += 1

    def connection_checked_out(self, event: Any) -> None:
        # pymongo publishes the duration in seconds, and it is optional: absent
        # means unknown, which is not the same as an instant checkout.
        duration = getattr(event, "duration", None)
        with self._lock:
            self._checked_out += 1
            if duration is not None:
                self._checkout_wait_ms_max = max(
                    self._checkout_wait_ms_max, duration * 1000
                )

    def connection_checked_in(self, event: Any) -> None:
        with self._lock:
            self._checked_in += 1

    def connection_check_out_failed(self, event: Any) -> None:
        with self._lock:
            self._checkout_failures += 1

    # -- Events the interface requires and this listener does not use ---------

    def pool_created(self, event: Any) -> None: ...

    def pool_ready(self, event: Any) -> None: ...

    def pool_cleared(self, event: Any) -> None: ...

    def pool_closed(self, event: Any) -> None: ...

    def connection_ready(self, event: Any) -> None: ...

    def connection_check_out_started(self, event: Any) -> None: ...
