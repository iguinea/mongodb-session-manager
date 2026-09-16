"""Cases every session repository implementation must satisfy.

Subclassed twice: once against `InMemorySessionRepository` (unit, fast) and
once against `MongoDBSessionRepository` on a real MongoDB (integration). Both
subclasses run the very same assertions, which is the only thing that actually
proves the in-memory double does not lie about the behaviour the session
manager depends on.

Adding a method to the repository means adding its cases here, so neither
implementation can drift without a red test on the other side.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from strands.types.session import Session, SessionAgent, SessionMessage, SessionType


class SessionRepositoryContract:
    """Shared behaviour of the repository, independent of where it stores."""

    @pytest.fixture
    def store(self) -> Any:
        """Provide a repository under test. Overridden by each subclass."""
        raise NotImplementedError

    @pytest.fixture
    def session_id(self) -> str:
        """Identify the session used by a case. Overridden for integration."""
        return "contract-session"

    @pytest.fixture
    def populated(self, store, session_id):
        """Create a session with one agent and two messages."""
        store.create_session(
            Session(session_id=session_id, session_type=SessionType.AGENT)
        )
        store.create_agent(
            session_id,
            SessionAgent(agent_id="a1", state={}, conversation_manager_state={}),
        )
        for index in range(2):
            store.create_message(
                session_id,
                "a1",
                SessionMessage(
                    message_id=index,
                    message={"role": "user", "content": [{"text": f"m{index}"}]},
                ),
            )
        return session_id

    # -- update_message_fields --------------------------------------------

    def test_writes_a_field_on_the_message(self, store, populated):
        store.update_message_fields(populated, "a1", 1, {"guardrail_event": {"a": 1}})

        assert store.read_message(populated, "a1", 1) is not None
        stored = self._raw_message(store, populated, 1)
        assert stored["guardrail_event"] == {"a": 1}

    def test_a_dotted_write_keeps_its_siblings(self, store, populated):
        """Writing a.b must not wipe a.c -- that was the bug behind #64."""
        store.update_message_fields(
            populated, "a1", 1, {"event_loop_metrics.accumulated_usage": {"t": 1}}
        )
        store.update_message_fields(
            populated, "a1", 1, {"event_loop_metrics.cycle_metrics": {"c": 2}}
        )

        metrics = self._raw_message(store, populated, 1)["event_loop_metrics"]
        assert metrics["accumulated_usage"] == {"t": 1}
        assert metrics["cycle_metrics"] == {"c": 2}

    def test_does_not_touch_the_other_messages(self, store, populated):
        store.update_message_fields(populated, "a1", 1, {"guardrail_event": {"a": 1}})

        assert "guardrail_event" not in self._raw_message(store, populated, 0)

    def test_agent_fields_land_on_the_agent(self, store, populated):
        store.update_message_fields(
            populated,
            "a1",
            1,
            {"event_loop_metrics.cycle_metrics": {"c": 1}},
            agent_set_operations={"agent_data.model": "claude-opus-5"},
        )

        assert store.get_agent_config(populated, "a1")["model"] == "claude-opus-5"

    def test_returns_false_for_an_unknown_message(self, store, populated):
        assert store.update_message_fields(populated, "a1", 99, {"x": 1}) is False

    def test_matches_only_the_first_duplicate(self, store, populated):
        """message_id is not unique: Strands derives it in memory. See #78.

        Documents today's behaviour so that fixing #78 has to update this case
        deliberately, in both implementations at once.
        """
        store.create_message(
            populated,
            "a1",
            SessionMessage(
                message_id=1, message={"role": "user", "content": [{"text": "dup"}]}
            ),
        )

        store.update_message_fields(populated, "a1", 1, {"guardrail_event": {"n": 1}})

        duplicates = self._raw_messages_with_id(store, populated, 1)
        assert len(duplicates) == 2
        assert duplicates[0]["guardrail_event"] == {"n": 1}
        assert "guardrail_event" not in duplicates[1]

    # -- update_agent_fields ----------------------------------------------

    def test_update_agent_fields_writes_under_the_agent(self, store, populated):
        store.update_agent_fields(populated, "a1", {"agent_data.system_prompt": "hey"})

        assert store.get_agent_config(populated, "a1")["system_prompt"] == "hey"

    def test_update_agent_fields_returns_false_without_session(self, store):
        assert (
            store.update_agent_fields("nope", "a1", {"agent_data.model": "m"}) is False
        )

    # -- record_guardrail_event -------------------------------------------

    def test_guardrail_event_lands_on_message_and_session(self, store, populated):
        event = {
            "action": "BLOCKED",
            "timestamp": datetime.now(UTC),
            "policies_triggered": {"contentPolicy": ["HATE/HIGH"]},
            "trace": {"inputAssessment": {"big": "payload"}},
        }

        assert store.record_guardrail_event(populated, "a1", 1, event) is True

        on_message = self._raw_message(store, populated, 1)["guardrail_event"]
        assert on_message["trace"] == {"inputAssessment": {"big": "payload"}}

        on_session = self._session_guardrail_events(store, populated)
        assert len(on_session) == 1
        assert on_session[0]["message_id"] == 1
        assert on_session[0]["agent_id"] == "a1"
        assert on_session[0]["policies_triggered"] == {"contentPolicy": ["HATE/HIGH"]}
        assert "trace" not in on_session[0]

    def test_guardrail_event_on_an_unknown_message_writes_nothing(
        self, store, populated
    ):
        event = {"action": "BLOCKED", "timestamp": datetime.now(UTC)}

        assert store.record_guardrail_event(populated, "a1", 99, event) is False
        assert self._session_guardrail_events(store, populated) == []

    # -- Domain reads ------------------------------------------------------

    def test_agent_config_carries_the_four_fields(self, store, populated):
        store.update_agent_fields(
            populated,
            "a1",
            {
                "agent_data.model": "m",
                "agent_data.system_prompt": "sp",
                "agent_data.prompt_metadata": {"prompt_id": "p1"},
            },
        )

        assert store.get_agent_config(populated, "a1") == {
            "agent_id": "a1",
            "model": "m",
            "system_prompt": "sp",
            "prompt_metadata": {"prompt_id": "p1"},
        }

    def test_agent_config_is_none_when_unknown(self, store, populated):
        assert store.get_agent_config(populated, "ghost") is None

    def test_list_agent_configs_has_one_entry_per_agent(self, store, populated):
        store.create_agent(
            populated,
            SessionAgent(agent_id="a2", state={}, conversation_manager_state={}),
        )

        configs = store.list_agent_configs(populated)

        assert {c["agent_id"] for c in configs} == {"a1", "a2"}

    def test_list_agent_configs_is_empty_without_session(self, store):
        assert store.list_agent_configs("nope") == []

    def test_count_messages(self, store, populated):
        assert store.count_messages(populated, "a1") == 2
        assert store.count_messages(populated, "ghost") == 0

    def test_get_last_message_id(self, store, populated):
        assert store.get_last_message_id(populated, "a1") == 1
        assert store.get_last_message_id(populated, "ghost") is None

    # -- Raw access, implemented by each subclass --------------------------

    def _raw_message(self, store, session_id: str, message_id: int) -> dict[str, Any]:
        """Return one stored message document, extension fields included."""
        raise NotImplementedError

    def _raw_messages_with_id(
        self, store, session_id: str, message_id: int
    ) -> list[dict[str, Any]]:
        """Return every stored message carrying this message_id, in order."""
        raise NotImplementedError

    def _session_guardrail_events(self, store, session_id: str) -> list[dict[str, Any]]:
        """Return the session-level guardrail event array."""
        raise NotImplementedError
