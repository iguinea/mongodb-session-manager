"""When an agent write would change nothing, so the repository can skip it.

Strands calls `update_agent()` whenever the versions it tracks move, and on the
first sync of every manager because it has none to compare yet. Most of those
writes carry exactly what is already stored (issue #67): the state the manager
has just restored, or the one it had before `_interrupt_state.deactivate()`
bumped a version with nothing to deactivate. Each one is a round-trip, and on
DocumentDB a round-trip costs 40-55 ms whatever its size.

Comparing the content instead of the versions is what makes skipping safe. Once
this repository has read or written an agent, a write whose content is the same
has nothing to add, however the agent got there; one that differs is written,
however the agent got there too -- `state.set()`, a hook that replaces
`agent.state` whole, or a conversation manager migrating its state on restore.
Seeding Strands' version bookkeeping instead lost all three
(features/7_skip_unchanged_agent_writes/plan.md).

The rule lives here, in one place, so the MongoDB repository and the in-memory
double skip the same writes.
"""

from __future__ import annotations

import copy
from typing import Any

from strands.types.session import SessionAgent

# Stamped by SessionAgent.from_agent() on every sync, whether anything changed or not.
_TIMESTAMP_FIELDS = frozenset(["created_at", "updated_at"])


def _content(session_agent: SessionAgent) -> dict[str, Any]:
    """Every field of the agent except its timestamps.

    Fields are not listed: whatever a newer SDK adds is compared as well, so an
    unknown field can only make a write happen, never make one disappear.
    """
    return {
        name: value
        for name, value in vars(session_agent).items()
        if name not in _TIMESTAMP_FIELDS
    }


class LastPersistedAgents:
    """The content of each agent as this repository last read or wrote it.

    Only what went through this repository is known: a write made elsewhere is
    not seen, and an agent that has not changed will not overwrite it.

    Only the agents of one session are kept, the last one remembered. The
    factory builds a repository per session manager, so that is all it ever
    holds; a repository reused across sessions would otherwise pile up the state
    of every agent it touched, and forgetting costs nothing but a rewrite.
    """

    def __init__(self) -> None:
        """Start knowing nothing, so every first write happens."""
        self._content: dict[tuple[str, str], dict[str, Any]] = {}

    def remember(self, session_id: str, session_agent: SessionAgent) -> None:
        """Record an agent as persisted, once it has been read or written.

        The content is deep-copied: the dicts of a SessionAgent returned by
        read_agent() end up live inside the Agent (_InterruptState.from_dict()
        keeps `context` as is), and a remembered reference would change along
        with the agent, reporting as persisted what never was.
        """
        self._content = {
            key: content
            for key, content in self._content.items()
            if key[0] == session_id
        }
        key = (session_id, session_agent.agent_id)
        self._content[key] = copy.deepcopy(_content(session_agent))

    def unchanged(self, session_id: str, session_agent: SessionAgent) -> bool:
        """Tell whether writing this agent would store what is already stored."""
        key = (session_id, session_agent.agent_id)
        return self._content.get(key) == _content(session_agent)

    def forget(self, session_id: str, agent_id: str) -> None:
        """Stop assuming anything about an agent, e.g. when a read no longer finds it."""
        self._content.pop((session_id, agent_id), None)

    def forget_session(self, session_id: str) -> None:
        """Stop assuming anything about every agent of a session (#132).

        delete_session() calls it: the knowledge dies with the document, and a
        cache that survived it would make update_agent() skip the write that
        should say `not found`. Only this session's entries go; a repository
        shared across sessions keeps the rest.
        """
        self._content = {
            key: content
            for key, content in self._content.items()
            if key[0] != session_id
        }
