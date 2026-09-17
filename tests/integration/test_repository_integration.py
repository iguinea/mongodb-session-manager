"""Integration tests for MongoDBSessionRepository (requires MongoDB)."""

from datetime import UTC, datetime
from typing import Any

import pytest
from pymongo import MongoClient, monitoring
from strands.types.session import Session, SessionAgent, SessionMessage

from mongodb_session_manager.mongodb_session_repository import MongoDBSessionRepository

pytestmark = pytest.mark.integration


class ProjectionRecorder(monitoring.CommandListener):
    """Capture the projections that a real MongoDB receives in find commands."""

    def __init__(self) -> None:
        self.projections: list[dict[str, Any]] = []
        self.commands: list[tuple[str, dict[str, Any]]] = []
        self.enabled = False

    def started(self, event: Any) -> None:
        if not self.enabled:
            return
        self.commands.append((event.command_name, dict(event.command)))
        if event.command_name == "find":
            self.projections.append(dict(event.command.get("projection", {})))

    def succeeded(self, event: Any) -> None:
        # The assertion concerns the projection sent in started(); the listener
        # interface still requires a success callback.
        pass

    def failed(self, event: Any) -> None:
        # A failed command has already exposed its projection in started() and
        # the repository call propagates the error to the test.
        pass


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


