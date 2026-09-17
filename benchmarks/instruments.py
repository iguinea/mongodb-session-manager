"""What the harness observes while the workload runs.

Everything here is passive: samples arrive from the outside and are summarised
on demand. Nothing in this module talks to MongoDB or starts work of its own.
"""

from __future__ import annotations

import asyncio
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import bson
from pymongo import monitoring

# Commands the driver sends on its own behalf: handshakes, heartbeats, auth and
# teardown. They are not work the session manager asked for.
# `tests/integration/test_write_amplification_integration.py` keeps its own copy
# on purpose: the test suite must not depend on this package.
IGNORED_COMMANDS = frozenset(
    {
        "ping",
        "hello",
        "ismaster",
        "buildInfo",
        "endSessions",
        "saslStart",
        "saslContinue",
        "getnonce",
        "drop",
        "listIndexes",
        "killCursors",
    }
)


@dataclass(frozen=True)
class Distribution:
    """Dispersion of a sample. There is no mean on purpose: it hides the tail."""

    n: int
    min_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "n": self.n,
            "min_ms": self.min_ms,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "max_ms": self.max_ms,
        }


def percentile(ordered: Sequence[float], q: float) -> float:
    """Nearest-rank percentile: returns a value that was actually observed.

    Interpolating a p99 out of 30 repetitions reports a number nobody measured.
    """
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def summarize(values: Sequence[float]) -> Distribution:
    if not values:
        raise ValueError("no measured samples to summarize")
    ordered = sorted(values)
    return Distribution(
        n=len(ordered),
        min_ms=ordered[0],
        p50_ms=percentile(ordered, 50),
        p95_ms=percentile(ordered, 95),
        p99_ms=percentile(ordered, 99),
        max_ms=ordered[-1],
    )


class Samples:
    """Latency samples of one scenario cell, keeping warmups apart.

    The first ``warmups`` repetitions land in their own bucket: they measure
    filling the connection pool and the server cache, not the steady state the
    benchmark reports.
    """

    def __init__(self, warmups: int) -> None:
        if warmups < 0:
            raise ValueError("warmups must be greater than or equal to 0")
        self._warmups = warmups
        self._warmup: list[float] = []
        self._measured: list[float] = []

    def record(self, value_ms: float) -> None:
        if len(self._warmup) < self._warmups:
            self._warmup.append(value_ms)
        else:
            self._measured.append(value_ms)

    @property
    def completed(self) -> int:
        """Every repetition that ran, warmups included."""
        return len(self._warmup) + len(self._measured)

    @property
    def measured(self) -> list[float]:
        return list(self._measured)

    def summary(self) -> Distribution:
        return summarize(self._measured)

    def warmup_summary(self) -> Distribution:
        return summarize(self._warmup)


def _bson_size(document: dict[str, Any]) -> int:
    """Serialized size of a command or reply, with known caveats.

    It excludes the OP_MSG header, it re-encodes a document the driver already
    decoded instead of counting bytes off the wire, and it says nothing about
    what a negotiated compressor put on that wire. `environment.py` records the
    compressors in use so a reader can tell when this number stops meaning
    network traffic.
    """
    try:
        return len(bson.encode(document))
    except Exception:
        # A command the driver redacts (auth) or a type bson cannot re-encode
        # must not take the run down: it is a measurement, not the workload.
        return 0


@dataclass(frozen=True)
class CommandTally:
    """What the driver did inside one measurement window."""

    commands: dict[str, int]
    server_ms: dict[str, list[float]]
    request_bytes: int
    reply_bytes: int
    failures: int


