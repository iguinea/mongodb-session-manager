"""Itzulbira Session Manager implementation for Strands Agents."""

from __future__ import annotations

import json
import logging
import warnings
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, ClassVar

from pymongo import MongoClient
from strands import Agent, tool
from strands.session.repository_session_manager import RepositorySessionManager
from strands.types.content import Message
from strands.types.tools import JSONSchema

from .mongodb_session_repository import MongoDBSessionRepository

logger = logging.getLogger(__name__)

GUARDRAIL_ACTION_BLOCKED = "BLOCKED"
GUARDRAIL_STOP_REASONS = frozenset(["guardrail_intervened", "content_filtered"])


_MONGO_CLIENT_OPTIONS = frozenset(
    {
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
)


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
        connection_string: str | None = None,
        database_name: str = "database_name",
        collection_name: str = "collection_name",
        client: MongoClient | None = None,
        metadata_fields: list[str] | None = None,
        metadata_hook: Callable[[dict[str, Any]], None] | None = None,
        feedback_hook: Callable[[dict[str, Any]], None] | None = None,
        application_name: str | None = None,
        session_repository: Any | None = None,
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
            metadata_hook: Hook to be called when metadata is updated, deleted or retrieved
            feedback_hook: Hook to be called when feedback is added
            application_name: Application name for session categorization (immutable after creation)
            session_repository: Repository to store sessions in. Defaults to a
                MongoDB one built from the arguments above; pass an in-memory
                double to test without MongoDB. A replacement must implement
                the whole surface of MongoDBSessionRepository, including
                pop_read_agent_config(), which initialize() calls. That
                contract is not published as a Protocol: it lives as executable
                cases in tests/support/repository_contract.py
            **kwargs: Additional arguments passed to parent class and MongoClient
        """
        # Support deprecated camelCase parameter names (metadataHook, feedbackHook)
        if "metadataHook" in kwargs:
            warnings.warn(
                "metadataHook is deprecated, use metadata_hook instead",
                DeprecationWarning,
                stacklevel=2,
            )
            metadata_hook = metadata_hook or kwargs.pop("metadataHook")
        if "feedbackHook" in kwargs:
            warnings.warn(
                "feedbackHook is deprecated, use feedback_hook instead",
                DeprecationWarning,
                stacklevel=2,
            )
            feedback_hook = feedback_hook or kwargs.pop("feedbackHook")
        # Extract MongoDB client kwargs
        mongo_kwargs = {}
        parent_kwargs = {}

        for key, value in kwargs.items():
            if key in _MONGO_CLIENT_OPTIONS:
                mongo_kwargs[key] = value
            else:
                parent_kwargs[key] = value

        # Create MongoDB repository with optional client, unless one was injected
        if session_repository is not None:
            self.session_repository = session_repository
        else:
            self.session_repository = MongoDBSessionRepository(
                connection_string=connection_string,
                database_name=database_name,
                collection_name=collection_name,
                client=client,
                metadata_fields=metadata_fields,
                application_name=application_name,
                **mongo_kwargs,
            )

        # Initialize parent class with repository
        super().__init__(
            session_id=session_id,
            session_repository=self.session_repository,
            **parent_kwargs,
        )

        # Last (model, system_prompt) persisted per agent, to skip rewriting an
        # unchanged agent config on every sync. Keyed by agent_id because a
        # single manager can serve several agents in the same session.
        self._agent_config_cache: dict[str, tuple] = {}

        # Apply metadata hook if provided
        if metadata_hook:
            self._apply_metadata_hook(metadata_hook)

        # Apply feedback hook if provided
        if feedback_hook:
            self._apply_feedback_hook(feedback_hook)

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

        def wrapped_update(metadata: dict[str, Any]) -> None:
            return hook(original_update, "update", self.session_id, metadata=metadata)

        self.update_metadata = wrapped_update

        # Wrap get_metadata
        original_get = self.get_metadata

        def wrapped_get() -> dict[str, Any]:
            return hook(original_get, "get", self.session_id)

        self.get_metadata = wrapped_get

        # Wrap delete_metadata
        original_delete = self.delete_metadata

        def wrapped_delete(metadata_keys: list[str]) -> None:
            return hook(original_delete, "delete", self.session_id, keys=metadata_keys)

        self.delete_metadata = wrapped_delete

    def redact_latest_message(
        self, redact_message: Message, agent: Agent, **kwargs: Any
    ) -> None:
        """Redact the latest message and record guardrail event."""
        super().redact_latest_message(redact_message, agent, **kwargs)

        action = kwargs.get("action", GUARDRAIL_ACTION_BLOCKED)
        stop_reason = kwargs.get("stop_reason")
        guardrail_trace = kwargs.get("guardrail_trace")
        last_message_id = self._get_last_message_id(agent)
        if last_message_id is not None:
            self._record_guardrail_event(
                agent,
                last_message_id,
                action=action,
                stop_reason=stop_reason,
                guardrail_trace=guardrail_trace,
            )

    def _record_guardrail_event(
        self,
        agent: Agent,
        message_id: int,
        action: str = GUARDRAIL_ACTION_BLOCKED,
        stop_reason: str | None = None,
        guardrail_trace: dict[str, Any] | None = None,
    ) -> None:
        """Record guardrail intervention at message and session level.

        Only the message-level event is built here. Deriving the session-level
        one -- same fields, plus the identifiers, minus the full trace -- is the
        repository's job, so that rule lives in a single place.
        """
        policies_triggered = self._extract_guardrail_summary(guardrail_trace)

        # Optional fields are present only when truthy, which is what keeps a
        # plain interception stored as just action and timestamp.
        guardrail_event: dict[str, Any] = {
            "action": action,
            "timestamp": datetime.now(UTC),
        }
        if stop_reason:
            guardrail_event["stop_reason"] = stop_reason
        if policies_triggered:
            guardrail_event["policies_triggered"] = policies_triggered
        if guardrail_trace:
            guardrail_event["trace"] = guardrail_trace

        self.session_repository.record_guardrail_event(
            self.session_id, agent.agent_id, message_id, guardrail_event
        )

    # Policy extraction rules: (policy_name, list_path, format_fields)
    _POLICY_EXTRACTORS: ClassVar[list[tuple]] = [
        ("contentPolicy", ("contentPolicy", "filters"), ("type", "confidence")),
        ("topicPolicy", ("topicPolicy", "topics"), ("name", "action")),
        ("wordPolicy", ("wordPolicy", "customWords"), ("match",)),
        ("wordPolicy", ("wordPolicy", "managedWordLists"), ("type", "match")),
        (
            "sensitiveInformationPolicy",
            ("sensitiveInformationPolicy", "piiEntities"),
            ("type", "action"),
        ),
        (
            "sensitiveInformationPolicy",
            ("sensitiveInformationPolicy", "regexes"),
            ("name", "action"),
        ),
        (
            "contextualGroundingPolicy",
            ("contextualGroundingPolicy", "filters"),
            ("type", "score", "threshold"),
        ),
    ]

    @staticmethod
    def _extract_guardrail_summary(
        trace: dict[str, Any] | None,
    ) -> dict[str, list[str]]:
        """Extract a queryable summary of triggered policies from a GuardrailTrace.

        Returns a dict keyed by policy name with lists of triggered filter descriptions.
        Example: {"contentPolicy": ["HATE/HIGH", "VIOLENCE/MEDIUM"]}
        """
        if not trace:
            return {}

        assessments: list[dict] = []
        if "inputAssessment" in trace:
            assessments.append(trace["inputAssessment"])
        assessments.extend(trace.get("outputAssessments", []))

        summary: dict[str, list[str]] = {}
        for assessment in assessments:
            for policy_name, (
                policy_key,
                list_key,
            ), fields in MongoDBSessionManager._POLICY_EXTRACTORS:
                for item in assessment.get(policy_key, {}).get(list_key, []):
                    desc = "/".join(str(item.get(f, "UNKNOWN")) for f in fields)
                    summary.setdefault(policy_name, []).append(desc)

        return summary

    def initialize(self, agent: Agent, **kwargs: Any) -> None:
        """Initialize an agent with the session and learn its persisted config.

        When the agent is restored, read_agent() has already fetched its model
        and system_prompt. Seeding the config cache with them spares the first
        sync of every request from rewriting an unchanged system prompt, the
        largest write of the turn.
        """
        super().initialize(agent, **kwargs)

        persisted = self.session_repository.pop_read_agent_config(
            self.session_id, agent.agent_id
        )
        if persisted is not None:
            self._agent_config_cache[agent.agent_id] = (
                persisted["model"],
                persisted["system_prompt"],
            )

    def sync_agent(self, agent: Agent, **kwargs: Any) -> None:
        """Sync agent data and capture model/system_prompt.

        Captures comprehensive metrics from the agent's event loop including:
        - Token usage (input, output, total, cache read/write)
        - Performance metrics (latency, time to first byte)
        - Cycle metrics (count, durations, averages)
        - Tool metrics (call counts, success/error rates, execution times)
        """
        super().sync_agent(agent, **kwargs)

        # Metrics and agent config land on the same session document, so they
        # are combined into a single write. On DocumentDB every write costs
        # 40-55 ms regardless of its size, so the number of round-trips is what
        # drives latency, not the number of bytes.
        metrics_ops, message_id = self._build_metrics_update(agent)
        config_ops, config_cache_entry = self._build_agent_config_update(agent)

        # _build_agent_config_update() returns ({}, None) together, so the cache
        # entry is already None whenever there are no config operations.
        self._apply_sync_update(
            agent, metrics_ops, config_ops, message_id, config_cache_entry
        )

    def _build_metrics_update(self, agent: Agent) -> tuple:
        """Build the $set operations carrying event loop metrics.

        Returns:
            Tuple of (set operations, message_id they target). Both are empty
            when there are no metrics yet or the last message is unknown.
        """
        metrics_summary = agent.event_loop_metrics.get_summary()
        accumulated_metrics = metrics_summary.get("accumulated_metrics", {})

        if accumulated_metrics.get("latencyMs", 0) <= 0:
            return {}, None

        accumulated_usage = metrics_summary.get("accumulated_usage", {})
        usage_data = {
            "inputTokens": accumulated_usage.get("inputTokens", 0),
            "outputTokens": accumulated_usage.get("outputTokens", 0),
            "totalTokens": accumulated_usage.get("totalTokens", 0),
            "cacheReadInputTokens": accumulated_usage.get("cacheReadInputTokens", 0),
            "cacheWriteInputTokens": accumulated_usage.get("cacheWriteInputTokens", 0),
        }
        metrics_data = {
            "latencyMs": accumulated_metrics.get("latencyMs", 0),
            "timeToFirstByteMs": accumulated_metrics.get("timeToFirstByteMs", 0),
        }
        cycle_data = {
            "cycle_count": metrics_summary.get("total_cycles", 0),
            "total_duration": metrics_summary.get("total_duration", 0.0),
            "average_cycle_time": metrics_summary.get("average_cycle_time", 0.0),
        }
        tool_usage = self._extract_tool_usage(metrics_summary.get("tool_usage", {}))

        return self._metrics_set_operations(
            agent, usage_data, metrics_data, cycle_data, tool_usage
        )

    def _metrics_set_operations(
        self,
        agent: Agent,
        usage_data: dict,
        metrics_data: dict,
        cycle_data: dict,
        tool_usage: dict,
    ) -> tuple:
        """Build the field updates for the metrics of the last message.

        Keys are relative to the message document; where that message lives is
        the repository's business.
        """
        last_message_id = self._get_last_message_id(agent)
        if last_message_id is None:
            return {}, None

        return {
            "event_loop_metrics.accumulated_metrics": metrics_data,
            "event_loop_metrics.accumulated_usage": usage_data,
            "event_loop_metrics.cycle_metrics": cycle_data,
            "event_loop_metrics.tool_usage": tool_usage,
        }, last_message_id

    def _apply_sync_update(
        self,
        agent: Agent,
        message_operations: dict,
        agent_operations: dict,
        message_id: int | None,
        config_cache_entry: tuple | None,
    ) -> None:
        """Apply the agent's sync write, if there is anything to write.

        Exactly one write either way: when there are metrics the agent config
        rides along with them, and when there are none it goes on its own. The
        two branches are what used to be a filter built with or without the
        positional clause.

        Args:
            agent: Agent being synced.
            message_operations: Fields to write on the last message.
            agent_operations: Fields to write on the agent itself.
            message_id: Message the metrics belong to, when there are metrics.
            config_cache_entry: Agent config to remember as persisted, recorded
                only once the write is known to have matched.
        """
        if not message_operations and not agent_operations:
            return

        # Their only producer, _metrics_set_operations(), returns both or
        # neither, so the else branch never carries metrics today. The guard
        # stays because message keys without an id would write a positional
        # path with no positional clause, which MongoDB rejects with an opaque
        # error -- and if a future producer breaks that pairing, the metrics
        # would vanish into a write that cannot carry them, so it says so.
        if message_operations and message_id is not None:
            matched = self.session_repository.update_message_fields(
                self.session_id,
                agent.agent_id,
                message_id,
                message_operations,
                agent_set_operations=agent_operations or None,
            )
        else:
            if message_operations:
                logger.error(
                    f"Dropping metrics for agent {agent.agent_id} in session "
                    f"{self.session_id}: there is no message_id to write them "
                    f"onto ({sorted(message_operations)})"
                )
            matched = self.session_repository.update_agent_fields(
                self.session_id, agent.agent_id, agent_operations
            )

        if not matched:
            # Silent no-op otherwise: the agent config would also be lost, since
            # both halves travel in the same write.
            logger.warning(
                f"Sync update matched no document for agent {agent.agent_id} "
                f"in session {self.session_id} (message_id={message_id})"
            )
            return

        if config_cache_entry is not None:
            self._agent_config_cache[agent.agent_id] = config_cache_entry

    def _extract_tool_usage(self, tool_usage_raw: dict) -> dict:
        """Extract simplified tool usage metrics for storage."""
        tool_usage = {}
        for tool_name, tool_data in tool_usage_raw.items():
            exec_stats = tool_data.get("execution_stats", {})
            tool_usage[tool_name] = {
                "call_count": exec_stats.get("call_count", 0),
                "success_count": exec_stats.get("success_count", 0),
                "error_count": exec_stats.get("error_count", 0),
                "total_time": exec_stats.get("total_time", 0.0),
                "average_time": exec_stats.get("average_time", 0.0),
                "success_rate": exec_stats.get("success_rate", 0.0),
            }
        return tool_usage

    def _get_last_message_id(self, agent: Agent) -> int | None:
        """Get the message_id of the last message for an agent.

        Prefers the value the parent class already tracks in memory. Besides
        saving a query, this avoids a read-after-write: the lookup used to run
        milliseconds after create_message pushed the message, and on a
        secondaryPreferred cluster a lagging replica would return the previous
        message_id, silently attributing the metrics to the wrong message.
        """
        latest_message = getattr(self, "_latest_agent_message", {}).get(agent.agent_id)
        if latest_message is not None:
            return latest_message.message_id

        # No message tracked yet (e.g. a restored session that has not appended
        # anything in this process): fall back to reading it.
        return self.session_repository.get_last_message_id(
            self.session_id, agent.agent_id
        )

    def _update_last_message_metrics(
        self,
        agent: Agent,
        usage_data: dict,
        metrics_data: dict,
        cycle_data: dict,
        tool_usage: dict,
    ) -> None:
        """Update the last message in a session with event loop metrics."""
        set_operations, last_message_id = self._metrics_set_operations(
            agent, usage_data, metrics_data, cycle_data, tool_usage
        )
        self._apply_sync_update(agent, set_operations, {}, last_message_id, None)

    def _build_agent_config_update(self, agent: Agent) -> tuple:
        """Build the $set operations for the agent configuration.

        Returns empty operations when the configuration matches what was last
        persisted for this agent. The system prompt does not change within a
        turn, so rewriting it on every sync was the single largest source of
        write traffic.

        Returns:
            Tuple of (set operations, value to cache once persisted).
        """
        model_id = self._extract_model_id(agent)
        system_prompt = getattr(agent, "system_prompt", None)

        cache_entry = (model_id, system_prompt)
        if self._agent_config_cache.get(agent.agent_id) == cache_entry:
            return {}, None

        # Keys are relative to the agent document.
        set_operations = {}
        if model_id:
            set_operations["agent_data.model"] = model_id
        if system_prompt:
            set_operations["agent_data.system_prompt"] = system_prompt

        if not set_operations:
            return {}, None

        logger.debug(
            f"Captured agent configuration for {agent.agent_id}: model={model_id or 'N/A'}"
        )
        return set_operations, cache_entry

    def _capture_agent_config(self, agent: Agent) -> None:
        """Capture and store agent configuration (model and system_prompt)."""
        set_operations, cache_entry = self._build_agent_config_update(agent)
        self._apply_sync_update(agent, {}, set_operations, None, cache_entry)

    def _extract_model_id(self, agent: Agent) -> str | None:
        """Extract model identifier string from agent."""
        if not (hasattr(agent, "model") and agent.model):
            return None
        if hasattr(agent.model, "config") and isinstance(agent.model.config, dict):
            model_id = agent.model.config.get("model_id")
            if model_id:
                return model_id
        return getattr(agent.model, "model_id", str(agent.model))

    def close(self) -> None:
        """Close the underlying MongoDB connection."""
        self.session_repository.close()

    # CUSTOM METHODS
    def update_metadata(self, metadata: dict[str, Any]) -> None:
        """Update the metadata for the session."""
        self.session_repository.update_metadata(self.session_id, metadata)

    def get_metadata(self) -> dict[str, Any]:
        """Get the metadata for the session."""
        return self.session_repository.get_metadata(self.session_id)

    def delete_metadata(self, metadata_keys: list[str]) -> None:
        """Delete metadata keys for the session."""
        self.session_repository.delete_metadata(self.session_id, metadata_keys)

    def _parse_json_param(self, value: Any, param_name: str) -> tuple:
        """Parse a potential JSON string parameter into its Python equivalent."""
        if value is not None and isinstance(value, str):
            try:
                return json.loads(value), None
            except json.JSONDecodeError:
                return (
                    None,
                    f"Error: {param_name} must be a valid JSON, got: {value[:100]}...",
                )
        return value, None

    def _handle_metadata_get(self, keys: list[str] | None = None) -> str:
        """Handle get action for the metadata tool."""
        all_metadata = self.get_metadata()
        if not all_metadata or "metadata" not in all_metadata:
            return "No metadata found for this session"

        metadata_dict = all_metadata["metadata"]
        if keys:
            filtered = {k: metadata_dict.get(k) for k in keys if k in metadata_dict}
            if filtered:
                return f"Metadata retrieved: {json.dumps(filtered, default=str)}"
            return f"No metadata found for keys: {keys}"

        if metadata_dict:
            return f"All metadata: {json.dumps(metadata_dict, default=str)}"
        return "No metadata stored in session"

    def _handle_metadata_set(self, metadata: dict[str, Any]) -> str:
        """Handle set/update action for the metadata tool."""
        if not metadata:
            return "Error: metadata dictionary required for set/update action"
        self.update_metadata(metadata)
        return f"Successfully updated metadata fields: {list(metadata.keys())}"

    def _handle_metadata_delete(self, keys: list[str]) -> str:
        """Handle delete action for the metadata tool."""
        if not keys:
            return "Error: keys list required for delete action"
        self.delete_metadata(keys)
        return f"Successfully deleted metadata fields: {keys}"

    def get_metadata_tool(self) -> Callable:
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
            metadata: Any | None = None,
            keys: Any | None = None,
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

                metadata, error = session_manager._parse_json_param(
                    metadata, "metadata"
                )
                if error:
                    return error
                keys, error = session_manager._parse_json_param(keys, "keys")
                if error:
                    return error

                if action == "get":
                    return session_manager._handle_metadata_get(keys)
                elif action in ("set", "update"):
                    return session_manager._handle_metadata_set(metadata)
                elif action == "delete":
                    return session_manager._handle_metadata_delete(keys)
                else:
                    return f"Error: Unknown action '{action}'. Use 'get', 'set', 'update', or 'delete'"

            except Exception as e:
                logger.error(f"Error in manage_metadata tool: {e}")
                return f"Error managing metadata: {e!s}"

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

        def wrapped_add(feedback: dict[str, Any]) -> None:
            return hook(
                original_add,
                "add",
                self.session_id,
                session_manager=self,
                feedback=feedback,
            )

        self.add_feedback = wrapped_add

    def add_feedback(self, feedback: dict[str, Any]) -> None:
        """Add feedback to the session."""
        self.session_repository.add_feedback(self.session_id, feedback)

    def get_feedbacks(self) -> list[dict[str, Any]]:
        """Get all feedbacks for the session."""
        return self.session_repository.get_feedbacks(self.session_id)

    def get_session_viewer_password(self) -> str | None:
        """Get the session viewer password for this session.

        Returns:
            The session viewer password string, or None if session not found

        Example:
            password = session_manager.get_session_viewer_password()
            if password:
                print(f"Session Viewer URL: http://localhost:8883?session_id={session_id}&password={password}")
        """
        return self.session_repository.get_session_viewer_password(self.session_id)

    def get_application_name(self) -> str | None:
        """Get the application_name for this session (read-only, immutable).

        The application_name is set at session creation time and cannot be modified.

        Returns:
            The application name string, or None if session not found or not set

        Example:
            app_name = session_manager.get_application_name()
            if app_name:
                print(f"Application: {app_name}")
        """
        return self.session_repository.get_application_name(self.session_id)

    def get_agent_config(self, agent_id: str) -> dict[str, Any] | None:
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
            return self.session_repository.get_agent_config(self.session_id, agent_id)
        except Exception as e:
            logger.error(f"Failed to get agent config for {agent_id}: {e}")
            return None

    def update_agent_config(
        self,
        agent_id: str,
        model: str | None = None,
        system_prompt: str | None = None,
        prompt_metadata: dict[str, Any] | None = None,
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
        # Field names are relative to the agent; the repository owns the paths.
        update_fields = {}
        if model is not None:
            update_fields["agent_data.model"] = model
        if system_prompt is not None:
            update_fields["agent_data.system_prompt"] = system_prompt
        if prompt_metadata is not None:
            update_fields["agent_data.prompt_metadata"] = prompt_metadata

        if not update_fields:
            logger.warning(f"No fields to update for agent {agent_id}")
            return

        try:
            if not self.session_repository.update_agent_fields(
                self.session_id, agent_id, update_fields
            ):
                raise ValueError(f"Session {self.session_id} not found")

            logger.info(
                f"Updated agent config for {agent_id}: {list(update_fields.keys())}"
            )
        except Exception as e:
            logger.error(f"Failed to update agent config for {agent_id}: {e}")
            raise

    def set_prompt_metadata(
        self,
        agent_id: str,
        prompt_metadata: dict[str, Any],
    ) -> None:
        """Set prompt lineage metadata for a specific agent.

        Must be called after sync_agent() (agent must exist in session).

        Args:
            agent_id: ID of the agent to set metadata for
            prompt_metadata: Dict with prompt_id, prompt_name, prompt_version,
                deployment_id, deployment_name, temperature (optional, float)

        Raises:
            ValueError: If session not found
        """
        if not self.session_repository.update_agent_fields(
            self.session_id, agent_id, {"agent_data.prompt_metadata": prompt_metadata}
        ):
            raise ValueError(f"Session {self.session_id} not found")
        logger.info(
            f"Set prompt metadata for agent {agent_id}: "
            f"prompt_id={prompt_metadata.get('prompt_id')}, "
            f"version={prompt_metadata.get('prompt_version')}"
        )

    def list_agents(self) -> list[dict[str, Any]]:
        """List all agents in the session with their configurations.

        Returns:
            List of dicts with agent_id, model, system_prompt and prompt_metadata for each agent

        Example:
            agents = session_manager.list_agents()
            for agent in agents:
                print(f"Agent: {agent['agent_id']}")
                print(f"  Model: {agent.get('model', 'N/A')}")
                print(f"  System Prompt: {agent.get('system_prompt', 'N/A')}")
        """
        try:
            return self.session_repository.list_agent_configs(self.session_id)
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
            return self.session_repository.count_messages(self.session_id, agent_id)
        except Exception as e:
            logger.error(f"Failed to get message count for {agent_id}: {e}")
            return 0


# Convenience factory function
def create_mongodb_session_manager(
    session_id: str,
    connection_string: str | None = None,
    database_name: str = "database_name",
    collection_name: str = "collection_name",
    client: MongoClient | None = None,
    application_name: str | None = None,
    **kwargs: Any,
) -> MongoDBSessionManager:
    """Create an Itzulbira Session Manager with default settings.

    Args:
        session_id: Unique identifier for the session
        connection_string: MongoDB connection string (ignored if client is provided)
        database_name: Name of the database
        collection_name: Name of the collection for sessions
        client: Optional pre-configured MongoClient to use
        application_name: Application name for session categorization (immutable after creation)
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
        application_name=application_name,
        **kwargs,
    )
