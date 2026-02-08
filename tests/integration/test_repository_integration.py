"""Integration tests for MongoDBSessionRepository (requires MongoDB)."""

import pytest
from strands.types.session import Session, SessionAgent, SessionMessage

from mongodb_session_manager.mongodb_session_repository import MongoDBSessionRepository


pytestmark = pytest.mark.integration


@pytest.fixture
def repo(mongodb_connection, unique_session_id, cleanup_session):
    """Create a real repository connected to MongoDB."""
    r = MongoDBSessionRepository(
        connection_string=mongodb_connection,
        database_name="test_db",
        collection_name="test_sessions",
        application_name="integration-test",
    )
    cleanup_session(r.collection, unique_session_id)
    yield r
    r.close()


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    def test_create_and_read_session(self, repo, unique_session_id):
        session = Session(session_id=unique_session_id, session_type="chat")
        repo.create_session(session)

        result = repo.read_session(unique_session_id)
        assert result is not None
        assert result.session_id == unique_session_id
        assert result.session_type == "chat"

    def test_password_generated(self, repo, unique_session_id):
        session = Session(session_id=unique_session_id, session_type="default")
        repo.create_session(session)

        password = repo.get_session_viewer_password(unique_session_id)
        assert password is not None
        assert len(password) > 20

    def test_password_persists(self, repo, unique_session_id):
        session = Session(session_id=unique_session_id, session_type="default")
        repo.create_session(session)

        p1 = repo.get_session_viewer_password(unique_session_id)
        p2 = repo.get_session_viewer_password(unique_session_id)
        assert p1 == p2

    def test_application_name_stored(self, repo, unique_session_id):
        session = Session(session_id=unique_session_id, session_type="default")
        repo.create_session(session)

        doc = repo.collection.find_one({"_id": unique_session_id})
        assert doc["application_name"] == "integration-test"

    def test_application_name_index_exists(self, repo, unique_session_id):
        session = Session(session_id=unique_session_id, session_type="default")
        repo.create_session(session)

        indexes = repo.collection.index_information()
        has_index = any(
            "application_name" in str(idx.get("key", [])) for idx in indexes.values()
        )
        assert has_index


# ---------------------------------------------------------------------------
# Agent lifecycle
# ---------------------------------------------------------------------------


class TestAgentLifecycle:
    def test_create_and_read_agent(self, repo, unique_session_id):
        session = Session(session_id=unique_session_id, session_type="default")
        repo.create_session(session)

        agent = SessionAgent(
            agent_id="agent-1",
            state={"key": "val"},
            conversation_manager_state={},
        )
        repo.create_agent(unique_session_id, agent)

        result = repo.read_agent(unique_session_id, "agent-1")
        assert result is not None
        assert result.agent_id == "agent-1"

    def test_update_preserves_created_at(self, repo, unique_session_id):
        session = Session(session_id=unique_session_id, session_type="default")
        repo.create_session(session)

        agent = SessionAgent(
            agent_id="agent-1",
            state={},
            conversation_manager_state={},
        )
        repo.create_agent(unique_session_id, agent)

        doc_before = repo.collection.find_one({"_id": unique_session_id})
        created_at = doc_before["agents"]["agent-1"]["created_at"]

        agent_updated = SessionAgent(
            agent_id="agent-1",
            state={"new": "state"},
            conversation_manager_state={},
        )
        repo.update_agent(unique_session_id, agent_updated)

        doc_after = repo.collection.find_one({"_id": unique_session_id})
        assert doc_after["agents"]["agent-1"]["created_at"] == created_at

    def test_list_agents(self, repo, unique_session_id):
        session = Session(session_id=unique_session_id, session_type="default")
        repo.create_session(session)

        for i in range(3):
            agent = SessionAgent(
                agent_id=f"agent-{i}",
                state={},
                conversation_manager_state={},
            )
            repo.create_agent(unique_session_id, agent)

        doc = repo.collection.find_one({"_id": unique_session_id})
        assert len(doc["agents"]) == 3


# ---------------------------------------------------------------------------
# Message lifecycle
# ---------------------------------------------------------------------------


