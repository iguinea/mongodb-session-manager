"""What the pool listener can say about the pool (issue #59).

The numbers come from CMAP events, which pymongo only delivers to a listener
registered when the client is built. The listener is checked here on its own,
without a client: the connection pool tests then prove it is wired in and that
`get_pool_stats()` reads from it.
"""

from types import SimpleNamespace

import pytest
from pymongo import monitoring

from mongodb_session_manager.pool_telemetry import PoolTelemetry


def created() -> SimpleNamespace:
    return SimpleNamespace(address=("localhost", 27017), connection_id=1)


def checked_out(duration: float | None = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        address=("localhost", 27017), connection_id=1, duration=duration
    )


def check_out_failed(reason: str = "timeout") -> SimpleNamespace:
    return SimpleNamespace(address=("localhost", 27017), reason=reason)


class TestConnectionCensus:
    """How many connections there are, and how many are in use right now."""

    def test_starts_empty(self):
        assert PoolTelemetry().snapshot().as_dict() == {
            "total_connections": 0,
            "active_connections": 0,
            "available_connections": 0,
            "checkout_failures": 0,
            "checkout_wait_ms_max": 0.0,
        }

    def test_counts_connections_as_they_open_and_close(self):
        telemetry = PoolTelemetry()
        for _ in range(3):
            telemetry.connection_created(created())
        telemetry.connection_closed(created())

        assert telemetry.snapshot().total_connections == 2

    def test_a_checked_out_connection_is_active_until_it_comes_back(self):
        telemetry = PoolTelemetry()
        telemetry.connection_created(created())
        telemetry.connection_created(created())
        telemetry.connection_checked_out(checked_out())

        snapshot = telemetry.snapshot()
        assert snapshot.active_connections == 1
        assert snapshot.available_connections == 1

        telemetry.connection_checked_in(created())
        assert telemetry.snapshot().active_connections == 0

    def test_available_never_goes_negative(self):
        """A checkout can be seen before its `connection_created`, at startup."""
        telemetry = PoolTelemetry()
        telemetry.connection_checked_out(checked_out())

        assert telemetry.snapshot().available_connections == 0


class TestCheckoutWait:
    """The wait is what tells a saturated pool from a busy server."""

    def test_pymongo_reports_seconds_and_the_snapshot_reports_milliseconds(self):
        telemetry = PoolTelemetry()
        telemetry.connection_checked_out(checked_out(duration=0.124))

        assert telemetry.snapshot().checkout_wait_ms_max == pytest.approx(124.0)

    def test_keeps_the_worst_wait_seen(self):
        telemetry = PoolTelemetry()
        for seconds in (0.002, 0.180, 0.030):
            telemetry.connection_checked_out(checked_out(duration=seconds))

        assert telemetry.snapshot().checkout_wait_ms_max == pytest.approx(180.0)

    def test_a_missing_duration_is_unknown_not_zero(self):
        """`duration` is optional in CMAP: absent is not an instant checkout."""
        telemetry = PoolTelemetry()
        telemetry.connection_checked_out(checked_out(duration=0.5))
        telemetry.connection_checked_out(checked_out(duration=None))

        assert telemetry.snapshot().checkout_wait_ms_max == pytest.approx(500.0)


class TestCheckoutFailures:
    """A refused checkout is the symptom the pool config has to answer for."""

    def test_counts_them(self):
        telemetry = PoolTelemetry()
        telemetry.connection_check_out_failed(check_out_failed("timeout"))
        telemetry.connection_check_out_failed(check_out_failed("connectionError"))

        assert telemetry.snapshot().checkout_failures == 2


class TestEveryEventIsHandled:
    """pymongo logs a traceback per event for each method a listener leaves out."""

    def test_implements_the_whole_listener_interface(self):
        missing = [
            name
            for name in dir(monitoring.ConnectionPoolListener)
            if not name.startswith("_")
            and not hasattr(PoolTelemetry, name)  # pragma: no cover - assertion data
        ]
        assert missing == []

    @pytest.mark.parametrize(
        "event_name",
        [
            "pool_created",
            "pool_ready",
            "pool_cleared",
            "pool_closed",
            "connection_ready",
            "connection_check_out_started",
        ],
    )
    def test_the_events_it_does_not_count_are_harmless(self, event_name):
        telemetry = PoolTelemetry()
        getattr(telemetry, event_name)(created())

        assert telemetry.snapshot().total_connections == 0


class TestThreadSafety:
    """Several worker threads share one client, so they share one listener."""

    def test_counts_survive_concurrent_events(self):
        import threading

        telemetry = PoolTelemetry()

        def work():
            for _ in range(500):
                telemetry.connection_created(created())
                telemetry.connection_checked_out(checked_out(duration=0.001))
                telemetry.connection_checked_in(created())

        threads = [threading.Thread(target=work) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        snapshot = telemetry.snapshot()
        assert snapshot.total_connections == 8 * 500
        assert snapshot.active_connections == 0
