"""MongoDB Session Repository implementation for Strands Agents."""

from __future__ import annotations

import logging
import secrets
import threading
import weakref
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError
from strands.session.session_repository import SessionRepository
from strands.types.session import Session, SessionAgent, SessionMessage

from .agent_content import LastPersistedAgents
from .field_names import (
    apply_fields,
    nested_document,
    validate_agent_id,
    validate_field_paths,
)
from .message_identity import (
    STORAGE_ID_FIELD,
    MessageRef,
    attach_storage_id,
    new_storage_id,
    ref_of,
)

logger = logging.getLogger(__name__)

TIMEZONE_UTC_SUFFIX = "+00:00"

# MongoDB's append-to-array update operator, used by every write that pushes.
_PUSH = "$push"

# What a set of keys is, to name it in the error when one of them cannot go into
# a path (#79). They travel to field_names.py, which builds the message.
_AGENT_FIELD = "agent field"
_MESSAGE_FIELD = "message field"

# Aggregation operators shared by the server-side domain reads (#58).
_MATCH = "$match"
_PROJECT = "$project"
_IF_NULL = "$ifNull"

# Cursor batch negotiated for the message page (#92).
#
# The default batch is 101 documents, and on DocumentDB that applies to every
# batch and not only the first: draining 5.000 messages cost 49 `getMore` of
# 94 ms each, 5,04 s of restoration. MongoDB fills each batch up to 16 MiB
# instead and needed one.
#
# A session document cannot exceed 16 MiB, so its messages array cannot hold
# more entries than that divided by the smallest message create_message()
# writes -- well under this number. Asking for more than fits costs nothing:
# the server still caps a batch at 16 MiB and hands over a cursor for the rest.
# What matters is being strictly greater than the page: a batch of exactly its
# size returns the page with a live cursor, and closing it costs a round-trip.
_MESSAGE_BATCH_SIZE = 1_000_000

# Fields stored on message documents that SessionMessage.__init__() does not accept.
# Used to filter them out when reconstructing SessionMessage objects.
_MESSAGE_EXCLUDED_FIELDS = frozenset(
    [
        "event_loop_metrics",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "guardrail_event",
        STORAGE_ID_FIELD,
    ]
)

# Fields stored on agent documents for auditing that SessionAgent.__init__() does not accept.
_AGENT_CONFIG_FIELDS = frozenset(["model", "system_prompt", "prompt_metadata"])

# Collections whose indexes have already been ensured, keyed by MongoClient.
#
# pymongo does not cache create_index: every call is a round-trip to the server
# even when the index already exists. Since a session manager is typically
# created per request, that meant 4+ round-trips per instantiation.
#
# Keyed by client (not by database/collection name) so two clients pointing at
# different clusters that happen to share names each get their indexes. The
# WeakKeyDictionary drops the entry when the client is closed and collected.
_INDEX_REGISTRY: weakref.WeakKeyDictionary[Any, set[tuple]] = (
    weakref.WeakKeyDictionary()
)
_INDEX_REGISTRY_LOCK = threading.Lock()

# Server errors that another attempt cannot fix (#59).
#
# With a session manager per request, retrying something that will always fail
# is a wasted round-trip per request for ever, and creating an index costs
# 78-248 ms in DocumentDB. A collection at the 64-index limit, or a user without
# the right to index, answers the same way every time.
_PERMANENT_INDEX_ERRORS = frozenset(
    [
        67,  # CannotCreateIndex
        13,  # Unauthorized
        85,  # IndexOptionsConflict
        86,  # IndexKeySpecsConflict
    ]
)


def _reset_index_registry() -> None:
    """Clear the index registry. Intended for tests."""
    with _INDEX_REGISTRY_LOCK:
        _INDEX_REGISTRY.clear()


