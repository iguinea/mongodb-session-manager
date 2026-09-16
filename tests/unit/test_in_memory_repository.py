"""The in-memory double must behave like the MongoDB repository.

Runs the shared contract against the double. Its integration twin runs the very
same cases against a real MongoDB, and the two must agree.
"""

from __future__ import annotations

from typing import Any

import pytest

from mongodb_session_manager.mongodb_session_repository import MongoDBSessionRepository
from tests.support.in_memory_session_repository import InMemorySessionRepository
from tests.support.repository_contract import SessionRepositoryContract


class TestInMemoryContract(SessionRepositoryContract):
    """The contract, satisfied without MongoDB."""

    @pytest.fixture
    def store(self) -> InMemorySessionRepository:
        return InMemorySessionRepository()

    def _raw_message(self, store, session_id: str, message_id: int) -> dict[str, Any]:
        return store.message(session_id, "a1", message_id)

    def _raw_messages_with_id(
        self, store, session_id: str, message_id: int
    ) -> list[dict[str, Any]]:
        messages = store.session(session_id)["agents"]["a1"]["messages"]
        return [m for m in messages if m.get("message_id") == message_id]

    def _push_legacy_message(self, store, session_id: str, message_id: int) -> None:
        store.push_raw_message(
            session_id, "a1", self.legacy_message_document(message_id)
        )

    def _session_guardrail_events(self, store, session_id: str) -> list[dict[str, Any]]:
        return store.session(session_id)["guardrail_events"]


def _public_methods(cls: type) -> set[str]:
    """Return the public methods a class defines itself."""
    return {
        name
        for name, value in vars(cls).items()
        if not name.startswith("_") and callable(value)
    }


class TestDoubleKeepsUpWithTheRepository:
    """Structural guards, so the double cannot drift unnoticed."""

    def test_implements_every_public_method_of_the_real_repository(self):
        """A method added to the repository must reach the double too.

        The cheap half of the anti-drift net: it catches the omission the day
        after, while the shared contract catches the subtler case of a method
        that exists on both sides but behaves differently.
        """
        missing = _public_methods(MongoDBSessionRepository) - _public_methods(
            InMemorySessionRepository
        )

        assert not missing, f"InMemorySessionRepository is missing: {sorted(missing)}"

    def test_has_no_collection_attribute(self):
        """The double exposes no pymongo collection, and that is the point.

        It is what turns "the manager must not reach for the raw collection"
        into a failing test instead of a code-review note.
        """
        assert not hasattr(InMemorySessionRepository(), "collection")
