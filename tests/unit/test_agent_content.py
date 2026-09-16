"""When an agent write would change nothing (issue #67).

The rule is checked here on its own, without a repository: the contract suite
then proves that both repository implementations apply it at the same points.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from strands.types.session import SessionAgent

from mongodb_session_manager.agent_content import LastPersistedAgents


def _agent(**overrides) -> SessionAgent:
    fields = {
        "agent_id": "a1",
        "state": {"k": "v"},
        "conversation_manager_state": {"removed_message_count": 0},
        "_internal_state": {"interrupt_state": {"context": {}, "activated": False}},
    }
    fields.update(overrides)
    return SessionAgent(**fields)


class TestUnchanged:
    def test_nothing_is_unchanged_before_it_is_remembered(self):
        assert LastPersistedAgents().unchanged("s1", _agent()) is False

    def test_the_same_content_is_unchanged(self):
        persisted = LastPersistedAgents()
        persisted.remember("s1", _agent())

        assert persisted.unchanged("s1", _agent()) is True

    def test_timestamps_do_not_count(self):
        """SessionAgent.from_agent() stamps both on every sync, content or not."""
        persisted = LastPersistedAgents()
        persisted.remember(
            "s1", _agent(created_at="2026-01-01", updated_at="2026-01-01")
        )

        assert persisted.unchanged(
            "s1", _agent(created_at="2026-09-16", updated_at="2026-09-16")
        )

    def test_any_other_field_counts(self):
        persisted = LastPersistedAgents()
        persisted.remember("s1", _agent())

        assert not persisted.unchanged("s1", _agent(state={"k": "other"}))
        assert not persisted.unchanged(
            "s1", _agent(conversation_manager_state={"removed_message_count": 2})
        )
        assert not persisted.unchanged(
            "s1",
            _agent(
                _internal_state={"interrupt_state": {"context": {}, "activated": True}}
            ),
        )

    def test_a_field_this_code_does_not_know_counts(self):
        """Nothing lists the fields, so what a newer SDK adds is compared too."""

        @dataclass
        class NewerSessionAgent(SessionAgent):
            model_state: dict = field(default_factory=dict)

        persisted = LastPersistedAgents()
        persisted.remember("s1", NewerSessionAgent("a1", {}, {}, model_state={"x": 1}))

        assert not persisted.unchanged(
            "s1", NewerSessionAgent("a1", {}, {}, model_state={"x": 2})
        )

    def test_it_is_remembered_per_session_and_agent(self):
        persisted = LastPersistedAgents()
        persisted.remember("s1", _agent())

        assert not persisted.unchanged("s2", _agent())
        assert not persisted.unchanged("s1", _agent(agent_id="a2"))

    def test_only_the_last_session_is_kept(self):
        """A repository reused across sessions must not pile up agent state."""
        persisted = LastPersistedAgents()
        persisted.remember("s1", _agent())
        persisted.remember("s1", _agent(agent_id="a2"))

        persisted.remember("s2", _agent())

        assert persisted.unchanged("s2", _agent())
        assert not persisted.unchanged("s1", _agent())
        assert not persisted.unchanged("s1", _agent(agent_id="a2"))


class TestRemember:
    def test_the_last_write_wins(self):
        persisted = LastPersistedAgents()
        persisted.remember("s1", _agent(state={"k": "old"}))
        persisted.remember("s1", _agent(state={"k": "new"}))

        assert persisted.unchanged("s1", _agent(state={"k": "new"}))
        assert not persisted.unchanged("s1", _agent(state={"k": "old"}))

    def test_a_later_mutation_of_the_remembered_agent_is_not_remembered(self):
        """A copy, not a reference: see LastPersistedAgents.remember()."""
        read = _agent()
        persisted = LastPersistedAgents()
        persisted.remember("s1", read)

        read._internal_state["interrupt_state"]["context"]["responses"] = ["yes"]
        read.state["k"] = "mutated"

        assert not persisted.unchanged("s1", read)


class TestForget:
    def test_a_forgotten_agent_is_never_unchanged(self):
        persisted = LastPersistedAgents()
        persisted.remember("s1", _agent())

        persisted.forget("s1", "a1")

        assert not persisted.unchanged("s1", _agent())

    def test_forgetting_an_unknown_agent_is_harmless(self):
        LastPersistedAgents().forget("s1", "ghost")
