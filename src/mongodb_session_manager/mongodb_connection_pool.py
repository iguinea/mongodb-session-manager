"""MongoDB Connection Pool for optimized connection management in stateless environments."""

from __future__ import annotations

import logging
import time
from threading import RLock
from typing import Any

from pymongo import MongoClient
from pymongo import timeout as pymongo_timeout
from pymongo.errors import PyMongoError
from pymongo.uri_parser import parse_uri

from .pool_telemetry import PoolTelemetry

logger = logging.getLogger(__name__)

# What the pool asks for when the caller has not asked for it (#59).
#
# These are defaults, not policy: an option named in the connection string or
# passed as a keyword is left alone. See _resolve_options().
#
# maxIdleTimeMS is 5 minutes and no longer the half minute this library used to
# impose -- pymongo's own default is no expiry at all -- because it has to live
# with minPoolSize: whatever the idle timer expires, the pool reopens to stay at
# the minimum. Measured with 30 s, an idle pool with no traffic at all opened and
# closed its ten connections every half minute for ever -- 33.596 a day, per
# process and per server of the topology -- and each reopening costs 2,77 ms
# against MongoDB and 603 ms against DocumentDB. At 5 minutes that drops to 2.880
# a day while a burst's connections are still released. To turn the timer off
# entirely, pass maxIdleTimeMS=None: pymongo rejects a zero.
_POOL_DEFAULTS: dict[str, Any] = {
    "maxPoolSize": 100,
    "minPoolSize": 10,
    "maxIdleTimeMS": 300000,
    "waitQueueTimeoutMS": 5000,
    "serverSelectionTimeoutMS": 5000,
    "connectTimeoutMS": 10000,
    "socketTimeoutMS": 30000,
    "retryWrites": True,
    "retryReads": True,
}

# How long a health check may take before it is an answer in itself.
#
# Without one, a ping inherits serverSelectionTimeoutMS and socketTimeoutMS: 5 s
# against an unreachable server, and 20 s measured against a server that went
# mute with the connection already established. Callers run this from a /health
# endpoint, often on the event loop.
DEFAULT_HEALTH_CHECK_TIMEOUT_MS = 1000