class CommandProbe(monitoring.CommandListener):
    """Counts commands, their server-side duration, their bytes and their errors.

    `enabled` brackets the measured window, so the setup of a scenario does not
    land in its numbers. `measure_bytes` is off during the latency pass: see
    `_bson_size`.
    """

    def __init__(self) -> None:
        self.enabled = False
        self.measure_bytes = False
        self._commands: Counter[str] = Counter()
        self._server_ms: dict[str, list[float]] = {}
        self._request_bytes = 0
        self._reply_bytes = 0
        self._failures = 0

    def _watching(self, event: Any) -> bool:
        return self.enabled and event.command_name not in IGNORED_COMMANDS

    def started(self, event: Any) -> None:
        if not self._watching(event):
            return
        self._commands[event.command_name] += 1
        if self.measure_bytes:
            self._request_bytes += _bson_size(event.command)

    def succeeded(self, event: Any) -> None:
        if not self._watching(event):
            return
        self._server_ms.setdefault(event.command_name, []).append(
            event.duration_micros / 1000
        )
        if self.measure_bytes:
            self._reply_bytes += _bson_size(event.reply)

    def failed(self, event: Any) -> None:
        if not self._watching(event):
            return
        self._failures += 1

    def reset(self) -> None:
        """Empties the counters without closing the window the caller opened."""
        self._commands = Counter()
        self._server_ms = {}
        self._request_bytes = 0
        self._reply_bytes = 0
        self._failures = 0

    def tally(self) -> CommandTally:
        return CommandTally(
            commands=dict(self._commands),
            server_ms={name: list(v) for name, v in self._server_ms.items()},
            request_bytes=self._request_bytes,
            reply_bytes=self._reply_bytes,
            failures=self._failures,
        )


class LoopProbe:
    """Event-loop lag, measured as the drift of a heartbeat.

    A heartbeat that asks for 20 ms and gets 200 spent 180 ms unable to run:
    that is the cost a blocking driver call imposes on every other request
    sharing the loop. 20 ms and not 5: below that the sample is the operating
    system's scheduler, not the workload.

    The baseline of an idle loop is measured by `calibrate()` and reported
    beside the lag. The two are never subtracted from one another — the jitter
    of the machine is context for the reader, not something to net out.
    """

    def __init__(self, interval_ms: float = 20.0) -> None:
        self.interval_ms = interval_ms
        self.lag_ms: list[float] = []
        self._task: Any = None
        self._running = False

    async def __aenter__(self) -> LoopProbe:
        self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.stop()

    def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._beat(self.lag_ms))

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            await self._task
            self._task = None

    async def calibrate(self, seconds: float) -> Distribution:
        """Lag of an empty loop, to tell the machine's noise from the workload."""
        samples: list[float] = []
        self._running = True
        task = asyncio.create_task(self._beat(samples))
        await asyncio.sleep(seconds)
        self._running = False
        await task
        return summarize(samples)

    async def _beat(self, into: list[float]) -> None:
        loop = asyncio.get_running_loop()
        interval = self.interval_ms / 1000
        while self._running:
            expected = loop.time() + interval
            await asyncio.sleep(interval)
            into.append(max(0.0, (loop.time() - expected) * 1000))


@dataclass(frozen=True)
class PoolTally:
    """How long the workload waited for a connection, and when it gave up."""

    wait_ms: list[float]
    timeouts: int
    reasons: dict[str, int] = field(default_factory=dict)


class PoolProbe(monitoring.ConnectionPoolListener):
    """Checkout wait of the connection pool.

    With the default `minPoolSize=10` and low concurrency this reads zero
    forever, which proves nothing: the `pool` profile saturates a small pool on
    purpose so the probe has something to measure.
    """

    def __init__(self) -> None:
        self.enabled = False
        self._wait_ms: list[float] = []
        self._reasons: Counter[str] = Counter()

    def connection_checked_out(self, event: Any) -> None:
        # pymongo publishes seconds, and types the field optional: a missing
        # duration is unknown, not an instant checkout.
        if self.enabled and event.duration is not None:
            self._wait_ms.append(event.duration * 1000)

    def connection_check_out_failed(self, event: Any) -> None:
        if self.enabled:
            self._reasons[event.reason] += 1

    # The rest of the interface is abstract in pymongo and raises if left out;
    # the driver then logs a traceback per event. Nothing here needs them.
    def pool_created(self, event: Any) -> None: ...

    def pool_ready(self, event: Any) -> None: ...

    def pool_cleared(self, event: Any) -> None: ...

    def pool_closed(self, event: Any) -> None: ...

    def connection_created(self, event: Any) -> None: ...

    def connection_ready(self, event: Any) -> None: ...

    def connection_closed(self, event: Any) -> None: ...

    def connection_check_out_started(self, event: Any) -> None: ...

    def connection_checked_in(self, event: Any) -> None: ...

    def reset(self) -> None:
        self._wait_ms = []
        self._reasons = Counter()

    def tally(self) -> PoolTally:
        return PoolTally(
            wait_ms=list(self._wait_ms),
            timeouts=sum(self._reasons.values()),
            reasons=dict(self._reasons),
        )
