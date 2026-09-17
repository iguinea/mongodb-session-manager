"""Unit tests for MongoDBConnectionPool."""

from unittest.mock import MagicMock, patch

import pytest
from pymongo.errors import ConfigurationError, PyMongoError

from mongodb_session_manager.mongodb_connection_pool import MongoDBConnectionPool
from mongodb_session_manager.pool_telemetry import PoolTelemetry


def fake_client(**effective):
    """A MongoClient double that can answer what options it ended up with.

    The pool reads them back from the client now, because an option named in
    the connection string never reaches the kwargs.
    """
    client = MagicMock()
    client.admin.command.return_value = {"ok": 1}
    client.options.pool_options.max_pool_size = effective.get("maxPoolSize", 100)
    client.options.pool_options.min_pool_size = effective.get("minPoolSize", 10)
    client.options.pool_options.max_idle_time_seconds = effective.get(
        "maxIdleTimeSeconds", 300
    )
    client.options.retry_writes = effective.get("retryWrites", True)
    client.options.retry_reads = effective.get("retryReads", True)
    return client


@pytest.fixture(autouse=True)
def reset_connection_pool():
    """Reset the singleton state between tests."""
    yield
    # Reset singleton
    MongoDBConnectionPool._instance = None
    MongoDBConnectionPool._client = None
    MongoDBConnectionPool._connection_string = None
    MongoDBConnectionPool._user_kwargs = None
    MongoDBConnectionPool._resolved_kwargs = None
    MongoDBConnectionPool._telemetry = None
    MongoDBConnectionPool._server_version = None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_same_instance(self):
        a = MongoDBConnectionPool()
        b = MongoDBConnectionPool()
        assert a is b

    def test_thread_safety(self):
        import threading

        instances = []

        def create():
            instances.append(MongoDBConnectionPool())

        threads = [threading.Thread(target=create) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(inst is instances[0] for inst in instances)


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------


class TestInitialize:
    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_creates_client_with_defaults(self, mock_client_cls):
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        result = MongoDBConnectionPool.initialize("mongodb://localhost:27017/")
        assert result is mock_client
        mock_client_cls.assert_called_once()
        call_kwargs = mock_client_cls.call_args[1]
        assert call_kwargs["maxPoolSize"] == 100
        assert call_kwargs["retryWrites"] is True

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_reuses_for_same_params(self, mock_client_cls):
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        client1 = MongoDBConnectionPool.initialize("mongodb://localhost:27017/")
        client2 = MongoDBConnectionPool.initialize("mongodb://localhost:27017/")
        assert client1 is client2
        assert mock_client_cls.call_count == 1

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_recreates_when_params_change(self, mock_client_cls):
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://host1/")
        MongoDBConnectionPool.initialize("mongodb://host2/")
        assert mock_client_cls.call_count == 2

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_pings_admin(self, mock_client_cls):
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost:27017/")
        mock_client.admin.command.assert_called_once_with("ping")

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_raises_on_connection_error(self, mock_client_cls):
        mock_client_cls.side_effect = PyMongoError("connection failed")
        with pytest.raises(PyMongoError):
            MongoDBConnectionPool.initialize("mongodb://bad/")

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_a_client_that_fails_its_first_ping_is_closed(self, mock_client_cls):
        """Dropping the reference is not closing it (#59).

        The client was already built when the ping failed: it has its monitor
        threads per server and, with minPoolSize, connections on the way.
        pymongo does not close on `__del__`; it warns. A startup that retries
        against a MongoDB that is not up yet piled one of those up per attempt,
        and the 5-minute idle timeout makes each one last ten times longer.
        """
        mock_client = fake_client()
        mock_client.admin.command.side_effect = PyMongoError("server not ready")
        mock_client_cls.return_value = mock_client

        with pytest.raises(PyMongoError):
            MongoDBConnectionPool.initialize("mongodb://localhost/")

        mock_client.close.assert_called_once()

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_kwargs_override_defaults(self, mock_client_cls):
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/", maxPoolSize=50)
        call_kwargs = mock_client_cls.call_args[1]
        assert call_kwargs["maxPoolSize"] == 50

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_idle_connections_outlive_a_quiet_stretch(self, mock_client_cls):
        """minPoolSize refills whatever maxIdleTimeMS expires, for ever (#59).

        With the old 30 s an idle pool opened and closed its ten connections
        every half minute -- 33.596 a day per process and per node, each one a
        TLS handshake and an authentication nobody asked for.
        """
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        call_kwargs = mock_client_cls.call_args[1]
        assert call_kwargs["maxIdleTimeMS"] == 300000


# ---------------------------------------------------------------------------
# The connection string is the user speaking too
# ---------------------------------------------------------------------------


class TestDefaultsDoNotOverrideTheUri:
    """A default is for what nobody said, not something to impose (#59).

    pymongo gives a constructor keyword precedence over the connection string,
    so every default this class injected used to silently overrule the URI.
    """

    @pytest.mark.parametrize(
        ("query", "option"),
        [
            ("retryWrites=false", "retryWrites"),
            ("maxPoolSize=7", "maxPoolSize"),
            ("minPoolSize=0", "minPoolSize"),
            ("socketTimeoutMS=1234", "socketTimeoutMS"),
            ("serverSelectionTimeoutMS=250", "serverSelectionTimeoutMS"),
            ("retryReads=false", "retryReads"),
        ],
    )
    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_an_option_in_the_uri_is_left_alone(self, mock_client_cls, query, option):
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize(f"mongodb://localhost/?{query}")

        assert option not in mock_client_cls.call_args[1]

    @pytest.mark.parametrize(
        ("query", "read_option", "expected"),
        [
            ("retryWrites=false", "retry_writes", False),
            ("retryReads=false", "retry_reads", False),
            ("maxPoolSize=7", "pool_options.max_pool_size", 7),
            ("minPoolSize=3", "pool_options.min_pool_size", 3),
            ("maxIdleTimeMS=1000", "pool_options.max_idle_time_seconds", 1.0),
        ],
    )
    def test_pymongo_really_ends_up_with_the_uri_value(
        self, query, read_option, expected
    ):
        """Against the real driver, which is where the precedence lives.

        `connect=False` keeps this off the network: the options are resolved
        when the client is constructed, and that is the whole subject here.
        """
        options = MongoDBConnectionPool._resolve_options(
            f"mongodb://localhost/?{query}", {}
        )
        from pymongo import MongoClient as RealMongoClient

        client = RealMongoClient(
            f"mongodb://localhost/?{query}", connect=False, **options
        )
        try:
            value = client.options
            for attribute in read_option.split("."):
                value = getattr(value, attribute)
            assert value == expected
        finally:
            client.close()

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_documentdb_keeps_retry_writes_off(self, mock_client_cls):
        """Regression (#59): `retryWrites=True` breaks every update_one there.

        DocumentDB answers `OperationFailure 301` to an update carrying a
        txnNumber, so a session was created and then failed on its first
        message. AWS documents `retryWrites=false` in the URI, which is exactly
        what the default used to overrule.
        """
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize(
            "mongodb://docdb.example.com/?tls=true&retryWrites=false"
        )

        assert mock_client_cls.call_args[1].get("retryWrites") is not True

    @pytest.mark.parametrize(
        "small_pool",
        [
            {"connection_string": "mongodb://localhost/?maxPoolSize=4", "kwargs": {}},
            {
                "connection_string": "mongodb://localhost/",
                "kwargs": {"maxPoolSize": 4},
            },
        ],
    )
    def test_a_small_pool_is_not_rejected_by_our_own_minimum(self, small_pool):
        """The floor follows the ceiling the caller set (#59).

        pymongo refuses a minPoolSize above maxPoolSize. Now that a default no
        longer overrules the URI, `?maxPoolSize=4` left the default floor of 10
        standing and the client raised at startup -- a resource-constrained
        deployment, exactly the one that would set a small pool.
        """
        options = MongoDBConnectionPool._resolve_options(
            small_pool["connection_string"], small_pool["kwargs"]
        )
        from pymongo import MongoClient as RealMongoClient

        client = RealMongoClient(
            small_pool["connection_string"], connect=False, **options
        )
        try:
            assert client.options.pool_options.max_pool_size == 4
            assert client.options.pool_options.min_pool_size <= 4
        finally:
            client.close()

    @pytest.mark.parametrize(
        "big_pool",
        [
            {"connection_string": "mongodb://localhost/?minPoolSize=200", "kwargs": {}},
            {
                "connection_string": "mongodb://localhost/",
                "kwargs": {"minPoolSize": 200},
            },
        ],
    )
    def test_a_large_minimum_is_not_rejected_by_our_own_ceiling(self, big_pool):
        """And the ceiling follows the floor, which is the same bug mirrored.

        The clamp only ran one way: a caller who asked for 200 warm connections
        met our default ceiling of 100 and pymongo refused the pair at startup.
        The URI case is precisely what this method exists to protect.
        """
        options = MongoDBConnectionPool._resolve_options(
            big_pool["connection_string"], big_pool["kwargs"]
        )
        from pymongo import MongoClient as RealMongoClient

        client = RealMongoClient(
            big_pool["connection_string"], connect=False, **options
        )
        try:
            assert client.options.pool_options.min_pool_size == 200
            assert client.options.pool_options.max_pool_size >= 200
        finally:
            client.close()

    def test_a_contradiction_the_caller_wrote_is_left_to_pymongo(self):
        """Both halves named and inconsistent is their decision, not ours."""
        options = MongoDBConnectionPool._resolve_options(
            "mongodb://localhost/", {"maxPoolSize": 5, "minPoolSize": 50}
        )

        assert options["maxPoolSize"] == 5
        assert options["minPoolSize"] == 50

    @pytest.mark.parametrize("spelling", ["maxpoolsize", "MAXPOOLSIZE", "MaxPoolSize"])
    def test_a_keyword_spelled_any_way_is_the_caller_naming_it(self, spelling):
        """pymongo takes its keywords case-insensitively; so must the defaults.

        Matching by exact name let `maxpoolsize=5` through *alongside* our
        `maxPoolSize=100` and `minPoolSize=10`: pymongo resolved the ceiling to
        5, kept the floor at 10, and refused the pair at startup.
        """
        options = MongoDBConnectionPool._resolve_options(
            "mongodb://localhost/", {spelling: 5}
        )
        from pymongo import MongoClient as RealMongoClient

        client = RealMongoClient("mongodb://localhost/", connect=False, **options)
        try:
            assert client.options.pool_options.max_pool_size == 5
            assert client.options.pool_options.min_pool_size <= 5
        finally:
            client.close()

    def test_no_expiry_at_all_is_spelled_none(self):
        """`maxIdleTimeMS=None` is the documented way to disable the idle timer.

        Not `0`: pymongo rejects the zero, as a keyword and in the URI alike. And
        a connection string cannot express it -- leaving the option out gets our
        5-minute default -- so the keyword has to survive being an explicit None
        and not be mistaken for "the caller said nothing" (#59).
        """
        options = MongoDBConnectionPool._resolve_options(
            "mongodb://localhost/", {"maxIdleTimeMS": None}
        )
        from pymongo import MongoClient as RealMongoClient

        client = RealMongoClient("mongodb://localhost/", connect=False, **options)
        try:
            assert client.options.pool_options.max_idle_time_seconds is None
        finally:
            client.close()

    def test_an_explicit_minimum_is_never_second_guessed(self):
        options = MongoDBConnectionPool._resolve_options(
            "mongodb://localhost/", {"maxPoolSize": 20, "minPoolSize": 15}
        )

        assert options["minPoolSize"] == 15

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_a_kwarg_still_wins_over_the_uri(self, mock_client_cls):
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize(
            "mongodb://localhost/?maxPoolSize=7", maxPoolSize=50
        )

        assert mock_client_cls.call_args[1]["maxPoolSize"] == 50

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_the_other_defaults_still_apply(self, mock_client_cls):
        """Naming one option does not opt out of the rest."""
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/?socketTimeoutMS=1234")

        call_kwargs = mock_client_cls.call_args[1]
        assert call_kwargs["maxPoolSize"] == 100
        assert call_kwargs["minPoolSize"] == 10
        assert call_kwargs["retryWrites"] is True

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_a_uri_pymongo_cannot_parse_still_gets_the_defaults(
        self, mock_client_cls, caplog
    ):
        """An unresolvable `mongodb+srv://` must not cost the pool its config."""
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        with (
            patch(
                "mongodb_session_manager.mongodb_connection_pool.parse_uri",
                side_effect=ConfigurationError("no DNS answer"),
            ),
            caplog.at_level("WARNING"),
        ):
            MongoDBConnectionPool.initialize("mongodb+srv://cluster.example.com/")

        assert mock_client_cls.call_args[1]["maxPoolSize"] == 100
        assert any(record.levelname == "WARNING" for record in caplog.records)

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_the_singleton_is_still_keyed_on_what_the_user_passed(
        self, mock_client_cls
    ):
        """Resolving options must not change when the client is recreated."""
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/?maxPoolSize=7")
        MongoDBConnectionPool.initialize("mongodb://localhost/?maxPoolSize=7")

        assert mock_client_cls.call_count == 1


# ---------------------------------------------------------------------------
# Pool telemetry
# ---------------------------------------------------------------------------


class TestTelemetryIsWired:
    """The numbers only exist if the listener is registered when the client is built."""

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_registers_its_listener(self, mock_client_cls):
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")

        listeners = mock_client_cls.call_args[1]["event_listeners"]
        assert any(isinstance(listener, PoolTelemetry) for listener in listeners)

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_keeps_the_listeners_the_caller_passed(self, mock_client_cls):
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client
        mine = MagicMock()

        MongoDBConnectionPool.initialize("mongodb://localhost/", event_listeners=[mine])

        listeners = mock_client_cls.call_args[1]["event_listeners"]
        assert mine in listeners
        assert any(isinstance(listener, PoolTelemetry) for listener in listeners)


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    """A health check that can hang is worse than none (#59).

    Measured: with the server mute and the connection already established,
    `server_info()` took 20,04 s to give up. Callers run this from an endpoint.
    """

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_pings_instead_of_asking_for_the_build_info(self, mock_client_cls):
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        mock_client.admin.command.reset_mock()

        result = MongoDBConnectionPool.health_check()

        assert result["status"] == "connected"
        mock_client.admin.command.assert_called_once_with("ping")
        mock_client.server_info.assert_not_called()

    @patch("mongodb_session_manager.mongodb_connection_pool.pymongo_timeout")
    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_bounds_the_ping_with_the_timeout_it_was_given(
        self, mock_client_cls, mock_timeout
    ):
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        MongoDBConnectionPool.health_check(timeout_ms=250)

        mock_timeout.assert_called_once_with(0.25)

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_reports_how_long_it_took(self, mock_client_cls):
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        result = MongoDBConnectionPool.health_check()

        assert result["latency_ms"] >= 0

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_a_server_that_does_not_answer_is_a_result_not_an_exception(
        self, mock_client_cls
    ):
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        mock_client.admin.command.side_effect = PyMongoError("no reply")

        result = MongoDBConnectionPool.health_check()

        assert result["status"] == "error"
        assert "no reply" in result["error"]
        assert result["latency_ms"] >= 0

    def test_not_initialized(self):
        assert MongoDBConnectionPool.health_check()["status"] == "not_initialized"


# ---------------------------------------------------------------------------
# get_client
# ---------------------------------------------------------------------------


class TestGetClient:
    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_returns_client(self, mock_client_cls):
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        assert MongoDBConnectionPool.get_client() is mock_client

    def test_returns_none_when_not_initialized(self):
        assert MongoDBConnectionPool.get_client() is None


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_closes_and_cleans_state(self, mock_client_cls):
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        MongoDBConnectionPool.close()
        mock_client.close.assert_called_once()
        assert MongoDBConnectionPool.get_client() is None

    def test_handles_close_without_initialize(self):
        # Should not raise
        MongoDBConnectionPool.close()


# ---------------------------------------------------------------------------
# get_pool_stats
# ---------------------------------------------------------------------------


class TestGetPoolStats:
    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_stats_when_connected(self, mock_client_cls):
        mock_client = fake_client()
        mock_client.server_info.return_value = {"version": "7.0.0"}
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        stats = MongoDBConnectionPool.get_pool_stats()
        assert stats["status"] == "connected"
        assert stats["server_version"] == "7.0.0"

    def test_stats_not_initialized(self):
        stats = MongoDBConnectionPool.get_pool_stats()
        assert stats["status"] == "not_initialized"

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_a_silent_server_does_not_take_the_counters_with_it(self, mock_client_cls):
        """The version is the only thing here that needs the server (#59).

        Everything else -- the configured sizes, the CMAP counters -- is counted
        in this process, and a degraded server is exactly when someone reads
        them. Letting a `buildInfo` that timed out return `{"status": "error"}`
        threw away the answer the caller came for.
        """
        mock_client = fake_client()
        mock_client.server_info.side_effect = Exception("server went quiet")
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        stats = MongoDBConnectionPool.get_pool_stats()

        assert stats["server_version"] is None
        assert stats["pool_config"] == {"maxPoolSize": 100, "minPoolSize": 10}
        assert stats["total_connections"] == 0
        assert stats["active_connections"] == 0

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_stats_on_error(self, mock_client_cls):
        """A failure to read the local state is still an error."""
        mock_client = fake_client()
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        with patch.object(
            MongoDBConnectionPool,
            "_effective_options",
            side_effect=Exception("stats error"),
        ):
            stats = MongoDBConnectionPool.get_pool_stats()

        assert stats["status"] == "error"

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_asks_the_server_for_its_version_once(self, mock_client_cls):
        """The version does not change between two calls (#59).

        `server_info()` is `buildInfo`: 6.289 bytes in MongoDB, pinned to the
        primary, and it used to run on every single call.
        """
        mock_client = fake_client()
        mock_client.server_info.return_value = {"version": "8.2.7"}
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        for _ in range(5):
            stats = MongoDBConnectionPool.get_pool_stats()

        assert stats["server_version"] == "8.2.7"
        mock_client.server_info.assert_called_once()

    @patch("mongodb_session_manager.mongodb_connection_pool.pymongo_timeout")
    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_bounds_the_version_lookup_too(self, mock_client_cls, mock_timeout):
        """Otherwise the first call against a mute server hangs for 20 s."""
        mock_client = fake_client()
        mock_client.server_info.return_value = {"version": "8.2.7"}
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        MongoDBConnectionPool.get_pool_stats()

        mock_timeout.assert_called_once()

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_reports_pool_utilisation(self, mock_client_cls):
        """The three keys the SessionViewer has always asked for (#59)."""
        mock_client = fake_client()
        mock_client.server_info.return_value = {"version": "8.2.7"}
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        telemetry = next(
            listener
            for listener in mock_client_cls.call_args[1]["event_listeners"]
            if isinstance(listener, PoolTelemetry)
        )
        event = MagicMock(duration=0.5)
        telemetry.connection_created(event)
        telemetry.connection_created(event)
        telemetry.connection_checked_out(event)

        stats = MongoDBConnectionPool.get_pool_stats()

        assert stats["total_connections"] == 2
        assert stats["active_connections"] == 1
        assert stats["available_connections"] == 1
        assert stats["checkout_wait_ms_max"] == pytest.approx(500.0)

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_still_reports_the_configured_pool_size(self, mock_client_cls):
        mock_client = fake_client()
        mock_client.server_info.return_value = {"version": "8.2.7"}
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        stats = MongoDBConnectionPool.get_pool_stats()

        assert stats["pool_config"] == {"maxPoolSize": 100, "minPoolSize": 10}
