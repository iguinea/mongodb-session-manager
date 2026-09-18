"""Factory pattern for creating MongoDB session managers with connection pooling."""

from __future__ import annotations

import logging
import threading
from typing import Any

from pymongo import MongoClient

from .field_names import nested_document
from .mongodb_connection_pool import MongoDBConnectionPool
from .mongodb_session_manager import MongoDBSessionManager

logger = logging.getLogger(__name__)


class MongoDBSessionManagerFactory:
    """Factory for creating MongoDB session managers with shared connection pool.

    This factory ensures efficient resource usage in stateless environments
    by reusing MongoDB connections across multiple session managers.
    """

    def __init__(
        self,
        connection_string: str | None = None,
        database_name: str = "database_name",
        collection_name: str = "collection_name",
        client: MongoClient | None = None,
        metadata_fields: list[str] | None = None,
        application_name: str | None = None,
        **client_kwargs: Any,
    ) -> None:
        """Initialize the session manager factory.

        Args:
            connection_string: MongoDB connection string (required if client not provided)
            database_name: Default database name for sessions
            collection_name: Default collection name for sessions
            client: Pre-configured MongoClient (takes precedence over connection_string)
            metadata_fields: List of fields to include in metadata
            application_name: Default application name for all sessions created by this factory
            **client_kwargs: Additional arguments for MongoClient configuration

        Raises:
            ValueError: If a metadata field is not a valid dot-notation path, or
                if two of them cannot coexist in one document (`user` and
                `user.name`). Checked here, before connecting, so a bad config
                fails the application's startup instead of every request (#79).
        """
        # Built and thrown away: what matters is that an unusable configuration
        # raises here, at startup, and not on the first session of every request.
        nested_document(metadata_fields or ())
        self.database_name = database_name
        self.collection_name = collection_name
        self.metadata_fields = metadata_fields
        self.application_name = application_name

        if client is not None:
            # Use provided client
            self._client = client
            self._owns_client = False
            logger.info("Factory initialized with provided MongoDB client")
        elif connection_string is not None:
            # Initialize connection pool
            self._client = MongoDBConnectionPool.initialize(
                connection_string=connection_string, **client_kwargs
            )
            self._owns_client = True
            logger.info("Factory initialized with connection pool")
        else:
            raise ValueError("Either connection_string or client must be provided")

    def create_session_manager(
        self,
        session_id: str,
        database_name: str | None = None,
        collection_name: str | None = None,
        metadata_fields: list[str] | None = None,
        application_name: str | None = None,
        **kwargs: Any,
    ) -> MongoDBSessionManager:
        """Create a new session manager instance.

        Args:
            session_id: Unique identifier for the session
            database_name: Override default database name
            collection_name: Override default collection name
            metadata_fields: Override default metadata fields
            application_name: Override default application name for this session
            **kwargs: Additional arguments for MongoDBSessionManager (including hooks)

        Returns:
            New MongoDBSessionManager instance using shared connection
        """
        db_name = database_name if database_name is not None else self.database_name
        coll_name = (
            collection_name if collection_name is not None else self.collection_name
        )
        meta_fields = (
            metadata_fields if metadata_fields is not None else self.metadata_fields
        )
        app_name = (
            application_name if application_name is not None else self.application_name
        )

        # Create session manager with shared client
        manager = MongoDBSessionManager(
            session_id=session_id,
            database_name=db_name,
            collection_name=coll_name,
            client=self._client,
            metadata_fields=meta_fields,
            application_name=app_name,
            **kwargs,
        )

        return manager

    def get_connection_stats(self) -> dict[str, Any]:
        """Get statistics about the MongoDB connection pool.

        Returns:
            Dictionary with connection pool statistics
        """
        if self._owns_client:
            return MongoDBConnectionPool.get_pool_stats()
        else:
            return {
                "status": "external_client",
                "message": "Using externally managed MongoDB client",
            }

    def close(self) -> None:
        """Close the factory and clean up resources."""
        if self._owns_client:
            MongoDBConnectionPool.close()
            logger.info("Factory connection pool closed")
        else:
            logger.info("Factory using external client - not closing")


# Global factory instance for FastAPI integration
_global_factory: MongoDBSessionManagerFactory | None = None

# Serializes every lifecycle transition of _global_factory (#124): without it,
# two concurrent initialize_global_factory() calls can both see None, build
# two factories and orphan one while its managers are still alive, and close
# and get interleave the same way. Replacing the previous factory stays the
# sequential contract; only the interleavings are gone.
_factory_lock = threading.Lock()


def initialize_global_factory(
    connection_string: str,
    database_name: str = "database_name",
    collection_name: str = "collection_name",
    metadata_fields: list[str] | None = None,
    application_name: str | None = None,
    **client_kwargs: Any,
) -> MongoDBSessionManagerFactory:
    """Initialize the global factory instance.

    Thread-safe (#124): the close-and-replace transition is serialized by an
    internal lock, so concurrent calls cannot see an empty global at the same
    time and orphan one of the two factories. The sequential contract is
    unchanged: a second call closes the previous factory -- which invalidates
    every factory and manager created from it, because the pool singleton
    closes the client they hold -- and installs the new one as the global.

    If building the new factory raises (for example the bounded startup ping
    of #122 against an unreachable MongoDB), the previous factory is already
    closed and cannot be restored: the global is left empty and the error
    propagates, so the next `get_global_factory()` raises `RuntimeError`
    instead of handing out a client that answers `InvalidOperation` to
    everything. Re-call this function once the server is reachable.

    Args:
        connection_string: MongoDB connection string
        database_name: Default database name
        collection_name: Default collection name
        metadata_fields: Default metadata fields to index
        application_name: Default application name for all sessions
        **client_kwargs: Additional MongoDB client configuration

    Returns:
        The initialized global factory
    """
    global _global_factory

    with _factory_lock:
        if _global_factory is not None:
            logger.warning("Global factory already initialized, closing existing one")
            _global_factory.close()
            _global_factory = None

        try:
            new_factory = MongoDBSessionManagerFactory(
                connection_string=connection_string,
                database_name=database_name,
                collection_name=collection_name,
                metadata_fields=metadata_fields,
                application_name=application_name,
                **client_kwargs,
            )
        except Exception:
            logger.error(
                "Global factory initialization failed; the previous factory "
                "was closed and the global is left uninitialized"
            )
            raise

        _global_factory = new_factory

    logger.info("Global session manager factory initialized")
    return _global_factory


def get_global_factory() -> MongoDBSessionManagerFactory:
    """Get the global factory instance.

    Thread-safe (#124): the read takes the lifecycle lock, so a factory being
    closed by `close_global_factory()` or replaced by
    `initialize_global_factory()` is never handed out half-transitioned.

    Returns:
        The global factory instance

    Raises:
        RuntimeError: If factory not initialized
    """
    with _factory_lock:
        factory = _global_factory
    if factory is None:
        raise RuntimeError(
            "Global factory not initialized. "
            "Call initialize_global_factory() during startup."
        )
    return factory


def close_global_factory() -> None:
    """Close the global factory and clean up resources.

    Thread-safe (#124): the close-and-clear transition is serialized by the
    lifecycle lock, so a concurrent `get_global_factory()` cannot observe the
    factory between its close and its removal from the global.

    This should be called during FastAPI shutdown.
    """
    global _global_factory

    with _factory_lock:
        if _global_factory is not None:
            _global_factory.close()
            _global_factory = None
            logger.info("Global factory closed")
