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

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from strands.types.session import Session, SessionAgent, SessionMessage, SessionType

from mongodb_session_manager.message_identity import MessageRef, ref_of, storage_id_of


def _agent(agent_id: str, state: dict[str, Any] | None = None) -> SessionAgent:
    return SessionAgent(
        agent_id=agent_id, state=state or {}, conversation_manager_state={}
    )


def _resynced(read: SessionAgent) -> SessionAgent:
    """Rebuild a read agent the way Strands' sync does: same dicts, fresh timestamps.

    The dicts are shared on purpose, as they are in the live Agent. The read
    SessionAgent itself cannot be passed back: its timestamps come out of the
    store as datetimes, and update_agent() expects the ISO strings Strands sends.
    """
    now = datetime.now(UTC).isoformat()
    return replace(read, created_at=now, updated_at=now)


def _message(message_id: int = 0) -> SessionMessage:
    return SessionMessage(
        message_id=message_id, message={"role": "user", "content": [{"text": "hi"}]}
    )


# Every repository call that turns an agent_id into a path, as
# (store, session_id, agent_id) -> call. The empty-write variants are there on
# purpose: both implementations return early when there is nothing to write, and
# the agent_id must be rejected before that early return, not after.
AGENT_SCOPED_CALLS = [
    pytest.param(
        lambda s, sid, aid: s.create_agent(sid, _agent(aid)), id="create_agent"
    ),
    pytest.param(lambda s, sid, aid: s.read_agent(sid, aid), id="read_agent"),
    pytest.param(
        lambda s, sid, aid: s.update_agent(sid, _agent(aid)), id="update_agent"
    ),
    pytest.param(
        lambda s, sid, aid: s.create_message(sid, aid, _message()), id="create_message"
    ),
    pytest.param(lambda s, sid, aid: s.read_message(sid, aid, 0), id="read_message"),
    pytest.param(
        lambda s, sid, aid: s.update_message(sid, aid, _message()), id="update_message"
    ),
    pytest.param(lambda s, sid, aid: s.list_messages(sid, aid), id="list_messages"),
    pytest.param(
        lambda s, sid, aid: s.update_message_fields(
            sid, aid, MessageRef(0), {"guardrail_event": {}}
        ),
        id="update_message_fields",
    ),
    pytest.param(
        lambda s, sid, aid: s.update_message_fields(sid, aid, MessageRef(0), {}),
        id="update_message_fields_empty",
    ),
    pytest.param(
        lambda s, sid, aid: s.record_guardrail_event(
            sid, aid, MessageRef(0), {"action": "BLOCKED"}
        ),
        id="record_guardrail_event",
    ),
    pytest.param(
        lambda s, sid, aid: s.update_agent_fields(sid, aid, {"agent_data.model": "m"}),
        id="update_agent_fields",
    ),
    pytest.param(
        lambda s, sid, aid: s.update_agent_fields(sid, aid, {}),
        id="update_agent_fields_empty",
    ),
    pytest.param(
        lambda s, sid, aid: s.get_agent_config(sid, aid), id="get_agent_config"
    ),
    pytest.param(lambda s, sid, aid: s.count_messages(sid, aid), id="count_messages"),
    pytest.param(
        lambda s, sid, aid: s.get_last_message_ref(sid, aid), id="get_last_message_ref"
    ),
]

