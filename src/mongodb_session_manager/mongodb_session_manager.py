"""Itzulbira Session Manager implementation for Strands Agents."""

from __future__ import annotations

import json
import logging
import warnings
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from pymongo import MongoClient
from strands import Agent, tool
from strands.hooks import AfterInvocationEvent, BeforeInvocationEvent, HookOrder
from strands.session.repository_session_manager import RepositorySessionManager
from strands.types.content import Message
from strands.types.session import SessionMessage

from .field_names import resolve_path, validate_agent_id, validate_field_paths
from .message_identity import MessageRef, ref_of
from .mongodb_session_repository import MongoDBSessionRepository
from .sync_origin import MessageAddedTagging, syncing_added_message

if TYPE_CHECKING:
    from strands.hooks import HookRegistry
    from strands.types.agent import LocalAgent

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

        # Use the agent: messages, state and metrics are persisted through
        # the hooks the agent registers, with no call of your own
        response = agent("Hello!")

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

        # Messages of the invocation in flight, per agent, waiting for the write
        # that closes it (#53). Ordered as they were appended: the array they go
        # into is the conversation.
        self._pending_messages: dict[str, list[SessionMessage]] = {}

        # Agents with an invocation open. Only inside one is there something
        # bound to close -- and therefore to flush -- so only there may a
        # message wait.
        self._agents_invoking: set[str] = set()

        # Apply metadata hook if provided
        if metadata_hook:
            self._apply_metadata_hook(metadata_hook)

        # Apply feedback hook if provided
        if feedback_hook:
            self._apply_feedback_hook(feedback_hook)

        logger.debug(f"Initialized session manager for session: {session_id}")

    def _apply_metadata_hook(self, hook: Callable) -> None:
        """Apply the metadata hook as a decorator to metadata methods.

        The hook will be called with:
        - original_func: The original method being wrapped
        - action: "update", "get", or "delete"
        - session_id: The current session ID
        - **kwargs: Additional arguments (metadata for update, keys for delete)

        Keys are validated before the hook runs: a hook may publish what it
        receives before calling the original, and must never see a key the
        repository is about to reject (#79).
        """
        # Wrap update_metadata
        original_update = self.update_metadata

        def wrapped_update(metadata: dict[str, Any]) -> None:
            validate_field_paths(metadata, "metadata key")
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
            validate_field_paths(metadata_keys, "metadata key")
            return hook(original_delete, "delete", self.session_id, keys=metadata_keys)

        self.delete_metadata = wrapped_delete

    def append_message(
        self, message: Message, agent: LocalAgent, **kwargs: Any
    ) -> None:
        """Append a message, immediately or with the batch of its invocation.

        What the event loop produces -- a toolUse, a toolResult, the answer --
        waits for the write that closes the invocation, so a turn costs one
        `$push` instead of one per message (#53). `AfterInvocationEvent` comes
        out of a `finally` in `strands/agent/agent.py`, so an invocation that
        raises still flushes; what a batch cannot survive is the process dying.

        Two messages do not wait. The one that opens the invocation, because it
        is the user's question, the only thing in a turn that nothing can
        produce again, and writing it on arrival keeps it as durable as it was
        before batching. And any message appended outside an invocation, which
        has nothing bound to close it and would sit in the batch until close().

        Ordering is preserved by flushing before any immediate write: the array
        this ends up in *is* the conversation, so nothing may overtake what is
        still pending.
        """
        if agent.agent_id not in self._agents_invoking or self._opens_an_invocation(
            message
        ):
            self._flush_pending(agent.agent_id)
            super().append_message(message, agent, **kwargs)
            return

        # The index and the bookkeeping of `_latest_agent_message` are Strands'
        # rule (`RepositorySessionManager.append_message`), repeated here
        # because only the write is being deferred. `test_message_batching.py`
        # fails if an SDK upgrade changes how a message is numbered.
        latest = self._latest_agent_message[agent.agent_id]
        next_index = (latest.message_id + 1) if latest else 0
        session_message = SessionMessage.from_message(message, next_index)
        self._latest_agent_message[agent.agent_id] = session_message
        self._pending_messages.setdefault(agent.agent_id, []).append(session_message)

    @staticmethod
    def _opens_an_invocation(message: Message) -> bool:
        """Say whether a message is a prompt, rather than event loop output.

        Told apart by content and not by position: a `toolResult` is also a
        `user` message, and which event fires when is the SDK's business, while
        what a message *is* is visible in the message itself.
        """
        if message.get("role") != "user":
            return False
        return not any(
            isinstance(block, dict) and "toolResult" in block
            for block in message.get("content") or []
        )

    def _flush_pending(
        self,
        agent_id: str,
        fields_on_last: dict[str, Any] | None = None,
        agent_set_operations: dict[str, Any] | None = None,
    ) -> bool:
        """Write the batch of an agent, if it has one.

        The batch is let go whether the write lands or raises, and the error
        propagates to the caller as `create_message()`'s always did. It is
        deliberately not retried: a write that raised may well have been
        applied -- an update that reached the server and lost its ack is the
        case `test_invocation_metrics.py` keeps -- and pushing it again would
        duplicate the messages of a turn, which is worse than the loss it would
        be trying to prevent. Losing the batch is what a failed
        `create_message()` already did, one message at a time.

        Returns:
            Whether there was anything to write.
        """
        pending = self._pending_messages.pop(agent_id, None)
        if not pending:
            return False

        self.session_repository.create_messages(
            self.session_id,
            agent_id,
            pending,
            fields_on_last=fields_on_last,
            agent_set_operations=agent_set_operations,
        )
        return True

    def redact_latest_message(
        self, redact_message: Message, agent: LocalAgent, **kwargs: Any
    ) -> None:
        """Redact the latest message and record guardrail event.

        The event names the message super() has just redacted, taken from the
        same SessionMessage it used. Asking where the last message is a second
        time would be asking a different question: the answer could be another
        manager's message, and the audit trail would point at it.

        The batch is written first: a guardrail intervenes on the message that
        has just been added, which is the one still waiting in it, and the
        redaction locates it with the positional operator -- it has to be there.
        """
        self._flush_pending(agent.agent_id)
        super().redact_latest_message(redact_message, agent, **kwargs)

        # super() raises when there is nothing to redact, so by here there is a
        # message and it is the one it just wrote to.
        redacted = self._latest_agent_message[agent.agent_id]

        self._record_guardrail_event(
            agent,
            ref_of(redacted),
            action=kwargs.get("action", GUARDRAIL_ACTION_BLOCKED),
            stop_reason=kwargs.get("stop_reason"),
            guardrail_trace=kwargs.get("guardrail_trace"),
        )

    def _record_guardrail_event(
        self,
        agent: LocalAgent,
        ref: MessageRef,
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
            self.session_id, agent.agent_id, ref, guardrail_event
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

    def initialize(self, agent: LocalAgent, **kwargs: Any) -> None:
        """Initialize an agent with the session and learn its persisted config.

        When the agent is restored, read_agent() has already fetched its model
        and system_prompt. Seeding the config cache with them spares the first
        sync of every request from rewriting an unchanged system prompt, the
        largest write of the turn.

        Since strands 1.56 this is also the entry point for a `BidiAgent`: the
        SDK dropped `initialize_bidi_agent()` and fires `AgentInitializedEvent`
        for both kinds of agent, so the agent_id check below covers both (#69).

        Raises:
            ValueError: If the agent_id cannot be stored under `agents.<agent_id>`
                (#79). Checked before super(): Strands registers the id before it
                touches the repository, so failing later would turn a retry on
                the same manager into a misleading "must be unique" error.
        """
        validate_agent_id(agent.agent_id)
        super().initialize(agent, **kwargs)

        persisted = self.session_repository.pop_read_agent_config(
            self.session_id, agent.agent_id
        )
        if persisted is not None:
            self._agent_config_cache[agent.agent_id] = (
                persisted["model"],
                persisted["system_prompt"],
            )

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Register Strands' session hooks, telling apart the sync of each message.

        Strands registers the same sync_agent() for MessageAddedEvent and for
        AfterInvocationEvent. The registry is wrapped so that the callbacks of
        MessageAddedEvent run tagged, and sync_agent() can leave the metrics out
        of that sync: they are still the previous cycle's (issue #66).

        Two callbacks of this class' own bracket the invocation, so a batch is
        only ever held while there is something guaranteed to close it (#53).
        The closing one runs last and flushes again, which covers both orders it
        can end up in against a hook that appends a message of its own: if that
        hook runs first its message is in the batch and goes out here, and if it
        runs after, the invocation is already over and its message is written
        immediately.
        """
        super().register_hooks(MessageAddedTagging(registry), **kwargs)

        registry.add_callback(
            BeforeInvocationEvent,
            lambda event: self._agents_invoking.add(event.agent.agent_id),
            order=HookOrder.SDK_FIRST,
        )
        registry.add_callback(
            AfterInvocationEvent,
            lambda event: self._invocation_ended(event.agent),
            order=HookOrder.SDK_LAST,
        )

    def _invocation_ended(self, agent: LocalAgent) -> None:
        """Close the window in which messages may wait, and write what is left."""
        self._agents_invoking.discard(agent.agent_id)
        self._flush_pending(agent.agent_id)

    def sync_agent(self, agent: LocalAgent, **kwargs: Any) -> None:
        """Sync agent data and capture model/system_prompt.

        Captures comprehensive metrics from the agent's event loop including:
        - Token usage (input, output, total, cache read/write)
        - Performance metrics (latency, time to first byte)
        - Cycle metrics (count, durations, averages)
        - Tool metrics (call counts, success/error rates, execution times)

        The metrics go on the agent's last message, except in the sync Strands
        runs for each MessageAddedEvent. That event fires before the event loop
        accumulates the metrics of the model call behind the message, so they
        would be the previous cycle's: a stale snapshot on every intermediate
        message, and a write the closing sync overwrites an instant later. The
        closing sync (AfterInvocationEvent) writes them once, on the last message
        of the invocation, and so does any explicit call (issue #66).

        Since strands 1.56 a `BidiAgent` also arrives here, on
        `BidiAgentStopEvent`. It has no event loop, so it syncs without metrics
        (issue #69).

        What super() writes -- the agent state -- and what this class writes are
        separate round-trips, so the second runs in a `finally`: the state
        failing must not take the messages of the turn down with it, now that
        the write which stores them is this one (#53).
        """
        try:
            super().sync_agent(agent, **kwargs)
        finally:
            self._write_sync(agent)

    def _write_sync(self, agent: LocalAgent) -> None:
        """Write the metrics, the agent config and the pending batch, as one."""
        # Metrics and agent config land on the same session document, so they
        # are combined into a single write. On DocumentDB every write costs
        # 40-55 ms regardless of its size, so the number of round-trips is what
        # drives latency, not the number of bytes.
        if syncing_added_message():
            metrics_ops, message_ref = {}, None
        else:
            metrics_ops, message_ref = self._build_metrics_update(agent)
        config_ops, config_cache_entry = self._build_agent_config_update(agent)

        # The sync of each MessageAddedEvent is not the end of anything: the
        # batch closes with the invocation, and until then there is nothing to
        # write it onto.
        if not syncing_added_message() and self._flush_pending(
            agent.agent_id, metrics_ops, config_ops
        ):
            # The metrics belong to the last message of the batch, which the
            # flush has just stored with them inside: they cost no write of
            # their own, and neither does the agent config that rode along.
            if config_cache_entry is not None:
                self._agent_config_cache[agent.agent_id] = config_cache_entry
            return

        # _build_agent_config_update() returns ({}, None) together, so the cache
        # entry is already None whenever there are no config operations.
        self._apply_sync_update(
            agent, metrics_ops, config_ops, message_ref, config_cache_entry
        )

    def _build_metrics_update(self, agent: LocalAgent) -> tuple:
        """Build the $set operations carrying event loop metrics.

        An agent without an event loop has no metrics to write, and that is not
        an error: a `BidiAgent` has none, and since strands 1.56 it reaches
        `sync_agent()` through `BidiAgentStopEvent` like any other agent
        (`session/session_manager.py:65`). Until 1.55 it went to
        `sync_bidi_agent()`, a separate method that no longer exists (#69).

        An `Agent` is not given that benefit of the doubt: it must have an event
        loop, so asking one that no longer exposes it raises, loudly, instead of
        quietly persisting no metrics for every session -- which is the symptom
        of #66 with no signal left at all.

        Returns:
            Tuple of (set operations, reference to the message they target).
            Both are empty when the agent has no event loop, when there are no
            metrics yet, or when the last message is unknown.
        """
        if not isinstance(agent, Agent) and not hasattr(agent, "event_loop_metrics"):
            return {}, None

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
        agent: LocalAgent,
        usage_data: dict,
        metrics_data: dict,
        cycle_data: dict,
        tool_usage: dict,
    ) -> tuple:
        """Build the field updates for the metrics of the last message.

        Keys are relative to the message document; where that message lives is
        the repository's business.
        """
        message_ref = self._get_last_message_ref(agent)
        if message_ref is None:
            return {}, None

        return {
            "event_loop_metrics.accumulated_metrics": metrics_data,
            "event_loop_metrics.accumulated_usage": usage_data,
            "event_loop_metrics.cycle_metrics": cycle_data,
            "event_loop_metrics.tool_usage": tool_usage,
        }, message_ref

    def _apply_sync_update(
        self,
        agent: LocalAgent,
        message_operations: dict,
        agent_operations: dict,
        message_ref: MessageRef | None,
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
            message_ref: Message the metrics belong to, when there are metrics.
            config_cache_entry: Agent config to remember as persisted, recorded
                only once the write is known to have matched.
        """
        if not message_operations and not agent_operations:
            return

        # Their only producer, _metrics_set_operations(), returns both or
        # neither, so the else branch never carries metrics today. The guard
        # stays because message keys without a reference would write a
        # positional path with no positional clause, which MongoDB rejects with
        # an opaque error -- and if a future producer breaks that pairing, the
        # metrics would vanish into a write that cannot carry them, so it says so.
        if message_operations and message_ref is not None:
            matched = self.session_repository.update_message_fields(
                self.session_id,
                agent.agent_id,
                message_ref,
                message_operations,
                agent_set_operations=agent_operations or None,
            )
        else:
            if message_operations:
                logger.error(
                    f"Dropping metrics for agent {agent.agent_id} in session "
                    f"{self.session_id}: there is no message to write them "
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
                f"in session {self.session_id} (message={message_ref})"
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

    def _get_last_message_ref(self, agent: LocalAgent) -> MessageRef | None:
        """Reference the last message of an agent.

        Prefers the SessionMessage the parent class already tracks in memory,
        which carries the identity create_message() stamped on it: that is what
        points the write at the message *this* manager appended, and not at
        another one that happens to share its index (#78).

        Besides saving a query, this avoids a read-after-write: the lookup used
        to run milliseconds after create_message pushed the message, and on a
        secondaryPreferred cluster a lagging replica would return the previous
        message, silently attributing the metrics to the wrong one.
        """
        latest_message = getattr(self, "_latest_agent_message", {}).get(agent.agent_id)
        if latest_message is not None:
            return ref_of(latest_message)

        # No message tracked yet (e.g. a restored session that has not appended
        # anything in this process): fall back to reading it.
        return self.session_repository.get_last_message_ref(
            self.session_id, agent.agent_id
        )

    def _update_last_message_metrics(
        self,
        agent: LocalAgent,
        usage_data: dict,
        metrics_data: dict,
        cycle_data: dict,
        tool_usage: dict,
    ) -> None:
        """Update the last message in a session with event loop metrics."""
        set_operations, message_ref = self._metrics_set_operations(
            agent, usage_data, metrics_data, cycle_data, tool_usage
        )
        self._apply_sync_update(agent, set_operations, {}, message_ref, None)

    def _build_agent_config_update(self, agent: LocalAgent) -> tuple:
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

    def _capture_agent_config(self, agent: LocalAgent) -> None:
        """Capture and store agent configuration (model and system_prompt)."""
        set_operations, cache_entry = self._build_agent_config_update(agent)
        self._apply_sync_update(agent, {}, set_operations, None, cache_entry)

    def _extract_model_id(self, agent: LocalAgent) -> str | None:
        """Extract model identifier string from agent."""
        if not (hasattr(agent, "model") and agent.model):
            return None
        if hasattr(agent.model, "config") and isinstance(agent.model.config, dict):
            model_id = agent.model.config.get("model_id")
            if model_id:
                return model_id
        return getattr(agent.model, "model_id", str(agent.model))

    def close(self) -> None:
        """Flush whatever is still pending and close the MongoDB connection.

        The last chance for messages whose invocation never closed: what runs
        just before `AfterInvocationEvent` in the same `finally` --
        `conversation_manager.apply_management()` -- can raise and leave the
        batch unwritten (#66). A flush that fails here is logged and not
        re-raised: closing the connection is what the caller asked for, and
        raising instead would leak it.
        """
        for agent_id in list(self._pending_messages):
            pending = len(self._pending_messages.get(agent_id, []))
            try:
                self._flush_pending(agent_id)
            except Exception:
                logger.exception(
                    f"Lost {pending} message(s) of agent {agent_id} in session "
                    f"{self.session_id}: the batch of an invocation that never "
                    f"closed could not be written"
                )
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
        """Handle get action for the metadata tool.

        A requested key is a path, the same as it is when writing: the agent
        that stored `user.name` asks for `user.name`. It is resolved on the
        document the read already returned, so it costs no round-trip (#47).

        The keys that were not found are named. A reply that carried only what
        existed left the agent unable to tell an absence from a key it had not
        asked for, so it could neither retry with another name nor conclude
        that the data does not live in metadata at all (#107).
        """
        all_metadata = self.get_metadata()
        if not all_metadata or "metadata" not in all_metadata:
            return "No metadata found for this session"

        metadata_dict = all_metadata["metadata"]
        if keys:
            filtered = {}
            missing = []
            for key in keys:
                found, value = resolve_path(metadata_dict, key)
                if found:
                    filtered[key] = value
                else:
                    missing.append(key)
            if not filtered:
                return f"No metadata found for keys: {keys}"
            retrieved = f"Metadata retrieved: {json.dumps(filtered, default=str)}"
            if missing:
                return f"{retrieved}. Not found: {missing}"
            return retrieved

        if metadata_dict:
            return f"All metadata: {json.dumps(metadata_dict, default=str)}"
        return "No metadata stored in session"

    def _handle_metadata_set(self, metadata: dict[str, Any]) -> str:
        """Handle set/update action for the metadata tool.

        The reply names the keys whose value was a document, because MongoDB's
        `$set` replaces the stored one whole. Passing a subdocument is the
        natural thing for a model to do, and left unsaid it drops the siblings
        of what it wrote while being told it succeeded (#47).
        """
        if not metadata:
            return "Error: metadata dictionary required for set/update action"
        self.update_metadata(metadata)
        result = f"Successfully updated metadata fields: {list(metadata.keys())}"

        replaced = [key for key, value in metadata.items() if isinstance(value, dict)]
        if replaced:
            result += (
                f". Careful: {replaced} received a whole document, which replaces "
                f"what was stored under it. Use dot notation in the key "
                f'("{replaced[0]}.<field>") to update one field and keep the rest'
            )
        return result

    def _handle_metadata_delete(self, keys: list[str]) -> str:
        """Handle delete action for the metadata tool."""
        if not keys:
            return "Error: keys list required for delete action"
        self.delete_metadata(keys)
        return f"Successfully deleted metadata fields: {keys}"

    def get_metadata_tool(self) -> Callable:
        """Get a tool for managing session metadata.

        The docstring below is the tool's contract: Strands builds the
        description and the input schema from it, and that is all the model
        ever reads. It used to be overridden by a one-line `description=` and a
        hand-written `inputSchema=` that was missing the `{"json": ...}`
        wrapper every provider unwraps -- which made an agent holding this tool
        fail on its first call, whether or not it used it (#47).

        Returns:
            A Strands tool that can be used by agents to manage session metadata.
        """
        session_manager = self  # Capture reference for closure

        @tool(name="manage_metadata")
        def manage_metadata(
            action: str,
            metadata: Any | None = None,
            keys: Any | None = None,
        ) -> str:
            """
            Manage session metadata with get, set/update, or delete operations.

            A key is a path in dot notation: a dot addresses a field inside a
            stored document, in the three actions. Prefer it, because setting a
            key to a whole document replaces what was stored under it.

            Args:
                action: The action to perform - "get", "set", "update", or "delete"
                metadata: For set/update actions, a dictionary of key-value pairs
                      to set. A dotted key updates one nested field and keeps its
                      siblings ({"user.name": "Ana"}); a key whose value is a
                      document replaces the whole document stored under it
                      ({"user": {"name": "Ana"}} drops every other field of user).
                keys: For get action, optional list of specific keys to retrieve;
                      the reply names any of them that are not stored. For delete
                      action, list of keys to remove. Dotted keys address nested
                      fields here too ("user.name", "tags.0").

            Returns:
                A string describing the result of the operation
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
            Number of messages, or 0 if agent doesn't exist. Messages of an
            invocation still in flight count: this manager appended them, so
            from here they are part of the conversation even though the write
            that stores them has not happened yet (#53).

        Example:
            count = session_manager.get_message_count("assistant-1")
            if count == 0:
                print("This is the first interaction")
        """
        pending = len(self._pending_messages.get(agent_id, []))
        try:
            return self.session_repository.count_messages(self.session_id, agent_id) + (
                pending
            )
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
