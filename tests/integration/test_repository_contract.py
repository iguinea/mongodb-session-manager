"""The shared repository contract, run against a real MongoDB.

Twin of tests/unit/test_in_memory_repository.py. Same assertions, real driver:
this is what stops the in-memory double from quietly diverging.
"""

from __future__ import annotations

from typing import Any

import pytest

from mongodb_session_manager.mongodb_session_repository import MongoDBSessionRepository
from tests.support.repository_contract import SessionRepositoryContract

pytestmark = pytest.mark.integration


class TestMongoDBContract(SessionRepositoryContract):
    """The contract, satisfied by the MongoDB adapter."""

    @pytest.fixture
    def session_id(self, unique_session_id: str) -> str:
        return unique_session_id

    @pytest.fixture
    def store(self, mongodb_connection, cleanup_session, session_id):
        repo = MongoDBSessionRepository(
            connection_string=mongodb_connection,
            database_name="test_contract_db",
            collection_name="sessions",
        )
        cleanup_session(repo.collection, session_id)
        yield repo
        repo.close()

    @pytest.fixture
    def seeded_store(self, mongodb_connection, cleanup_session, session_id):
        """Repositories that seed metadata fields, closed with the test."""
        built = []

        def build(metadata_fields: list[str]) -> MongoDBSessionRepository:
            repo = MongoDBSessionRepository(
                connection_string=mongodb_connection,
                database_name="test_contract_db",
                collection_name="sessions",
                metadata_fields=metadata_fields,
            )
            built.append(repo)
            cleanup_session(repo.collection, session_id)
            return repo

        yield build
        for repo in built:
            repo.close()

    def _raw_session(self, store, session_id: str) -> dict[str, Any]:
        return store.collection.find_one({"_id": session_id})

    def _messages(self, store, session_id: str) -> list[dict[str, Any]]:
        return self._raw_session(store, session_id)["agents"]["a1"]["messages"]

    def _raw_message(self, store, session_id: str, message_id: int) -> dict[str, Any]:
        for msg in self._messages(store, session_id):
            if msg.get("message_id") == message_id:
                return msg
        raise KeyError(f"Message {message_id} not found")

    def _raw_messages_with_id(
        self, store, session_id: str, message_id: int
    ) -> list[dict[str, Any]]:
        return [
            m
            for m in self._messages(store, session_id)
            if m.get("message_id") == message_id
        ]

    def _push_legacy_message(self, store, session_id: str, message_id: int) -> None:
        store.collection.update_one(
            {"_id": session_id},
            {"$push": {"agents.a1.messages": self.legacy_message_document(message_id)}},
        )

    def _seed_legacy_bare_agent(self, store, session_id: str) -> None:
        store.collection.update_one(
            {"_id": session_id},
            {"$set": {"agents.ghost.agent_data.model": "m"}},
        )

    def _session_guardrail_events(self, store, session_id: str) -> list[dict[str, Any]]:
        return self._raw_session(store, session_id).get("guardrail_events", [])