class TestMessageLifecycle:
    def test_create_and_read_message(self, repo, unique_session_id):
        session = Session(session_id=unique_session_id, session_type="default")
        repo.create_session(session)

        agent = SessionAgent(
            agent_id="a1",
            state={},
            conversation_manager_state={},
        )
        repo.create_agent(unique_session_id, agent)

        msg = SessionMessage(
            message_id=1,
            message={"role": "user", "content": [{"text": "Hello"}]},
        )
        repo.create_message(unique_session_id, "a1", msg)

        result = repo.read_message(unique_session_id, "a1", 1)
        assert result is not None
        assert result.message_id == 1

    def test_list_messages_with_pagination(self, repo, unique_session_id):
        session = Session(session_id=unique_session_id, session_type="default")
        repo.create_session(session)

        agent = SessionAgent(
            agent_id="a1",
            state={},
            conversation_manager_state={},
        )
        repo.create_agent(unique_session_id, agent)

        for i in range(5):
            msg = SessionMessage(
                message_id=i,
                message={"role": "user", "content": [{"text": f"msg {i}"}]},
            )
            repo.create_message(unique_session_id, "a1", msg)

        all_msgs = repo.list_messages(unique_session_id, "a1")
        assert len(all_msgs) == 5

        page = repo.list_messages(unique_session_id, "a1", limit=2, offset=1)
        assert len(page) == 2

    def test_update_message(self, repo, unique_session_id):
        session = Session(session_id=unique_session_id, session_type="default")
        repo.create_session(session)

        agent = SessionAgent(
            agent_id="a1",
            state={},
            conversation_manager_state={},
        )
        repo.create_agent(unique_session_id, agent)

        msg = SessionMessage(
            message_id=1,
            message={"role": "user", "content": [{"text": "original"}]},
        )
        repo.create_message(unique_session_id, "a1", msg)

        updated = SessionMessage(
            message_id=1,
            message={"role": "user", "content": [{"text": "redacted"}]},
            redact_message={"role": "user", "content": [{"text": "***"}]},
        )
        repo.update_message(unique_session_id, "a1", updated)

        result = repo.read_message(unique_session_id, "a1", 1)
        assert result is not None


# ---------------------------------------------------------------------------
# Metadata lifecycle
# ---------------------------------------------------------------------------


class TestMetadataLifecycle:
    def test_update_and_get(self, repo, unique_session_id):
        session = Session(session_id=unique_session_id, session_type="default")
        repo.create_session(session)

        repo.update_metadata(
            unique_session_id, {"status": "active", "priority": "high"}
        )
        result = repo.get_metadata(unique_session_id)

        assert result["metadata"]["status"] == "active"
        assert result["metadata"]["priority"] == "high"

    def test_delete_preserves_other_fields(self, repo, unique_session_id):
        session = Session(session_id=unique_session_id, session_type="default")
        repo.create_session(session)

        repo.update_metadata(unique_session_id, {"a": "1", "b": "2", "c": "3"})
        repo.delete_metadata(unique_session_id, ["b"])

        result = repo.get_metadata(unique_session_id)
        assert result["metadata"]["a"] == "1"
        assert result["metadata"]["c"] == "3"
        assert "b" not in result["metadata"]


# ---------------------------------------------------------------------------
# Feedback lifecycle
# ---------------------------------------------------------------------------


class TestFeedbackLifecycle:
    def test_add_and_get(self, repo, unique_session_id):
        session = Session(session_id=unique_session_id, session_type="default")
        repo.create_session(session)

        repo.add_feedback(unique_session_id, {"rating": "up", "comment": "good"})
        repo.add_feedback(unique_session_id, {"rating": "down", "comment": "bad"})

        feedbacks = repo.get_feedbacks(unique_session_id)
        assert len(feedbacks) == 2

    def test_created_at_auto_added(self, repo, unique_session_id):
        session = Session(session_id=unique_session_id, session_type="default")
        repo.create_session(session)

        repo.add_feedback(unique_session_id, {"rating": "up"})
        feedbacks = repo.get_feedbacks(unique_session_id)
        assert "created_at" in feedbacks[0]
