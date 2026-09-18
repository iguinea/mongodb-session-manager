"""In-memory session repository, to exercise the session manager without MongoDB.

This is a test double, not part of the published package. It exists so the
manager's tests can assert on *what ends up stored* instead of on which pymongo
command was emitted, which is what `.claude/rules/workflow-persistence.md` asks
for when it requires an in-memory implementation.

It deliberately mirrors the MongoDB document shape and reuses the shaping
helpers of `MongoDBSessionRepository`, so a test written against this double
reads the same as its integration counterpart.

Two behaviours are reproduced *on purpose*, warts included -- a double that is
kinder than the real thing lies:

- A message is located by the identity it carries; a message stored before #78
  has none, and falls back to `message_id`, where a duplicate matches only its
  first occurrence.
- `update_agent()` writes field by field, so it does not wipe the config the
  manager keeps under `agent_data` (see issue #65), and skips an agent whose
  content is what it last read or wrote, with the same rule (#67).

Names MongoDB would read as syntax -- an `agent_id` with a dot, a segment
starting with `$`, an empty one -- are rejected here exactly as there, with the
same rule and at the same point, before anything is looked up (#79).

Known divergence: `_set_dotted()` only walks documents. On MongoDB `tags.0`
over an existing array writes its first element; here it replaces the array
with `{"0": ...}`. No test relies on it.

It has no `collection` attribute, and that is the point: any manager code that
reaches for the raw pymongo collection fails loudly against this double.
"""

from __future__ import annotations

import copy
import secrets
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from strands.session.session_repository import SessionRepository
from strands.types.session import Session, SessionAgent, SessionMessage

from mongodb_session_manager.agent_content import LastPersistedAgents
from mongodb_session_manager.field_names import (
    apply_fields,
    nested_document,
    validate_agent_id,
    validate_field_paths,
)
from mongodb_session_manager.message_identity import (
    STORAGE_ID_FIELD,
    MessageRef,
    attach_storage_id,
    new_storage_id,
    ref_of,
)
from mongodb_session_manager.mongodb_session_repository import (
    MongoDBSessionRepository,
)


def _set_dotted(document: dict[str, Any], path: str, value: Any) -> None:
    """Apply one dotted $set path, creating intermediate documents like MongoDB.

    Replacing only the leaf is what keeps a write on
    `event_loop_metrics.accumulated_usage` from wiping its sibling
    `event_loop_metrics.cycle_metrics`.
    """
    keys = path.split(".")
    target = document
    for key in keys[:-1]:
        child = target.get(key)
        if not isinstance(child, dict):
            child = {}
            target[key] = child
        target = child
    target[keys[-1]] = value


def _unset_dotted(document: dict[str, Any], path: str) -> None:
    """Apply one dotted $unset path, removing only the leaf.

    The mirror of _set_dotted: `metadata.user.name` has to reach the same key
    a write on that path created, not a flat key that spells it with dots.
    """
    keys = path.split(".")
    target = document
    for key in keys[:-1]:
        child = target.get(key)
        if not isinstance(child, dict):
            return
        target = child
    target.pop(keys[-1], None)