@pytest.fixture
def projection_repo(mongodb_connection, unique_session_id, cleanup_session):
    """Repository whose client records the find command sent over the wire."""
    recorder = ProjectionRecorder()
    client = MongoClient(mongodb_connection, event_listeners=[recorder])
    repository = MongoDBSessionRepository(
        client=client,
        database_name="test_db",
        collection_name="test_sessions",
        application_name="integration-test",
    )
    cleanup_session(repository.collection, unique_session_id)
    yield repository, recorder
    repository.close()
    client.close()


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

    def test_read_session_projects_only_the_header_on_mongodb(
        self, projection_repo, unique_session_id
    ):
        repo, recorder = projection_repo
        repo.create_session(Session(session_id=unique_session_id, session_type="chat"))
        recorder.enabled = True

        result = repo.read_session(unique_session_id)

        assert result is not None
        assert recorder.projections == [
            {
                "session_id": 1,
                "session_type": 1,
                "created_at": 1,
                "updated_at": 1,
            }
        ]

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

    def test_read_agent_projects_agent_data_and_keeps_config_on_mongodb(
        self, projection_repo, unique_session_id
    ):
        repo, recorder = projection_repo
        repo.create_session(Session(session_id=unique_session_id, session_type="chat"))
        repo.create_agent(
            unique_session_id,
            SessionAgent(
                agent_id="agent-1",
                state={"key": "value"},
                conversation_manager_state={},
            ),
        )
        repo.collection.update_one(
            {"_id": unique_session_id},
            {
                "$set": {
                    "agents.agent-1.agent_data.model": "model-1",
                    "agents.agent-1.agent_data.system_prompt": "prompt-1",
                }
            },
        )
        repo.create_message(
            unique_session_id,
            "agent-1",
            SessionMessage(
                message_id=0,
                message={"role": "user", "content": [{"text": "hello"}]},
            ),
        )
        recorder.enabled = True

        result = repo.read_agent(unique_session_id, "agent-1")

        assert result is not None
        assert result.state == {"key": "value"}
        assert repo.pop_read_agent_config(unique_session_id, "agent-1") == {
            "model": "model-1",
            "system_prompt": "prompt-1",
        }
        assert recorder.projections == [{"agents.agent-1.agent_data": 1}]

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

    def test_update_preserves_agent_config(self, repo, unique_session_id):
        """update_agent no borra lo que el session manager guarda en agent_data.

        SessionAgent no conoce model, system_prompt ni prompt_metadata: un $set
        del subdocumento entero los borraba en cada sync del SDK.
        """
        session = Session(session_id=unique_session_id, session_type="default")
        repo.create_session(session)

        agent = SessionAgent(
            agent_id="agent-1",
            state={"old": "state"},
            conversation_manager_state={},
        )
        repo.create_agent(unique_session_id, agent)
        repo.collection.update_one(
            {"_id": unique_session_id},
            {
                "$set": {
                    "agents.agent-1.agent_data.model": "claude-3",
                    "agents.agent-1.agent_data.system_prompt": "You are helpful",
                    "agents.agent-1.agent_data.prompt_metadata": {"prompt_id": "p1"},
                }
            },
        )

        agent_updated = SessionAgent(
            agent_id="agent-1",
            state={"new": "state"},
            conversation_manager_state={},
        )
        repo.update_agent(unique_session_id, agent_updated)

        doc = repo.collection.find_one({"_id": unique_session_id})
        agent_data = doc["agents"]["agent-1"]["agent_data"]
        assert agent_data["model"] == "claude-3"
        assert agent_data["system_prompt"] == "You are helpful"
        assert agent_data["prompt_metadata"] == {"prompt_id": "p1"}
        # The SDK fields are still replaced whole, not merged.
        assert agent_data["state"] == {"new": "state"}

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

    def test_single_message_count_and_configs_are_server_side(
        self, projection_repo, unique_session_id
    ):
        repo, recorder = projection_repo
        repo.create_session(Session(session_id=unique_session_id, session_type="chat"))
        repo.create_agent(
            unique_session_id,
            SessionAgent(agent_id="a1", state={}, conversation_manager_state={}),
        )
        repo.create_message(
            unique_session_id,
            "a1",
            SessionMessage(
                message_id=0,
                message={"role": "user", "content": [{"text": "hello"}]},
            ),
        )
        recorder.enabled = True

        assert repo.read_message(unique_session_id, "a1", 0) is not None
        assert repo.count_messages(unique_session_id, "a1") == 1
        assert repo.list_agent_configs(unique_session_id)[0]["agent_id"] == "a1"

        assert [name for name, _ in recorder.commands] == [
            "aggregate",
            "aggregate",
            "aggregate",
        ]
        pipelines = [command["pipeline"] for _, command in recorder.commands]
        assert "$filter" in repr(pipelines[0])
        assert "$arrayElemAt" in repr(pipelines[0])
        assert "$size" in repr(pipelines[1])
        assert "$objectToArray" in repr(pipelines[2])
        assert "messages" not in repr(pipelines[2])
        assert "state" not in repr(pipelines[2])

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

    def test_a_long_history_is_drained_without_a_second_round_trip(
        self, projection_repo, unique_session_id
    ):
        """Restaurar el historial cuesta un `aggregate` y ningún `getMore` (#92).

        Con el tamaño de lote por defecto, DocumentDB corta el cursor cada ~101
        documentos: 5.000 mensajes salían en 49 `getMore` de 94 ms, 5,04 s de
        restauración. Aquí bastan 200 mensajes para pasar de 101 y ver el
        cursor partirse; el test no mide tiempo, cuenta round-trips.
        """
        repo, recorder = projection_repo
        repo.create_session(Session(session_id=unique_session_id, session_type="chat"))
        repo.create_agent(
            unique_session_id,
            SessionAgent(agent_id="a1", state={}, conversation_manager_state={}),
        )
        history = 200
        now = datetime.now(UTC)
        repo.collection.update_one(
            {"_id": unique_session_id},
            {
                "$push": {
                    "agents.a1.messages": {
                        "$each": [
                            {
                                "message_id": i,
                                "storage_id": f"s{i:04d}",
                                "message": {
                                    "role": "user",
                                    "content": [{"text": "x" * 512}],
                                },
                                "created_at": now,
                                "updated_at": now,
                            }
                            for i in range(history)
                        ]
                    }
                }
            },
        )
        recorder.enabled = True

        messages = repo.list_messages(unique_session_id, "a1")

        assert len(messages) == history
        commands = [name for name, _ in recorder.commands]
        assert commands == ["aggregate"], f"el cursor necesitó varios lotes: {commands}"

    def test_server_sorts_before_paginating_and_puts_missing_dates_last(
        self, projection_repo, unique_session_id
    ):
        repo, recorder = projection_repo
        repo.create_session(Session(session_id=unique_session_id, session_type="chat"))
        repo.create_agent(
            unique_session_id,
            SessionAgent(agent_id="a1", state={}, conversation_manager_state={}),
        )
        for message_id in range(3):
            repo.create_message(
                unique_session_id,
                "a1",
                SessionMessage(
                    message_id=message_id,
                    message={
                        "role": "user",
                        "content": [{"text": f"m{message_id}"}],
                    },
                ),
            )
        repo.collection.update_one(
            {"_id": unique_session_id, "agents.a1.messages.message_id": 0},
            {
                "$set": {
                    "agents.a1.messages.$.created_at": datetime(2026, 1, 2, tzinfo=UTC)
                }
            },
        )
        repo.collection.update_one(
            {"_id": unique_session_id, "agents.a1.messages.message_id": 1},
            {
                "$set": {
                    "agents.a1.messages.$.created_at": datetime(2026, 1, 1, tzinfo=UTC)
                }
            },
        )
        repo.collection.update_one(
            {"_id": unique_session_id, "agents.a1.messages.message_id": 2},
            {"$unset": {"agents.a1.messages.$.created_at": ""}},
        )
        recorder.enabled = True

        page = repo.list_messages(unique_session_id, "a1", limit=2, offset=1)

        assert [message.message_id for message in page] == [0, 2]
        assert [name for name, _ in recorder.commands] == ["aggregate"]
        pipeline = recorder.commands[0][1]["pipeline"]
        assert {"$skip": 1} in pipeline
        assert {"$limit": 2} in pipeline
        assert pipeline[-1] == {
            "$sort": {
                "_missing_created_at": 1,
                "message.created_at": 1,
                "_array_index": 1,
            }
        }

    def _seed_message(self, repo, session_id, text="original"):
        """Sesión + agente `a1` + un mensaje con message_id 1.

        Devuelve el SessionMessage creado, que vuelve con su identidad puesta
        por `create_message()` -- igual que lo recibe Strands.
        """
        repo.create_session(Session(session_id=session_id, session_type="default"))
        repo.create_agent(
            session_id,
            SessionAgent(agent_id="a1", state={}, conversation_manager_state={}),
        )
        message = SessionMessage(
            message_id=1,
            message={"role": "user", "content": [{"text": text}]},
        )
        repo.create_message(session_id, "a1", message)
        return message

    @staticmethod
    def _redaction(message_id=1, text="original"):
        return SessionMessage(
            message_id=message_id,
            message={"role": "user", "content": [{"text": text}]},
            redact_message={"role": "user", "content": [{"text": "***"}]},
        )

    def test_update_message(self, repo, unique_session_id):
        self._seed_message(repo, unique_session_id)

        repo.update_message(unique_session_id, "a1", self._redaction())

        result = repo.read_message(unique_session_id, "a1", 1)
        assert result is not None
        assert result.redact_message is not None

    def test_update_message_preserves_manager_fields(self, repo, unique_session_id):
        """Redactar no borra lo que el session manager guarda en el mensaje.

        event_loop_metrics y guardrail_event viven en el documento del mensaje,
        pero SessionMessage no los conoce: el $set del subdocumento entero los
        borraba en cada redacción.
        """
        self._seed_message(repo, unique_session_id, text="sensitive")
        metrics = {"accumulated_usage": {"totalTokens": 1280}}
        event = {"action": "BLOCKED"}
        repo.collection.update_one(
            {"_id": unique_session_id, "agents.a1.messages.message_id": 1},
            {
                "$set": {
                    "agents.a1.messages.$.event_loop_metrics": metrics,
                    "agents.a1.messages.$.guardrail_event": event,
                }
            },
        )

        repo.update_message(unique_session_id, "a1", self._redaction(text="sensitive"))

        stored = repo.collection.find_one({"_id": unique_session_id})
        message_doc = stored["agents"]["a1"]["messages"][0]
        assert message_doc["event_loop_metrics"] == metrics
        assert message_doc["guardrail_event"] == event
        assert message_doc["redact_message"]["content"][0]["text"] == "***"

    def test_update_message_preserves_created_at(self, repo, unique_session_id):
        """Contrato: created_at conserva valor y tipo; updated_at avanza."""
        self._seed_message(repo, unique_session_id)
        before = repo.collection.find_one({"_id": unique_session_id})["agents"]["a1"][
            "messages"
        ][0]

        repo.update_message(unique_session_id, "a1", self._redaction())

        after = repo.collection.find_one({"_id": unique_session_id})["agents"]["a1"][
            "messages"
        ][0]
        assert after["created_at"] == before["created_at"]
        assert isinstance(after["created_at"], datetime)
        assert after["updated_at"] >= before["updated_at"]

    def test_update_message_raises_for_unknown_message(self, repo, unique_session_id):
        self._seed_message(repo, unique_session_id)

        with pytest.raises(ValueError, match="Message 99 not found"):
            repo.update_message(unique_session_id, "a1", self._redaction(message_id=99))

    def test_update_message_raises_for_unknown_agent(self, repo, unique_session_id):
        self._seed_message(repo, unique_session_id)

        with pytest.raises(ValueError, match="Agent ghost not found"):
            repo.update_message(unique_session_id, "ghost", self._redaction())

    def test_duplicate_message_id_redacts_its_own_message(
        self, repo, unique_session_id
    ):
        """message_id no es una identidad única, y aun así se acierta. Ver #78.

        Strands deriva el id en memoria (`append_message`: latest.message_id + 1),
        así que dos managers concurrentes pueden duplicarlo. La redacción va
        contra el SessionMessage que devolvió `create_message()`, que lleva su
        storage_id: el operador posicional casa con ese, no con el primero que
        comparte índice.
        """
        self._seed_message(repo, unique_session_id, text="first")
        second = SessionMessage(
            message_id=1,
            message={"role": "user", "content": [{"text": "second"}]},
        )
        repo.create_message(unique_session_id, "a1", second)
        second.redact_message = {"role": "user", "content": [{"text": "***"}]}

        repo.update_message(unique_session_id, "a1", second)

        messages = repo.collection.find_one({"_id": unique_session_id})["agents"]["a1"][
            "messages"
        ]
        assert messages[0]["redact_message"] is None
        assert messages[1]["redact_message"]["content"][0]["text"] == "***"

    def test_message_stored_before_the_identity_is_still_redactable(
        self, repo, unique_session_id
    ):
        """Compatibilidad: sin storage_id se localiza por índice, como siempre."""
        self._seed_message(repo, unique_session_id)
        repo.collection.update_one(
            {"_id": unique_session_id},
            {"$unset": {"agents.a1.messages.$[].storage_id": ""}},
        )

        repo.update_message(unique_session_id, "a1", self._redaction())

        message_doc = repo.collection.find_one({"_id": unique_session_id})["agents"][
            "a1"
        ]["messages"][0]
        assert "storage_id" not in message_doc
        assert message_doc["redact_message"]["content"][0]["text"] == "***"


# ---------------------------------------------------------------------------
# Metadata lifecycle
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Redact message lifecycle
# ---------------------------------------------------------------------------


class TestRedactMessageLifecycle:
    def test_redact_message_persists_and_reads(self, repo, unique_session_id):
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
            message={"role": "user", "content": [{"text": "sensitive data"}]},
        )
        repo.create_message(unique_session_id, "a1", msg)

        # Update with redact_message
        redacted = SessionMessage(
            message_id=1,
            message={"role": "user", "content": [{"text": "sensitive data"}]},
            redact_message={"role": "user", "content": [{"text": "***"}]},
        )
        repo.update_message(unique_session_id, "a1", redacted)

        result = repo.read_message(unique_session_id, "a1", 1)
        assert result is not None
        assert result.redact_message is not None
        assert result.redact_message["content"][0]["text"] == "***"

        # to_message() should return the redacted content
        message = result.to_message()
        assert message["content"][0]["text"] == "***"

    def test_guardrail_events_field_exists_on_creation(self, repo, unique_session_id):
        session = Session(session_id=unique_session_id, session_type="default")
        repo.create_session(session)

        doc = repo.collection.find_one({"_id": unique_session_id})
        assert "guardrail_events" in doc
        assert doc["guardrail_events"] == []


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
