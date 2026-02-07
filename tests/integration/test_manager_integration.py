"""Integration tests for MongoDBSessionManager (requires MongoDB).

Migrates tests from test_application_name.py (TestApplicationNameIntegration)
and test_session_viewer_password.py.
"""

import pytest
from unittest.mock import MagicMock

from mongodb_session_manager import (
    create_mongodb_session_manager,
)


pytestmark = pytest.mark.integration


@pytest.fixture
def manager(mongodb_connection, unique_session_id, cleanup_session):
    """Create a real session manager."""
    mgr = create_mongodb_session_manager(
        session_id=unique_session_id,
        connection_string=mongodb_connection,
        database_name="test_db",
        collection_name="test_sessions",
        application_name="integration-test",
    )
    cleanup_session(mgr.session_repository.collection, unique_session_id)
    yield mgr
    mgr.close()


class TestManagerIntegration:
    def test_application_name_stored_in_document(self, manager, unique_session_id):
        doc = manager.session_repository.collection.find_one({"_id": unique_session_id})
        assert doc is not None
        assert doc["application_name"] == "integration-test"

    def test_get_application_name(self, manager):
        assert manager.get_application_name() == "integration-test"

    def test_application_name_none_when_not_set(
        self, mongodb_connection, unique_session_id, cleanup_session
    ):
        mgr = create_mongodb_session_manager(
            session_id=unique_session_id + "-noapp",
            connection_string=mongodb_connection,
            database_name="test_db",
            collection_name="test_sessions",
        )
        cleanup_session(mgr.session_repository.collection, unique_session_id + "-noapp")
        try:
            assert mgr.get_application_name() is None
        finally:
            mgr.close()

    def test_password_generated(self, manager):
        password = manager.get_session_viewer_password()
        assert password is not None
        assert len(password) > 20

    def test_password_persists(
        self, mongodb_connection, unique_session_id, cleanup_session
    ):
        mgr1 = create_mongodb_session_manager(
            session_id=unique_session_id,
            connection_string=mongodb_connection,
            database_name="test_db",
            collection_name="test_sessions",
        )
        cleanup_session(mgr1.session_repository.collection, unique_session_id)
        p1 = mgr1.get_session_viewer_password()

        mgr2 = create_mongodb_session_manager(
            session_id=unique_session_id,
            connection_string=mongodb_connection,
            database_name="test_db",
            collection_name="test_sessions",
        )
        p2 = mgr2.get_session_viewer_password()

        assert p1 == p2
        mgr1.close()
        mgr2.close()

    def test_metadata_roundtrip(self, manager, unique_session_id):
        manager.update_metadata({"status": "active", "priority": "high"})
        result = manager.get_metadata()
        assert result["metadata"]["status"] == "active"

    def test_feedback_roundtrip(self, manager, unique_session_id):
        manager.add_feedback({"rating": "up", "comment": "great"})
        feedbacks = manager.get_feedbacks()
        assert len(feedbacks) == 1
        assert feedbacks[0]["rating"] == "up"

    def test_agent_config_roundtrip(self, manager, unique_session_id):
        # Create an agent by creating a mock and syncing
        mock_agent = MagicMock()
        mock_agent.agent_id = "test-agent"
        mock_agent.messages = []
        mock_agent.system_prompt = "You are helpful"
        mock_agent.model = MagicMock()
        mock_agent.model.config = {"model_id": "claude-3-sonnet"}

        summary = {
            "total_cycles": 0,
            "total_duration": 0,
            "average_cycle_time": 0,
            "accumulated_usage": {
                "inputTokens": 0,
                "outputTokens": 0,
                "totalTokens": 0,
                "cacheReadInputTokens": 0,
                "cacheWriteInputTokens": 0,
            },
            "accumulated_metrics": {"latencyMs": 0, "timeToFirstByteMs": 0},
            "tool_usage": {},
            "traces": [],
        }
        mock_agent.event_loop_metrics.get_summary.return_value = summary
        manager.sync_agent(mock_agent)

        config = manager.get_agent_config("test-agent")
        assert config is not None
        assert config.get("model") == "claude-3-sonnet"
        assert config.get("system_prompt") == "You are helpful"

    def test_list_agents(self, manager, unique_session_id):
        for i in range(2):
            mock_agent = MagicMock()
            mock_agent.agent_id = f"agent-{i}"
            mock_agent.messages = []
            summary = {
                "total_cycles": 0,
                "total_duration": 0,
                "average_cycle_time": 0,
                "accumulated_usage": {
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "totalTokens": 0,
                    "cacheReadInputTokens": 0,
                    "cacheWriteInputTokens": 0,
                },
                "accumulated_metrics": {"latencyMs": 0, "timeToFirstByteMs": 0},
                "tool_usage": {},
                "traces": [],
            }
            mock_agent.event_loop_metrics.get_summary.return_value = summary
            manager.sync_agent(mock_agent)

        agents = manager.list_agents()
        assert len(agents) >= 2
