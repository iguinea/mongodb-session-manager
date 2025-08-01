"""Factory pattern for creating MongoDB session managers with connection pooling."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pymongo import MongoClient

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
        connection_string: Optional[str] = None,
        database_name: str = "database_name",
        collection_name: str = "collection_name",
        client: Optional[MongoClient] = None,
        metadata_fields: Optional[List[str]] = None,
        **client_kwargs: Any,
    ) -> None:
        """Initialize the session manager factory.

        Args:
            connection_string: MongoDB connection string (required if client not provided)
            database_name: Default database name for sessions
            collection_name: Default collection name for sessions
            client: Pre-configured MongoClient (takes precedence over connection_string)
            metadata_fields: List of fields to include in metadata
            **client_kwargs: Additional arguments for MongoClient configuration
        """
        self.database_name = database_name
        self.collection_name = collection_name
        self.metadata_fields = metadata_fields

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

        # Cache for index creation status (per collection)
        self._indexes_created: Dict[str, bool] = {}

    def create_session_manager(
        self,
        session_id: str,
        database_name: Optional[str] = None,
        collection_name: Optional[str] = None,
        metadata_fields: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> MongoDBSessionManager:
        """Create a new session manager instance.

        Args:
            session_id: Unique identifier for the session
            database_name: Override default database name
            collection_name: Override default collection name
            metadata_fields: Override default metadata fields
            **kwargs: Additional arguments for MongoDBSessionManager (including hooks)

        Returns:
            New MongoDBSessionManager instance using shared connection
        """
        db_name = database_name or self.database_name
        coll_name = collection_name or self.collection_name
        meta_fields = metadata_fields or self.metadata_fields

        # Create session manager with shared client
        manager = MongoDBSessionManager(
            session_id=session_id,
            database_name=db_name,
            collection_name=coll_name,
            client=self._client,
            metadata_fields=meta_fields,
            **kwargs,
        )

        return manager

    def get_connection_stats(self) -> Dict[str, Any]:
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
_global_factory: Optional[MongoDBSessionManagerFactory] = None


def initialize_global_factory(
    connection_string: str,
    database_name: str = "database_name",
    collection_name: str = "virtualagent_sessions",
    metadata_fields: Optional[List[str]] = None,
    **client_kwargs: Any,
) -> MongoDBSessionManagerFactory:
    """Initialize the global factory instance.

    This should be called once during FastAPI startup.

    Args:
        connection_string: MongoDB connection string
        database_name: Default database name
        collection_name: Default collection name
        **client_kwargs: Additional MongoDB client configuration

    Returns:
        The initialized global factory
    """
    global _global_factory

    if _global_factory is not None:
        logger.warning("Global factory already initialized, closing existing one")
        _global_factory.close()

    _global_factory = MongoDBSessionManagerFactory(
        connection_string=connection_string,
        database_name=database_name,
        collection_name=collection_name,
        metadata_fields=metadata_fields,
        **client_kwargs,
    )

    logger.info("Global session manager factory initialized")
    return _global_factory


def get_global_factory() -> MongoDBSessionManagerFactory:
    """Get the global factory instance.

    Returns:
        The global factory instance

    Raises:
        RuntimeError: If factory not initialized
    """
    if _global_factory is None:
        raise RuntimeError(
            "Global factory not initialized. "
            "Call initialize_global_factory() during startup."
        )
    return _global_factory


def close_global_factory() -> None:
    """Close the global factory and clean up resources.

    This should be called during FastAPI shutdown.
    """
    global _global_factory

    if _global_factory is not None:
        _global_factory.close()
        _global_factory = None
        logger.info("Global factory closed")
