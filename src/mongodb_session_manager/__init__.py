"""MongoDB Session Manager for Strands Agents."""

from .mongodb_session_manager import (
    MongoDBSessionManager,
    create_mongodb_session_manager,
)
from .mongodb_session_repository import MongoDBSessionRepository
from .mongodb_connection_pool import MongoDBConnectionPool
from .mongodb_session_factory import (
    MongoDBSessionManagerFactory,
    initialize_global_factory,
    get_global_factory,
    close_global_factory,
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
]
__version__ = "0.1.6"
__author__ = "Iñaki Guinea Beristain"
__author_email__ = "iguinea@gmail.com"