# Every repository call that turns a metadata key into a path, as
# (store, session_id, key) -> call.
METADATA_CALLS = [
    pytest.param(
        lambda s, sid, key: s.update_metadata(sid, {key: "x"}), id="update_metadata"
    ),
    pytest.param(
        lambda s, sid, key: s.delete_metadata(sid, [key]), id="delete_metadata"
    ),
]


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
        store.create_agent(session_id, _agent("a1"))
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

    # -- Message identity --------------------------------------------------

    def test_create_message_stamps_a_storage_id(self, store, populated):
        """Every message is born with an identity that does not come from its index."""
        stored = [self._raw_message(store, populated, i) for i in range(2)]

        assert all(msg.get("storage_id") for msg in stored)
        assert stored[0]["storage_id"] != stored[1]["storage_id"]

    def test_create_message_hands_the_identity_back(self, store, populated):
        """The identity travels on the SessionMessage Strands keeps in memory.

        That is what lets the redaction and the turn metrics point at the very
        message this process appended, instead of at whatever shares its index.
        """
        message = SessionMessage(
            message_id=2, message={"role": "user", "content": [{"text": "m2"}]}
        )

        store.create_message(populated, "a1", message)

        assert (
            storage_id_of(message)
            == self._raw_message(store, populated, 2)["storage_id"]
        )

    def test_reading_a_message_carries_its_identity(self, store, populated):
        """A restored manager gets the identity back from storage."""
        listed = store.list_messages(populated, "a1")

        assert (
            storage_id_of(listed[1])
            == self._raw_message(store, populated, 1)["storage_id"]
        )
        assert storage_id_of(store.read_message(populated, "a1", 1)) == storage_id_of(
            listed[1]
        )

    # -- update_message_fields --------------------------------------------

    def test_writes_a_field_on_the_message(self, store, populated):
        store.update_message_fields(
            populated,
            "a1",
            self._ref(store, populated, 1),
            {"guardrail_event": {"a": 1}},
        )

        assert store.read_message(populated, "a1", 1) is not None
        stored = self._raw_message(store, populated, 1)
        assert stored["guardrail_event"] == {"a": 1}

    def test_a_dotted_write_keeps_its_siblings(self, store, populated):
        """Writing a.b must not wipe a.c -- that was the bug behind #64."""
        ref = self._ref(store, populated, 1)
        store.update_message_fields(
            populated, "a1", ref, {"event_loop_metrics.accumulated_usage": {"t": 1}}
        )
        store.update_message_fields(
            populated, "a1", ref, {"event_loop_metrics.cycle_metrics": {"c": 2}}
        )

        metrics = self._raw_message(store, populated, 1)["event_loop_metrics"]
        assert metrics["accumulated_usage"] == {"t": 1}
        assert metrics["cycle_metrics"] == {"c": 2}

    def test_does_not_touch_the_other_messages(self, store, populated):
        store.update_message_fields(
            populated,
            "a1",
            self._ref(store, populated, 1),
            {"guardrail_event": {"a": 1}},
        )

        assert "guardrail_event" not in self._raw_message(store, populated, 0)

    def test_agent_fields_land_on_the_agent(self, store, populated):
        store.update_message_fields(
            populated,
            "a1",
            self._ref(store, populated, 1),
            {"event_loop_metrics.cycle_metrics": {"c": 1}},
            agent_set_operations={"agent_data.model": "claude-opus-5"},
        )

        assert store.get_agent_config(populated, "a1")["model"] == "claude-opus-5"

    def test_returns_false_for_an_unknown_message(self, store, populated):
        assert (
            store.update_message_fields(populated, "a1", MessageRef(99), {"x": 1})
            is False
        )

    def test_returns_false_for_an_unknown_storage_id(self, store, populated):
        """An identity nobody stored matches nothing, whatever its index says."""
        ref = MessageRef(message_id=1, storage_id="0" * 32)

        assert store.update_message_fields(populated, "a1", ref, {"x": 1}) is False

    def test_targets_its_own_duplicate(self, store, populated):
        """message_id is not unique: Strands derives it in memory. See #78.

        Two managers restoring the same agent at once compute the same index, so
        the array can hold two messages numbered 1. Each write must land on the
        message its own identity names -- the second one here, not the first one
        the positional operator would otherwise match.
        """
        duplicate = SessionMessage(
            message_id=1, message={"role": "user", "content": [{"text": "dup"}]}
        )
        store.create_message(populated, "a1", duplicate)

        store.update_message_fields(
            populated,
            "a1",
            MessageRef(message_id=1, storage_id=storage_id_of(duplicate)),
            {"guardrail_event": {"n": 1}},
        )

        duplicates = self._raw_messages_with_id(store, populated, 1)
        assert len(duplicates) == 2
        assert "guardrail_event" not in duplicates[0]
        assert duplicates[1]["guardrail_event"] == {"n": 1}

    def test_falls_back_to_message_id_without_a_storage_id(self, store, populated):
        """Messages stored before #78 have no identity, and stay updatable.

        They are located by message_id exactly as they always were, which is why
        this change needs no migration.
        """
        self._push_legacy_message(store, populated, 2)

        assert (
            store.update_message_fields(
                populated, "a1", MessageRef(2), {"guardrail_event": {"old": True}}
            )
            is True
        )
        assert self._raw_message(store, populated, 2)["guardrail_event"] == {
            "old": True
        }

    # -- update_agent_fields ----------------------------------------------

    def test_update_agent_fields_writes_under_the_agent(self, store, populated):
        store.update_agent_fields(populated, "a1", {"agent_data.system_prompt": "hey"})

        assert store.get_agent_config(populated, "a1")["system_prompt"] == "hey"

    def test_update_agent_fields_returns_false_without_session(self, store):
        assert (
            store.update_agent_fields("nope", "a1", {"agent_data.model": "m"}) is False
        )

    def test_update_agent_fields_creates_a_bare_agent(self, store, populated):
        """Writing on an unknown agent builds it without a messages array.

        That is what MongoDB's $set on `agents.<id>.<field>` leaves behind, so
        every reader has to cope with a half-built agent. The double must not
        be kinder than the real thing here either -- it is the anti-drift net.
        """
        assert (
            store.update_agent_fields(populated, "ghost", {"agent_data.model": "m"})
            is True
        )

        assert store.get_agent_config(populated, "ghost")["model"] == "m"
        assert store.count_messages(populated, "ghost") == 0
        assert store.get_last_message_ref(populated, "ghost") is None
        assert store.list_messages(populated, "ghost") == []
        assert (
            store.update_message_fields(populated, "ghost", MessageRef(0), {"x": 1})
            is False
        )

    # -- update_agent: an unchanged agent is not rewritten (#67) -----------

    def test_update_agent_with_the_created_content_writes_nothing(
        self, store, populated
    ):
        """The first sync of a new agent carries what create_agent() stored.

        Nothing moves, updated_at included: a skipped write is not a write.
        """
        before = self._raw_session(store, populated)

        store.update_agent(populated, _agent("a1"))

        assert self._raw_session(store, populated) == before

    def test_update_agent_with_the_read_content_writes_nothing(self, store, populated):
        """The first sync of a restored agent carries what read_agent() returned."""
        read = store.read_agent(populated, "a1")
        before = self._raw_session(store, populated)

        store.update_agent(populated, _resynced(read))

        assert self._raw_session(store, populated) == before

    def test_update_agent_writes_a_changed_agent(self, store, populated):
        store.update_agent(populated, _agent("a1", state={"k": "v"}))

        assert self._stored_agent_state(store, populated) == {"k": "v"}

    def test_update_agent_compares_with_the_last_write(self, store, populated):
        """Going back to the created content is a change once something else was written."""
        store.update_agent(populated, _agent("a1", state={"k": "v"}))

        store.update_agent(populated, _agent("a1"))

        assert self._stored_agent_state(store, populated) == {}

    def test_a_read_agent_mutated_in_place_is_written(self, store, populated):
        """What is remembered is a copy, not the dicts Strands keeps live."""
        read = store.read_agent(populated, "a1")
        read.state["k"] = "v"

        store.update_agent(populated, _resynced(read))

        assert self._stored_agent_state(store, populated) == {"k": "v"}

    def test_update_agent_without_session_still_raises(self, store, populated):
        """What is remembered belongs to one session: another one is not found."""
        with pytest.raises(ValueError, match="not found"):
            store.update_agent("nope", _agent("a1"))

    def _stored_agent_state(self, store, session_id: str) -> dict[str, Any]:
        return self._raw_session(store, session_id)["agents"]["a1"]["agent_data"][
            "state"
        ]

    # -- record_guardrail_event -------------------------------------------

    def test_guardrail_event_lands_on_message_and_session(self, store, populated):
        event = {
            "action": "BLOCKED",
            "timestamp": datetime.now(UTC),
            "policies_triggered": {"contentPolicy": ["HATE/HIGH"]},
            "trace": {"inputAssessment": {"big": "payload"}},
        }
        ref = self._ref(store, populated, 1)

        assert store.record_guardrail_event(populated, "a1", ref, event) is True

        on_message = self._raw_message(store, populated, 1)["guardrail_event"]
        assert on_message["trace"] == {"inputAssessment": {"big": "payload"}}

        on_session = self._session_guardrail_events(store, populated)
        assert len(on_session) == 1
        assert on_session[0]["message_id"] == 1
        assert on_session[0]["storage_id"] == ref.storage_id
        assert on_session[0]["agent_id"] == "a1"
        assert on_session[0]["policies_triggered"] == {"contentPolicy": ["HATE/HIGH"]}
        assert "trace" not in on_session[0]

    def test_guardrail_event_on_an_unknown_message_writes_nothing(
        self, store, populated
    ):
        event = {"action": "BLOCKED", "timestamp": datetime.now(UTC)}

        assert (
            store.record_guardrail_event(populated, "a1", MessageRef(99), event)
            is False
        )
        assert self._session_guardrail_events(store, populated) == []

    def test_guardrail_event_names_the_message_it_landed_on(self, store, populated):
        """The session-level audit entry must survive a duplicated index.

        message_id alone would point the auditor at two messages; the identity
        says which one was actually intercepted.
        """
        duplicate = SessionMessage(
            message_id=1, message={"role": "user", "content": [{"text": "dup"}]}
        )
        store.create_message(populated, "a1", duplicate)

        store.record_guardrail_event(
            populated,
            "a1",
            MessageRef(message_id=1, storage_id=storage_id_of(duplicate)),
            {"action": "BLOCKED", "timestamp": datetime.now(UTC)},
        )

        on_session = self._session_guardrail_events(store, populated)
        assert on_session[0]["message_id"] == 1
        assert on_session[0]["storage_id"] == storage_id_of(duplicate)

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
        store.create_agent(populated, _agent("a2"))

        configs = store.list_agent_configs(populated)

        assert {c["agent_id"] for c in configs} == {"a1", "a2"}

    def test_list_agent_configs_is_empty_without_session(self, store):
        assert store.list_agent_configs("nope") == []

    def test_count_messages(self, store, populated):
        assert store.count_messages(populated, "a1") == 2
        assert store.count_messages(populated, "ghost") == 0

    def test_get_last_message_ref(self, store, populated):
        ref = store.get_last_message_ref(populated, "a1")

        assert ref.message_id == 1
        assert ref.storage_id == self._raw_message(store, populated, 1)["storage_id"]
        assert store.get_last_message_ref(populated, "ghost") is None

    def test_get_last_message_ref_without_a_storage_id(self, store, populated):
        """A message stored before #78 still answers, with no identity to give."""
        self._push_legacy_message(store, populated, 2)

        assert store.get_last_message_ref(populated, "a1") == MessageRef(2)

    # -- Agent config handover ---------------------------------------------

    def test_read_agent_hands_its_config_over_once(self, store, populated):
        """The manager seeds its config cache from here, so both sides agree.

        Consuming it is the point: a second caller must not be told a config
        is already persisted when the first one has taken responsibility.
        """
        store.update_agent_fields(
            populated,
            "a1",
            {"agent_data.model": "m", "agent_data.system_prompt": "sp"},
        )
        assert store.read_agent(populated, "a1") is not None

        assert store.pop_read_agent_config(populated, "a1") == {
            "model": "m",
            "system_prompt": "sp",
        }
        assert store.pop_read_agent_config(populated, "a1") is None

    # -- Metadata ----------------------------------------------------------

    def test_delete_metadata_reaches_dotted_keys(self, store, populated):
        """A dotted key is a path, not a flat key that happens to have dots."""
        store.update_metadata(populated, {"user.name": "ana", "user.role": "admin"})

        store.delete_metadata(populated, ["user.name"])

        assert store.get_metadata(populated)["metadata"] == {"user": {"role": "admin"}}

    # -- Names inside paths (#79) ------------------------------------------
    #
    # One invalid name per call is enough here: which names are invalid is
    # tests/unit/test_field_names.py's job. What these cases prove is that both
    # implementations apply the rule, and before anything else happens.

    @pytest.mark.parametrize("call", AGENT_SCOPED_CALLS)
    def test_an_invalid_agent_id_is_rejected_without_writing(
        self, store, populated, call
    ):
        """Every call that builds `agents.<agent_id>` refuses what MongoDB would parse.

        With `a.b` the agent landed nested under `agents.a.b`, where no read
        looks, so every request created it again and wiped its history.
        """
        before = self._raw_session(store, populated)

        with pytest.raises(ValueError, match="agent_id"):
            call(store, populated, "a.b")

        assert self._raw_session(store, populated) == before

    @pytest.mark.parametrize("call", AGENT_SCOPED_CALLS)
    def test_the_agent_id_is_checked_before_the_session(self, store, call):
        """Both implementations fail the same way, whether or not the session exists."""
        with pytest.raises(ValueError, match="agent_id"):
            call(store, "nope", "a.b")

    def test_a_dollar_inside_an_agent_id_works_end_to_end(self, store, populated):
        """Only a *leading* `$` breaks MongoDB; `a$b` must keep working."""
        agent_id = "a$b"
        message = _message()
        store.create_agent(populated, _agent(agent_id))
        store.create_message(populated, agent_id, message)

        assert store.read_agent(populated, agent_id) is not None
        assert [m.message_id for m in store.list_messages(populated, agent_id)] == [0]
        assert store.read_message(populated, agent_id, 0) is not None
        assert store.count_messages(populated, agent_id) == 1
        assert store.get_last_message_ref(populated, agent_id) == ref_of(message)
        assert (
            store.update_message_fields(
                populated, agent_id, ref_of(message), {"guardrail_event": {"a": 1}}
            )
            is True
        )
        assert store.get_agent_config(populated, agent_id)["agent_id"] == agent_id

    @pytest.mark.parametrize("call", METADATA_CALLS)
    def test_an_array_operator_is_rejected_without_writing(
        self, store, populated, call
    ):
        """`tags.$[]` would rewrite, or null out, every element of an existing array."""
        store.update_metadata(populated, {"tags": ["a", "b"]})
        before = self._raw_session(store, populated)

        with pytest.raises(ValueError, match="metadata key"):
            call(store, populated, "tags.$[]")

        assert self._raw_session(store, populated) == before

    @pytest.mark.parametrize("call", METADATA_CALLS)
    def test_a_metadata_key_is_checked_before_the_session(self, store, call):
        with pytest.raises(ValueError, match="metadata key"):
            call(store, "nope", "$where")

    def test_a_batch_with_one_invalid_key_writes_none_of_them(self, store, populated):
        """The valid key comes first on purpose: nothing may land before the check."""
        with pytest.raises(ValueError):
            store.update_metadata(populated, {"status": "ok", "$where": 1})

        assert "status" not in store.get_metadata(populated)["metadata"]

    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(
                lambda s, sid, field: s.update_message_fields(
                    sid, "a1", MessageRef(0), {field: 1}
                ),
                id="message_field",
            ),
            pytest.param(
                lambda s, sid, field: s.update_message_fields(
                    sid, "a1", MessageRef(0), {"x": 1}, agent_set_operations={field: 1}
                ),
                id="agent_field",
            ),
            pytest.param(
                lambda s, sid, field: s.update_agent_fields(sid, "a1", {field: 1}),
                id="update_agent_fields",
            ),
        ],
    )
    def test_a_relative_field_is_rejected_without_writing(self, store, populated, call):
        """`$where` on purpose: MongoDB would store it silently as a literal field."""
        before = self._raw_session(store, populated)

        with pytest.raises(ValueError, match="field"):
            call(store, populated, "$where")

        assert self._raw_session(store, populated) == before

    # -- Raw access, implemented by each subclass --------------------------

    def _raw_session(self, store, session_id: str) -> dict[str, Any]:
        """Return the whole stored session document, to compare before and after."""
        raise NotImplementedError

    def _ref(self, store, session_id: str, message_id: int) -> MessageRef:
        """Build the reference of a stored message, identity included."""
        return MessageRef.from_document(
            self._raw_message(store, session_id, message_id)
        )

    def _raw_message(self, store, session_id: str, message_id: int) -> dict[str, Any]:
        """Return one stored message document, extension fields included."""
        raise NotImplementedError

    @staticmethod
    def legacy_message_document(message_id: int) -> dict[str, Any]:
        """Shape a message as it was stored before #78: no identity at all."""
        now = datetime.now(UTC)
        return {
            "message_id": message_id,
            "message": {"role": "user", "content": [{"text": "legacy"}]},
            "redact_message": None,
            "created_at": now,
            "updated_at": now,
        }

    def _push_legacy_message(self, store, session_id: str, message_id: int) -> None:
        """Append legacy_message_document() straight into the store.

        It bypasses create_message() on purpose: that method stamps an identity
        by design, so this is the only way to get a pre-#78 message.
        """
        raise NotImplementedError

    def _raw_messages_with_id(
        self, store, session_id: str, message_id: int
    ) -> list[dict[str, Any]]:
        """Return every stored message carrying this message_id, in order."""
        raise NotImplementedError

    def _session_guardrail_events(self, store, session_id: str) -> list[dict[str, Any]]:
        """Return the session-level guardrail event array."""
        raise NotImplementedError
