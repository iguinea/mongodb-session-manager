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

- The positional update matches only the first message carrying a given
  message_id (see issue #78).
- `update_agent()` writes field by field, so it does not wipe the config the
  manager keeps under `agent_data` (see issue #65).

Known divergence: MongoDB's dot-notation paths break when an `agent_id`
contains `.` or `$` (issue #79). This double resolves those paths its own way,
so it is not evidence about that case either way.

It has no `collection` attribute, and that is the point: any manager code that
reaches for the raw pymongo collection fails loudly against this double.
"""

from __future__ import annotations

import copy
import secrets
from datetime import UTC, datetime
from typing import Any

from strands.session.session_repository import SessionRepository
from strands.types.session import Session, SessionAgent, SessionMessage

from mongodb_session_manager.mongodb_session_repository import (
    _AGENT_CONFIG_FIELDS,
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


class InMemorySessionRepository(SessionRepository):
    """SessionRepository backed by a dict. Single-threaded, for unit tests."""

    def __init__(self, application_name: str | None = None) -> None:
        """Start with no sessions stored."""
        self.application_name = application_name
        self._sessions: dict[str, dict[str, Any]] = {}
        self._last_read_agent_config: dict[tuple[str, str], dict[str, Any]] = {}

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

    # -- Internals ---------------------------------------------------------

    def _agent(self, session_id: str, agent_id: str) -> dict[str, Any] | None:
        """Return the live agent subdocument, or None if session or agent is gone."""
        session = self._sessions.get(session_id)
        if not session or agent_id not in session["agents"]:
            return None
        return session["agents"][agent_id]

    def _find_message(
        self, session_id: str, agent_id: str, message_id: int
    ) -> dict[str, Any] | None:
        """Return the first message with this id, mirroring the positional operator."""
        agent = self._agent(session_id, agent_id)
        if agent is None:
            return None
        # First match only, exactly like MongoDB's `$`. See #78.
        for msg in agent["messages"]:
            if msg.get("message_id") == message_id:
                return msg
        return None

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
            "metadata": {},
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

    def read_agent(
        self, session_id: str, agent_id: str, **kwargs: Any
    ) -> SessionAgent | None:
        """Read an agent, remembering its stored config for the manager."""
        agent = self._agent(session_id, agent_id)
        if agent is None:
            return None

        agent_data = agent["agent_data"]
        filtered = {
            k: v for k, v in agent_data.items() if k not in _AGENT_CONFIG_FIELDS
        }
        session_agent = SessionAgent(**copy.deepcopy(filtered))
        self._last_read_agent_config = {
            (session_id, agent_id): {
                "model": agent_data.get("model"),
                "system_prompt": agent_data.get("system_prompt"),
            }
        }
        return session_agent

    def _pop_read_agent_config(
        self, session_id: str, agent_id: str
    ) -> dict[str, Any] | None:
        """Return, and forget, the agent config found by read_agent()."""
        return self._last_read_agent_config.pop((session_id, agent_id), None)

    def update_agent(
        self, session_id: str, session_agent: SessionAgent, **kwargs: Any
    ) -> None:
        """Update an agent field by field, preserving the manager's config."""
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

    # -- Message -----------------------------------------------------------

    def create_message(
        self,
        session_id: str,
        agent_id: str,
        session_message: SessionMessage,
        **kwargs: Any,
    ) -> None:
        """Append a message to an agent."""
        agent = self._agent(session_id, agent_id)
        if agent is None:
            raise ValueError(f"Session {session_id} not found")

        now = datetime.now(UTC)
        message_data = copy.deepcopy(session_message.__dict__)
        message_data["created_at"] = now
        message_data["updated_at"] = now

        agent["messages"].append(message_data)
        agent["updated_at"] = now
        self._sessions[session_id]["updated_at"] = now

    def read_message(
        self, session_id: str, agent_id: str, message_id: int, **kwargs: Any
    ) -> SessionMessage | None:
        """Read one message."""
        msg = self._find_message(session_id, agent_id, message_id)
        if msg is None:
            return None
        return SessionMessage(
            **MongoDBSessionRepository._filter_message_data(copy.deepcopy(msg))
        )

    def update_message(
        self,
        session_id: str,
        agent_id: str,
        session_message: SessionMessage,
        **kwargs: Any,
    ) -> None:
        """Update a message, writing only the allowlisted fields."""
        matched = self.update_message_fields(
            session_id,
            agent_id,
            session_message.message_id,
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
                f"Message {session_message.message_id} not found in agent {agent_id} "
                f"of session {session_id}"
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
        if agent is None:
            return []

        messages = copy.deepcopy(agent["messages"])
        messages.sort(
            key=lambda x: (x.get("created_at") is None, x.get("created_at") or 0)
        )
        messages = (
            messages[offset : offset + limit]
            if limit is not None
            else messages[offset:]
        )
        return [
            SessionMessage(**MongoDBSessionRepository._filter_message_data(msg))
            for msg in messages
        ]

    # -- Write primitives --------------------------------------------------

    def update_message_fields(
        self,
        session_id: str,
        agent_id: str,
        message_id: int,
        set_operations: dict[str, Any],
        agent_set_operations: dict[str, Any] | None = None,
        touch_timestamps: bool = False,
    ) -> bool:
        """Write fields on one message, and optionally on its agent, in one go."""
        if not set_operations and not agent_set_operations and not touch_timestamps:
            return False

        agent = self._agent(session_id, agent_id)
        if agent is None:
            return False

        msg = self._find_message(session_id, agent_id, message_id)
        if msg is None:
            return False

        for path, value in set_operations.items():
            _set_dotted(msg, path, copy.deepcopy(value))
        if agent_set_operations:
            for path, value in agent_set_operations.items():
                _set_dotted(agent, path, copy.deepcopy(value))

        if touch_timestamps:
            now = datetime.now(UTC)
            msg["updated_at"] = now
            agent["updated_at"] = now
            self._sessions[session_id]["updated_at"] = now

        return True

    def update_agent_fields(
        self, session_id: str, agent_id: str, set_operations: dict[str, Any]
    ) -> bool:
        """Write fields under an agent without touching its messages."""
        if not set_operations:
            return False

        session = self._sessions.get(session_id)
        if session is None:
            return False

        agent = session["agents"].setdefault(agent_id, {})
        for path, value in set_operations.items():
            _set_dotted(agent, path, copy.deepcopy(value))
        return True

    def record_guardrail_event(
        self, session_id: str, agent_id: str, message_id: int, event: dict[str, Any]
    ) -> bool:
        """Record a guardrail intervention on its message and on the session."""
        session_event: dict[str, Any] = {
            "message_id": message_id,
            "agent_id": agent_id,
            **{name: value for name, value in event.items() if name != "trace"},
        }

        matched = self.update_message_fields(
            session_id, agent_id, message_id, {"guardrail_event": dict(event)}
        )
        if matched:
            self._sessions[session_id]["guardrail_events"].append(
                copy.deepcopy(session_event)
            )
        return matched

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
        return len(agent["messages"]) if agent else 0

    def get_last_message_id(self, session_id: str, agent_id: str) -> int | None:
        """Read the message_id of the agent's last message."""
        agent = self._agent(session_id, agent_id)
        if agent is None or not agent["messages"]:
            return None
        return agent["messages"][-1]["message_id"]

    # -- Metadata, feedback, lifecycle -------------------------------------

    def update_metadata(self, session_id: str, metadata: dict[str, Any]) -> None:
        """Merge keys into the session metadata."""
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
        """Remove keys from the session metadata."""
        session = self._sessions.get(session_id)
        if session is None:
            return
        for key in metadata_keys:
            session["metadata"].pop(key, None)

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
