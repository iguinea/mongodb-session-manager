"""Unit tests for MongoDBSessionRepository."""

import logging
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from pymongo.errors import OperationFailure, PyMongoError
from strands.types.session import Session, SessionMessage

from mongodb_session_manager.message_identity import (
    MessageRef,
    attach_storage_id,
    storage_id_of,
)
from mongodb_session_manager.mongodb_session_repository import (
    MongoDBSessionRepository,
    _reset_index_registry,
)
from tests.support.repository_contract import AGENT_SCOPED_CALLS

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
        with (
            patch.object(MongoDBSessionRepository, "_ensure_indexes"),
            pytest.raises(ValueError, match="Connection string is required"),
        ):
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

    def test_client_options_with_a_borrowed_client_are_logged(
        self, mock_mongo_client, caplog
    ):
        """A client someone else built cannot take options any more (#111).

        They were dropped without a word, which is how a `maxPoolSize` passed
        to the factory's `create_session_manager()` did nothing.
        """
        with (
            patch.object(MongoDBSessionRepository, "_ensure_indexes"),
            caplog.at_level(logging.WARNING),
        ):
            MongoDBSessionRepository(client=mock_mongo_client, maxPoolSize=5)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "maxPoolSize" in warnings[0].getMessage()

    def test_a_borrowed_client_without_options_logs_nothing(
        self, mock_mongo_client, caplog
    ):
        with (
            patch.object(MongoDBSessionRepository, "_ensure_indexes"),
            caplog.at_level(logging.WARNING),
        ):
            MongoDBSessionRepository(client=mock_mongo_client)

        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


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


class TestOneIndexFailingDoesNotTakeTheOthers:
    """Every index used to share a single try (#59).

    Reproduced against MongoDB 8.2.7 by filling a collection to 62 indexes, two
    below the server limit: `session_id` failed with `CannotCreateIndex`, and
    `application_name` and every `metadata.*` were never even attempted.
    """

    def test_the_ones_after_the_failure_are_still_attempted(
        self, mock_mongo_client, mock_mongo_collection
    ):
        def fail_on_session_id(field, *args, **kwargs):
            if field == "session_id":
                raise PyMongoError("too many indexes")

        mock_mongo_collection.create_index.side_effect = fail_on_session_id

        MongoDBSessionRepository(
            client=mock_mongo_client,
            database_name="db",
            collection_name="coll",
            metadata_fields=["status"],
        )

        attempted = [
            call.args[0] for call in mock_mongo_collection.create_index.call_args_list
        ]
        assert "application_name" in attempted
        assert "metadata.status" in attempted

    def test_application_name_goes_before_the_fields_someone_configured(
        self, mock_mongo_client, mock_mongo_collection
    ):
        """A bad `metadata_fields` must not be able to cost the library its own index."""
        MongoDBSessionRepository(
            client=mock_mongo_client,
            database_name="db",
            collection_name="coll",
            metadata_fields=["status"],
        )

        attempted = [
            call.args[0] for call in mock_mongo_collection.create_index.call_args_list
        ]
        assert attempted.index("application_name") < attempted.index("metadata.status")


class TestRetryingIndexCreation:
    """Whether the next manager tries again depends on what went wrong (#59).

    With a manager per request, retrying something that will always fail is an
    extra round-trip per request for ever -- and creating an index costs
    78-248 ms in DocumentDB.
    """

    def test_a_transient_failure_is_tried_again(
        self, mock_mongo_client, mock_mongo_collection
    ):
        _reset_index_registry()
        mock_mongo_collection.create_index.side_effect = PyMongoError("no primary")

        MongoDBSessionRepository(
            client=mock_mongo_client, database_name="db", collection_name="coll"
        )
        first = mock_mongo_collection.create_index.call_count
        MongoDBSessionRepository(
            client=mock_mongo_client, database_name="db", collection_name="coll"
        )

        assert mock_mongo_collection.create_index.call_count > first

    def test_a_permanent_failure_is_not(
        self, mock_mongo_client, mock_mongo_collection, caplog
    ):
        _reset_index_registry()
        refusal = OperationFailure("too many indexes", code=67)
        mock_mongo_collection.create_index.side_effect = refusal

        with caplog.at_level(logging.WARNING):
            MongoDBSessionRepository(
                client=mock_mongo_client, database_name="db", collection_name="coll"
            )
        first = mock_mongo_collection.create_index.call_count
        MongoDBSessionRepository(
            client=mock_mongo_client, database_name="db", collection_name="coll"
        )

        assert mock_mongo_collection.create_index.call_count == first
        assert any(record.levelname == "WARNING" for record in caplog.records)


