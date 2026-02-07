"""Unit tests for MongoDBSessionRepository."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from pymongo.errors import PyMongoError
from strands.types.session import Session, SessionMessage

from mongodb_session_manager.mongodb_session_repository import MongoDBSessionRepository


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestSessionRepositoryInit:
    """Test constructor and initialization."""

    def test_init_with_connection_string(self):
        with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
            repo = MongoDBSessionRepository(
                connection_string="mongodb://localhost:27017/",
                database_name="db",
                collection_name="coll",
            )
        assert repo._owns_client is True

    def test_init_with_client(self, mock_mongo_client):
        with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
            repo = MongoDBSessionRepository(
                client=mock_mongo_client,
                database_name="db",
                collection_name="coll",
            )
        assert repo._owns_client is False

    def test_init_raises_without_connection_or_client(self):
        with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
            with pytest.raises(ValueError, match="Connection string is required"):
                MongoDBSessionRepository(database_name="db", collection_name="coll")

    def test_init_stores_application_name(self, mock_mongo_client):
        with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
            repo = MongoDBSessionRepository(
                client=mock_mongo_client,
                database_name="db",
                collection_name="coll",
                application_name="my-app",
            )
        assert repo.application_name == "my-app"

    def test_init_application_name_defaults_to_none(self, mock_mongo_client):
        with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
            repo = MongoDBSessionRepository(
                client=mock_mongo_client,
                database_name="db",
                collection_name="coll",
            )
        assert repo.application_name is None

    def test_init_stores_metadata_fields(self, mock_mongo_client):
        with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
            repo = MongoDBSessionRepository(
                client=mock_mongo_client,
                database_name="db",
                collection_name="coll",
                metadata_fields=["status", "priority"],
            )
        assert repo.metadata_fields == ["status", "priority"]

    def test_init_calls_ensure_indexes(self, mock_mongo_client):
        with patch.object(MongoDBSessionRepository, "_ensure_indexes") as mock_idx:
            MongoDBSessionRepository(
                client=mock_mongo_client,
                database_name="db",
                collection_name="coll",
            )
        mock_idx.assert_called_once()

    def test_init_client_kwarg_takes_precedence(self, mock_mongo_client):
        """When both client and connection_string are given, client wins."""
        with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
            repo = MongoDBSessionRepository(
                connection_string="mongodb://localhost:27017/",
                client=mock_mongo_client,
                database_name="db",
                collection_name="coll",
            )
        assert repo._owns_client is False


# ---------------------------------------------------------------------------
# _ensure_indexes
# ---------------------------------------------------------------------------


class TestEnsureIndexes:
    def test_creates_standard_indexes(self, mock_mongo_client, mock_mongo_collection):
        MongoDBSessionRepository(
            client=mock_mongo_client,
            database_name="db",
            collection_name="coll",
        )
        index_calls = [
            c.args[0] for c in mock_mongo_collection.create_index.call_args_list
        ]
        assert "created_at" in index_calls
        assert "updated_at" in index_calls
        assert "session_id" in index_calls
        assert "application_name" in index_calls

    def test_creates_metadata_field_indexes(
        self, mock_mongo_client, mock_mongo_collection
    ):
        MongoDBSessionRepository(
            client=mock_mongo_client,
            database_name="db",
            collection_name="coll",
            metadata_fields=["status", "priority"],
        )
        index_calls = [
            c.args[0] for c in mock_mongo_collection.create_index.call_args_list
        ]
        assert "metadata.status" in index_calls
        assert "metadata.priority" in index_calls

    def test_no_metadata_field_indexes_when_empty(
        self, mock_mongo_client, mock_mongo_collection
    ):
        MongoDBSessionRepository(
            client=mock_mongo_client,
            database_name="db",
            collection_name="coll",
        )
        index_calls = [
            c.args[0] for c in mock_mongo_collection.create_index.call_args_list
        ]
        assert not any(c.startswith("metadata.") for c in index_calls)

    def test_handles_pymongo_error_gracefully(
        self, mock_mongo_client, mock_mongo_collection
    ):
        mock_mongo_collection.create_index.side_effect = PyMongoError("index error")
        # Should not raise
        MongoDBSessionRepository(
            client=mock_mongo_client,
            database_name="db",
            collection_name="coll",
        )


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------


class TestCreateSession:
    def test_creates_document_with_correct_structure(
        self, mock_repository, mock_mongo_collection
    ):
        session = Session(session_id="s1", session_type="chat")
        mock_repository.create_session(session)

        mock_mongo_collection.insert_one.assert_called_once()
        doc = mock_mongo_collection.insert_one.call_args[0][0]

        assert doc["_id"] == "s1"
        assert doc["session_id"] == "s1"
        assert doc["session_type"] == "chat"
        assert "session_viewer_password" in doc
        assert isinstance(doc["created_at"], datetime)
        assert isinstance(doc["updated_at"], datetime)
        assert doc["agents"] == {}
        assert doc["metadata"] == {}
        assert doc["feedbacks"] == []

    def test_generates_password(self, mock_repository, mock_mongo_collection):
        session = Session(session_id="s1", session_type="default")
        mock_repository.create_session(session)

        doc = mock_mongo_collection.insert_one.call_args[0][0]
        password = doc["session_viewer_password"]
        assert isinstance(password, str)
        assert len(password) > 20

    def test_includes_application_name(self, mock_mongo_client, mock_mongo_collection):
        with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
            repo = MongoDBSessionRepository(
                client=mock_mongo_client,
                database_name="db",
                collection_name="coll",
                application_name="my-app",
            )
        session = Session(session_id="s1", session_type="default")
        repo.create_session(session)

        doc = mock_mongo_collection.insert_one.call_args[0][0]
        assert doc["application_name"] == "my-app"

    def test_includes_metadata_fields_empty(
        self, mock_mongo_client, mock_mongo_collection
    ):
        with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
            repo = MongoDBSessionRepository(
                client=mock_mongo_client,
                database_name="db",
                collection_name="coll",
                metadata_fields=["status", "priority"],
            )
        session = Session(session_id="s1", session_type="default")
        repo.create_session(session)

        doc = mock_mongo_collection.insert_one.call_args[0][0]
        assert doc["metadata"]["status"] == ""
        assert doc["metadata"]["priority"] == ""

    def test_returns_session(self, mock_repository):
        session = Session(session_id="s1", session_type="default")
        result = mock_repository.create_session(session)
        assert result is session

    def test_raises_on_pymongo_error(self, mock_repository, mock_mongo_collection):
        mock_mongo_collection.insert_one.side_effect = PyMongoError("insert error")
        session = Session(session_id="s1", session_type="default")
        with pytest.raises(PyMongoError):
            mock_repository.create_session(session)

    def test_timestamps_are_utc(self, mock_repository, mock_mongo_collection):
        session = Session(session_id="s1", session_type="default")
        mock_repository.create_session(session)

        doc = mock_mongo_collection.insert_one.call_args[0][0]
        assert doc["created_at"].tzinfo is not None
        assert doc["updated_at"].tzinfo is not None


# ---------------------------------------------------------------------------
# read_session
# ---------------------------------------------------------------------------


class TestReadSession:
    def test_returns_session_when_found(self, mock_repository, mock_mongo_collection):
        mock_mongo_collection.find_one.return_value = {
            "session_id": "s1",
            "session_type": "chat",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        result = mock_repository.read_session("s1")
        assert result is not None
        assert result.session_id == "s1"
        assert result.session_type == "chat"

    def test_returns_none_when_not_found(self, mock_repository, mock_mongo_collection):
        mock_mongo_collection.find_one.return_value = None
        assert mock_repository.read_session("missing") is None

    def test_raises_on_pymongo_error(self, mock_repository, mock_mongo_collection):
        mock_mongo_collection.find_one.side_effect = PyMongoError("read error")
        with pytest.raises(PyMongoError):
            mock_repository.read_session("s1")


# ---------------------------------------------------------------------------
# Agent operations
# ---------------------------------------------------------------------------


class TestAgentOperations:
    def test_create_agent(
        self, mock_repository, mock_mongo_collection, sample_session_agent
    ):
        mock_repository.create_agent("s1", sample_session_agent)
        mock_mongo_collection.update_one.assert_called_once()

    def test_create_agent_raises_when_session_missing(
        self, mock_repository, mock_mongo_collection, sample_session_agent
    ):
        mock_mongo_collection.update_one.return_value = MagicMock(matched_count=0)
        with pytest.raises(ValueError, match="Session s1 not found"):
            mock_repository.create_agent("s1", sample_session_agent)

    def test_read_agent_returns_agent(self, mock_repository, mock_mongo_collection):
        mock_mongo_collection.find_one.return_value = {
            "agents": {
                "a1": {
                    "agent_data": {
                        "agent_id": "a1",
                        "state": {},
                        "conversation_manager_state": {},
                        "created_at": "2024-01-01T00:00:00+00:00",
                        "updated_at": "2024-01-01T00:00:00+00:00",
                    }
                }
            }
        }
        result = mock_repository.read_agent("s1", "a1")
        assert result is not None
        assert result.agent_id == "a1"

    def test_read_agent_returns_none_when_missing(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = {"agents": {}}
        assert mock_repository.read_agent("s1", "missing") is None

    def test_read_agent_filters_config_fields(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = {
            "agents": {
                "a1": {
                    "agent_data": {
                        "agent_id": "a1",
                        "state": {},
                        "conversation_manager_state": {},
                        "model": "claude-3",
                        "system_prompt": "You are helpful",
                        "created_at": "2024-01-01T00:00:00+00:00",
                        "updated_at": "2024-01-01T00:00:00+00:00",
                    }
                }
            }
        }
        result = mock_repository.read_agent("s1", "a1")
        assert result is not None

    def test_update_agent(
        self, mock_repository, mock_mongo_collection, sample_session_agent
    ):
        mock_mongo_collection.find_one.return_value = {
            "agents": {
                sample_session_agent.agent_id: {
                    "created_at": datetime.now(UTC),
                }
            }
        }
        mock_repository.update_agent("s1", sample_session_agent)
        assert mock_mongo_collection.update_one.called

    def test_update_agent_preserves_created_at(
        self, mock_repository, mock_mongo_collection, sample_session_agent
    ):
        original_created = datetime(2024, 1, 1, tzinfo=UTC)
        mock_mongo_collection.find_one.return_value = {
            "agents": {
                sample_session_agent.agent_id: {
                    "created_at": original_created,
                }
            }
        }
        mock_repository.update_agent("s1", sample_session_agent)

        update_call = mock_mongo_collection.update_one.call_args
        set_data = update_call[0][1]["$set"]
        key = f"agents.{sample_session_agent.agent_id}.created_at"
        assert set_data[key] == original_created

    def test_update_agent_raises_when_session_missing(
        self, mock_repository, mock_mongo_collection, sample_session_agent
    ):
        mock_mongo_collection.find_one.return_value = {"agents": {}}
        mock_mongo_collection.update_one.return_value = MagicMock(matched_count=0)
        with pytest.raises(ValueError, match="Session s1 not found"):
            mock_repository.update_agent("s1", sample_session_agent)


# ---------------------------------------------------------------------------
# Message operations
# ---------------------------------------------------------------------------


class TestMessageOperations:
    def test_create_message(
        self, mock_repository, mock_mongo_collection, sample_session_message
    ):
        mock_repository.create_message("s1", "a1", sample_session_message)
        mock_mongo_collection.update_one.assert_called_once()

    def test_create_message_raises_when_session_missing(
        self, mock_repository, mock_mongo_collection, sample_session_message
    ):
        mock_mongo_collection.update_one.return_value = MagicMock(matched_count=0)
        with pytest.raises(ValueError, match="Session s1 not found"):
            mock_repository.create_message("s1", "a1", sample_session_message)

    def test_read_message_returns_message(self, mock_repository, mock_mongo_collection):
        mock_mongo_collection.find_one.return_value = {
            "agents": {
                "a1": {
                    "messages": [
                        {
                            "message_id": 1,
                            "message": {"role": "user", "content": [{"text": "Hi"}]},
                            "created_at": datetime.now(UTC),
                            "updated_at": datetime.now(UTC),
                        }
                    ]
                }
            }
        }
        result = mock_repository.read_message("s1", "a1", 1)
        assert result is not None
        assert result.message_id == 1

    def test_read_message_returns_none_when_missing(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = {
            "agents": {"a1": {"messages": []}}
        }
        assert mock_repository.read_message("s1", "a1", 99) is None

    def test_read_message_filters_metrics_fields(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = {
            "agents": {
                "a1": {
                    "messages": [
                        {
                            "message_id": 1,
                            "message": {"role": "user", "content": [{"text": "Hi"}]},
                            "created_at": datetime.now(UTC),
                            "updated_at": datetime.now(UTC),
                            "event_loop_metrics": {"latencyMs": 100},
                            "latency_ms": 100,
                            "input_tokens": 50,
                            "output_tokens": 30,
                        }
                    ]
                }
            }
        }
        result = mock_repository.read_message("s1", "a1", 1)
        assert result is not None

    def test_update_message(self, mock_repository, mock_mongo_collection):
        mock_mongo_collection.find_one.return_value = {
            "agents": {
                "a1": {
                    "messages": [
                        {
                            "message_id": 1,
                            "message": {"role": "user", "content": [{"text": "old"}]},
                            "created_at": datetime.now(UTC),
                            "updated_at": datetime.now(UTC),
                        }
                    ]
                }
            }
        }
        msg = SessionMessage(
            message_id=1,
            message={"role": "user", "content": [{"text": "redacted"}]},
        )
        mock_repository.update_message("s1", "a1", msg)
        assert mock_mongo_collection.update_one.called

    def test_update_message_raises_when_not_found(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = {
            "agents": {"a1": {"messages": []}}
        }
        msg = SessionMessage(
            message_id=99,
            message={"role": "user", "content": [{"text": "x"}]},
        )
        with pytest.raises(ValueError, match="Message 99 not found"):
            mock_repository.update_message("s1", "a1", msg)

    def test_list_messages_returns_list(self, mock_repository, mock_mongo_collection):
        mock_mongo_collection.find_one.return_value = {
            "agents": {
                "a1": {
                    "messages": [
                        {
                            "message_id": 1,
                            "message": {"role": "user", "content": [{"text": "Hi"}]},
                            "created_at": datetime.now(UTC),
                            "updated_at": datetime.now(UTC),
                        },
                        {
                            "message_id": 2,
                            "message": {
                                "role": "assistant",
                                "content": [{"text": "Hello"}],
                            },
                            "created_at": datetime.now(UTC),
                            "updated_at": datetime.now(UTC),
                        },
                    ]
                }
            }
        }
        result = mock_repository.list_messages("s1", "a1")
        assert len(result) == 2

    def test_list_messages_with_pagination(
        self, mock_repository, mock_mongo_collection
    ):
        messages = [
            {
                "message_id": i,
                "message": {"role": "user", "content": [{"text": f"msg {i}"}]},
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
            for i in range(5)
        ]
        mock_mongo_collection.find_one.return_value = {
            "agents": {"a1": {"messages": messages}}
        }
        result = mock_repository.list_messages("s1", "a1", limit=2, offset=1)
        assert len(result) == 2

    def test_list_messages_returns_empty_for_missing_session(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = None
        assert mock_repository.list_messages("s1", "a1") == []

    def test_list_messages_returns_empty_for_missing_agent(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = {"agents": {}}
        assert mock_repository.list_messages("s1", "missing") == []


# ---------------------------------------------------------------------------
# Metadata operations
# ---------------------------------------------------------------------------


class TestMetadataOperations:
    def test_update_metadata_uses_dot_notation(
        self, mock_repository, mock_mongo_collection
    ):
        mock_repository.update_metadata("s1", {"key1": "val1", "key2": "val2"})
        update_call = mock_mongo_collection.update_one.call_args
        set_ops = update_call[0][1]["$set"]
        assert set_ops == {"metadata.key1": "val1", "metadata.key2": "val2"}

    def test_get_metadata(self, mock_repository, mock_mongo_collection):
        mock_mongo_collection.find_one.return_value = {"metadata": {"key": "value"}}
        result = mock_repository.get_metadata("s1")
        assert result == {"metadata": {"key": "value"}}

    def test_delete_metadata_uses_unset(self, mock_repository, mock_mongo_collection):
        mock_repository.delete_metadata("s1", ["key1", "key2"])
        update_call = mock_mongo_collection.update_one.call_args
        unset_ops = update_call[0][1]["$unset"]
        assert unset_ops == {"metadata.key1": "", "metadata.key2": ""}


# ---------------------------------------------------------------------------
# Feedback operations
# ---------------------------------------------------------------------------


class TestFeedbackOperations:
    def test_add_feedback_pushes_to_array(self, mock_repository, mock_mongo_collection):
        mock_repository.add_feedback("s1", {"rating": "up", "comment": "Great!"})
        update_call = mock_mongo_collection.update_one.call_args
        assert "$push" in update_call[0][1]
        feedback_doc = update_call[0][1]["$push"]["feedbacks"]
        assert feedback_doc["rating"] == "up"
        assert "created_at" in feedback_doc

    def test_get_feedbacks_returns_list(self, mock_repository, mock_mongo_collection):
        mock_mongo_collection.find_one.return_value = {
            "feedbacks": [{"rating": "up"}, {"rating": "down"}]
        }
        result = mock_repository.get_feedbacks("s1")
        assert len(result) == 2

    def test_get_feedbacks_returns_empty_for_missing_session(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = None
        assert mock_repository.get_feedbacks("missing") == []

    def test_add_feedback_raises_on_pymongo_error(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.update_one.side_effect = PyMongoError("feedback error")
        with pytest.raises(PyMongoError):
            mock_repository.add_feedback("s1", {"rating": "up"})


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    def test_closes_when_owns_client(self, mock_mongo_client, mock_mongo_collection):
        with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
            repo = MongoDBSessionRepository(
                connection_string="mongodb://localhost:27017/",
                database_name="db",
                collection_name="coll",
            )
        # Replace auto-created client with our mock
        repo.client = mock_mongo_client
        repo._owns_client = True
        repo.close()
        mock_mongo_client.close.assert_called_once()

    def test_does_not_close_borrowed_client(self, mock_mongo_client):
        with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
            repo = MongoDBSessionRepository(
                client=mock_mongo_client,
                database_name="db",
                collection_name="coll",
            )
        repo.close()
        mock_mongo_client.close.assert_not_called()


# ---------------------------------------------------------------------------
# get_session_viewer_password / get_application_name
# ---------------------------------------------------------------------------


class TestSessionViewerPassword:
    def test_returns_password(self, mock_repository, mock_mongo_collection):
        mock_mongo_collection.find_one.return_value = {
            "session_viewer_password": "abc123"
        }
        assert mock_repository.get_session_viewer_password("s1") == "abc123"

    def test_returns_none_when_session_missing(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = None
        assert mock_repository.get_session_viewer_password("missing") is None


class TestGetApplicationName:
    def test_returns_application_name(self, mock_repository, mock_mongo_collection):
        mock_mongo_collection.find_one.return_value = {"application_name": "my-app"}
        assert mock_repository.get_application_name("s1") == "my-app"

    def test_returns_none_when_session_missing(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = None
        assert mock_repository.get_application_name("missing") is None
