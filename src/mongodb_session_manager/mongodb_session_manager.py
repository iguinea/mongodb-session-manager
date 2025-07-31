"""Itzulbira Session Manager implementation for Strands Agents."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Callable

from pymongo import MongoClient
from strands import Agent
from strands.session.repository_session_manager import RepositorySessionManager
from strands.types.content import Message
from strands import tool
from strands.types.tools import JSONSchema

from .mongodb_session_repository import MongoDBSessionRepository

logger = logging.getLogger(__name__)


class MongoDBSessionManager(RepositorySessionManager):
    """MongoDB Session Manager for Strands Agents with comprehensive session persistence and metadata management.

    This class provides a complete session management solution for Strands Agents, storing conversations,
    agent state, and metadata in MongoDB. It extends RepositorySessionManager from the Strands SDK to
    provide MongoDB-specific functionality with automatic metrics tracking and metadata management.

    Key Features:
        - Persistent storage of agent conversations and state in MongoDB
        - Automatic capture of event loop metrics (tokens, latency) during sync operations
        - Partial metadata updates that preserve existing fields
        - Built-in metadata tool for agent integration
        - Smart connection management (supports both owned and borrowed MongoDB clients)
        - Thread-safe operations with connection pooling support

    Methods:
        __init__(session_id, connection_string, database_name, collection_name, client, **kwargs):
            Initialize the session manager with MongoDB connection details.

        append_message(message, agent):
            Append a message to the session for the specified agent.

        redact_latest_message(redact_message, agent, **kwargs):
            Redact the latest message in the conversation.

        sync_agent(agent, **kwargs):
            Synchronize agent data and capture event loop metrics (tokens, latency).

        initialize(agent, **kwargs):
            Initialize an agent with the session, loading conversation history.

        update_metadata(metadata):
            Update session metadata with partial updates (preserves existing fields).

        get_metadata():
            Retrieve all metadata for the current session.

        delete_metadata(metadata_keys):
            Delete specific metadata fields from the session.

        get_metadata_tool():
            Get a Strands tool that agents can use to manage metadata autonomously.

        close():
            Close the MongoDB connection and clean up resources.

    Example:
        ```python
        # Create session manager
        session_manager = MongoDBSessionManager(
            session_id="user-123",
            connection_string="mongodb://localhost:27017/",
            database_name="chat_db",
            collection_name="sessions"
        )

        # Create agent with session persistence
        agent = Agent(
            model="claude-3-sonnet",
            session_manager=session_manager,
            tools=[session_manager.get_metadata_tool()]
        )

        # Use the agent
        response = agent("Hello!")
        session_manager.sync_agent(agent)  # Captures metrics

        # Manage metadata
        session_manager.update_metadata({"user_name": "Alice", "topic": "AI"})
        metadata = session_manager.get_metadata()

        # Clean up
        session_manager.close()
        ```
    """

    def __init__(
        self,
        session_id: str,
        connection_string: Optional[str] = None,
        database_name: str = "database_name",
        collection_name: str = "collection_name",
        client: Optional[MongoClient] = None,
        metadata_fields: Optional[List[str]] = None,
        metadataHook: Optional[Callable[[Dict[str, Any]], None]] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize Itzulbira Session Manager.

        Args:
            session_id: Unique identifier for the session
            connection_string: MongoDB connection string (ignored if client is provided)
            database_name: Name of the database
            collection_name: Name of the collection for sessions
            client: Optional pre-configured MongoClient to use
            metadata_fields: List of fields to be indexed in the metadata
            metadataHook: Hook to be called when metadata is updated, deleted or retrieved
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
            metadata_fields=metadata_fields,
            **mongo_kwargs,
        )

        # Initialize parent class with repository
        super().__init__(
            session_id=session_id,
            session_repository=self.session_repository,
            **parent_kwargs,
        )
        
        # Apply metadata hook if provided
        if metadataHook:
            self._apply_metadata_hook(metadataHook)

        logger.info(f"Initialized Itzulbira session manager for session: {session_id}")
    
    def _apply_metadata_hook(self, hook: Callable) -> None:
        """Apply the metadata hook as a decorator to metadata methods.
        
        The hook will be called with:
        - original_func: The original method being wrapped
        - action: "update", "get", or "delete"
        - session_id: The current session ID
        - **kwargs: Additional arguments (metadata for update, keys for delete)
        """
        # Wrap update_metadata
        original_update = self.update_metadata
        def wrapped_update(metadata: Dict[str, Any]) -> None:
            return hook(original_update, "update", self.session_id, metadata=metadata)
        self.update_metadata = wrapped_update
        
        # Wrap get_metadata
        original_get = self.get_metadata
        def wrapped_get() -> Dict[str, Any]:
            return hook(original_get, "get", self.session_id)
        self.get_metadata = wrapped_get
        
        # Wrap delete_metadata
        original_delete = self.delete_metadata
        def wrapped_delete(metadata_keys: List[str]) -> None:
            return hook(original_delete, "delete", self.session_id, keys=metadata_keys)
        self.delete_metadata = wrapped_delete

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

    def get_metadata_tool(self):
        """Get a tool for managing session metadata.

        Returns:
            A Strands tool that can be used by agents to manage session metadata.
        """
        session_manager = self  # Capture reference for closure

        @tool(
            name="manage_metadata",
            description="Manage session metadata with get, set/update, or delete operations.",
            inputSchema=JSONSchema(
                {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "metadata": {"type": "object"},
                        "keys": {"type": "array"},
                    },
                    "required": ["action"],
                }
            ),
        )
        def manage_metadata(
            action: str,
            metadata: Optional[Dict[str, Any]] = None,
            keys: Optional[List[str]] = None,
        ) -> str:
            """
            Manage session metadata with get, set/update, or delete operations.

            Args:
                action: The action to perform - "get", "set", "update", or "delete"
                metadata: For set/update actions, a dictionary of key-value pairs to set
                keys: For get action, optional list of specific keys to retrieve.
                      For delete action, list of keys to remove.

            Returns:
                A string describing the result of the operation

            Examples:
                - Get all metadata: manage_metadata("get")
                - Get specific keys: manage_metadata("get", keys=["priority", "status"])
                - Set/update metadata: manage_metadata("set", {"priority": "high", "category": "support"})
                - Delete keys: manage_metadata("delete", keys=["temp_field", "old_data"])
            """
            try:
                action = action.lower()

                if action == "get":
                    # Retrieve metadata
                    all_metadata = session_manager.get_metadata()
                    if all_metadata and "metadata" in all_metadata:
                        metadata_dict = all_metadata["metadata"]
                        if keys:
                            # Return only requested keys
                            filtered = {
                                k: metadata_dict.get(k)
                                for k in keys
                                if k in metadata_dict
                            }
                            if filtered:
                                return f"Metadata retrieved: {json.dumps(filtered, default=str)}"
                            else:
                                return f"No metadata found for keys: {keys}"
                        else:
                            # Return all metadata
                            if metadata_dict:
                                return f"All metadata: {json.dumps(metadata_dict, default=str)}"
                            else:
                                return "No metadata stored in session"
                    else:
                        return "No metadata found for this session"

                elif action in ["set", "update"]:
                    # Update metadata
                    if not metadata:
                        return (
                            "Error: metadata dictionary required for set/update action"
                        )

                    session_manager.update_metadata(metadata)
                    updated_keys = list(metadata.keys())
                    return f"Successfully updated metadata fields: {updated_keys}"

                elif action == "delete":
                    # Delete metadata keys
                    if not keys:
                        return "Error: keys list required for delete action"

                    session_manager.delete_metadata(keys)
                    return f"Successfully deleted metadata fields: {keys}"

                else:
                    return f"Error: Unknown action '{action}'. Use 'get', 'set', 'update', or 'delete'"

            except Exception as e:
                logger.error(f"Error in manage_metadata tool: {e}")
                return f"Error managing metadata: {str(e)}"

        return manage_metadata


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
