"""MongoDB Session Manager for Strands Agents."""

from .mongodb_session_manager import (
    MongoDBSessionManager, 
    create_mongodb_session_manager
)
from .mongodb_session_repository import MongoDBSessionRepository
from .mongodb_connection_pool import MongoDBConnectionPool
from .mongodb_session_factory import (
    MongoDBSessionManagerFactory,
    initialize_global_factory,
    get_global_factory,
    close_global_factory
)
from .session_cache import (
    SessionMetadataCache,
    CachedMongoDBSessionManager,
    get_global_metadata_cache
)

__all__ = [
    "MongoDBSessionManager", 
    "MongoDBSessionRepository", 
    "create_mongodb_session_manager",
    "MongoDBConnectionPool",
    "MongoDBSessionManagerFactory",
    "initialize_global_factory",
    "get_global_factory",
    "close_global_factory",
    "SessionMetadataCache",
    "CachedMongoDBSessionManager",
    "get_global_metadata_cache"
]
__version__ = "0.1.0"