class MongoDBConnectionPool:
    """Singleton MongoDB connection pool for efficient connection reuse.

    This class ensures that only one MongoClient instance is created and shared
    across all session managers, significantly improving performance in stateless
    environments like FastAPI.
    """

    _instance: MongoDBConnectionPool | None = None
    _lock: RLock = RLock()
    _client: MongoClient | None = None
    _connection_string: str | None = None
    _user_kwargs: dict[str, Any] | None = None
    _resolved_kwargs: dict[str, Any] | None = None
    _telemetry: PoolTelemetry | None = None
    _server_version: str | None = None

    def __new__(cls) -> MongoDBConnectionPool:
        """Ensure singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def initialize(cls, connection_string: str, **kwargs: Any) -> MongoClient:
        """Initialize the connection pool with given parameters.

        Args:
            connection_string: MongoDB connection string
            **kwargs: Additional arguments for MongoClient (maxPoolSize, etc.)

        Returns:
            The MongoClient instance
        """
        with cls._lock:
            instance = cls._instance or cls()

            # If already initialized with same connection string, return existing client
            if (
                instance._client is not None
                and instance._connection_string == connection_string
                and instance._user_kwargs == kwargs
            ):
                logger.debug("Returning existing MongoDB client from pool")
                return instance._client

            # Close existing client if connection parameters changed
            if instance._client is not None:
                logger.info("Connection parameters changed, recreating MongoDB client")
                try:
                    instance._client.close()
                except Exception as e:
                    logger.warning(f"Error closing previous MongoDB client: {e}")
                instance._client = None

            merged_kwargs = cls._resolve_options(connection_string, kwargs)
            telemetry = PoolTelemetry()
            merged_kwargs["event_listeners"] = [
                *merged_kwargs.get("event_listeners", []),
                telemetry,
            ]

            try:
                instance._client = MongoClient(connection_string, **merged_kwargs)
                instance._connection_string = connection_string
                # Keyed on what the user passed, not on what was resolved: this
                # is what decides whether the client is recreated.
                instance._user_kwargs = kwargs
                instance._resolved_kwargs = merged_kwargs
                instance._telemetry = telemetry
                instance._server_version = None

                # Test the connection
                instance._client.admin.command("ping")

                # Read back from the client, not from the kwargs: an option
                # that came from the connection string is not in them, and what
                # matters here is the value that ended up in force.
                effective = cls._effective_options(instance._client)
                logger.info(
                    f"MongoDB connection pool initialized - "
                    f"maxPoolSize: {effective['maxPoolSize']}, "
                    f"minPoolSize: {effective['minPoolSize']}, "
                    f"maxIdleTimeMS: {effective['maxIdleTimeMS']}, "
                    f"retryWrites: {effective['retryWrites']}"
                )

                return instance._client

            except PyMongoError as e:
                logger.error(f"Failed to initialize MongoDB connection pool: {e}")
                # Dropping the reference is not closing it: the client is
                # already built, with a monitor thread per server and, with
                # minPoolSize, connections on the way. pymongo does not close on
                # __del__, it warns -- so a startup retrying against a MongoDB
                # that is not up yet piles one of these up per attempt.
                if instance._client is not None:
                    try:
                        instance._client.close()
                    except Exception as close_error:
                        logger.warning(
                            f"Error closing the MongoDB client that failed to "
                            f"initialize: {close_error}"
                        )
                instance._client = None
                instance._telemetry = None
                raise

    @classmethod
    def _resolve_options(
        cls, connection_string: str, kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        """Apply each default only to an option the caller did not express.

        pymongo gives a constructor keyword precedence over the connection
        string, so a default passed as a keyword overrules the URI without
        saying so. That turned `?retryWrites=false` -- which AWS requires for
        DocumentDB, and which this repository's own runbook documents -- into
        `retryWrites=True`, and DocumentDB answers `OperationFailure 301` to
        every `update_one` that carries a txnNumber (#59).

        `parse_uri` normalises the option names, so `?maxpoolsize=7` is seen as
        `maxPoolSize`. pymongo takes its keywords case-insensitively too, so the
        match is made on the lowercased name: comparing the spelling let
        `maxpoolsize=5` through *alongside* our own `maxPoolSize`, and the two
        contradicted each other. It also resolves DNS for `mongodb+srv://`,
        which can fail: the defaults are still applied then, and the MongoClient
        built next raises the real error if the URI is genuinely unusable.
        """
        try:
            uri_options = parse_uri(connection_string)["options"]
        except Exception as e:
            logger.warning(
                f"Could not read the options of the connection string, "
                f"applying every pool default: {e}"
            )
            uri_options = {}

        # A keyword beats the URI in pymongo, and it beats it here too: it is
        # written last, so it wins the collision when both spell one option.
        named = {
            name.lower(): value for name, value in {**uri_options, **kwargs}.items()
        }
        defaults = {
            name: value
            for name, value in _POOL_DEFAULTS.items()
            if name.lower() not in named
        }

        # The floor and the ceiling of the pool are one setting in two halves:
        # pymongo refuses a minPoolSize above maxPoolSize, and the ValueError it
        # raises is not a PyMongoError, so it escapes initialize() bare. Nobody
        # may be turned away at startup by the half they did not choose -- a
        # small `?maxPoolSize=4` for a constrained container, a large
        # `minPoolSize=200` for a busy one -- so that half gives way. When both
        # are the caller's and they contradict each other, the decision is
        # theirs and pymongo says so.
        floor = named.get("minpoolsize", _POOL_DEFAULTS["minPoolSize"])
        ceiling = named.get("maxpoolsize", _POOL_DEFAULTS["maxPoolSize"])
        if isinstance(floor, int) and isinstance(ceiling, int) and floor > ceiling:
            if "minPoolSize" in defaults:
                defaults["minPoolSize"] = ceiling
            elif "maxPoolSize" in defaults:
                defaults["maxPoolSize"] = floor

        return {**defaults, **kwargs}

    @staticmethod
    def _effective_options(client: MongoClient) -> dict[str, Any]:
        """What the driver ended up with, whoever asked for it.

        The resolved kwargs no longer tell the whole story: an option named in
        the connection string is deliberately absent from them.
        """
        pool_options = client.options.pool_options
        max_idle_seconds = pool_options.max_idle_time_seconds
        return {
            "maxPoolSize": pool_options.max_pool_size,
            "minPoolSize": pool_options.min_pool_size,
            "maxIdleTimeMS": (
                None if max_idle_seconds is None else int(max_idle_seconds * 1000)
            ),
            "retryWrites": client.options.retry_writes,
            "retryReads": client.options.retry_reads,
        }

    @classmethod
    def get_client(cls) -> MongoClient | None:
        """Get the current MongoDB client.

        Returns:
            The MongoClient instance or None if not initialized
        """
        instance = cls()
        return instance._client

    @classmethod
    def close(cls) -> None:
        """Close the MongoDB connection pool."""
        with cls._lock:
            instance = cls._instance or cls()
            if instance._client is not None:
                try:
                    instance._client.close()
                    logger.info("MongoDB connection pool closed")
                except Exception as e:
                    logger.error(f"Error closing MongoDB connection pool: {e}")
                finally:
                    instance._client = None
                    instance._connection_string = None
                    instance._user_kwargs = None
                    instance._resolved_kwargs = None
                    instance._telemetry = None
                    instance._server_version = None

    @classmethod
    def health_check(
        cls, timeout_ms: int = DEFAULT_HEALTH_CHECK_TIMEOUT_MS
    ) -> dict[str, Any]:
        """Ask the server whether it is there, within a time you choose.

        A `ping` rather than `server_info()`: not because it is faster -- the
        two are indistinguishable, the cost is the round-trip -- but because
        `server_info()` is `buildInfo` pinned to `ReadPreference.PRIMARY`, so it
        reports a cluster unhealthy during a failover even while the
        application keeps reading from a secondary. And because 17 bytes of
        answer beat 6.289 (#59).

        The timeout is the point. Without one the call inherits
        serverSelectionTimeoutMS and socketTimeoutMS: 5 s against an
        unreachable server, 20 s measured against one that went mute with its
        connection already open. That is a thread, or an event loop, held for
        20 s.

        Args:
            timeout_ms: How long the ping may take before it counts as a
                failure. Applies to the whole operation, selection included.

        Returns:
            `status` of `connected`, `error` or `not_initialized`, plus
            `latency_ms`, and `error` when it failed. Never raises: an
            unreachable server is the answer, not an exception.
        """
        instance = cls()
        if instance._client is None:
            return {"status": "not_initialized"}

        started = time.perf_counter()
        try:
            with pymongo_timeout(timeout_ms / 1000):
                instance._client.admin.command("ping")
        except Exception as e:
            latency_ms = round((time.perf_counter() - started) * 1000, 3)
            logger.warning(f"MongoDB health check failed after {latency_ms} ms: {e}")
            return {"status": "error", "error": str(e), "latency_ms": latency_ms}

        return {
            "status": "connected",
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }

    @classmethod
    def _cached_server_version(cls, instance: MongoDBConnectionPool) -> str:
        """Ask the server for its version once and remember it.

        It cannot change under a live client, and asking costs a `buildInfo`
        against the primary. Bounded in time for the same reason as
        health_check(): the first call must not be able to hang.
        """
        if instance._server_version is None and instance._client is not None:
            with pymongo_timeout(DEFAULT_HEALTH_CHECK_TIMEOUT_MS / 1000):
                server_info = instance._client.server_info()
            instance._server_version = server_info.get("version", "unknown")
        return instance._server_version or "unknown"

    @classmethod
    def get_pool_stats(cls) -> dict[str, Any]:
        """Get connection pool statistics.

        Returns the configuration and what the pool is actually doing:
        `total_connections`, `active_connections`, `available_connections`,
        `checkout_failures` and `checkout_wait_ms_max`, counted from the
        driver's CMAP events. pymongo publishes no other way to know (#59).

        Read `checkout_wait_ms_max` before `maxPoolSize`: a wait only appears
        when there was no warm connection, and that is usually minPoolSize
        being too low rather than maxPoolSize being too small.

        `status` says whether the pool is initialized, not whether the server
        answers -- that is what health_check() is for. `server_version` is the
        one field here that needs the server, and it comes back `None` when it
        did not answer, without taking the counters with it.

        Returns:
            Dictionary with pool statistics
        """
        instance = cls()
        if instance._client is None:
            return {"status": "not_initialized"}

        try:
            effective = cls._effective_options(instance._client)
            stats: dict[str, Any] = {
                "status": "connected",
                "pool_config": {
                    "maxPoolSize": effective["maxPoolSize"],
                    "minPoolSize": effective["minPoolSize"],
                },
            }
            if instance._telemetry is not None:
                stats.update(instance._telemetry.snapshot().as_dict())

        except Exception as e:
            logger.error(f"Error getting pool stats: {e}")
            return {"status": "error", "error": str(e)}

        # Asked for last and on its own: everything above is counted in this
        # process, and a server too busy to answer a buildInfo is exactly when
        # someone is reading these counters.
        try:
            stats["server_version"] = cls._cached_server_version(instance)
        except Exception as e:
            logger.warning(f"Could not read the MongoDB server version: {e}")
            stats["server_version"] = None

        return stats
