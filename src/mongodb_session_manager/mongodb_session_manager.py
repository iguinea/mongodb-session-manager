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
        feedbackHook: Optional[Callable[[Dict[str, Any]], None]] = None,
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
            feedbackHook: Hook to be called when feedback is added
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
        
        # Apply feedback hook if provided
        if feedbackHook:
            self._apply_feedback_hook(feedbackHook)

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
        """Sync agent data and capture model/system_prompt.

        Captures comprehensive metrics from the agent's event loop including:
        - Token usage (input, output, total, cache read/write)
        - Performance metrics (latency, time to first byte)
        - Cycle metrics (count, durations, averages)
        - Tool metrics (call counts, success/error rates, execution times)
        """
        super().sync_agent(agent, **kwargs)

        # Get metrics using get_summary() for comprehensive data
        metrics_summary = agent.event_loop_metrics.get_summary()

        # Extract token usage metrics
        accumulated_usage = metrics_summary.get("accumulated_usage", {})
        _inputTokens = accumulated_usage.get("inputTokens", 0)
        _outputTokens = accumulated_usage.get("outputTokens", 0)
        _totalTokens = accumulated_usage.get("totalTokens", 0)
        # Cache metrics for AWS Bedrock prompt caching (optional, backwards compatible)
        _cacheReadInputTokens = accumulated_usage.get("cacheReadInputTokens", 0)
        _cacheWriteInputTokens = accumulated_usage.get("cacheWriteInputTokens", 0)

        # Extract performance metrics
        accumulated_metrics = metrics_summary.get("accumulated_metrics", {})
        _latencyMs = accumulated_metrics.get("latencyMs", 0)
        _timeToFirstByteMs = accumulated_metrics.get("timeToFirstByteMs", 0)

        # Extract cycle metrics
        _cycle_count = metrics_summary.get("total_cycles", 0)
        _total_duration = metrics_summary.get("total_duration", 0.0)
        _average_cycle_time = metrics_summary.get("average_cycle_time", 0.0)

        # Extract tool metrics (simplified structure for storage)
        tool_usage_raw = metrics_summary.get("tool_usage", {})
        _tool_usage = {}
        for tool_name, tool_data in tool_usage_raw.items():
            exec_stats = tool_data.get("execution_stats", {})
            _tool_usage[tool_name] = {
                "call_count": exec_stats.get("call_count", 0),
                "success_count": exec_stats.get("success_count", 0),
                "error_count": exec_stats.get("error_count", 0),
                "total_time": exec_stats.get("total_time", 0.0),
                "average_time": exec_stats.get("average_time", 0.0),
                "success_rate": exec_stats.get("success_rate", 0.0),
            }

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
                            "timeToFirstByteMs": _timeToFirstByteMs,
                        },
                        f"agents.{agent.agent_id}.messages.$.event_loop_metrics.accumulated_usage": {
                            "inputTokens": _inputTokens,
                            "outputTokens": _outputTokens,
                            "totalTokens": _totalTokens,
                            "cacheReadInputTokens": _cacheReadInputTokens,
                            "cacheWriteInputTokens": _cacheWriteInputTokens,
                        },
                        f"agents.{agent.agent_id}.messages.$.event_loop_metrics.cycle_metrics": {
                            "cycle_count": _cycle_count,
                            "total_duration": _total_duration,
                            "average_cycle_time": _average_cycle_time,
                        },
                        f"agents.{agent.agent_id}.messages.$.event_loop_metrics.tool_usage": _tool_usage,
                    }
                    self.session_repository.collection.update_one(
                        {
                            "_id": self.session_id,
                            f"agents.{agent.agent_id}.messages.message_id": last_message_id,
                        },
                        {"$set": update_data},
                    )

        # Capture and store agent configuration (model and system_prompt)
        agent_config_update = {}
        if hasattr(agent, "model") and agent.model:
            # Extract model identifier as string from BedrockModel.config['model_id']
            # or fall back to model_id attribute or str representation
            model_id = None
            if hasattr(agent.model, "config") and isinstance(agent.model.config, dict):
                model_id = agent.model.config.get("model_id")
            if not model_id:
                model_id = getattr(agent.model, "model_id", str(agent.model))
            agent_config_update[f"agents.{agent.agent_id}.agent_data.model"] = model_id
        if hasattr(agent, "system_prompt") and agent.system_prompt:
            agent_config_update[f"agents.{agent.agent_id}.agent_data.system_prompt"] = agent.system_prompt

        if agent_config_update:
            self.session_repository.collection.update_one(
                {"_id": self.session_id},
                {"$set": agent_config_update},
            )
            logger.debug(f"Captured agent configuration for {agent.agent_id}: model={model_id if 'model_id' in locals() else 'N/A'}")

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
            metadata: Optional[Any] = None,
            keys: Optional[Any] = None,
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

                # Handle case where model sends metadata as JSON string instead of dict
                if metadata is not None and isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except json.JSONDecodeError:
                        return f"Error: metadata must be a valid JSON object, got: {metadata[:100]}..."

                # Handle case where model sends keys as JSON string instead of list
                if keys is not None and isinstance(keys, str):
                    try:
                        keys = json.loads(keys)
                    except json.JSONDecodeError:
                        return f"Error: keys must be a valid JSON array, got: {keys[:100]}..."

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
    
    def _apply_feedback_hook(self, hook: Callable) -> None:
        """Apply the feedback hook as a decorator to feedback methods.

        The hook will be called with:
        - original_func: The original method being wrapped
        - action: "add" (only action for feedback)
        - session_id: The current session ID
        - **kwargs: Additional arguments (feedback object, session_manager instance)
        """
        # Wrap add_feedback
        original_add = self.add_feedback
        def wrapped_add(feedback: Dict[str, Any]) -> None:
            return hook(original_add, "add", self.session_id,
                       session_manager=self, feedback=feedback)
        self.add_feedback = wrapped_add
    
    def add_feedback(self, feedback: Dict[str, Any]) -> None:
        """Add feedback to the session."""
        self.session_repository.add_feedback(self.session_id, feedback)
    
    def get_feedbacks(self) -> List[Dict[str, Any]]:
        """Get all feedbacks for the session."""
        return self.session_repository.get_feedbacks(self.session_id)

    def get_session_viewer_password(self) -> Optional[str]:
        """Get the session viewer password for this session.

        Returns:
            The session viewer password string, or None if session not found

        Example:
            password = session_manager.get_session_viewer_password()
            if password:
                print(f"Session Viewer URL: http://localhost:8883?session_id={session_id}&password={password}")
        """
        return self.session_repository.get_session_viewer_password(self.session_id)

    def get_agent_config(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get configuration (model and system_prompt) for a specific agent.

        Args:
            agent_id: ID of the agent to retrieve configuration for

        Returns:
            Dict with agent_id, model, and system_prompt if found, None if agent doesn't exist

        Example:
            config = session_manager.get_agent_config("assistant-1")
            if config:
                print(f"Model: {config.get('model')}")
                print(f"System prompt: {config.get('system_prompt')}")
        """
        try:
            doc = self.session_repository.collection.find_one(
                {"_id": self.session_id},
                {f"agents.{agent_id}.agent_data": 1}
            )

            if not doc or "agents" not in doc or agent_id not in doc["agents"]:
                logger.debug(f"Agent {agent_id} not found in session {self.session_id}")
                return None

            agent_data = doc["agents"][agent_id].get("agent_data", {})

            return {
                "agent_id": agent_id,
                "model": agent_data.get("model"),
                "system_prompt": agent_data.get("system_prompt")
            }
        except Exception as e:
            logger.error(f"Failed to get agent config for {agent_id}: {e}")
            return None

    def update_agent_config(
        self,
        agent_id: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None
    ) -> None:
        """Update model or system_prompt for a specific agent.

        Args:
            agent_id: ID of the agent to update
            model: New model identifier (optional)
            system_prompt: New system prompt (optional)

        Raises:
            ValueError: If agent doesn't exist

        Example:
            # Update only model
            session_manager.update_agent_config("assistant-1", model="claude-3-opus")

            # Update only system_prompt
            session_manager.update_agent_config(
                "assistant-1",
                system_prompt="You are an expert coder"
            )

            # Update both
            session_manager.update_agent_config(
                "assistant-1",
                model="claude-3-opus",
                system_prompt="You are an expert coder"
            )
        """
        # Build update dict
        update_fields = {}
        if model is not None:
            update_fields[f"agents.{agent_id}.agent_data.model"] = model
        if system_prompt is not None:
            update_fields[f"agents.{agent_id}.agent_data.system_prompt"] = system_prompt

        if not update_fields:
            logger.warning(f"No fields to update for agent {agent_id}")
            return

        try:
            result = self.session_repository.collection.update_one(
                {"_id": self.session_id},
                {"$set": update_fields}
            )

            if result.matched_count == 0:
                raise ValueError(f"Session {self.session_id} not found")

            logger.info(f"Updated agent config for {agent_id}: {list(update_fields.keys())}")
        except Exception as e:
            logger.error(f"Failed to update agent config for {agent_id}: {e}")
            raise

    def list_agents(self) -> List[Dict[str, Any]]:
        """List all agents in the session with their configurations.

        Returns:
            List of dicts with agent_id, model, and system_prompt for each agent

        Example:
            agents = session_manager.list_agents()
            for agent in agents:
                print(f"Agent: {agent['agent_id']}")
                print(f"  Model: {agent.get('model', 'N/A')}")
                print(f"  System Prompt: {agent.get('system_prompt', 'N/A')}")
        """
        try:
            doc = self.session_repository.collection.find_one(
                {"_id": self.session_id},
                {"agents": 1}
            )

            if not doc or "agents" not in doc:
                logger.debug(f"No agents found in session {self.session_id}")
                return []

            agents_list = []
            for agent_id, agent_obj in doc["agents"].items():
                agent_data = agent_obj.get("agent_data", {})
                agents_list.append({
                    "agent_id": agent_id,
                    "model": agent_data.get("model"),
                    "system_prompt": agent_data.get("system_prompt")
                })

            return agents_list
        except Exception as e:
            logger.error(f"Failed to list agents for session {self.session_id}: {e}")
            return []

    def get_message_count(self, agent_id: str) -> int:
        """Get the count of messages for a specific agent.

        Args:
            agent_id: ID of the agent to count messages for

        Returns:
            Number of messages, or 0 if agent doesn't exist

        Example:
            count = session_manager.get_message_count("assistant-1")
            if count == 0:
                print("This is the first interaction")
        """
        try:
            doc = self.session_repository.collection.find_one(
                {"_id": self.session_id},
                {f"agents.{agent_id}.messages": 1}
            )
            if doc and "agents" in doc and agent_id in doc["agents"]:
                return len(doc["agents"][agent_id].get("messages", []))
            return 0
        except Exception as e:
            logger.error(f"Failed to get message count for {agent_id}: {e}")
            return 0


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