class MongoDBSessionRepository(SessionRepository):
    """MongoDB implementation of SessionRepository interface for persistent session storage.

    This class provides low-level MongoDB operations for session management, implementing
    the SessionRepository interface from Strands SDK. It handles all database interactions
    including CRUD operations for sessions, agents, and messages, with support for
    metadata management and connection lifecycle control.

    Key Features:
        - Document-based storage with embedded agents and messages
        - Smart connection management (owns vs borrows MongoDB client)
        - Automatic index creation for optimized queries
        - Datetime serialization/deserialization for MongoDB compatibility
        - Metadata field indexing with partial updates support
        - Thread-safe operations with proper error handling

    Methods:
        __init__(connection_string, database_name, collection_name, client, metadata_fields, metadata_hook, **kwargs):
            Initialize repository with MongoDB connection and configuration.

        create_session(session, **kwargs):
            Create a new session document in MongoDB.

        read_session(session_id, **kwargs):
            Read a session from MongoDB by ID.

        create_agent(session_id, session_agent, **kwargs):
            Create an agent within a session document.

        read_agent(session_id, agent_id, **kwargs):
            Read an agent from a session by agent ID.

        update_agent(session_id, session_agent, **kwargs):
            Update an existing agent, preserving timestamps and the stored config.

        create_message(session_id, agent_id, session_message, **kwargs):
            Add a message to an agent's message array.

        read_message(session_id, agent_id, message_id, **kwargs):
            Read a specific message by ID.

        update_message(session_id, agent_id, session_message, **kwargs):
            Update a message (typically for redaction).

        list_messages(session_id, agent_id, limit, offset, **kwargs):
            List messages with pagination support.

        update_metadata(session_id, metadata):
            Update session metadata with partial updates (preserves existing fields).

        get_metadata(session_id):
            Retrieve metadata for a specific session.

        delete_metadata(session_id, metadata_keys):
            Delete specific metadata fields using MongoDB $unset.

        close():
            Close MongoDB connection if owned by this repository.

    MongoDB Schema:
        ```json
        {
            "_id": "session-id",
            "session_id": "session-id",
            "session_type": "default",
            "session_viewer_password": "abc123...xyz789",
            "created_at": ISODate(),
            "updated_at": ISODate(),
            "metadata": {
                "key": "value"
            },
            "agents": {
                "agent-id": {
                    "agent_data": {...},
                    "created_at": ISODate(),
                    "updated_at": ISODate(),
                    "messages": [
                        {
                            "message_id": 1,
                            "storage_id": "9f1c...",
                            "role": "user",
                            "content": "...",
                            "created_at": ISODate(),
                            "updated_at": ISODate(),
                            "event_loop_metrics": {...}
                        }
                    ]
                }
            }
        }
        ```

        Note: session_viewer_password is automatically generated (32-char alphanumeric) on session creation.

    Example:
        ```python
        # Create repository with new connection
        repo = MongoDBSessionRepository(
            connection_string="mongodb://localhost:27017/",
            database_name="chat_db",
            collection_name="sessions"
        )

        # Or reuse existing client
        repo = MongoDBSessionRepository(
            client=existing_mongo_client,
            database_name="chat_db",
            collection_name="sessions"
        )

        # Create session
        session = Session(session_id="user-123", session_type="chat")
        repo.create_session(session)

        # Manage metadata
        repo.update_metadata("user-123", {"priority": "high"})
        metadata = repo.get_metadata("user-123")

        # Clean up
        repo.close()
        ```
    """

    def __init__(
        self,
        connection_string: str | None = None,
        database_name: str = "database_name",
        collection_name: str = "collection_name",
        client: MongoClient | None = None,
        metadata_fields: list[str] | None = None,
        application_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize MongoDB Session Repository.

        Args:
            connection_string: MongoDB connection string (ignored if client is provided)
            database_name: Name of the database
            collection_name: Name of the collection for sessions
            client: Optional pre-configured MongoClient to use
            application_name: Application name for session categorization (immutable after creation)
            **kwargs: Additional arguments for MongoClient. A provided client
                cannot take them any more: they are ignored, with a warning

        Raises:
            ValueError: If a metadata field is not a valid dot-notation path, or
                if two of them cannot coexist in one document (`user` and
                `user.name`, where one would have to be both a value and a
                subdocument). Both are checked before any client is created: an
                invalid name cannot be indexed, and a pair that conflicts would
                lose one of the two silently when the session is seeded.
        """
        # Built here, before any client, so a configuration that cannot be
        # seeded fails the application's startup and not every create_session().
        self._metadata_seed = nested_document(metadata_fields or ())
        self.application_name = application_name
        if client is not None:
            # Use provided client
            self.client: MongoClient = client
            self._owns_client = False  # Don't close a client we didn't create
            logger.debug("Using provided MongoDB client")
            if kwargs:
                # Said out loud since #111: a maxPoolSize passed to the
                # factory's create_session_manager() used to do nothing, quietly.
                logger.warning(
                    f"MongoClient options {sorted(kwargs)} ignored: the client "
                    f"was provided, so configure them where it is created"
                )
        else:
            # Create new client (legacy behavior)
            if connection_string is None:
                raise ValueError("Connection string is required")
            self.client = MongoClient(connection_string, **kwargs)
            self._owns_client = True  # We created it, we should close it
            logger.debug("Created new MongoDB client")

        self.database: Database = self.client[database_name]
        self.collection: Collection = self.database[collection_name]
        self.metadata_fields = metadata_fields
        # Config found by the last read_agent(); see pop_read_agent_config().
        self._last_read_agent_config: dict[tuple[str, str], dict[str, Any]] = {}
        # What each agent looked like when last read or written; see update_agent().
        self._persisted_agents = LastPersistedAgents()
        # Create indexes for timestamp ordering (only once per collection)
        self._ensure_indexes()

        logger.debug(
            f"Initialized MongoDB session repository - "
            f"Database: {database_name}, Collection: {collection_name}"
        )

    def _indexed_fields(self) -> list[str]:
        """The indexes this collection needs, in the order they are created.

        The library's own go first, and `application_name` with them: it used to
        be last, behind the `metadata_fields` that whoever configures the
        application chooses. A failure no longer takes the rest down -- there is
        a `try` per index now -- but the order still decides who gets served
        when the collection runs out of its 64 index slots (#59). Messages are a
        nested array and MongoDB does not accept a
        positional operator in an index definition, so they are reached through
        the `_id` index of their session.
        """
        return [
            "created_at",
            "updated_at",
            "session_id",
            "application_name",
            *(f"metadata.{field}" for field in self.metadata_fields or ()),
        ]

    def _ensure_indexes(self) -> None:
        """Ensure necessary indexes exist on the collection.

        Idempotent per client: the indexes are only sent to the server the first
        time this collection is seen through a given MongoClient. See
        _INDEX_REGISTRY for why.

        Each index is created on its own: they shared a single `try`, so the
        first failure skipped every index after it and the collection silently
        went without them (#59). Whether the next manager tries again depends on
        what failed -- see _PERMANENT_INDEX_ERRORS.
        """
        registry_key = (
            self.database.name,
            self.collection.name,
            tuple(self.metadata_fields or ()),
        )
        with _INDEX_REGISTRY_LOCK:
            ensured = _INDEX_REGISTRY.get(self.client)
            if ensured is not None and registry_key in ensured:
                logger.debug("MongoDB indexes already ensured for this client")
                return

        worth_retrying = False
        for field in self._indexed_fields():
            try:
                self.collection.create_index(field)
            except PyMongoError as e:
                if getattr(e, "code", None) in _PERMANENT_INDEX_ERRORS:
                    logger.warning(
                        f"Index on {field!r} cannot be created and will not be "
                        f"retried; queries filtering on it will scan the "
                        f"collection: {e}"
                    )
                else:
                    worth_retrying = True
                    logger.warning(f"Failed to create index on {field!r}: {e}")

        if worth_retrying:
            # Not recorded: the next manager should try the whole set again.
            return

        try:
            with _INDEX_REGISTRY_LOCK:
                _INDEX_REGISTRY.setdefault(self.client, set()).add(registry_key)
        except TypeError:
            # Client does not support weak references (exotic test doubles).
            # Losing the cache only costs round-trips, so carry on.
            logger.debug("MongoDB client does not support weak references")

    @staticmethod
    def _parse_iso_datetime(dt_str: str) -> datetime:
        """Convert ISO 8601 string (possibly with Z suffix) to Python datetime."""
        return datetime.fromisoformat(dt_str.replace("Z", TIMEZONE_UTC_SUFFIX))

    @staticmethod
    def _agent_path(agent_id: str) -> str:
        """Build `agents.<agent_id>`, the only place an agent path is built.

        Validating here is what keeps a name MongoDB would parse as syntax from
        ever reaching a path (#79): with `a.b` the agent landed nested, where no
        read looks, and every request wiped its history. Call it in the first
        statement of a method, before any early return or round-trip.
        """
        validate_agent_id(agent_id)
        return f"agents.{agent_id}"

    @staticmethod
    def _prefixed(prefix: str, fields: Mapping[str, Any], what: str) -> dict[str, Any]:
        """Join a caller's keys to a path the repository owns, validating them first.

        The sibling of _agent_path() for the keys that come from outside: metadata
        keys and the keys relative to a message or an agent. Every key is checked
        before any is joined, so a batch with one bad key produces nothing to write.
        """
        validate_field_paths(fields, what)
        return {f"{prefix}.{name}": value for name, value in fields.items()}

    @staticmethod
    def _agent_exists(doc: dict | None, agent_id: str) -> bool:
        """Check if an agent exists in a session document."""
        return bool(doc and "agents" in doc and agent_id in doc["agents"])

    @staticmethod
    def _filter_message_data(msg_data: Mapping[str, Any]) -> dict:
        """Filter out fields that SessionMessage.__init__() does not accept."""
        return {k: v for k, v in msg_data.items() if k not in _MESSAGE_EXCLUDED_FIELDS}

    @classmethod
    def _to_session_message(cls, msg_data: Mapping[str, Any]) -> SessionMessage:
        """Rebuild a SessionMessage, identity included.

        Shared with the in-memory double: a message read back has to carry its
        storage_id, or a restored manager would go back to redacting by index.
        """
        session_message = SessionMessage(**cls._filter_message_data(msg_data))
        attach_storage_id(session_message, msg_data.get(STORAGE_ID_FIELD))
        return session_message

    @staticmethod
    def _filter_agent_data(agent_data: Mapping[str, Any]) -> dict:
        """Filter out fields that SessionAgent.__init__() does not accept."""
        return {k: v for k, v in agent_data.items() if k not in _AGENT_CONFIG_FIELDS}

    def create_session(self, session: Session, **kwargs: Any) -> Session:
        """Create a new Session in MongoDB.

        Automatically generates a secure 32-character alphanumeric password
        for session viewer access stored in session_viewer_password field.
        """
        # Generate secure 32-character alphanumeric password
        # secrets.token_urlsafe(24) generates ~32 chars in base64url encoding
        now = datetime.now(UTC)
        session_viewer_password = secrets.token_urlsafe(24)

        session_doc = {
            "_id": session.session_id,
            "session_id": session.session_id,
            "application_name": self.application_name,
            "session_type": session.session_type,
            "session_viewer_password": session_viewer_password,
            "created_at": now,
            "updated_at": now,
            "agents": {},
            # A copy: the seed is nested now, so sharing it would let one
            # session's metadata reach into the next one's document.
            "metadata": deepcopy(self._metadata_seed),
            "feedbacks": [],
            "guardrail_events": [],
        }

        try:
            self.collection.insert_one(session_doc)
            logger.info(f"Created session: {session.session_id} with viewer password")
        except PyMongoError as e:
            logger.error(f"Failed to create session {session.session_id}: {e}")
            raise

        return session

    def read_session(self, session_id: str, **kwargs: Any) -> Session | None:
        """Read a Session header from MongoDB without its embedded history."""
        try:
            doc = self.collection.find_one(
                {"_id": session_id},
                {
                    "session_id": 1,
                    "session_type": 1,
                    "created_at": 1,
                    "updated_at": 1,
                },
            )
            if not doc:
                logger.debug(f"Session not found: {session_id}")
                return None

            # Convert MongoDB document to Session object
            session = Session(
                session_id=doc["session_id"],
                session_type=doc.get("session_type", "default"),
                created_at=doc.get("created_at"),
                updated_at=doc.get("updated_at"),
            )

            logger.debug(f"Read session: {session_id}")
            return session

        except PyMongoError as e:
            logger.error(f"Failed to read session {session_id}: {e}")
            raise

    def delete_session(self, session_id: str, **kwargs: Any) -> None:
        """Delete a Session and everything embedded in it.

        Session, agents, messages, metadata, feedbacks and guardrail events
        share one document, so a single delete_one removes them all atomically
        (#132).

        Raises:
            ValueError: If the session does not exist, like every other write
                on a missing session. One round-trip: the delete's
                deleted_count says so, no read first.

        The knowledge this repository holds in memory about the session dies
        with the document: update_agent() consults the persisted-content cache
        before the store, so a cache that survived the delete would turn the
        next sync of the very same content into a silent no-op instead of
        `not found`.
        """
        try:
            result = self.collection.delete_one({"_id": session_id})
            if result.deleted_count == 0:
                raise ValueError(f"Session {session_id} not found")
        except PyMongoError as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            raise

        self._persisted_agents.forget_session(session_id)
        self._last_read_agent_config = {
            key: config
            for key, config in self._last_read_agent_config.items()
            if key[0] != session_id
        }
        logger.info(f"Deleted session: {session_id}")

    def create_agent(
        self, session_id: str, session_agent: SessionAgent, **kwargs: Any
    ) -> None:
        """Create a new Agent in a Session."""
        agent_path = self._agent_path(session_agent.agent_id)
        now = datetime.now(UTC)
        agent_data = session_agent.__dict__.copy()
        agent_data["created_at"] = self._parse_iso_datetime(session_agent.created_at)
        agent_data["updated_at"] = self._parse_iso_datetime(session_agent.updated_at)

        agent_doc = {
            "agent_data": agent_data,
            "messages": [],
            "created_at": now,
            "updated_at": now,
        }

        try:
            result = self.collection.update_one(
                {"_id": session_id},
                {
                    "$set": {
                        agent_path: agent_doc,
                        "updated_at": now,
                    }
                },
            )

            if result.matched_count == 0:
                raise ValueError(f"Session {session_id} not found")

            self._persisted_agents.remember(session_id, session_agent)
            logger.info(
                f"Created agent {session_agent.agent_id} in session {session_id}"
            )

        except PyMongoError as e:
            logger.error(f"Failed to create agent {session_agent.agent_id}: {e}")
            raise

    def read_agent(
        self, session_id: str, agent_id: str, **kwargs: Any
    ) -> SessionAgent | None:
        """Read an Agent from a Session."""
        agent_path = self._agent_path(agent_id)
        try:
            # Only agent_data is restored here; list_messages() fetches the
            # history separately. Keep model and system_prompt inside this
            # projection: the manager uses them to seed its config cache.
            doc = self.collection.find_one(
                {"_id": session_id}, {f"{agent_path}.agent_data": 1}
            )

            if not self._agent_exists(doc, agent_id):
                logger.debug(f"Agent {agent_id} not found in session {session_id}")
                self._persisted_agents.forget(session_id, agent_id)
                return None

            agent_data = doc["agents"][agent_id]["agent_data"]

            session_agent = SessionAgent(**self._filter_agent_data(agent_data))
            self._persisted_agents.remember(session_id, session_agent)
            self._last_read_agent_config = {
                (session_id, agent_id): {
                    "model": agent_data.get("model"),
                    "system_prompt": agent_data.get("system_prompt"),
                }
            }
            logger.debug(f"Read agent {agent_id} from session {session_id}")
            return session_agent

        except PyMongoError as e:
            logger.error(f"Failed to read agent {agent_id}: {e}")
            raise

    def pop_read_agent_config(
        self, session_id: str, agent_id: str
    ) -> dict[str, Any] | None:
        """Return, and forget, the agent config found by read_agent().

        Public because the session manager calls it: a method reached from
        another class is part of the interface whatever the underscore says,
        and any repository passed as session_repository= has to provide it.

        read_agent() already fetches model and system_prompt but cannot return
        them inside a SessionAgent. The session manager takes them from here to
        skip rewriting a config that is already persisted, without reading the
        agent a second time. Only the last read is kept, so a long-lived
        repository does not pile up system prompts.

        Returns:
            Dict with model and system_prompt, or None if it was already taken
            or another agent has been read since.
        """
        return self._last_read_agent_config.pop((session_id, agent_id), None)

    def update_agent(
        self, session_id: str, session_agent: SessionAgent, **kwargs: Any
    ) -> None:
        """Update an Agent in a Session.

        Each SessionAgent field is written on its own path. Setting agent_data
        as a whole would replace the subdocument and wipe model, system_prompt
        and prompt_metadata, which the session manager also stores there but
        SessionAgent does not carry. Every field is still replaced whole, so
        keys removed from the agent state do disappear.

        An agent whose content, timestamps aside, is what this repository last
        read or wrote is not written at all (#67): no round-trip, no updated_at
        refreshed and no "not found" check. Strands sends exactly that on the
        first sync of every manager and after every tool run.
        """
        agent_path = self._agent_path(session_agent.agent_id)
        if self._persisted_agents.unchanged(session_id, session_agent):
            logger.debug(
                f"Agent {session_agent.agent_id} unchanged in session {session_id}"
            )
            return

        now = datetime.now(UTC)
        agent_data = session_agent.__dict__.copy()
        agent_data["created_at"] = self._parse_iso_datetime(session_agent.created_at)
        agent_data["updated_at"] = self._parse_iso_datetime(session_agent.updated_at)

        set_operations = {
            f"{agent_path}.agent_data.{name}": value
            for name, value in agent_data.items()
        }
        set_operations[f"{agent_path}.updated_at"] = now
        set_operations["updated_at"] = now

        try:
            # The agent's own created_at (agents.<id>.created_at) is deliberately
            # absent from the $set: it was written by create_agent and an update
            # that does not name it leaves it alone. Reading it back first would
            # be a read-after-write, which on a secondaryPreferred cluster can
            # return a stale document and end up overwriting the original
            # timestamp with now.
            result = self.collection.update_one(
                {"_id": session_id},
                {"$set": set_operations},
            )

            if result.matched_count == 0:
                raise ValueError(f"Session {session_id} not found")

            # Only a write that landed counts as persisted: one that raised or
            # matched nothing must be tried again by the next sync.
            self._persisted_agents.remember(session_id, session_agent)
            logger.debug(
                f"Updated agent {session_agent.agent_id} in session {session_id}"
            )

        except PyMongoError as e:
            logger.error(f"Failed to update agent {session_agent.agent_id}: {e}")
            raise

    def create_message(
        self,
        session_id: str,
        agent_id: str,
        session_message: SessionMessage,
        **kwargs: Any,
    ) -> None:
        """Create a new Message for the Agent.

        The message is born with a storage_id: an identity that does not come
        from its index, so later writes can name it even if another manager
        appends a message numbered the same (issue #78). The same value is
        attached to the SessionMessage, which Strands keeps for the rest of the
        turn and hands back for the redaction.
        """
        self.create_messages(session_id, agent_id, [session_message], **kwargs)

    def create_messages(
        self,
        session_id: str,
        agent_id: str,
        session_messages: Sequence[SessionMessage],
        fields_on_last: Mapping[str, Any] | None = None,
        agent_set_operations: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Append messages to an agent, in order, in a single write.

        The sibling of create_message() for a whole batch: `$each` preserves the
        order of the list, and the array only ever grows at its end, so a batch
        is indistinguishable from the same messages pushed one by one -- except
        in the number of round-trips, which on DocumentDB is what costs 40-55 ms
        each (#53).

        Args:
            session_messages: The messages, in conversation order. Each is born
                with its own storage_id, attached back onto it (#78).
            fields_on_last: Fields to store on the last message of the batch,
                as dot-notation keys relative to its document
                ("event_loop_metrics.cycle_metrics"). They are nested into the
                document before it is pushed, because `$set` cannot reach a
                message the same write is creating. This is how the metrics of
                an invocation cost no write of their own.
            agent_set_operations: Keys relative to the agent document, to land
                in the same round-trip.

        Raises:
            ValueError: If the session does not exist, or if the agent_id or a
                field key would be parsed as syntax. The names are checked
                before the early return for an empty batch, so a bad one fails
                the same way whether or not there is anything to write.
        """
        agent_path = self._agent_path(agent_id)
        agent_fields = self._prefixed(
            agent_path, agent_set_operations or {}, _AGENT_FIELD
        )
        # Checked here, and applied further down, so a bad key fails the same
        # way whether or not there is a batch to write it on.
        validate_field_paths(fields_on_last or {}, _MESSAGE_FIELD)

        if not session_messages:
            return

        now = datetime.now(UTC)
        storage_ids = [new_storage_id() for _ in session_messages]
        documents = [
            {
                **session_message.__dict__,
                STORAGE_ID_FIELD: storage_id,
                "created_at": now,
                "updated_at": now,
            }
            for session_message, storage_id in zip(
                session_messages, storage_ids, strict=True
            )
        ]
        apply_fields(documents[-1], fields_on_last or {}, _MESSAGE_FIELD)

        try:
            result = self.collection.update_one(
                {"_id": session_id},
                {
                    _PUSH: {f"{agent_path}.messages": {"$each": documents}},
                    "$set": {
                        **agent_fields,
                        f"{agent_path}.updated_at": now,
                        "updated_at": now,
                    },
                },
            )

            if result.matched_count == 0:
                raise ValueError(f"Session {session_id} not found")

            for session_message, storage_id in zip(
                session_messages, storage_ids, strict=True
            ):
                attach_storage_id(session_message, storage_id)
            logger.debug(
                f"Created {len(documents)} message(s) for agent {agent_id}: "
                f"{[m.message_id for m in session_messages]}"
            )

        except PyMongoError as e:
            logger.error(f"Failed to create messages: {e}")
            raise

    def read_message(
        self, session_id: str, agent_id: str, message_id: int, **kwargs: Any
    ) -> SessionMessage | None:
        """Read the first message with this Strands index.

        ``message_id`` is not unique under concurrent managers (#78), so this
        deliberately keeps the historical first-match behaviour. ``$filter``
        performs the search in MongoDB and ``$arrayElemAt`` returns at most one
        array element. A ``$elemMatch`` projection cannot target this nested
        array (MongoDB error 31275).
        """
        agent_path = self._agent_path(agent_id)
        pipeline = [
            {_MATCH: {"_id": session_id}},
            {
                _PROJECT: {
                    "_id": 0,
                    "message": {
                        "$arrayElemAt": [
                            {
                                "$filter": {
                                    "input": {
                                        _IF_NULL: [f"${agent_path}.messages", []]
                                    },
                                    "as": "message",
                                    "cond": {
                                        "$eq": ["$$message.message_id", message_id]
                                    },
                                }
                            },
                            0,
                        ]
                    },
                }
            },
        ]
        try:
            doc = next(iter(self.collection.aggregate(pipeline)), None)
            if not doc or "message" not in doc:
                return None
            return self._to_session_message(doc["message"])

        except PyMongoError as e:
            logger.error(f"Failed to read message {message_id}: {e}")
            raise

    def _missing_message_error(
        self, session_id: str, agent_id: str, ref: MessageRef
    ) -> ValueError:
        """Say which of session, agent or message is missing after a no-match.

        The compound filter of update_message() cannot tell them apart, and
        reporting a missing message when the agent does not even exist would be
        a misleading diagnostic.

        Existence is checked with counts, not with find_one: projecting
        agents.<id> would pull the agent subdocument with its whole messages
        array, which is the very read this method's caller exists to avoid.
        These are bounded by _id equality and limit=1, so they cost the same on
        a session of three messages and on one of three thousand. They only ever
        run on the path that is already raising.
        """
        if self.collection.count_documents({"_id": session_id}, limit=1) == 0:
            return ValueError(f"Session {session_id} not found")

        agent_filter = {
            "_id": session_id,
            self._agent_path(agent_id): {"$exists": True},
        }
        if self.collection.count_documents(agent_filter, limit=1) == 0:
            return ValueError(f"Agent {agent_id} not found in session {session_id}")

        return ValueError(self._missing_message_text(session_id, agent_id, ref))

    @staticmethod
    def _missing_message_text(session_id: str, agent_id: str, ref: MessageRef) -> str:
        """Word the diagnostic for a message that was not found.

        Names what was actually searched for. Naming the index alone would be a
        lie in the very case this exists for: with a duplicated message_id the
        index does exist, and what is missing is the identity.

        Shared with the in-memory double so both raise the same sentence.
        """
        field, value = ref.locator()
        return (
            f"Message {ref.message_id} not found in agent {agent_id} "
            f"of session {session_id} (searched by {field}={value})"
        )

    def _update_message_document(
        self,
        session_id: str,
        agent_id: str,
        ref: MessageRef,
        message_fields: Mapping[str, Any],
        *,
        agent_fields: Mapping[str, Any] | None = None,
        push: Mapping[str, Any] | None = None,
        touch_timestamps: bool = False,
    ) -> bool:
        """Write fields onto one message, located server-side by its reference.

        This is the only place in the project that builds the positional
        selector. Everything that writes on a message goes through here:
        update_message(), the turn metrics and the guardrail event.

        Args:
            message_fields: Keys relative to the message document
                ("guardrail_event", "event_loop_metrics.cycle_metrics"). The
                positional prefix is this method's business, not the caller's.
            agent_fields: Keys relative to the agent document, to land in the
                same round-trip.
            push: Absolute paths to $push onto. Stays private precisely because
                these keys are not prefixed by anything the repository owns.
            touch_timestamps: Refresh updated_at on message, agent and session.
                Private on purpose: a redaction is a visible change to the
                session, but annotating a turn that already happened is not, and
                moving the session clock for it would misreport session duration
                to its consumers.

        Returns:
            True when the filter matched a document. A no-match is not an error
            here: update_message() turns it into a ValueError, the agent sync
            logs it and the guardrail event ignores it. matched_count is pymongo
            vocabulary and does not leave this class.

        Raises:
            ValueError: If the agent_id or a field key would be parsed as syntax.
                Checked before the early return for an empty write, so a bad
                name fails the same way whether or not there is anything to write.
        """
        agent_path = self._agent_path(agent_id)
        message_prefix = f"{agent_path}.messages.$"
        set_operations = self._prefixed(message_prefix, message_fields, _MESSAGE_FIELD)
        set_operations.update(
            self._prefixed(agent_path, agent_fields or {}, _AGENT_FIELD)
        )

        if touch_timestamps:
            now = datetime.now(UTC)
            set_operations[f"{message_prefix}.updated_at"] = now
            set_operations[f"{agent_path}.updated_at"] = now
            set_operations["updated_at"] = now

        if not set_operations and not push:
            return False

        update: dict[str, Any] = {}
        if set_operations:
            update["$set"] = set_operations
        if push:
            update[_PUSH] = dict(push)

        # Which field names a message is MessageRef's rule, not this method's:
        # the in-memory double resolves it the same way over a list.
        field, value = ref.locator()

        try:
            result = self.collection.update_one(
                {"_id": session_id, f"{agent_path}.messages.{field}": value},
                update,
            )
        except PyMongoError as e:
            logger.error(
                f"Failed to update message {ref.message_id} of agent {agent_id} "
                f"in session {session_id}: {e}"
            )
            raise

        return result.matched_count > 0

    def update_message_fields(
        self,
        session_id: str,
        agent_id: str,
        ref: MessageRef,
        set_operations: Mapping[str, Any],
        agent_set_operations: Mapping[str, Any] | None = None,
    ) -> bool:
        """Write fields on one message, and optionally on its agent, in one write.

        Args:
            ref: Which message to write on. Build it from the message itself,
                with `ref_of()` or `get_last_message_ref()`: a hand-made
                MessageRef with no storage_id falls back to naming the message
                by its index, which is what MessageRef exists to avoid.
            set_operations: Keys relative to the message document.
            agent_set_operations: Keys relative to the agent document
                ("agent_data.model"). They travel in the same round-trip: on
                DocumentDB every write costs 40-55 ms regardless of its size,
                so what drives latency is the number of round-trips.

        Returns:
            True when the filter matched a document.
        """
        return self._update_message_document(
            session_id,
            agent_id,
            ref,
            set_operations,
            agent_fields=agent_set_operations,
        )

    def update_agent_fields(
        self, session_id: str, agent_id: str, set_operations: Mapping[str, Any]
    ) -> bool:
        """Write fields under agents.<agent_id> without touching its messages.

        The non-positional sibling of update_message_fields(): the filter names
        the session and requires the agent to exist. The existence guard keeps
        MongoDB's dotted $set from creating a half-built agent (#119). Used when
        there is no message to point at, such as the first sync of an agent that
        has not appended anything yet.

        Args:
            set_operations: Keys relative to the agent document.

        Returns:
            True when the session and the agent were found.

        Raises:
            ValueError: If the agent_id or a key would be parsed as syntax,
                checked before the early return for an empty write.
        """
        agent_path = self._agent_path(agent_id)
        prefixed = self._prefixed(agent_path, set_operations, _AGENT_FIELD)
        if not prefixed:
            return False

        try:
            result = self.collection.update_one(
                {"_id": session_id, agent_path: {"$exists": True}},
                {"$set": prefixed},
            )
        except PyMongoError as e:
            logger.error(
                f"Failed to update agent {agent_id} in session {session_id}: {e}"
            )
            raise

        return result.matched_count > 0

    def update_message(
        self,
        session_id: str,
        agent_id: str,
        session_message: SessionMessage,
        **kwargs: Any,
    ) -> None:
        """Update a Message (usually for redaction).

        Strands hands back the very SessionMessage it appended, so the message
        still carries the identity create_message() gave it and the redaction
        lands on it -- see MessageRef. Located server-side, so the happy path is
        a single write: the whole history no longer has to be read to compute an
        index in the client.

        Only `message` and `redact_message` are written, each on its own path.
        Setting the message subdocument as a whole would replace it and wipe the
        fields the session manager keeps there but SessionMessage does not carry
        (event_loop_metrics, guardrail_event). They are listed by hand on
        purpose: deriving them from SessionMessage.__dict__ would let a new SDK
        field into the schema without review. created_at is never named, and an
        update that does not name it leaves it alone, keeping value and type.
        """
        ref = ref_of(session_message)
        matched = self._update_message_document(
            session_id,
            agent_id,
            ref,
            {
                "message": session_message.message,
                "redact_message": session_message.redact_message,
            },
            touch_timestamps=True,
        )

        if not matched:
            raise self._missing_message_error(session_id, agent_id, ref)

        logger.debug(
            f"Updated message {session_message.message_id} for agent {agent_id}"
        )

    @staticmethod
    def _message_page_pipeline(
        session_id: str, agent_path: str, limit: int | None, offset: int
    ) -> list[dict[str, Any]]:
        """Build the stable chronological page used by list_messages()."""
        sort_order = {
            "_missing_created_at": 1,
            "message.created_at": 1,
            "_array_index": 1,
        }
        missing_created_at = {
            "$cond": [
                {"$eq": [{_IF_NULL: ["$message.created_at", None]}, None]},
                1,
                0,
            ]
        }
        pipeline: list[dict[str, Any]] = [
            {_MATCH: {"_id": session_id}},
            {
                _PROJECT: {
                    "_id": 0,
                    "message": {_IF_NULL: [f"${agent_path}.messages", []]},
                }
            },
            {
                "$unwind": {
                    "path": "$message",
                    "includeArrayIndex": "_array_index",
                }
            },
            {
                _PROJECT: {
                    "_id": 0,
                    "message": 1,
                    "_array_index": 1,
                    "_missing_created_at": missing_created_at,
                }
            },
            {"$sort": sort_order},
        ]
        if offset:
            pipeline.append({"$skip": offset})
        if limit is not None:
            pipeline.append({"$limit": limit})
        if offset or limit is not None:
            pipeline.append({"$sort": dict(sort_order)})
        return pipeline

    def list_messages(
        self,
        session_id: str,
        agent_id: str,
        limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> list[SessionMessage]:
        """List messages in stable chronological order, paginated in MongoDB.

        Sorting before ``$skip``/``$limit`` preserves the public contract when
        physical append order differs from ``created_at``. The array index is a
        deterministic tie-breaker, and missing timestamps sort last. The final
        ``$sort`` is intentional: DocumentDB only guarantees aggregation result
        order when sorting is the last pipeline stage.

        The page travels in a single batch: what made restoring a long session
        expensive was not its bytes but how many round-trips the cursor took to
        hand them over -- see _MESSAGE_BATCH_SIZE (#92).
        """
        agent_path = self._agent_path(agent_id)
        if offset < 0:
            raise ValueError("offset must be greater than or equal to 0")
        if limit is not None and limit < 0:
            raise ValueError("limit must be greater than or equal to 0")
        if limit == 0:
            return []
        pipeline = self._message_page_pipeline(session_id, agent_path, limit, offset)

        try:
            result = []
            cursor = self.collection.aggregate(pipeline, batchSize=_MESSAGE_BATCH_SIZE)
            for i, item in enumerate(cursor):
                try:
                    result.append(self._to_session_message(item["message"]))
                except Exception as e:
                    logger.error(f"Failed to convert message {i}: {e}")

            logger.debug(
                f"Listed {len(result)} messages for agent {agent_id} in session {session_id}"
            )
            return result

        except PyMongoError as e:
            logger.error(f"Failed to list messages: {e}")
            raise

    def close(self) -> None:
        """Close the MongoDB connection."""
        if self._owns_client:
            self.client.close()
            logger.debug("MongoDB connection closed")
        else:
            logger.debug("Skipping close - using shared MongoDB client")

    # CUSTOM METHODS
    def update_metadata(self, session_id: str, metadata: dict[str, Any]) -> None:
        """Update the metadata for the session.

        A dotted key is a path (`user.name`, `tags.0`), which is what keeps
        sibling fields intact.

        Raises:
            ValueError: If any key has an empty segment, a segment starting with
                `$` or a NUL byte. The whole batch is checked first, so nothing
                is written.
            ValueError: If the session does not exist.
        """
        # Dot notation preserves the existing values of every other key.
        set_operations = self._prefixed("metadata", metadata, "metadata key")
        try:
            result = self.collection.update_one(
                {"_id": session_id},
                {"$set": set_operations},
            )
            if result.matched_count == 0:
                raise ValueError(f"Session {session_id} not found")
        except PyMongoError as e:
            logger.error(f"Failed to update metadata for session {session_id}: {e}")
            raise

    def get_metadata(self, session_id: str) -> dict[str, Any]:
        """Get the metadata for the session."""
        return self.collection.find_one({"_id": session_id}, {"metadata": 1})

    def delete_metadata(self, session_id: str, metadata_keys: list[str]) -> None:
        """Delete metadata keys for the session.

        Raises:
            ValueError: Under the same rule as update_metadata(), before any write.
            ValueError: If the session does not exist.
        """
        unset_operations = self._prefixed(
            "metadata", dict.fromkeys(metadata_keys, ""), "metadata key"
        )
        try:
            result = self.collection.update_one(
                {"_id": session_id},
                {"$unset": unset_operations},
            )
            if result.matched_count == 0:
                raise ValueError(f"Session {session_id} not found")
        except PyMongoError as e:
            logger.error(
                f"Failed to delete metadata keys {metadata_keys} for session {session_id}: {e}"
            )
            raise

    def add_feedback(self, session_id: str, feedback: dict[str, Any]) -> None:
        """Add feedback to the session.

        Raises:
            ValueError: If the session does not exist.
        """
        try:
            now = datetime.now(UTC)
            feedback_doc = {**feedback, "created_at": now}

            result = self.collection.update_one(
                {"_id": session_id},
                {
                    _PUSH: {"feedbacks": feedback_doc},
                    "$set": {"updated_at": now},
                },
            )
            if result.matched_count == 0:
                raise ValueError(f"Session {session_id} not found")
            logger.info(f"Added feedback to session {session_id}")
        except PyMongoError as e:
            logger.error(f"Failed to add feedback to session {session_id}: {e}")
            raise

    def get_feedbacks(self, session_id: str) -> list[dict[str, Any]]:
        """Get all feedbacks for the session."""
        try:
            doc = self.collection.find_one({"_id": session_id}, {"feedbacks": 1})

            if not doc:
                logger.debug(f"Session not found: {session_id}")
                return []

            return doc.get("feedbacks", [])
        except PyMongoError as e:
            logger.error(f"Failed to get feedbacks for session {session_id}: {e}")
            raise

    def get_session_viewer_password(self, session_id: str) -> str | None:
        """Get the session viewer password for the session.

        Args:
            session_id: The session ID to retrieve the password for

        Returns:
            The session viewer password string, or None if session not found

        Raises:
            PyMongoError: If database operation fails
        """
        try:
            doc = self.collection.find_one(
                {"_id": session_id}, {"session_viewer_password": 1}
            )

            if not doc:
                logger.debug(f"Session not found: {session_id}")
                return None

            password = doc.get("session_viewer_password")
            if password:
                logger.debug(f"Retrieved viewer password for session {session_id}")
            else:
                logger.warning(
                    f"Session {session_id} has no viewer password (legacy session?)"
                )

            return password
        except PyMongoError as e:
            logger.error(f"Failed to get viewer password for session {session_id}: {e}")
            raise

    def get_application_name(self, session_id: str) -> str | None:
        """Get the application_name for the session (read-only).

        The application_name is immutable and set at session creation time.

        Args:
            session_id: The session ID to retrieve the application name for

        Returns:
            The application name string, or None if session not found or not set

        Raises:
            PyMongoError: If database operation fails
        """
        try:
            doc = self.collection.find_one({"_id": session_id}, {"application_name": 1})

            if not doc:
                logger.debug(f"Session not found: {session_id}")
                return None

            return doc.get("application_name")
        except PyMongoError as e:
            logger.error(
                f"Failed to get application_name for session {session_id}: {e}"
            )
            raise

    def record_guardrail_event(
        self,
        session_id: str,
        agent_id: str,
        ref: MessageRef,
        event: Mapping[str, Any],
    ) -> bool:
        """Record a guardrail intervention on its message and on the session.

        The session-level entry is derived from the message one: the same fields
        plus the identifiers needed to find the message again, minus the full
        GuardrailTrace. The session array is read whole to audit a session and
        grows with every intervention, so the trace stays on the message, where
        it is read only when someone opens that message.

        Both halves travel in a single write.

        Args:
            event: The guardrail event as stored on the message, trace included.

        Returns:
            True when the message was found.
        """
        return self._update_message_document(
            session_id,
            agent_id,
            ref,
            {"guardrail_event": event},
            push={
                "guardrail_events": self._session_guardrail_entry(agent_id, ref, event)
            },
        )

    @staticmethod
    def _session_guardrail_entry(
        agent_id: str, ref: MessageRef, event: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Derive the session-level guardrail entry from the message-level one.

        Carries the identity next to the index, when the message has one:
        message_id alone would point an auditor at two messages the day the
        index is duplicated, which is the whole reason for MessageRef.

        Shared with the in-memory double so the rule -- the full trace stays on
        the message -- cannot drift between the two implementations.
        """
        entry = {
            "message_id": ref.message_id,
            "agent_id": agent_id,
            **{name: value for name, value in event.items() if name != "trace"},
        }
        if ref.storage_id is not None:
            entry[STORAGE_ID_FIELD] = ref.storage_id
        return entry

    @staticmethod
    def _agent_config(agent_id: str, agent_data: Mapping[str, Any]) -> dict[str, Any]:
        """Shape the configuration a session stores for one agent."""
        return {
            "agent_id": agent_id,
            "model": agent_data.get("model"),
            "system_prompt": agent_data.get("system_prompt"),
            "prompt_metadata": agent_data.get("prompt_metadata"),
        }

    def get_agent_config(self, session_id: str, agent_id: str) -> dict[str, Any] | None:
        """Read the stored configuration of one agent, None when it does not exist.

        Unlike pop_read_agent_config(), this is a standalone read that consumes
        nothing and also carries prompt_metadata.
        """
        agent_path = self._agent_path(agent_id)
        try:
            # Projecting agents.<id> would pull the agent subdocument with its
            # whole messages array; only agent_data is needed here.
            doc = self.collection.find_one(
                {"_id": session_id}, {f"{agent_path}.agent_data": 1}
            )

            if not self._agent_exists(doc, agent_id):
                logger.debug(f"Agent {agent_id} not found in session {session_id}")
                return None

            return self._agent_config(
                agent_id, doc["agents"][agent_id].get("agent_data", {})
            )
        except PyMongoError as e:
            logger.error(
                f"Failed to read config of agent {agent_id} "
                f"in session {session_id}: {e}"
            )
            raise

    def list_agent_configs(self, session_id: str) -> list[dict[str, Any]]:
        """List every agent config without transferring state or messages."""
        pipeline = [
            {_MATCH: {"_id": session_id}},
            {
                _PROJECT: {
                    "_id": 0,
                    "configs": {
                        "$map": {
                            "input": {"$objectToArray": {_IF_NULL: ["$agents", {}]}},
                            "as": "agent",
                            "in": {
                                "agent_id": "$$agent.k",
                                "model": "$$agent.v.agent_data.model",
                                "system_prompt": "$$agent.v.agent_data.system_prompt",
                                "prompt_metadata": (
                                    "$$agent.v.agent_data.prompt_metadata"
                                ),
                            },
                        }
                    },
                }
            },
        ]
        try:
            doc = next(iter(self.collection.aggregate(pipeline)), None)

            if not doc:
                logger.debug(f"No agents found in session {session_id}")
                return []

            return [
                self._agent_config(config["agent_id"], config)
                for config in doc.get("configs", [])
            ]
        except PyMongoError as e:
            logger.error(f"Failed to list agents of session {session_id}: {e}")
            raise

    def count_messages(self, session_id: str, agent_id: str) -> int:
        """Count messages in MongoDB, returning 0 for an unknown agent."""
        agent_path = self._agent_path(agent_id)
        pipeline = [
            {_MATCH: {"_id": session_id}},
            {
                _PROJECT: {
                    "_id": 0,
                    "count": {"$size": {_IF_NULL: [f"${agent_path}.messages", []]}},
                }
            },
        ]
        try:
            doc = next(iter(self.collection.aggregate(pipeline)), None)
            return doc["count"] if doc else 0
        except PyMongoError as e:
            logger.error(
                f"Failed to count messages of agent {agent_id} "
                f"in session {session_id}: {e}"
            )
            raise

    def get_last_message_ref(self, session_id: str, agent_id: str) -> MessageRef | None:
        """Reference the agent's last message, None when there is none.

        The fallback for a manager that has not appended anything in this
        process: the reference normally travels on the SessionMessage itself.
        The identity comes along, so a write built from here names a message
        and not an index -- see MessageRef.
        """
        agent_path = self._agent_path(agent_id)
        try:
            # $slice keeps the whole history from travelling over the wire.
            doc = self.collection.find_one(
                {"_id": session_id},
                {f"{agent_path}.messages": {"$slice": -1}},
            )

            if not self._agent_exists(doc, agent_id):
                return None

            messages = doc["agents"][agent_id].get("messages", [])
            return MessageRef.from_document(messages[-1]) if messages else None
        except PyMongoError as e:
            logger.error(
                f"Failed to read the last message reference of agent {agent_id} "
                f"in session {session_id}: {e}"
            )
            raise