class InMemorySessionRepository(SessionRepository):
    """SessionRepository backed by a dict. Single-threaded, for unit tests."""

    def __init__(
        self,
        application_name: str | None = None,
        metadata_fields: list[str] | None = None,
    ) -> None:
        """Start with no sessions stored."""
        self.application_name = application_name
        self.metadata_fields = metadata_fields
        # Same rule and same moment as the MongoDB repository: an unusable
        # configuration raises here, before anything is stored.
        self._metadata_seed = nested_document(metadata_fields or ())
        self._sessions: dict[str, dict[str, Any]] = {}
        self._last_read_agent_config: dict[tuple[str, str], dict[str, Any]] = {}
        self._persisted_agents = LastPersistedAgents()

    # -- Test helpers ------------------------------------------------------

    def session(self, session_id: str) -> dict[str, Any]:
        """Return a copy of a stored session document, for assertions."""
        return copy.deepcopy(self._sessions[session_id])

    def message(
        self, session_id: str, agent_id: str, message_id: int
    ) -> dict[str, Any]:
        """Return a copy of one stored message document, for assertions."""
        for msg in self._sessions[session_id]["agents"][agent_id]["messages"]:
            if msg["message_id"] == message_id:
                return copy.deepcopy(msg)
        raise KeyError(f"Message {message_id} not found in agent {agent_id}")

    def push_raw_message(
        self, session_id: str, agent_id: str, message_data: dict[str, Any]
    ) -> None:
        """Append a message document as stored, bypassing create_message().

        The counterpart of a hand-written `$push` against MongoDB. Used to place
        a message that create_message() would never produce -- one without a
        storage_id, as everything written before #78 is.
        """
        self._sessions[session_id]["agents"][agent_id]["messages"].append(
            copy.deepcopy(message_data)
        )

    # -- Internals ---------------------------------------------------------

    def _agent(self, session_id: str, agent_id: str) -> dict[str, Any] | None:
        """Return the live agent subdocument, or None if session or agent is gone.

        Every agent-scoped read goes through here, so this is where the agent_id
        is checked for them -- before the session is even looked up.
        """
        validate_agent_id(agent_id)
        session = self._sessions.get(session_id)
        if not session or agent_id not in session["agents"]:
            return None
        return session["agents"][agent_id]

    def _find_message(
        self, session_id: str, agent_id: str, ref: MessageRef
    ) -> dict[str, Any] | None:
        """Return the message a reference names, mirroring the positional operator.

        Which field names the message is MessageRef's rule, the same one the
        real repository asks; the first match wins, exactly like MongoDB's `$`.
        """
        agent = self._agent(session_id, agent_id)
        if agent is None:
            return None

        field, value = ref.locator()
        return next(
            (msg for msg in agent.get("messages", []) if msg.get(field) == value),
            None,
        )

    # -- Session -----------------------------------------------------------

    def create_session(self, session: Session, **kwargs: Any) -> Session:
        """Create a new session document."""
        now = datetime.now(UTC)
        self._sessions[session.session_id] = {
            "_id": session.session_id,
            "session_id": session.session_id,
            "application_name": self.application_name,
            "session_type": session.session_type,
            "session_viewer_password": secrets.token_urlsafe(24),
            "created_at": now,
            "updated_at": now,
            "agents": {},
            "metadata": copy.deepcopy(self._metadata_seed),
            "feedbacks": [],
            "guardrail_events": [],
        }
        return session

    def read_session(self, session_id: str, **kwargs: Any) -> Session | None:
        """Read a session."""
        doc = self._sessions.get(session_id)
        if not doc:
            return None
        return Session(
            session_id=doc["session_id"],
            session_type=doc.get("session_type", "default"),
            created_at=doc.get("created_at"),
            updated_at=doc.get("updated_at"),
        )

    # -- Agent -------------------------------------------------------------

    def create_agent(
        self, session_id: str, session_agent: SessionAgent, **kwargs: Any
    ) -> None:
        """Create an agent inside a session."""
        validate_agent_id(session_agent.agent_id)
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")

        now = datetime.now(UTC)
        agent_data = session_agent.__dict__.copy()
        agent_data["created_at"] = MongoDBSessionRepository._parse_iso_datetime(
            session_agent.created_at
        )
        agent_data["updated_at"] = MongoDBSessionRepository._parse_iso_datetime(
            session_agent.updated_at
        )

        session["agents"][session_agent.agent_id] = {
            "agent_data": agent_data,
            "messages": [],
            "created_at": now,
            "updated_at": now,
        }
        session["updated_at"] = now
        self._persisted_agents.remember(session_id, session_agent)

    def read_agent(
        self, session_id: str, agent_id: str, **kwargs: Any
    ) -> SessionAgent | None:
        """Read an agent, remembering its stored config for the manager."""
        agent = self._agent(session_id, agent_id)
        if agent is None:
            self._persisted_agents.forget(session_id, agent_id)
            return None

        agent_data = agent["agent_data"]
        session_agent = SessionAgent(
            **copy.deepcopy(MongoDBSessionRepository._filter_agent_data(agent_data))
        )
        self._persisted_agents.remember(session_id, session_agent)
        self._last_read_agent_config = {
            (session_id, agent_id): {
                "model": agent_data.get("model"),
                "system_prompt": agent_data.get("system_prompt"),
            }
        }
        return session_agent

    def pop_read_agent_config(
        self, session_id: str, agent_id: str
    ) -> dict[str, Any] | None:
        """Return, and forget, the agent config found by read_agent()."""
        return self._last_read_agent_config.pop((session_id, agent_id), None)

    def update_agent(
        self, session_id: str, session_agent: SessionAgent, **kwargs: Any
    ) -> None:
        """Update an agent field by field, preserving the manager's config.

        Skipped, like on MongoDB, when the content is what was last read or
        written: after the agent_id check, before the session is looked up.
        """
        validate_agent_id(session_agent.agent_id)
        if self._persisted_agents.unchanged(session_id, session_agent):
            return

        agent = self._agent(session_id, session_agent.agent_id)
        if agent is None:
            raise ValueError(f"Session {session_id} not found")

        now = datetime.now(UTC)
        agent_data = session_agent.__dict__.copy()
        agent_data["created_at"] = MongoDBSessionRepository._parse_iso_datetime(
            session_agent.created_at
        )
        agent_data["updated_at"] = MongoDBSessionRepository._parse_iso_datetime(
            session_agent.updated_at
        )

        # Field by field: setting agent_data whole would wipe model,
        # system_prompt and prompt_metadata. See #65.
        for name, value in agent_data.items():
            agent["agent_data"][name] = copy.deepcopy(value)
        agent["updated_at"] = now
        self._sessions[session_id]["updated_at"] = now
        self._persisted_agents.remember(session_id, session_agent)

    # -- Message -----------------------------------------------------------

    def create_message(
        self,
        session_id: str,
        agent_id: str,
        session_message: SessionMessage,
        **kwargs: Any,
    ) -> None:
        """Append a message to an agent, stamping its stable identity."""
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
        """Append messages in order, in what MongoDB does with one `$push`."""
        validate_agent_id(agent_id)
        validate_field_paths(agent_set_operations or {}, "agent field")
        validate_field_paths(fields_on_last or {}, "message field")

        if not session_messages:
            return

        agent = self._agent(session_id, agent_id)
        if agent is None:
            raise ValueError(f"Session {session_id} not found")

        now = datetime.now(UTC)
        documents = []
        for session_message in session_messages:
            storage_id = new_storage_id()
            message_data = copy.deepcopy(session_message.__dict__)
            message_data[STORAGE_ID_FIELD] = storage_id
            message_data["created_at"] = now
            message_data["updated_at"] = now
            documents.append((message_data, session_message, storage_id))

        apply_fields(documents[-1][0], fields_on_last or {}, "message field")

        for message_data, session_message, storage_id in documents:
            agent["messages"].append(message_data)
            attach_storage_id(session_message, storage_id)

        for name, value in (agent_set_operations or {}).items():
            _set_dotted(agent, name, copy.deepcopy(value))

        agent["updated_at"] = now
        self._sessions[session_id]["updated_at"] = now

    def read_message(
        self, session_id: str, agent_id: str, message_id: int, **kwargs: Any
    ) -> SessionMessage | None:
        """Read one message."""
        msg = self._find_message(session_id, agent_id, MessageRef(message_id))
        if msg is None:
            return None
        return MongoDBSessionRepository._to_session_message(copy.deepcopy(msg))

    def update_message(
        self,
        session_id: str,
        agent_id: str,
        session_message: SessionMessage,
        **kwargs: Any,
    ) -> None:
        """Update a message, writing only the allowlisted fields."""
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
            if session_id not in self._sessions:
                raise ValueError(f"Session {session_id} not found")
            if self._agent(session_id, agent_id) is None:
                raise ValueError(f"Agent {agent_id} not found in session {session_id}")
            raise ValueError(
                MongoDBSessionRepository._missing_message_text(
                    session_id, agent_id, ref
                )
            )

    def list_messages(
        self,
        session_id: str,
        agent_id: str,
        limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> list[SessionMessage]:
        """List an agent's messages, oldest first, with pagination."""
        agent = self._agent(session_id, agent_id)
        if offset < 0:
            raise ValueError("offset must be greater than or equal to 0")
        if limit is not None and limit < 0:
            raise ValueError("limit must be greater than or equal to 0")
        if limit == 0:
            return []
        if agent is None:
            return []

        # Sort and paginate over references, then copy only the page: a deepcopy
        # of the whole history to return N messages is work nobody asked for.
        messages = sorted(
            agent.get("messages", []),
            key=lambda x: (x.get("created_at") is None, x.get("created_at") or 0),
        )
        page = (
            messages[offset : offset + limit]
            if limit is not None
            else messages[offset:]
        )
        return [
            MongoDBSessionRepository._to_session_message(copy.deepcopy(msg))
            for msg in page
        ]

    # -- Write primitives --------------------------------------------------

    def _update_message_document(
        self,
        session_id: str,
        agent_id: str,
        ref: MessageRef,
        message_fields: dict[str, Any],
        *,
        agent_fields: dict[str, Any] | None = None,
        push: dict[str, Any] | None = None,
        touch_timestamps: bool = False,
    ) -> bool:
        """Mirror of the repository's positional primitive, over a dict."""
        validate_agent_id(agent_id)
        validate_field_paths(message_fields, "message field")
        validate_field_paths(agent_fields or (), "agent field")
        if not message_fields and not agent_fields and not push:
            return False

        msg = self._find_message(session_id, agent_id, ref)
        if msg is None:
            return False
        # _find_message already proved both exist.
        agent = self._sessions[session_id]["agents"][agent_id]

        for path, value in message_fields.items():
            _set_dotted(msg, path, copy.deepcopy(value))
        for path, value in (agent_fields or {}).items():
            _set_dotted(agent, path, copy.deepcopy(value))
        for array, entry in (push or {}).items():
            self._sessions[session_id][array].append(copy.deepcopy(entry))

        if touch_timestamps:
            now = datetime.now(UTC)
            msg["updated_at"] = now
            agent["updated_at"] = now
            self._sessions[session_id]["updated_at"] = now

        return True

    def update_message_fields(
        self,
        session_id: str,
        agent_id: str,
        ref: MessageRef,
        set_operations: dict[str, Any],
        agent_set_operations: dict[str, Any] | None = None,
    ) -> bool:
        """Write fields on one message, and optionally on its agent, in one go."""
        return self._update_message_document(
            session_id,
            agent_id,
            ref,
            set_operations,
            agent_fields=agent_set_operations,
        )

    def update_agent_fields(
        self, session_id: str, agent_id: str, set_operations: dict[str, Any]
    ) -> bool:
        """Write fields under an agent without touching its messages."""
        validate_agent_id(agent_id)
        validate_field_paths(set_operations, "agent field")
        if not set_operations:
            return False

        session = self._sessions.get(session_id)
        if session is None:
            return False
        if agent_id not in session["agents"]:
            return False

        # Readers still tolerate half-built agents left by the old bug and
        # seeded through raw access, but this write never creates one (#119).
        agent = session["agents"][agent_id]
        for path, value in set_operations.items():
            _set_dotted(agent, path, copy.deepcopy(value))
        return True

    def record_guardrail_event(
        self, session_id: str, agent_id: str, ref: MessageRef, event: dict[str, Any]
    ) -> bool:
        """Record a guardrail intervention on its message and on the session."""
        return self._update_message_document(
            session_id,
            agent_id,
            ref,
            {"guardrail_event": event},
            push={
                "guardrail_events": MongoDBSessionRepository._session_guardrail_entry(
                    agent_id, ref, event
                )
            },
        )

    # -- Domain reads ------------------------------------------------------

    def get_agent_config(self, session_id: str, agent_id: str) -> dict[str, Any] | None:
        """Read the stored configuration of one agent."""
        agent = self._agent(session_id, agent_id)
        if agent is None:
            return None
        return MongoDBSessionRepository._agent_config(
            agent_id, copy.deepcopy(agent.get("agent_data", {}))
        )

    def list_agent_configs(self, session_id: str) -> list[dict[str, Any]]:
        """List the stored configuration of every agent in the session."""
        session = self._sessions.get(session_id)
        if not session:
            return []
        return [
            MongoDBSessionRepository._agent_config(
                agent_id, copy.deepcopy(agent.get("agent_data", {}))
            )
            for agent_id, agent in session["agents"].items()
        ]

    def count_messages(self, session_id: str, agent_id: str) -> int:
        """Count the messages stored for one agent."""
        agent = self._agent(session_id, agent_id)
        return len(agent.get("messages", [])) if agent else 0

    def get_last_message_ref(self, session_id: str, agent_id: str) -> MessageRef | None:
        """Reference the agent's last message, identity included."""
        agent = self._agent(session_id, agent_id)
        messages = agent.get("messages", []) if agent else []
        if not messages:
            return None
        return MessageRef.from_document(messages[-1])

    # -- Metadata, feedback, lifecycle -------------------------------------

    def update_metadata(self, session_id: str, metadata: dict[str, Any]) -> None:
        """Merge keys into the session metadata, all of them checked first."""
        validate_field_paths(metadata, "metadata key")
        session = self._sessions.get(session_id)
        if session is None:
            return
        for key, value in metadata.items():
            _set_dotted(session["metadata"], key, copy.deepcopy(value))

    def get_metadata(self, session_id: str) -> dict[str, Any] | None:
        """Return the session document projected on its metadata."""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return {"_id": session_id, "metadata": copy.deepcopy(session["metadata"])}

    def delete_metadata(self, session_id: str, metadata_keys: list[str]) -> None:
        """Remove keys from the session metadata, all of them checked first."""
        validate_field_paths(metadata_keys, "metadata key")
        session = self._sessions.get(session_id)
        if session is None:
            return
        for key in metadata_keys:
            _unset_dotted(session["metadata"], key)

    def add_feedback(self, session_id: str, feedback: dict[str, Any]) -> None:
        """Append feedback to the session."""
        session = self._sessions.get(session_id)
        if session is None:
            return
        now = datetime.now(UTC)
        session["feedbacks"].append({**copy.deepcopy(feedback), "created_at": now})
        session["updated_at"] = now

    def get_feedbacks(self, session_id: str) -> list[dict[str, Any]]:
        """Return every feedback stored for the session."""
        session = self._sessions.get(session_id)
        return copy.deepcopy(session["feedbacks"]) if session else []

    def get_session_viewer_password(self, session_id: str) -> str | None:
        """Return the session viewer password."""
        session = self._sessions.get(session_id)
        return session.get("session_viewer_password") if session else None

    def get_application_name(self, session_id: str) -> str | None:
        """Return the immutable application name of the session."""
        session = self._sessions.get(session_id)
        return session.get("application_name") if session else None

    def close(self) -> None:
        """No connection to close."""
