"""Itzulbira Session Manager implementation for Strands Agents."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pymongo import MongoClient
from strands import Agent
from strands.session.repository_session_manager import RepositorySessionManager
from strands.types.content import Message

from .mongodb_session_repository import MongoDBSessionRepository

logger = logging.getLogger(__name__)


class MongoDBSessionManager(RepositorySessionManager):
    """Itzulbira Session Manager for Strands Agents with comprehensive metrics tracking."""

    def __init__(
        self,
        session_id: str,
        connection_string: Optional[str] = None,
        database_name: str = "database_name",
        collection_name: str = "collection_name",
        client: Optional[MongoClient] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize Itzulbira Session Manager.

        Args:
            session_id: Unique identifier for the session
            connection_string: MongoDB connection string (ignored if client is provided)
            database_name: Name of the database
            collection_name: Name of the collection for sessions
            client: Optional pre-configured MongoClient to use
            **kwargs: Additional arguments passed to parent class and MongoClient
        """
        # Extract MongoDB client kwargs
        mongo_kwargs = {}
        parent_kwargs = {}

        # Common MongoDB client options
        mongo_options = {
            "maxPoolSize",
            "minPoolSize",
            "maxIdleTimeMS",
            "waitQueueTimeoutMS",
            "serverSelectionTimeoutMS",
            "connectTimeoutMS",
            "socketTimeoutMS",
            "compressors",
            "retryWrites",
            "retryReads",
            "w",
            "journal",
            "fsync",
            "authSource",
            "authMechanism",
            "tlsAllowInvalidCertificates",
        }

        for key, value in kwargs.items():
            if key in mongo_options:
                mongo_kwargs[key] = value
            else:
                parent_kwargs[key] = value

        # Create MongoDB repository with optional client
        self.session_repository = MongoDBSessionRepository(
            connection_string=connection_string,
            database_name=database_name,
            collection_name=collection_name,
            client=client,
            **mongo_kwargs,
        )

        # Initialize parent class with repository
        super().__init__(
            session_id=session_id,
            session_repository=self.session_repository,
            **parent_kwargs,
        )

        logger.info(f"Initialized Itzulbira session manager for session: {session_id}")

    def append_message(self, message: Message, agent: Agent) -> None:
        """Append a message to the session."""
        super().append_message(message, agent)

    def redact_latest_message(
        self, redact_message: Message, agent: Agent, **kwargs: Any
    ) -> None:
        """Redact the latest message for an agent."""
        super().redact_latest_message(redact_message, agent, **kwargs)

    def sync_agent(self, agent: Agent, **kwargs: Any) -> None:
        """Sync agent data and capture model/system_prompt."""
        super().sync_agent(agent, **kwargs)

        _latencyMs = agent.event_loop_metrics.accumulated_metrics["latencyMs"]
        _inputTokens = agent.event_loop_metrics.accumulated_usage["inputTokens"]
        _outputTokens = agent.event_loop_metrics.accumulated_usage["outputTokens"]
        _totalTokens = agent.event_loop_metrics.accumulated_usage["totalTokens"]

        if _latencyMs > 0:

            # Recupera el ultimo mensaje de la conversación. Será el que updatearemos las metricas obtenidas.
            doc = self.session_repository.collection.find_one(
                {"_id": self.session_id},
                {f"agents.{agent.agent_id}.messages": {"$slice": -1}},
            )

            if doc and "agents" in doc and agent.agent_id in doc["agents"]:
                messages = doc["agents"][agent.agent_id].get("messages", [])
                if messages:
                    last_message_id = messages[-1]["message_id"]

                    update_data = {
                        f"agents.{agent.agent_id}.messages.$.event_loop_metrics.accumulated_metrics": {
                            "latencyMs": _latencyMs,
                        },
                        f"agents.{agent.agent_id}.messages.$.event_loop_metrics.accumulated_usage": {
                            "inputTokens": _inputTokens,
                            "outputTokens": _outputTokens,
                            "totalTokens": _totalTokens,
                        },
                    }
                    self.session_repository.collection.update_one(
                        {
                            "_id": self.session_id,
                            f"agents.{agent.agent_id}.messages.message_id": last_message_id,
                        },
                        {"$set": update_data},
                    )

    def initialize(self, agent: "Agent", **kwargs: Any) -> None:
        """Initialize an agent with a session."""
        super().initialize(agent, **kwargs)

    def close(self) -> None:
        """Close the underlying MongoDB connection."""
        # Access the repository through the parent class attribute
        if hasattr(self, "session_repository") and hasattr(
            self.session_repository, "close"
        ):
            self.session_repository.close()

    # CUSTOM METHODS
    def update_metadata(self, metadata: Dict[str, Any]) -> None:
        """Update the metadata for the session."""
        self.session_repository.update_metadata(self.session_id, metadata)

    def get_metadata(self) -> Dict[str, Any]:
        """Get the metadata for the session."""
        return self.session_repository.get_metadata(self.session_id)

    def delete_metadata(self, metadata_keys: List[str]) -> None:
        """Delete metadata keys for the session."""
        self.session_repository.delete_metadata(self.session_id, metadata_keys)


# Convenience factory function
def create_mongodb_session_manager(
    session_id: str,
    connection_string: Optional[str] = None,
    database_name: str = "database_name",
    collection_name: str = "collection_name",
    client: Optional[MongoClient] = None,
    **kwargs: Any,
) -> MongoDBSessionManager:
    """Create an Itzulbira Session Manager with default settings.

    Args:
        session_id: Unique identifier for the session
        connection_string: MongoDB connection string (ignored if client is provided)
        database_name: Name of the database
        collection_name: Name of the collection for sessions
        client: Optional pre-configured MongoClient to use
        **kwargs: Additional arguments passed to MongoDBSessionManager

    Returns:
        Configured MongoDBSessionManager instance
    """
    return MongoDBSessionManager(
        session_id=session_id,
        connection_string=connection_string,
        database_name=database_name,
        collection_name=collection_name,
        client=client,
        **kwargs,
    )
