"""MongoDB Connection Pool for optimized connection management in stateless environments."""

from __future__ import annotations

import logging
from threading import RLock
from typing import Any, Dict, Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)


class MongoDBConnectionPool:
    """Singleton MongoDB connection pool for efficient connection reuse.

    This class ensures that only one MongoClient instance is created and shared
    across all session managers, significantly improving performance in stateless
    environments like FastAPI.
    """

    _instance: Optional[MongoDBConnectionPool] = None
    _lock: RLock = RLock()
    _client: Optional[MongoClient] = None
    _connection_string: Optional[str] = None
    _user_kwargs: Optional[Dict[str, Any]] = None
    _resolved_kwargs: Optional[Dict[str, Any]] = None

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

            # Create new client with optimized defaults for high concurrency
            default_kwargs = {
                "maxPoolSize": 100,
                "minPoolSize": 10,
                "maxIdleTimeMS": 30000,
                "waitQueueTimeoutMS": 5000,
                "serverSelectionTimeoutMS": 5000,
                "connectTimeoutMS": 10000,
                "socketTimeoutMS": 30000,
                "retryWrites": True,
                "retryReads": True,
            }

            # Merge with user-provided kwargs (user kwargs take precedence)
            merged_kwargs = {**default_kwargs, **kwargs}

            try:
                instance._client = MongoClient(connection_string, **merged_kwargs)
                instance._connection_string = connection_string
                instance._user_kwargs = kwargs
                instance._resolved_kwargs = merged_kwargs

                # Test the connection
                instance._client.admin.command("ping")

                logger.info(
                    f"MongoDB connection pool initialized - "
                    f"maxPoolSize: {merged_kwargs['maxPoolSize']}, "
                    f"minPoolSize: {merged_kwargs['minPoolSize']}, "
                    f"retryWrites: {merged_kwargs['retryWrites']}, "
                    f"retryReads: {merged_kwargs['retryReads']}"
                )

                return instance._client

            except PyMongoError as e:
                logger.error(f"Failed to initialize MongoDB connection pool: {e}")
                instance._client = None
                raise

    @classmethod
    def get_client(cls) -> Optional[MongoClient]:
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

    @classmethod
    def get_pool_stats(cls) -> Dict[str, Any]:
        """Get connection pool statistics.

        Returns:
            Dictionary with pool statistics
        """
        instance = cls()
        if instance._client is None:
            return {"status": "not_initialized"}

        try:
            server_info = instance._client.server_info()
            resolved = instance._resolved_kwargs or {}

            stats = {
                "status": "connected",
                "server_version": server_info.get("version", "unknown"),
                "pool_config": {
                    "maxPoolSize": resolved.get("maxPoolSize"),
                    "minPoolSize": resolved.get("minPoolSize"),
                },
            }

            return stats

        except Exception as e:
            logger.error(f"Error getting pool stats: {e}")
            return {"status": "error", "error": str(e)}