class TestHotPathLogging:
    """What a turn writes to INFO is what someone pays to ingest (#59).

    A reference turn emitted 14 INFO records and 1.900 bytes, eight of them
    repeated for every manager -- and with the factory pattern there is a
    manager per request plus one per sub-agent. The level is the contract here:
    an event of the session stays at INFO, the per-message and per-manager
    bookkeeping goes to DEBUG.
    """

    def test_creating_a_message_says_nothing_at_info(
        self, mock_repository, mock_mongo_collection, caplog
    ):
        mock_mongo_collection.update_one.return_value = MagicMock(matched_count=1)

        with caplog.at_level(logging.INFO):
            mock_repository.create_message(
                "s1",
                "a1",
                SessionMessage(
                    message_id=1,
                    message={"role": "user", "content": [{"text": "hi"}]},
                ),
            )

        assert [record.message for record in caplog.records] == []

    def test_but_it_is_still_traceable_at_debug(
        self, mock_repository, mock_mongo_collection, caplog
    ):
        mock_mongo_collection.update_one.return_value = MagicMock(matched_count=1)

        with caplog.at_level(logging.DEBUG):
            mock_repository.create_message(
                "s1",
                "a1",
                SessionMessage(
                    message_id=1,
                    message={"role": "user", "content": [{"text": "hi"}]},
                ),
            )

        assert any(
            "message(s) for agent a1" in record.message for record in caplog.records
        )

    def test_creating_a_session_is_worth_an_info_record(self, mock_repository, caplog):
        with caplog.at_level(logging.INFO):
            mock_repository.create_session(
                Session(session_id="s1", session_type="default")
            )

        assert any(
            record.levelname == "INFO" and "Created session" in record.message
            for record in caplog.records
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

    def test_seeds_a_dotted_field_where_it_is_indexed(
        self, mock_mongo_client, mock_mongo_collection
    ):
        """The index is on `metadata.user.name`, so the seed goes there (#59).

        Seeded as the literal key `user.name` it matched neither its own index
        nor what `update_metadata({"user.name": ...})` writes, and it stayed in
        the document for ever as a key nothing read.
        """
        with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
            repo = MongoDBSessionRepository(
                client=mock_mongo_client,
                database_name="db",
                collection_name="coll",
                metadata_fields=["user.name", "plain"],
            )
        repo.create_session(Session(session_id="s1", session_type="default"))

        doc = mock_mongo_collection.insert_one.call_args[0][0]
        assert doc["metadata"] == {"user": {"name": ""}, "plain": ""}

    def test_two_sessions_do_not_share_the_seed(
        self, mock_mongo_client, mock_mongo_collection
    ):
        """The seed is nested now, so handing out the same dict would alias it."""
        with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
            repo = MongoDBSessionRepository(
                client=mock_mongo_client,
                database_name="db",
                collection_name="coll",
                metadata_fields=["user.name"],
            )
        repo.create_session(Session(session_id="s1", session_type="default"))
        first = mock_mongo_collection.insert_one.call_args[0][0]
        first["metadata"]["user"]["name"] = "ana"

        repo.create_session(Session(session_id="s2", session_type="default"))
        second = mock_mongo_collection.insert_one.call_args[0][0]

        assert second["metadata"] == {"user": {"name": ""}}

    def test_conflicting_metadata_fields_fail_before_connecting(
        self, mock_mongo_client, mock_mongo_collection
    ):
        """`user` and `user.name` cannot both be seeded: one buries the other."""
        with pytest.raises(ValueError, match="conflict"):
            MongoDBSessionRepository(
                client=mock_mongo_client,
                database_name="db",
                collection_name="coll",
                metadata_fields=["user", "user.name"],
            )

        mock_mongo_collection.create_index.assert_not_called()

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

    def test_projects_only_the_session_header(
        self, mock_repository, mock_mongo_collection
    ):
        """El historial embebido no viaja para reconstruir un Session."""
        mock_mongo_collection.find_one.return_value = {
            "session_id": "s1",
            "session_type": "chat",
        }

        mock_repository.read_session("s1")

        mock_mongo_collection.find_one.assert_called_once_with(
            {"_id": "s1"},
            {
                "session_id": 1,
                "session_type": 1,
                "created_at": 1,
                "updated_at": 1,
            },
        )

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

    def test_read_agent_projects_only_agent_data(
        self, mock_repository, mock_mongo_collection
    ):
        """El estado y la config viajan; el array de mensajes, no."""
        mock_mongo_collection.find_one.return_value = {
            "agents": {
                "a1": {
                    "agent_data": {
                        "agent_id": "a1",
                        "state": {},
                        "conversation_manager_state": {},
                    }
                }
            }
        }

        mock_repository.read_agent("s1", "a1")

        mock_mongo_collection.find_one.assert_called_once_with(
            {"_id": "s1"}, {"agents.a1.agent_data": 1}
        )

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

        # Left out of the SessionAgent, but handed over to the session manager
        # (issue #65): once, and only for the session they were read from.
        assert mock_repository.pop_read_agent_config("s2", "a1") is None
        assert mock_repository.pop_read_agent_config("s1", "a1") == {
            "model": "claude-3",
            "system_prompt": "You are helpful",
        }
        assert mock_repository.pop_read_agent_config("s1", "a1") is None

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
        """El created_at del agente sobrevive a un update_agent.

        Se preserva por omisión: un $set que no lo nombra no lo toca. Antes se
        leía para reescribirlo, lo que además de costar un find era un
        read-after-write capaz de falsear el valor sobre un secundario
        atrasado (issue #54).
        """
        mock_repository.update_agent("s1", sample_session_agent)

        set_data = mock_mongo_collection.update_one.call_args[0][1]["$set"]
        key = f"agents.{sample_session_agent.agent_id}.created_at"
        assert key not in set_data
        assert mock_mongo_collection.find_one.call_count == 0

    def test_update_agent_does_not_replace_agent_data(
        self, mock_repository, mock_mongo_collection, sample_session_agent
    ):
        """update_agent escribe cada campo de SessionAgent, no agent_data entero.

        El session manager guarda model, system_prompt y prompt_metadata dentro
        de agent_data. Un $set del subdocumento completo los borraba en cada
        sync del SDK.
        """
        mock_repository.update_agent("s1", sample_session_agent)

        set_data = mock_mongo_collection.update_one.call_args[0][1]["$set"]
        prefix = f"agents.{sample_session_agent.agent_id}.agent_data"
        assert prefix not in set_data
        assert set_data[f"{prefix}.state"] == sample_session_agent.state
        assert (
            set_data[f"{prefix}.conversation_manager_state"]
            == sample_session_agent.conversation_manager_state
        )

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

    def test_create_message_stamps_the_identity_on_both_sides(
        self, mock_repository, mock_mongo_collection, sample_session_message
    ):
        """El storage_id se escribe y se queda en el SessionMessage. Ver #78."""
        mock_repository.create_message("s1", "a1", sample_session_message)

        pushed = mock_mongo_collection.update_one.call_args[0][1]["$push"][
            "agents.a1.messages"
        ]["$each"]
        assert len(pushed) == 1
        assert pushed[0]["storage_id"] == storage_id_of(sample_session_message)
        assert pushed[0]["storage_id"]

    def test_create_message_does_not_hand_over_an_identity_it_failed_to_store(
        self, mock_repository, mock_mongo_collection, sample_session_message
    ):
        """Sin sesión no hay mensaje, y por tanto tampoco identidad que llevar."""
        mock_mongo_collection.update_one.return_value = MagicMock(matched_count=0)

        with pytest.raises(ValueError):
            mock_repository.create_message("s1", "a1", sample_session_message)

        assert storage_id_of(sample_session_message) is None

    def test_read_message_returns_message(self, mock_repository, mock_mongo_collection):
        mock_mongo_collection.aggregate.return_value = [
            {
                "message": {
                    "message_id": 1,
                    "message": {"role": "user", "content": [{"text": "Hi"}]},
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                }
            }
        ]
        result = mock_repository.read_message("s1", "a1", 1)
        assert result is not None
        assert result.message_id == 1

        pipeline = mock_mongo_collection.aggregate.call_args.args[0]
        assert pipeline == [
            {"$match": {"_id": "s1"}},
            {
                "$project": {
                    "_id": 0,
                    "message": {
                        "$arrayElemAt": [
                            {
                                "$filter": {
                                    "input": {"$ifNull": ["$agents.a1.messages", []]},
                                    "as": "message",
                                    "cond": {"$eq": ["$$message.message_id", 1]},
                                }
                            },
                            0,
                        ]
                    },
                }
            },
        ]
        mock_mongo_collection.find_one.assert_not_called()

    def test_read_message_returns_none_when_missing(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.aggregate.return_value = []
        assert mock_repository.read_message("s1", "a1", 99) is None

    def test_read_message_filters_metrics_fields(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.aggregate.return_value = [
            {
                "message": {
                    "message_id": 1,
                    "message": {"role": "user", "content": [{"text": "Hi"}]},
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                    "event_loop_metrics": {"latencyMs": 100},
                    "latency_ms": 100,
                    "input_tokens": 50,
                    "output_tokens": 30,
                }
            }
        ]
        result = mock_repository.read_message("s1", "a1", 1)
        assert result is not None

    def test_update_message(
        self, mock_repository, mock_mongo_collection, sample_session_message
    ):
        mock_repository.update_message("s1", "a1", sample_session_message)
        assert mock_mongo_collection.update_one.call_count == 1

    def test_update_message_does_not_read_first(
        self, mock_repository, mock_mongo_collection, sample_session_message
    ):
        """El mensaje se localiza en el servidor, sin leer el historial.

        Leer el array para calcular el índice costaba un round-trip por
        redacción y ataba la escritura a una posición que solo es válida
        mientras nadie reordene el array.
        """
        mock_repository.update_message("s1", "a1", sample_session_message)
        assert mock_mongo_collection.find_one.call_count == 0

    def test_update_message_matches_by_message_id(
        self, mock_repository, mock_mongo_collection
    ):
        msg = SessionMessage(
            message_id=7,
            message={"role": "user", "content": [{"text": "redacted"}]},
        )
        mock_repository.update_message("s1", "a1", msg)

        query = mock_mongo_collection.update_one.call_args[0][0]
        assert query["_id"] == "s1"
        assert query["agents.a1.messages.message_id"] == 7

    def test_update_message_uses_positional_paths(
        self, mock_repository, mock_mongo_collection, sample_session_message
    ):
        """Cada campo va por su ruta posicional, nunca por un índice."""
        mock_repository.update_message("s1", "a1", sample_session_message)

        set_data = mock_mongo_collection.update_one.call_args[0][1]["$set"]
        message_keys = [k for k in set_data if k.startswith("agents.a1.messages.")]
        assert message_keys
        for key in message_keys:
            assert key.startswith("agents.a1.messages.$.")
        assert (
            set_data["agents.a1.messages.$.message"] == sample_session_message.message
        )
        # created_at pertenece a create_message; message_id es la clave de filtro.
        assert "agents.a1.messages.$.created_at" not in set_data
        assert "agents.a1.messages.$.message_id" not in set_data

    def test_update_message_ignores_unknown_attributes(
        self, mock_repository, mock_mongo_collection, sample_session_message
    ):
        """Solo se escriben los campos listados, no lo que traiga el objeto.

        SessionMessage no usa slots: un atributo suelto —o un campo nuevo del
        SDK— no puede entrar en el esquema sin una decisión consciente, y menos
        aún pisar los campos de extensión que este método debe preservar.
        """
        setattr(  # noqa: B010
            sample_session_message, "event_loop_metrics", {"should": "not be written"}
        )

        mock_repository.update_message("s1", "a1", sample_session_message)

        set_data = mock_mongo_collection.update_one.call_args[0][1]["$set"]
        assert "agents.a1.messages.$.event_loop_metrics" not in set_data

    def test_update_message_raises_when_not_found(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.update_one.return_value = MagicMock(
            matched_count=0, modified_count=0
        )
        # El diagnóstico comprueba existencia: sesión y agente están, el mensaje no.
        mock_mongo_collection.count_documents.return_value = 1
        msg = SessionMessage(
            message_id=99,
            message={"role": "user", "content": [{"text": "x"}]},
        )
        with pytest.raises(ValueError, match="Message 99 not found"):
            mock_repository.update_message("s1", "a1", msg)

    def test_update_message_says_what_it_searched_for(
        self, mock_repository, mock_mongo_collection
    ):
        """Con un índice duplicado, «mensaje 7 no encontrado» sería mentira.

        El índice sí existe; lo que no se encontró es la identidad. El
        diagnóstico tiene que decir por cuál de los dos se buscó.
        """
        mock_mongo_collection.update_one.return_value = MagicMock(matched_count=0)
        mock_mongo_collection.count_documents.return_value = 1
        msg = SessionMessage(
            message_id=7, message={"role": "user", "content": [{"text": "x"}]}
        )
        attach_storage_id(msg, "9f1c")

        with pytest.raises(ValueError, match="searched by storage_id=9f1c"):
            mock_repository.update_message("s1", "a1", msg)

    def test_update_message_names_the_missing_agent(
        self, mock_repository, mock_mongo_collection, sample_session_message
    ):
        """Un agente ausente no puede reportarse como «mensaje no encontrado».

        El filtro compuesto deja los tres casos sin casar, así que el camino de
        error comprueba existencia para dar el diagnóstico correcto.
        """
        mock_mongo_collection.update_one.return_value = MagicMock(
            matched_count=0, modified_count=0
        )
        # La sesión existe; el agente no.
        mock_mongo_collection.count_documents.side_effect = [1, 0]

        with pytest.raises(ValueError, match="Agent a1 not found in session s1"):
            mock_repository.update_message("s1", "a1", sample_session_message)

    def test_update_message_diagnosis_does_not_read_the_history(
        self, mock_repository, mock_mongo_collection, sample_session_message
    ):
        """El diagnóstico no puede releer el historial que este método evita.

        Proyectar `agents.<id>` traería el subdocumento del agente entero, con
        su array de mensajes: justo la lectura que el cambio elimina.
        """
        mock_mongo_collection.update_one.return_value = MagicMock(
            matched_count=0, modified_count=0
        )
        mock_mongo_collection.count_documents.return_value = 1

        with pytest.raises(ValueError):
            mock_repository.update_message("s1", "a1", sample_session_message)

        assert mock_mongo_collection.find_one.call_count == 0
        for call in mock_mongo_collection.count_documents.call_args_list:
            assert call.kwargs.get("limit") == 1

    def test_update_message_names_the_missing_session(
        self, mock_repository, mock_mongo_collection, sample_session_message
    ):
        mock_mongo_collection.update_one.return_value = MagicMock(
            matched_count=0, modified_count=0
        )
        mock_mongo_collection.count_documents.return_value = 0

        with pytest.raises(ValueError, match="Session s1 not found"):
            mock_repository.update_message("s1", "a1", sample_session_message)

    def test_list_messages_tolerates_missing_created_at(
        self, mock_repository, mock_mongo_collection
    ):
        """Un mensaje sin created_at no puede dejar al agente sin listar.

        Ordenar mezclando `datetime` con el `""` por defecto lanza TypeError.
        Antes lo tapaba que cada redacción reescribiera `created_at`; desde que
        update_message() deja de reescribirlo, nada lo repara.
        """
        mock_mongo_collection.aggregate.return_value = [
            {
                "message": {
                    "message_id": 2,
                    "message": {"role": "user", "content": [{"text": "b"}]},
                    "created_at": datetime.now(UTC),
                }
            },
            {
                "message": {
                    "message_id": 1,
                    "message": {"role": "user", "content": [{"text": "a"}]},
                }
            },
        ]

        result = mock_repository.list_messages("s1", "a1")

        # El que no tiene timestamp va al final, pero se lista.
        assert [m.message_id for m in result] == [2, 1]

        pipeline = mock_mongo_collection.aggregate.call_args.args[0]
        assert pipeline[-1] == {
            "$sort": {
                "_missing_created_at": 1,
                "message.created_at": 1,
                "_array_index": 1,
            }
        }

    def test_list_messages_returns_list(self, mock_repository, mock_mongo_collection):
        mock_mongo_collection.aggregate.return_value = [
            {
                "message": {
                    "message_id": 1,
                    "message": {"role": "user", "content": [{"text": "Hi"}]},
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                }
            },
            {
                "message": {
                    "message_id": 2,
                    "message": {
                        "role": "assistant",
                        "content": [{"text": "Hello"}],
                    },
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                }
            },
        ]
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
        mock_mongo_collection.aggregate.return_value = [
            {"message": message} for message in messages[1:3]
        ]
        result = mock_repository.list_messages("s1", "a1", limit=2, offset=1)
        assert len(result) == 2

        pipeline = mock_mongo_collection.aggregate.call_args.args[0]
        assert {"$skip": 1} in pipeline
        assert {"$limit": 2} in pipeline
        assert pipeline[-1] == pipeline[-4]
        mock_mongo_collection.find_one.assert_not_called()

    def test_list_messages_asks_for_the_whole_page_in_one_batch(
        self, mock_repository, mock_mongo_collection
    ):
        """El historial se pide en un lote, no en lotes de 101 (#92).

        DocumentDB corta cada lote del cursor en ~101 documentos, así que
        restaurar 5.000 mensajes costaba 49 `getMore` de 94 ms. El tamaño de
        lote se negocia para que quepa cualquier página que un documento de
        16 MiB pueda contener.
        """
        mock_mongo_collection.aggregate.return_value = []

        mock_repository.list_messages("s1", "a1")

        batch_size = mock_mongo_collection.aggregate.call_args.kwargs["batchSize"]
        # Cota superior de mensajes en un documento, independiente de la
        # constante de producción: el límite BSON entre el mensaje más pequeño
        # que `create_message()` puede escribir (un role y un content vacío).
        bson_document_limit = 16 * 1024 * 1024
        smallest_message_bson = 80
        assert batch_size > bson_document_limit // smallest_message_bson

    def test_list_messages_batch_outgrows_the_page_it_asks_for(
        self, mock_repository, mock_mongo_collection
    ):
        """Un lote del tamaño exacto de la página aún cuesta un `getMore`.

        El servidor no sabe que el cursor está agotado hasta que un lote sale
        corto, así que `batchSize == limit` devuelve la página y un cursor
        vivo. Estrictamente mayor lo agota en el propio `aggregate`.
        """
        mock_mongo_collection.aggregate.return_value = []

        mock_repository.list_messages("s1", "a1", limit=2, offset=1)

        assert mock_mongo_collection.aggregate.call_args.kwargs["batchSize"] > 2

    def test_list_messages_returns_empty_for_missing_session(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.aggregate.return_value = []
        assert mock_repository.list_messages("s1", "a1") == []

    def test_list_messages_returns_empty_for_missing_agent(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.aggregate.return_value = []
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


# ---------------------------------------------------------------------------
# Guardrail event filtering
# ---------------------------------------------------------------------------


class TestGuardrailEventFiltering:
    def test_create_session_includes_guardrail_events_field(
        self, mock_repository, mock_mongo_collection
    ):
        session = Session(session_id="s1", session_type="default")
        mock_repository.create_session(session)

        doc = mock_mongo_collection.insert_one.call_args[0][0]
        assert "guardrail_events" in doc
        assert doc["guardrail_events"] == []

    def test_read_message_filters_guardrail_event(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.aggregate.return_value = [
            {
                "message": {
                    "message_id": 1,
                    "message": {"role": "user", "content": [{"text": "Hi"}]},
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                    "guardrail_event": {
                        "action": "BLOCKED",
                        "timestamp": datetime.now(UTC),
                    },
                }
            }
        ]
        result = mock_repository.read_message("s1", "a1", 1)
        assert result is not None
        assert result.message_id == 1

    def test_list_messages_filters_guardrail_event(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.aggregate.return_value = [
            {
                "message": {
                    "message_id": 1,
                    "message": {"role": "user", "content": [{"text": "Hi"}]},
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                    "guardrail_event": {
                        "action": "BLOCKED",
                        "timestamp": datetime.now(UTC),
                    },
                }
            }
        ]
        result = mock_repository.list_messages("s1", "a1")
        assert len(result) == 1
        assert result[0].message_id == 1

    def test_update_message_with_redact_message(
        self, mock_repository, mock_mongo_collection
    ):
        msg = SessionMessage(
            message_id=1,
            message={"role": "user", "content": [{"text": "original"}]},
            redact_message={"role": "user", "content": [{"text": "***"}]},
        )
        mock_repository.update_message("s1", "a1", msg)
        assert mock_mongo_collection.update_one.called
        set_data = mock_mongo_collection.update_one.call_args[0][1]["$set"]
        assert set_data["agents.a1.messages.$.redact_message"] == {
            "role": "user",
            "content": [{"text": "***"}],
        }


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


class TestAgentConfigFields:
    def test_includes_prompt_metadata(self):
        from mongodb_session_manager.mongodb_session_repository import (
            _AGENT_CONFIG_FIELDS,
        )

        assert "prompt_metadata" in _AGENT_CONFIG_FIELDS

    def test_read_agent_filters_prompt_metadata(
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
                        "prompt_metadata": {
                            "prompt_id": "p1",
                            "prompt_name": "Test",
                            "prompt_version": "1.0.0",
                            "deployment_id": "d1",
                            "deployment_name": "prod",
                        },
                        "created_at": "2024-01-01T00:00:00+00:00",
                        "updated_at": "2024-01-01T00:00:00+00:00",
                    }
                }
            }
        }
        result = mock_repository.read_agent("s1", "a1")
        assert result is not None
        assert result.agent_id == "a1"


class TestGetApplicationName:
    def test_returns_application_name(self, mock_repository, mock_mongo_collection):
        mock_mongo_collection.find_one.return_value = {"application_name": "my-app"}
        assert mock_repository.get_application_name("s1") == "my-app"

    def test_returns_none_when_session_missing(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = None
        assert mock_repository.get_application_name("missing") is None


# ---------------------------------------------------------------------------
# Write primitives (#80)
# ---------------------------------------------------------------------------


class TestUpdateMessageFields:
    """El primitivo posicional que comparten los tres escritores de mensajes.

    Antes de #80, el filtro `{"_id", "agents.<id>.messages.message_id"}` y el
    prefijo `agents.<id>.messages.$.` se construían a mano en tres sitios:
    `update_message()`, y los dos accesos directos a la colección del session
    manager. Aquí viven una sola vez.
    """

    def test_prefixes_relative_keys_with_the_positional_path(
        self, mock_repository, mock_mongo_collection
    ):
        """El llamante nombra campos del mensaje; el prefijo lo pone el repositorio."""
        mock_repository.update_message_fields(
            "s1",
            "a1",
            MessageRef(3, "abc"),
            {"event_loop_metrics.cycle_metrics": {"cycle_count": 2}},
        )

        set_data = mock_mongo_collection.update_one.call_args[0][1]["$set"]
        assert set_data["agents.a1.messages.$.event_loop_metrics.cycle_metrics"] == {
            "cycle_count": 2
        }

    def test_matches_the_message_by_its_identity(
        self, mock_repository, mock_mongo_collection
    ):
        """El selector nombra la identidad, no el índice. Es el fix de #78."""
        mock_repository.update_message_fields(
            "s1", "a1", MessageRef(7, "9f1c"), {"guardrail_event": {}}
        )

        query = mock_mongo_collection.update_one.call_args[0][0]
        assert query["_id"] == "s1"
        assert query["agents.a1.messages.storage_id"] == "9f1c"
        assert "agents.a1.messages.message_id" not in query

    def test_falls_back_to_message_id_without_an_identity(
        self, mock_repository, mock_mongo_collection
    ):
        """Los mensajes anteriores a #78 no tienen identidad: siguen por índice."""
        mock_repository.update_message_fields(
            "s1", "a1", MessageRef(7), {"guardrail_event": {}}
        )

        query = mock_mongo_collection.update_one.call_args[0][0]
        assert query["agents.a1.messages.message_id"] == 7
        assert "agents.a1.messages.storage_id" not in query

    def test_agent_fields_travel_in_the_same_write(
        self, mock_repository, mock_mongo_collection
    ):
        """Métricas y configuración del agente comparten round-trip.

        Es la optimización que sostiene el presupuesto de escrituras por turno:
        en DocumentDB cada escritura cuesta 40-55 ms sin importar su tamaño.
        """
        mock_repository.update_message_fields(
            "s1",
            "a1",
            MessageRef(3, "abc"),
            {"event_loop_metrics.accumulated_usage": {"totalTokens": 10}},
            agent_set_operations={"agent_data.model": "claude-opus-5"},
        )

        assert mock_mongo_collection.update_one.call_count == 1
        set_data = mock_mongo_collection.update_one.call_args[0][1]["$set"]
        assert set_data["agents.a1.agent_data.model"] == "claude-opus-5"
        assert "agents.a1.messages.$.event_loop_metrics.accumulated_usage" in set_data

    def test_returns_true_when_a_document_matched(self, mock_repository):
        assert (
            mock_repository.update_message_fields(
                "s1", "a1", MessageRef(1, "abc"), {"x": 1}
            )
            is True
        )

    def test_returns_false_when_nothing_matched(
        self, mock_repository, mock_mongo_collection
    ):
        """No lanza: cada llamante decide qué hacer con un no-match.

        `update_message()` lo convierte en ValueError, el sync lo loguea y el
        guardarraíl lo ignora. `matched_count` no sale del repositorio.
        """
        mock_mongo_collection.update_one.return_value = MagicMock(
            matched_count=0, modified_count=0
        )
        assert (
            mock_repository.update_message_fields(
                "s1", "a1", MessageRef(1, "abc"), {"x": 1}
            )
            is False
        )

    def test_touch_timestamps_refreshes_the_three_levels(
        self, mock_repository, mock_mongo_collection
    ):
        """Una redacción sí es un cambio visible de la sesión.

        El flag vive solo en el primitivo privado: ningún llamante externo tiene
        por qué decidir si una escritura mueve el reloj de la sesión.
        """
        mock_repository._update_message_document(
            "s1", "a1", MessageRef(1, "abc"), {"message": {}}, touch_timestamps=True
        )

        set_data = mock_mongo_collection.update_one.call_args[0][1]["$set"]
        assert set_data["agents.a1.messages.$.updated_at"] == set_data["updated_at"]
        assert set_data["agents.a1.updated_at"] == set_data["updated_at"]

    def test_without_touch_timestamps_no_updated_at_is_written(
        self, mock_repository, mock_mongo_collection
    ):
        """Anotar métricas o un guardrail_event no mueve el reloj de la sesión.

        El `updated_at` raíz mide actividad conversacional; las anotaciones que
        el manager hace sobre el turno recién cerrado no lo son.
        """
        mock_repository.update_message_fields(
            "s1", "a1", MessageRef(1, "abc"), {"guardrail_event": {}}
        )

        set_data = mock_mongo_collection.update_one.call_args[0][1]["$set"]
        assert "updated_at" not in set_data
        assert "agents.a1.updated_at" not in set_data

    def test_does_not_read_before_writing(self, mock_repository, mock_mongo_collection):
        mock_repository.update_message_fields(
            "s1", "a1", MessageRef(1, "abc"), {"x": 1}
        )
        assert mock_mongo_collection.find_one.call_count == 0

    def test_no_write_when_there_is_nothing_to_set(
        self, mock_repository, mock_mongo_collection
    ):
        assert (
            mock_repository.update_message_fields("s1", "a1", MessageRef(1, "abc"), {})
            is False
        )
        assert mock_mongo_collection.update_one.call_count == 0


class TestUpdateAgentFields:
    """El hermano no posicional: escribe bajo el agente, sin tocar sus mensajes."""

    def test_prefixes_keys_with_the_agent_path(
        self, mock_repository, mock_mongo_collection
    ):
        mock_repository.update_agent_fields(
            "s1", "a1", {"agent_data.system_prompt": "hola"}
        )

        set_data = mock_mongo_collection.update_one.call_args[0][1]["$set"]
        assert set_data["agents.a1.agent_data.system_prompt"] == "hola"

    def test_filter_requires_the_agent_without_a_positional_clause(
        self, mock_repository, mock_mongo_collection
    ):
        """Sin métricas no hay mensaje al que apuntar, pero el agente debe existir.

        Colar aquí una cláusula posicional dejaría la configuración sin escribir
        en el primer sync de un agente que todavía no tiene mensajes.
        """
        mock_repository.update_agent_fields("s1", "a1", {"agent_data.model": "m"})

        query = mock_mongo_collection.update_one.call_args[0][0]
        assert query == {"_id": "s1", "agents.a1": {"$exists": True}}

    def test_returns_false_when_the_session_or_agent_is_missing(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.update_one.return_value = MagicMock(
            matched_count=0, modified_count=0
        )
        assert (
            mock_repository.update_agent_fields("s1", "a1", {"agent_data.model": "m"})
            is False
        )

    def test_no_write_when_there_is_nothing_to_set(
        self, mock_repository, mock_mongo_collection
    ):
        assert mock_repository.update_agent_fields("s1", "a1", {}) is False
        assert mock_mongo_collection.update_one.call_count == 0


class TestRecordGuardrailEvent:
    """La intervención de un guardarraíl se anota en el mensaje y en la sesión.

    Antes de #80 el session manager construía los dos eventos a mano y decidía
    allí qué campos llevaba cada uno. La regla —el trace completo se queda en el
    mensaje— vive ahora en un solo sitio.
    """

    @staticmethod
    def _event(**extra):
        return {
            "action": "BLOCKED",
            "timestamp": datetime.now(UTC),
            **extra,
        }

    def test_writes_the_event_on_the_message(
        self, mock_repository, mock_mongo_collection
    ):
        event = self._event()
        mock_repository.record_guardrail_event("s1", "a1", MessageRef(5, "9f1c"), event)

        set_data = mock_mongo_collection.update_one.call_args[0][1]["$set"]
        assert set_data["agents.a1.messages.$.guardrail_event"] == event

    def test_message_and_session_event_share_one_write(
        self, mock_repository, mock_mongo_collection
    ):
        """Una sola escritura: el $set del mensaje y el $push de la sesión juntos."""
        mock_repository.record_guardrail_event(
            "s1", "a1", MessageRef(5, "9f1c"), self._event()
        )

        assert mock_mongo_collection.update_one.call_count == 1
        update = mock_mongo_collection.update_one.call_args[0][1]
        assert "$set" in update
        assert "$push" in update

    def test_session_event_identifies_the_message(
        self, mock_repository, mock_mongo_collection
    ):
        mock_repository.record_guardrail_event(
            "s1", "a1", MessageRef(5, "9f1c"), self._event()
        )

        pushed = mock_mongo_collection.update_one.call_args[0][1]["$push"][
            "guardrail_events"
        ]
        assert pushed["message_id"] == 5
        assert pushed["storage_id"] == "9f1c"
        assert pushed["agent_id"] == "a1"
        assert pushed["action"] == "BLOCKED"
        assert "timestamp" in pushed

    def test_session_event_excludes_the_full_trace(
        self, mock_repository, mock_mongo_collection
    ):
        """El trace es voluminoso: se guarda en el mensaje, no en el array de sesión.

        El array crece con cada intervención y se lee entero para auditar; meter
        ahí el GuardrailTrace completo lo haría impracticable.
        """
        event = self._event(trace={"inputAssessment": {"huge": "payload"}})
        mock_repository.record_guardrail_event("s1", "a1", MessageRef(5, "9f1c"), event)

        update = mock_mongo_collection.update_one.call_args[0][1]
        assert update["$set"]["agents.a1.messages.$.guardrail_event"]["trace"] == {
            "inputAssessment": {"huge": "payload"}
        }
        assert "trace" not in update["$push"]["guardrail_events"]

    def test_session_event_keeps_the_queryable_summary(
        self, mock_repository, mock_mongo_collection
    ):
        """Lo que sí es consultable acompaña al evento de sesión."""
        event = self._event(
            stop_reason="guardrail_intervened",
            policies_triggered={"contentPolicy": ["HATE/HIGH"]},
        )
        mock_repository.record_guardrail_event("s1", "a1", MessageRef(5, "9f1c"), event)

        pushed = mock_mongo_collection.update_one.call_args[0][1]["$push"][
            "guardrail_events"
        ]
        assert pushed["stop_reason"] == "guardrail_intervened"
        assert pushed["policies_triggered"] == {"contentPolicy": ["HATE/HIGH"]}

    def test_does_not_move_the_session_clock(
        self, mock_repository, mock_mongo_collection
    ):
        """Anotar un turno ya cerrado no es actividad conversacional."""
        mock_repository.record_guardrail_event(
            "s1", "a1", MessageRef(5, "9f1c"), self._event()
        )

        set_data = mock_mongo_collection.update_one.call_args[0][1]["$set"]
        assert "updated_at" not in set_data

    def test_returns_false_when_nothing_matched(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.update_one.return_value = MagicMock(
            matched_count=0, modified_count=0
        )
        assert (
            mock_repository.record_guardrail_event(
                "s1", "a1", MessageRef(5, "9f1c"), self._event()
            )
            is False
        )


# ---------------------------------------------------------------------------
# Domain reads (#80)
# ---------------------------------------------------------------------------


class TestAgentConfigReads:
    """Lecturas que el session manager hacía contra la colección a pelo."""

    def test_get_agent_config_returns_the_stored_fields(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = {
            "agents": {
                "a1": {
                    "agent_data": {
                        "model": "claude-opus-5",
                        "system_prompt": "eres util",
                        "prompt_metadata": {"prompt_id": "p-1"},
                    }
                }
            }
        }

        config = mock_repository.get_agent_config("s1", "a1")

        assert config == {
            "agent_id": "a1",
            "model": "claude-opus-5",
            "system_prompt": "eres util",
            "prompt_metadata": {"prompt_id": "p-1"},
        }

    def test_get_agent_config_returns_none_when_the_agent_is_unknown(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = {"agents": {}}
        assert mock_repository.get_agent_config("s1", "missing") is None

    def test_get_agent_config_returns_none_when_the_session_is_unknown(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = None
        assert mock_repository.get_agent_config("missing", "a1") is None

    def test_get_agent_config_does_not_project_the_messages(
        self, mock_repository, mock_mongo_collection
    ):
        """Proyectar el agente entero traería su historial completo."""
        mock_mongo_collection.find_one.return_value = {"agents": {}}
        mock_repository.get_agent_config("s1", "a1")

        projection = mock_mongo_collection.find_one.call_args[0][1]
        assert projection == {"agents.a1.agent_data": 1}

    def test_missing_fields_come_back_as_none(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = {
            "agents": {"a1": {"agent_data": {}}}
        }

        config = mock_repository.get_agent_config("s1", "a1")

        assert config["model"] is None
        assert config["system_prompt"] is None
        assert config["prompt_metadata"] is None

    def test_list_agent_configs_returns_one_entry_per_agent(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.aggregate.return_value = [
            {
                "configs": [
                    {"agent_id": "a1", "model": "m1"},
                    {"agent_id": "a2", "model": "m2"},
                ]
            }
        ]

        configs = mock_repository.list_agent_configs("s1")

        assert {c["agent_id"] for c in configs} == {"a1", "a2"}
        assert {c["model"] for c in configs} == {"m1", "m2"}
        assert all(c["system_prompt"] is None for c in configs)

        pipeline = mock_mongo_collection.aggregate.call_args.args[0]
        assert "$objectToArray" in repr(pipeline)
        assert "$map" in repr(pipeline)
        assert "messages" not in repr(pipeline)
        assert "state" not in repr(pipeline)
        mock_mongo_collection.find_one.assert_not_called()

    def test_list_agent_configs_returns_empty_when_there_are_no_agents(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.aggregate.return_value = []
        assert mock_repository.list_agent_configs("s1") == []


class TestMessageReads:
    def test_count_messages_counts_the_array(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.aggregate.return_value = [{"count": 2}]
        assert mock_repository.count_messages("s1", "a1") == 2

        pipeline = mock_mongo_collection.aggregate.call_args.args[0]
        assert pipeline == [
            {"$match": {"_id": "s1"}},
            {
                "$project": {
                    "_id": 0,
                    "count": {
                        "$size": {
                            "$ifNull": ["$agents.a1.messages", []],
                        }
                    },
                }
            },
        ]
        mock_mongo_collection.find_one.assert_not_called()

    def test_count_messages_returns_zero_for_an_unknown_agent(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.aggregate.return_value = [{"count": 0}]
        assert mock_repository.count_messages("s1", "missing") == 0

    def test_get_last_message_ref_carries_the_identity(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = {
            "agents": {"a1": {"messages": [{"message_id": 7, "storage_id": "9f1c"}]}}
        }
        assert mock_repository.get_last_message_ref("s1", "a1") == MessageRef(7, "9f1c")

    def test_get_last_message_ref_without_an_identity(
        self, mock_repository, mock_mongo_collection
    ):
        """Un mensaje anterior a #78 responde igual, sin identidad que dar."""
        mock_mongo_collection.find_one.return_value = {
            "agents": {"a1": {"messages": [{"message_id": 7}]}}
        }
        assert mock_repository.get_last_message_ref("s1", "a1") == MessageRef(7)

    def test_get_last_message_ref_slices_the_array_server_side(
        self, mock_repository, mock_mongo_collection
    ):
        """Solo el último mensaje viaja por la red, no el historial entero."""
        mock_mongo_collection.find_one.return_value = {"agents": {}}
        mock_repository.get_last_message_ref("s1", "a1")

        projection = mock_mongo_collection.find_one.call_args[0][1]
        assert projection == {"agents.a1.messages": {"$slice": -1}}

    def test_get_last_message_ref_returns_none_without_messages(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = {
            "agents": {"a1": {"messages": []}}
        }
        assert mock_repository.get_last_message_ref("s1", "a1") is None

    def test_get_last_message_ref_returns_none_for_an_unknown_agent(
        self, mock_repository, mock_mongo_collection
    ):
        mock_mongo_collection.find_one.return_value = {"agents": {}}
        assert mock_repository.get_last_message_ref("s1", "missing") is None


# ---------------------------------------------------------------------------
# Names inside paths (#79)
# ---------------------------------------------------------------------------


class TestNamesInPathsCostNoRoundTrip:
    """The contract proves nothing is written; this proves nothing is even sent."""

    @pytest.mark.parametrize("call", AGENT_SCOPED_CALLS)
    def test_an_invalid_agent_id_never_reaches_the_collection(
        self, mock_repository, mock_mongo_collection, call
    ):
        with pytest.raises(ValueError, match="agent_id"):
            call(mock_repository, "s1", "a.b")

        assert mock_mongo_collection.method_calls == []

    @pytest.mark.parametrize(
        "call",
        [
            lambda repo: repo.update_metadata("s1", {"ok": 1, "$where": 1}),
            lambda repo: repo.delete_metadata("s1", ["ok", "a..b"]),
        ],
        ids=["update_metadata", "delete_metadata"],
    )
    def test_an_invalid_metadata_key_never_reaches_the_collection(
        self, mock_repository, mock_mongo_collection, call
    ):
        with pytest.raises(ValueError, match="metadata key"):
            call(mock_repository)

        assert mock_mongo_collection.method_calls == []

    def test_invalid_metadata_fields_fail_before_any_index(
        self, mock_mongo_client, mock_mongo_collection
    ):
        """A config error at startup, instead of indexes that go missing in silence.

        `metadata.$where` cannot be indexed, and the failure used to be swallowed
        together with every index created after it -- application_name included.
        Which names are invalid is tests/unit/test_field_names.py's job.
        """
        with pytest.raises(ValueError, match="metadata field"):
            MongoDBSessionRepository(
                client=mock_mongo_client,
                database_name="db",
                collection_name="coll",
                metadata_fields=["status", "$where"],
            )

        mock_mongo_collection.create_index.assert_not_called()

    def test_valid_names_build_the_same_paths_as_before(
        self, mock_repository, mock_mongo_collection
    ):
        """Validation is a gate, not a rewrite: `a$b` and dotted keys pass untouched."""
        mock_repository.update_metadata("s1", {"user.name": "ana"})
        mock_repository.count_messages("s1", "a$b")

        set_ops = mock_mongo_collection.update_one.call_args[0][1]["$set"]
        assert set_ops == {"metadata.user.name": "ana"}
        pipeline = mock_mongo_collection.aggregate.call_args.args[0]
        assert "$agents.a$b.messages" in repr(pipeline)

    def test_a_non_string_metadata_key_still_becomes_its_text(
        self, mock_repository, mock_mongo_collection
    ):
        """Before #79 the key went through an f-string; validation must not break that."""
        mock_repository.update_metadata("s1", {1: "x"})

        set_ops = mock_mongo_collection.update_one.call_args[0][1]["$set"]
        assert set_ops == {"metadata.1": "x"}
