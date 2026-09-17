"""The probes that watch the driver while the workload runs (issue #60).

Driven with stub events instead of a real MongoDB: what is under test is the
bookkeeping, and pymongo's event objects are plain attribute holders. The shape
of those attributes is pinned against pymongo 4.18 in
`test_the_probe_reads_the_fields_pymongo_publishes`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pymongo import monitoring

from benchmarks.instruments import CommandProbe, PoolProbe


@dataclass
class FakeStarted:
    command_name: str
    command: dict[str, Any] = field(default_factory=dict)
    operation_id: int = 1
    database_name: str = "bench"


@dataclass
class FakeSucceeded:
    command_name: str
    reply: dict[str, Any] = field(default_factory=dict)
    duration_micros: int = 1_000
    operation_id: int = 1


@dataclass
class FakeFailed:
    command_name: str
    failure: dict[str, Any] = field(default_factory=dict)
    duration_micros: int = 1_000
    operation_id: int = 1


@dataclass
class FakeCheckedOut:
    duration: float | None  # pymongo publishes seconds, and types it optional


@dataclass
class FakeCheckOutFailed:
    duration: float | None
    reason: str = "timeout"


def _run_command(probe: CommandProbe, name: str, *, reply=None, operation_id=1):
    probe.started(
        FakeStarted(command_name=name, command={name: 1}, operation_id=operation_id)
    )
    probe.succeeded(
        FakeSucceeded(
            command_name=name, reply=reply or {"ok": 1}, operation_id=operation_id
        )
    )


class TestCommandProbe:
    def test_sums_request_and_reply_bytes_per_command(self):
        probe = CommandProbe()
        probe.enabled = True
        probe.measure_bytes = True

        _run_command(probe, "find", reply={"ok": 1, "payload": "x" * 500})

        tally = probe.tally()
        assert tally.request_bytes > 0
        assert tally.reply_bytes > 500

    def test_the_latency_pass_does_not_touch_bytes(self):
        """Re-encoding a 3 MB reply inside the driver callback would be measured
        as if it were the query. The latency pass must not pay for it."""
        probe = CommandProbe()
        probe.enabled = True

        _run_command(probe, "find", reply={"ok": 1, "payload": "x" * 500})

        tally = probe.tally()
        assert tally.request_bytes == 0
        assert tally.reply_bytes == 0
        assert tally.commands["find"] == 1

    def test_driver_noise_is_ignored(self):
        probe = CommandProbe()
        probe.enabled = True

        for noise in ("hello", "ping", "buildInfo", "endSessions"):
            _run_command(probe, noise)
        _run_command(probe, "update")

        assert dict(probe.tally().commands) == {"update": 1}

    def test_a_disabled_probe_records_nothing(self):
        """The window is opened around the measured work, not around the setup."""
        probe = CommandProbe()

        _run_command(probe, "update")

        assert probe.tally().commands == {}

    def test_a_cursor_reports_every_round_trip_it_needed(self):
        """Draining a cursor costs one `getMore` per batch, and each is counted.

        An earlier version of this harness tried to fold them into their
        originating read by `operation_id`. Measured against pymongo 4.18, the
        driver gives every `getMore` an id of its own, so that grouping was
        reporting a number it had invented. The round-trips are the honest
        signal, and they show up by name.
        """
        probe = CommandProbe()
        probe.enabled = True

        _run_command(probe, "aggregate", operation_id=7)
        _run_command(probe, "getMore", operation_id=8)
        _run_command(probe, "getMore", operation_id=9)

        assert probe.tally().commands == {"aggregate": 1, "getMore": 2}

    def test_server_duration_is_recorded_per_command_in_milliseconds(self):
        probe = CommandProbe()
        probe.enabled = True

        probe.started(FakeStarted(command_name="update"))
        probe.succeeded(FakeSucceeded(command_name="update", duration_micros=2_500))

        assert probe.tally().server_ms["update"] == [2.5]

    def test_failed_commands_are_counted_as_errors(self):
        probe = CommandProbe()
        probe.enabled = True

        probe.started(FakeStarted(command_name="update"))
        probe.failed(FakeFailed(command_name="update"))

        tally = probe.tally()
        assert tally.failures == 1
        assert tally.commands["update"] == 1

    def test_reset_empties_the_counters_without_closing_the_window(self):
        """Repetitions reset between samples; closing the window there would
        silently stop measuring after the first one."""
        probe = CommandProbe()
        probe.enabled = True
        probe.measure_bytes = True
        _run_command(probe, "update")

        probe.reset()
        _run_command(probe, "update")

        assert probe.tally().commands == {"update": 1}
        assert probe.enabled and probe.measure_bytes

    def test_the_probe_reads_the_fields_pymongo_publishes(self):
        """Pins the contract with the driver: an upgrade that renames these
        fails here instead of silently reporting zeros."""
        assert issubclass(CommandProbe, monitoring.CommandListener)
        for attribute in ("command_name", "command", "operation_id"):
            assert isinstance(
                getattr(monitoring.CommandStartedEvent, attribute), property
            )
        for attribute in ("reply", "duration_micros"):
            assert isinstance(
                getattr(monitoring.CommandSucceededEvent, attribute), property
            )


class TestPoolProbe:
    def test_records_pool_checkout_wait(self):
        probe = PoolProbe()
        probe.enabled = True

        probe.connection_checked_out(FakeCheckedOut(duration=0.004))
        probe.connection_checked_out(FakeCheckedOut(duration=0.010))

        assert probe.tally().wait_ms == [4.0, 10.0]

    def test_checkout_timeouts_are_counted_with_their_reason(self):
        probe = PoolProbe()
        probe.enabled = True

        probe.connection_check_out_failed(FakeCheckOutFailed(duration=2.0))

        tally = probe.tally()
        assert tally.timeouts == 1
        assert tally.reasons == {"timeout": 1}

    def test_a_disabled_probe_records_nothing(self):
        probe = PoolProbe()

        probe.connection_checked_out(FakeCheckedOut(duration=0.004))

        assert probe.tally().wait_ms == []

    def test_a_missing_duration_is_not_a_zero_wait(self):
        """pymongo types duration as optional; None is unknown, not instant."""
        probe = PoolProbe()
        probe.enabled = True

        probe.connection_checked_out(FakeCheckedOut(duration=None))

        assert probe.tally().wait_ms == []

    def test_the_probe_is_a_pool_listener(self):
        assert issubclass(PoolProbe, monitoring.ConnectionPoolListener)
