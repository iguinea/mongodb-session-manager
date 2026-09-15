"""MongoDB Session Repository implementation for Strands Agents."""

from __future__ import annotations

import logging
import secrets
import threading
import weakref
from datetime import UTC, datetime
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError
from strands.session.session_repository import SessionRepository
from strands.types.session import Session, SessionAgent, SessionMessage

logger = logging.getLogger(__name__)

TIMEZONE_UTC_SUFFIX = "+00:00"

# Fields stored on message documents that SessionMessage.__init__() does not accept.
# Used to filter them out when reconstructing SessionMessage objects.
_MESSAGE_EXCLUDED_FIELDS = frozenset(
    [
        "event_loop_metrics",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "guardrail_event",
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

        pop_read_agent_config(session_id, agent_id):
            Hand over, once, the model and system_prompt found by read_agent().

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
            **kwargs: Additional arguments for MongoClient (ignored if client is provided)
        """
        self.application_name = application_name
        if client is not None:
            # Use provided client
            self.client: MongoClient = client
            self._owns_client = False  # Don't close a client we didn't create
            logger.info("Using provided MongoDB client")
        else:
            # Create new client (legacy behavior)
            if connection_string is None:
                raise ValueError("Connection string is required")
            self.client = MongoClient(connection_string, **kwargs)
            self._owns_client = True  # We created it, we should close it
            logger.info("Created new MongoDB client")

        self.database: Database = self.client[database_name]
        self.collection: Collection = self.database[collection_name]
        self.metadata_fields = metadata_fields
        # model and system_prompt found by read_agent(), keyed by
        # (session_id, agent_id), until pop_read_agent_config() hands them over.
        self._read_agent_configs: dict[tuple[str, str], dict[str, Any]] = {}
        # Create indexes for timestamp ordering (only once per collection)
        self._ensure_indexes()

        logger.info(
            f"Initialized MongoDB session repository - "
            f"Database: {database_name}, Collection: {collection_name}"
        )

    def _ensure_indexes(self) -> None:
        """Ensure necessary indexes exist on the collection.

        Idempotent per client: the indexes are only sent to the server the first
        time this collection is seen through a given MongoClient. See
        _INDEX_REGISTRY for why.
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

        try:
            # Index on session timestamps
            self.collection.create_index("created_at")
            self.collection.create_index("updated_at")
            # Index on session_id for efficient searches in Session Viewer
            self.collection.create_index("session_id")
            # Note: MongoDB doesn't support positional operators ($) in index definitions
            # Messages are nested arrays, so we rely on the _id index for document lookup
            if self.metadata_fields:
                for field in self.metadata_fields:
                    self.collection.create_index("metadata." + field)
            # Index on application_name for filtering sessions by application
            self.collection.create_index("application_name")

            logger.info("MongoDB indexes created successfully")
        except PyMongoError as e:
            # Not recorded in the registry: a later manager should retry.
            logger.warning(f"Failed to create indexes: {e}")
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
    def _agent_exists(doc: dict | None, agent_id: str) -> bool:
        """Check if an agent exists in a session document."""
        return bool(doc and "agents" in doc and agent_id in doc["agents"])

    @staticmethod
    def _filter_message_data(msg_data: dict) -> dict:
        """Filter out fields that SessionMessage.__init__() does not accept."""
        return {k: v for k, v in msg_data.items() if k not in _MESSAGE_EXCLUDED_FIELDS}

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
            "metadata": {},
            "feedbacks": [],
            "guardrail_events": [],
        }

        if self.metadata_fields:
            for field in self.metadata_fields:
                session_doc["metadata"][field] = ""

        try:
            self.collection.insert_one(session_doc)
            logger.info(f"Created session: {session.session_id} with viewer password")
        except PyMongoError as e:
            logger.error(f"Failed to create session {session.session_id}: {e}")
            raise

        return session

    def read_session(self, session_id: str, **kwargs: Any) -> Session | None:
        """Read a Session from MongoDB."""
        try:
            doc = self.collection.find_one({"_id": session_id})
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

    def create_agent(
        self, session_id: str, session_agent: SessionAgent, **kwargs: Any
    ) -> None:
        """Create a new Agent in a Session."""
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
                        f"agents.{session_agent.agent_id}": agent_doc,
                        "updated_at": now,
                    }
                },
            )

            if result.matched_count == 0:
                raise ValueError(f"Session {session_id} not found")

            logger.info(
                f"Created agent {session_agent.agent_id} in session {session_id}"
            )

        except PyMongoError as e:
            logger.error(f"Failed to create agent {session_agent.agent_id}: {e}")
            raise

    def read_agent(
        self, session_id: str, agent_id: str, **kwargs: Any
    ) -> SessionAgent | None:
        """Read an Agent from a Session.

        The model and system_prompt stored with the agent do not fit in a
        SessionAgent; they are kept for pop_read_agent_config() instead.
        """
        try:
            # Any narrower projection must keep agent_data.model and
            # agent_data.system_prompt: the session manager relies on them to
            # know which config is already persisted.
            doc = self.collection.find_one(
                {"_id": session_id}, {f"agents.{agent_id}": 1}
            )

            if not self._agent_exists(doc, agent_id):
                logger.debug(f"Agent {agent_id} not found in session {session_id}")
                return None

            agent_data = doc["agents"][agent_id]["agent_data"]

            filtered_agent_data = {
                k: v for k, v in agent_data.items() if k not in _AGENT_CONFIG_FIELDS
            }

            session_agent = SessionAgent(**filtered_agent_data)
            self._read_agent_configs[(session_id, agent_id)] = {
                "model": agent_data.get("model"),
                "system_prompt": agent_data.get("system_prompt"),
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

        read_agent() already fetches model and system_prompt but cannot return
        them inside a SessionAgent. Handing them over here lets the session
        manager skip rewriting a config that is already persisted, without
        reading the agent a second time.

        Returns:
            Dict with model and system_prompt, or None if read_agent() has not
            found this agent in this session since the last call.
        """
        return self._read_agent_configs.pop((session_id, agent_id), None)

    def update_agent(
        self, session_id: str, session_agent: SessionAgent, **kwargs: Any
    ) -> None:
        """Update an Agent in a Session.

        Each SessionAgent field is written on its own path. Setting agent_data
        as a whole would replace the subdocument and wipe model, system_prompt
        and prompt_metadata, which the session manager also stores there but
        SessionAgent does not carry. Every field is still replaced whole, so
        keys removed from the agent state do disappear.
        """
        now = datetime.now(UTC)
        agent_data = session_agent.__dict__.copy()
        agent_data["created_at"] = self._parse_iso_datetime(session_agent.created_at)
        agent_data["updated_at"] = self._parse_iso_datetime(session_agent.updated_at)

        agent_prefix = f"agents.{session_agent.agent_id}"
        set_operations = {
            f"{agent_prefix}.agent_data.{name}": value
            for name, value in agent_data.items()
        }
        set_operations[f"{agent_prefix}.updated_at"] = now
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

            logger.info(
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
        """Create a new Message for the Agent."""
        now = datetime.now(UTC)
        message_data = session_message.__dict__.copy()
        message_data["created_at"] = now
        message_data["updated_at"] = now

        try:
            result = self.collection.update_one(
                {"_id": session_id},
                {
                    "$push": {f"agents.{agent_id}.messages": message_data},
                    "$set": {
                        f"agents.{agent_id}.updated_at": now,
                        "updated_at": now,
                    },
                },
            )

            if result.matched_count == 0:
                raise ValueError(f"Session {session_id} not found")

            logger.info(
                f"Created message {session_message.message_id} for agent {agent_id}"
            )

        except PyMongoError as e:
            logger.error(f"Failed to create message: {e}")
            raise

    def read_message(
        self, session_id: str, agent_id: str, message_id: int, **kwargs: Any
    ) -> SessionMessage | None:
        """Read a Message from an Agent."""
        try:
            doc = self.collection.find_one(
                {"_id": session_id}, {f"agents.{agent_id}.messages": 1}
            )

            if not self._agent_exists(doc, agent_id):
                return None

            messages = doc["agents"][agent_id].get("messages", [])

            # Find message by ID
            for msg_data in messages:
                if msg_data.get("message_id") == message_id:
                    return SessionMessage(**self._filter_message_data(msg_data))

            logger.debug(f"Message {message_id} not found")
            return None

        except PyMongoError as e:
            logger.error(f"Failed to read message {message_id}: {e}")
            raise

    def update_message(
        self,
        session_id: str,
        agent_id: str,
        session_message: SessionMessage,
        **kwargs: Any,
    ) -> None:
        """Update a Message (usually for redaction)."""

        message_data = session_message.__dict__.copy()

        try:
            # First, get the current messages to find the index
            doc = self.collection.find_one(
                {"_id": session_id}, {f"agents.{agent_id}.messages": 1}
            )

            if not self._agent_exists(doc, agent_id):
                raise ValueError(f"Agent {agent_id} not found in session {session_id}")

            messages = doc["agents"][agent_id].get("messages", [])

            # Find the message index
            message_index = -1
            for i, msg in enumerate(messages):
                if msg.get("message_id") == session_message.message_id:
                    message_index = i
                    # Preserve created_at timestamp
                    message_data["created_at"] = msg.get(
                        "created_at", datetime.now(UTC)
                    )
                    message_data["updated_at"] = datetime.now(UTC)
                    break

            if message_index == -1:
                raise ValueError(f"Message {session_message.message_id} not found")

            # Update the specific message
            result = self.collection.update_one(
                {"_id": session_id},
                {
                    "$set": {
                        f"agents.{agent_id}.messages.{message_index}": message_data,
                        f"agents.{agent_id}.updated_at": datetime.now(UTC),
                        "updated_at": datetime.now(UTC),
                    }
                },
            )

            if result.matched_count == 0:
                raise ValueError(f"Session {session_id} not found")

            logger.info(
                f"Updated message {session_message.message_id} for agent {agent_id}"
            )

        except PyMongoError as e:
            logger.error(f"Failed to update message: {e}")
            raise

    def list_messages(
        self,
        session_id: str,
        agent_id: str,
        limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> list[SessionMessage]:
        """List Messages from an Agent with pagination support."""
        try:
            doc = self.collection.find_one(
                {"_id": session_id}, {f"agents.{agent_id}.messages": 1}
            )

            if not doc or not self._agent_exists(doc, agent_id):
                logger.debug(f"Agent {agent_id} not found in session {session_id}")
                return []

            messages = doc["agents"][agent_id].get("messages", [])

            # Sort messages by created_at (oldest first - chronological order)
            messages.sort(key=lambda x: x.get("created_at", ""), reverse=False)

            # Apply pagination
            if limit is not None:
                messages = messages[offset : offset + limit]
            else:
                messages = messages[offset:]

            # Convert to SessionMessage objects
            result = []
            for i, msg_data in enumerate(messages):
                try:
                    result.append(SessionMessage(**self._filter_message_data(msg_data)))
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
            logger.info("MongoDB connection closed")
        else:
            logger.info("Skipping close - using shared MongoDB client")

    # CUSTOM METHODS
    def update_metadata(self, session_id: str, metadata: dict[str, Any]) -> None:
        """Update the metadata for the session."""
        try:
            # Build $set operation with dot notation to preserve existing values
            set_operations = {
                f"metadata.{key}": value for key, value in metadata.items()
            }

            self.collection.update_one(
                {"_id": session_id},
                {"$set": set_operations},
            )
        except PyMongoError as e:
            logger.error(f"Failed to update metadata for session {session_id}: {e}")
            raise

    def get_metadata(self, session_id: str) -> dict[str, Any]:
        """Get the metadata for the session."""
        return self.collection.find_one({"_id": session_id}, {"metadata": 1})

    def delete_metadata(self, session_id: str, metadata_keys: list[str]) -> None:
        """Delete metadata keys for the session."""
        try:
            # Build $unset operation with dot notation
            unset_operations = {
                f"metadata.{metadata_key}": "" for metadata_key in metadata_keys
            }

            self.collection.update_one(
                {"_id": session_id},
                {"$unset": unset_operations},
            )
        except PyMongoError as e:
            logger.error(
                f"Failed to delete metadata keys {metadata_keys} for session {session_id}: {e}"
            )
            raise

    def add_feedback(self, session_id: str, feedback: dict[str, Any]) -> None:
        """Add feedback to the session."""
        try:
            now = datetime.now(UTC)
            feedback_doc = {**feedback, "created_at": now}

            self.collection.update_one(
                {"_id": session_id},
                {
                    "$push": {"feedbacks": feedback_doc},
                    "$set": {"updated_at": now},
                },
            )
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
