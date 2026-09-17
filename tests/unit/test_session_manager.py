"""Unit tests for MongoDBSessionManager."""

import warnings
from unittest.mock import MagicMock, patch

import pytest
from strands.agent.state import AgentState
from strands.experimental.bidi.hooks import BidiAgentStopEvent
from strands.hooks import HookRegistry
from strands.types.exceptions import SessionException
from strands.types.session import SessionAgent, SessionMessage

from mongodb_session_manager.mongodb_session_manager import (
    MongoDBSessionManager,
    create_mongodb_session_manager,
)
from mongodb_session_manager.mongodb_session_repository import MongoDBSessionRepository
from tests.support.in_memory_session_repository import InMemorySessionRepository


@pytest.fixture
def mock_repo():
    """Repository double limited to the real repository's public surface.

    The `spec=` is load-bearing: `collection` is an *instance* attribute, so it
    does not exist on the spec. Any raw pymongo access reintroduced in the
    manager raises AttributeError here instead of passing silently.
    """
    repo = MagicMock(spec=MongoDBSessionRepository)
    repo.read_session.return_value = None
    return repo


@pytest.fixture
def manager(mock_repo):
    """Create a MongoDBSessionManager with mocked repository."""
    with patch(
        "mongodb_session_manager.mongodb_session_manager.MongoDBSessionRepository",
        return_value=mock_repo,
    ):
        mgr = MongoDBSessionManager(
            session_id="test-session",
            connection_string="mongodb://localhost:27017/",
            database_name="test_db",
            collection_name="test_coll",
        )
    return mgr


@pytest.fixture
def fake_repo():
    """In-memory repository, to exercise the manager without MongoDB."""
    return InMemorySessionRepository()


@pytest.fixture
def manager_fake(fake_repo):
    """Manager backed by the in-memory double.

    Assertions land on what ends up stored, instead of on which pymongo command
    was emitted. The double exposes no `collection`, so a raw access
    reintroduced in the manager fails here instead of passing silently.
    """
    return MongoDBSessionManager(
        session_id="test-session", session_repository=fake_repo
    )


@pytest.fixture
def agent_in_session(fake_repo, manager_fake):
    """Add an agent "a1" to the session the manager created on construction."""
    fake_repo.create_agent(
        "test-session",
        SessionAgent(agent_id="a1", state={}, conversation_manager_state={}),
    )
    return manager_fake


@pytest.fixture
def stored_message(fake_repo, agent_in_session):
    """Give agent "a1" one stored message, the one a turn would annotate.

    The message is also registered as the agent's latest, which is what Strands
    does for every message it appends or restores. A manager that has not seen
    a message cannot claim the turn wrote it.
    """
    message = SessionMessage(
        message_id=5, message={"role": "assistant", "content": [{"text": "hi"}]}
    )
    fake_repo.create_message("test-session", "a1", message)
    agent_in_session._latest_agent_message["a1"] = message
    return agent_in_session


REDACTED: dict = {"role": "user", "content": [{"text": "***"}]}


def guardrail_events(fake_repo):
    """Return the session-level guardrail audit trail."""
    return fake_repo.session("test-session")["guardrail_events"]


@pytest.fixture
def syncable_agent(mock_agent):
    """Build an agent the parent class can sync without tripping over mocks.

    `state` es real porque `SessionAgent.from_agent()` guarda `state.get()`, y un
    MagicMock ahí solo se compara consigo mismo. Las versiones que el SDK miraba
    (`state._get_version()`, `_interrupt_state._get_version()`) ya no hacen falta:
    desde strands 1.56 `sync_agent()` ni las consulta para lo que no es un
    `Agent`, y un mock nunca lo es (#69).
    """

    def _build(**kwargs):
        agent = mock_agent(agent_id="a1", **kwargs)
        agent.state = AgentState()
        return agent

    return _build


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestSessionManagerInit:
    @patch("mongodb_session_manager.mongodb_session_manager.MongoDBSessionRepository")
    def test_passes_application_name_to_repo(self, mock_repo_cls):
        mock_repo_cls.return_value = MagicMock(
            read_session=MagicMock(return_value=None)
        )
        MongoDBSessionManager(
            session_id="s1",
            connection_string="mongodb://localhost:27017/",
            application_name="my-app",
        )
        call_kwargs = mock_repo_cls.call_args[1]
        assert call_kwargs["application_name"] == "my-app"

    @patch("mongodb_session_manager.mongodb_session_manager.MongoDBSessionRepository")
    def test_passes_metadata_fields_to_repo(self, mock_repo_cls):
        mock_repo_cls.return_value = MagicMock(
            read_session=MagicMock(return_value=None)
        )
        MongoDBSessionManager(
            session_id="s1",
            connection_string="mongodb://localhost:27017/",
            metadata_fields=["status"],
        )
        call_kwargs = mock_repo_cls.call_args[1]
        assert call_kwargs["metadata_fields"] == ["status"]

    @patch("mongodb_session_manager.mongodb_session_manager.MongoDBSessionRepository")
    def test_applies_metadata_hook(self, mock_repo_cls):
        mock_repo_cls.return_value = MagicMock(
            read_session=MagicMock(return_value=None)
        )
        hook = MagicMock()
        mgr = MongoDBSessionManager(
            session_id="s1",
            connection_string="mongodb://localhost:27017/",
            metadata_hook=hook,
        )
        # After hook applied, update_metadata should be wrapped
        mgr.update_metadata({"key": "val"})
        hook.assert_called_once()

    @patch("mongodb_session_manager.mongodb_session_manager.MongoDBSessionRepository")
    def test_applies_feedback_hook(self, mock_repo_cls):
        mock_repo_cls.return_value = MagicMock(
            read_session=MagicMock(return_value=None)
        )
        hook = MagicMock()
        mgr = MongoDBSessionManager(
            session_id="s1",
            connection_string="mongodb://localhost:27017/",
            feedback_hook=hook,
        )
        mgr.add_feedback({"rating": "up"})
        hook.assert_called_once()

    @patch("mongodb_session_manager.mongodb_session_manager.MongoDBSessionRepository")
    def test_deprecation_warning_camel_case_metadata_hook(self, mock_repo_cls):
        mock_repo_cls.return_value = MagicMock(
            read_session=MagicMock(return_value=None)
        )
        hook = MagicMock()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            MongoDBSessionManager(
                session_id="s1",
                connection_string="mongodb://localhost:27017/",
                metadataHook=hook,
            )
        assert any(
            "metadataHook is deprecated" in str(warning.message) for warning in w
        )

    @patch("mongodb_session_manager.mongodb_session_manager.MongoDBSessionRepository")
    def test_deprecation_warning_camel_case_feedback_hook(self, mock_repo_cls):
        mock_repo_cls.return_value = MagicMock(
            read_session=MagicMock(return_value=None)
        )
        hook = MagicMock()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            MongoDBSessionManager(
                session_id="s1",
                connection_string="mongodb://localhost:27017/",
                feedbackHook=hook,
            )
        assert any(
            "feedbackHook is deprecated" in str(warning.message) for warning in w
        )

    @patch("mongodb_session_manager.mongodb_session_manager.MongoDBSessionRepository")
    def test_passes_mongo_options_to_repo(self, mock_repo_cls):
        mock_repo_cls.return_value = MagicMock(
            read_session=MagicMock(return_value=None)
        )
        MongoDBSessionManager(
            session_id="s1",
            connection_string="mongodb://localhost:27017/",
            maxPoolSize=50,
        )
        call_kwargs = mock_repo_cls.call_args[1]
        assert call_kwargs.get("maxPoolSize") == 50

    @patch("mongodb_session_manager.mongodb_session_manager.MongoDBSessionRepository")
    def test_create_factory_function(self, mock_repo_cls):
        mock_repo_cls.return_value = MagicMock(
            read_session=MagicMock(return_value=None)
        )
        mgr = create_mongodb_session_manager(
            session_id="s1",
            connection_string="mongodb://localhost:27017/",
            application_name="test",
        )
        assert isinstance(mgr, MongoDBSessionManager)


# ---------------------------------------------------------------------------
# sync_agent / metrics extraction
# ---------------------------------------------------------------------------


class TestSyncAgent:
    """Contra el doble: se comprueba dónde acaban las métricas, no la ruta escrita."""

    def test_stores_usage_on_the_last_message(
        self, stored_message, fake_repo, syncable_agent
    ):
        stored_message.sync_agent(
            syncable_agent(input_tokens=500, output_tokens=200, total_tokens=700)
        )

        usage = fake_repo.message("test-session", "a1", 5)["event_loop_metrics"][
            "accumulated_usage"
        ]
        assert usage["inputTokens"] == 500
        assert usage["outputTokens"] == 200
        assert usage["totalTokens"] == 700

    def test_skips_metrics_when_latency_zero(
        self, stored_message, fake_repo, syncable_agent
    ):
        """Sin latencia no hubo turno que medir."""
        stored_message.sync_agent(syncable_agent(latency_ms=0))

        assert "event_loop_metrics" not in fake_repo.message("test-session", "a1", 5)

    def test_captures_cycle_metrics(self, stored_message, fake_repo, syncable_agent):
        stored_message.sync_agent(
            syncable_agent(cycle_count=3, total_duration=4.5, average_cycle_time=1.5)
        )

        cycles = fake_repo.message("test-session", "a1", 5)["event_loop_metrics"][
            "cycle_metrics"
        ]
        assert cycles["cycle_count"] == 3
        assert cycles["total_duration"] == pytest.approx(4.5)

    def test_captures_tool_usage(self, stored_message, fake_repo, syncable_agent):
        tool_usage = {
            "search": {
                "execution_stats": {
                    "call_count": 5,
                    "success_count": 4,
                    "error_count": 1,
                    "total_time": 2.5,
                    "average_time": 0.5,
                    "success_rate": 0.8,
                }
            }
        }

        stored_message.sync_agent(syncable_agent(tool_usage=tool_usage))

        stored = fake_repo.message("test-session", "a1", 5)["event_loop_metrics"][
            "tool_usage"
        ]
        assert stored["search"]["call_count"] == 5
        assert stored["search"]["success_rate"] == pytest.approx(0.8)

    def test_captures_agent_config_model(self, stored_message, syncable_agent):
        stored_message.sync_agent(
            syncable_agent(model_id="claude-3-sonnet", latency_ms=0)
        )

        assert stored_message.get_agent_config("a1")["model"] == "claude-3-sonnet"

    def test_captures_agent_config_system_prompt(self, stored_message, syncable_agent):
        stored_message.sync_agent(
            syncable_agent(system_prompt="You are helpful", latency_ms=0)
        )

        assert (
            stored_message.get_agent_config("a1")["system_prompt"] == "You are helpful"
        )

    def test_metrics_and_config_land_together(
        self, stored_message, fake_repo, syncable_agent
    ):
        """Ambas mitades viajan en la misma escritura, así que ambas deben estar."""
        stored_message.sync_agent(
            syncable_agent(latency_ms=100, model_id="m1", system_prompt="p")
        )

        assert "event_loop_metrics" in fake_repo.message("test-session", "a1", 5)
        assert stored_message.get_agent_config("a1")["model"] == "m1"

    def test_agent_without_messages_records_no_metrics(
        self, agent_in_session, fake_repo, syncable_agent
    ):
        """Sin mensajes no hay dónde anotar las métricas, y no puede reventar."""
        agent_in_session.sync_agent(syncable_agent(latency_ms=100, model_id="m1"))

        assert fake_repo.count_messages("test-session", "a1") == 0
        # La configuración sí se persiste: va por su propia rama de escritura.
        assert agent_in_session.get_agent_config("a1")["model"] == "m1"


# ---------------------------------------------------------------------------
# Agentes sin event loop: el BidiAgent (#69)
# ---------------------------------------------------------------------------


class TestAgentWithoutEventLoop:
    """Un `BidiAgent` no tiene event loop, y desde strands 1.56 llega aquí.

    Hasta 1.55 el SDK lo sincronizaba por `sync_bidi_agent()`, un método aparte
    que este manager no sobrescribía. 1.56 borra esa familia de métodos y
    enruta `BidiAgentStopEvent` al mismo `sync_agent()` que usa un `Agent`.
    """

    def test_the_bidi_stop_event_syncs_without_metrics(
        self, stored_message, fake_repo, mock_agent
    ):
        """Pedirle las métricas a un agente que no las tiene no puede reventar.

        El evento se dispara por el registry de verdad, en vez de llamar a
        `sync_agent()` a mano: lo que hay que fijar es el camino entero, porque
        es el SDK quien decidió mandar los dos tipos de agente al mismo sitio.
        """
        agent = mock_agent(agent_id="a1", latency_ms=100, model_id="m1")
        agent.state = AgentState()
        del agent.event_loop_metrics  # como un BidiAgent: no hay event loop

        registry = HookRegistry()
        stored_message.register_hooks(registry)
        registry.invoke_callbacks(BidiAgentStopEvent(agent=agent))

        assert "event_loop_metrics" not in fake_repo.message("test-session", "a1", 5)
        # La configuración sí viaja: esa no sale del event loop.
        assert stored_message.get_agent_config("a1")["model"] == "m1"


# ---------------------------------------------------------------------------
# _extract_tool_usage
# ---------------------------------------------------------------------------


class TestExtractToolUsage:
    def test_simplifies_stats(self, manager):
        raw = {
            "search": {
                "tool_info": {"name": "search"},
                "execution_stats": {
                    "call_count": 5,
                    "success_count": 4,
                    "error_count": 1,
                    "total_time": 2.5,
                    "average_time": 0.5,
                    "success_rate": 0.8,
                },
            }
        }
        result = manager._extract_tool_usage(raw)
        assert result["search"]["call_count"] == 5
        assert "tool_info" not in result["search"]

    def test_empty_tool_usage(self, manager):
        assert manager._extract_tool_usage({}) == {}

    def test_multiple_tools(self, manager):
        raw = {
            "tool_a": {
                "execution_stats": {
                    "call_count": 1,
                    "success_count": 1,
                    "error_count": 0,
                    "total_time": 0.1,
                    "average_time": 0.1,
                    "success_rate": 1.0,
                }
            },
            "tool_b": {
                "execution_stats": {
                    "call_count": 2,
                    "success_count": 2,
                    "error_count": 0,
                    "total_time": 0.2,
                    "average_time": 0.1,
                    "success_rate": 1.0,
                }
            },
        }
        result = manager._extract_tool_usage(raw)
        assert len(result) == 2

    def test_missing_execution_stats(self, manager):
        raw = {"tool_x": {"tool_info": {"name": "tool_x"}}}
        result = manager._extract_tool_usage(raw)
        assert result["tool_x"]["call_count"] == 0


# ---------------------------------------------------------------------------
# _extract_model_id
# ---------------------------------------------------------------------------


class TestExtractModelId:
    def test_from_config_dict(self, manager):
        agent = MagicMock()
        agent.model.config = {"model_id": "claude-3-opus"}
        result = manager._extract_model_id(agent)
        assert result == "claude-3-opus"

    def test_from_model_id_attribute(self, manager):
        agent = MagicMock()
        agent.model.config = {}
        agent.model.model_id = "claude-3-haiku"
        result = manager._extract_model_id(agent)
        assert result == "claude-3-haiku"

    def test_fallback_to_str(self, manager):
        agent = MagicMock()
        agent.model.config = {}
        del agent.model.model_id
        agent.model.__str__ = MagicMock(return_value="custom-model")
        result = manager._extract_model_id(agent)
        assert result == "custom-model"

    def test_returns_none_without_model(self, manager):
        agent = MagicMock(spec=[])
        result = manager._extract_model_id(agent)
        assert result is None


# ---------------------------------------------------------------------------
# Metadata operations
# ---------------------------------------------------------------------------


class TestMetadataOperations:
    def test_update_metadata_delegates(self, manager, mock_repo):
        # Reset mock after init
        mock_repo.reset_mock()
        manager.update_metadata({"key": "val"})
        mock_repo.update_metadata.assert_called_once_with(
            "test-session", {"key": "val"}
        )

    def test_get_metadata_delegates(self, manager, mock_repo):
        mock_repo.reset_mock()
        manager.get_metadata()
        mock_repo.get_metadata.assert_called_once_with("test-session")

    def test_delete_metadata_delegates(self, manager, mock_repo):
        mock_repo.reset_mock()
        manager.delete_metadata(["key1"])
        mock_repo.delete_metadata.assert_called_once_with("test-session", ["key1"])


# ---------------------------------------------------------------------------
# _apply_metadata_hook
# ---------------------------------------------------------------------------


class TestApplyMetadataHook:
    def test_wraps_update_metadata(self):
        hook = MagicMock()
        with patch(
            "mongodb_session_manager.mongodb_session_manager.MongoDBSessionRepository"
        ) as mock_cls:
            mock_cls.return_value = MagicMock(read_session=MagicMock(return_value=None))
            mgr = MongoDBSessionManager(
                session_id="s1",
                connection_string="mongodb://localhost:27017/",
                metadata_hook=hook,
            )
        mgr.update_metadata({"key": "val"})
        hook.assert_called_once()
        args = hook.call_args
        assert args[0][1] == "update"
        assert args[0][2] == "s1"

    def test_wraps_get_metadata(self):
        hook = MagicMock()
        with patch(
            "mongodb_session_manager.mongodb_session_manager.MongoDBSessionRepository"
        ) as mock_cls:
            mock_cls.return_value = MagicMock(read_session=MagicMock(return_value=None))
            mgr = MongoDBSessionManager(
                session_id="s1",
                connection_string="mongodb://localhost:27017/",
                metadata_hook=hook,
            )
        mgr.get_metadata()
        args = hook.call_args
        assert args[0][1] == "get"

    def test_wraps_delete_metadata(self):
        hook = MagicMock()
        with patch(
            "mongodb_session_manager.mongodb_session_manager.MongoDBSessionRepository"
        ) as mock_cls:
            mock_cls.return_value = MagicMock(read_session=MagicMock(return_value=None))
            mgr = MongoDBSessionManager(
                session_id="s1",
                connection_string="mongodb://localhost:27017/",
                metadata_hook=hook,
            )
        mgr.delete_metadata(["k1"])
        args = hook.call_args
        assert args[0][1] == "delete"

    def test_hook_receives_correct_session_id(self):
        hook = MagicMock()
        with patch(
            "mongodb_session_manager.mongodb_session_manager.MongoDBSessionRepository"
        ) as mock_cls:
            mock_cls.return_value = MagicMock(read_session=MagicMock(return_value=None))
            mgr = MongoDBSessionManager(
                session_id="my-session",
                connection_string="mongodb://localhost:27017/",
                metadata_hook=hook,
            )
        mgr.update_metadata({"x": 1})
        assert hook.call_args[0][2] == "my-session"


# ---------------------------------------------------------------------------
# _apply_feedback_hook
# ---------------------------------------------------------------------------


class TestApplyFeedbackHook:
    def test_wraps_add_feedback(self):
        hook = MagicMock()
        with patch(
            "mongodb_session_manager.mongodb_session_manager.MongoDBSessionRepository"
        ) as mock_cls:
            mock_cls.return_value = MagicMock(read_session=MagicMock(return_value=None))
            mgr = MongoDBSessionManager(
                session_id="s1",
                connection_string="mongodb://localhost:27017/",
                feedback_hook=hook,
            )
        mgr.add_feedback({"rating": "up"})
        hook.assert_called_once()
        args = hook.call_args
        assert args[0][1] == "add"

    def test_hook_receives_session_manager(self):
        hook = MagicMock()
        with patch(
            "mongodb_session_manager.mongodb_session_manager.MongoDBSessionRepository"
        ) as mock_cls:
            mock_cls.return_value = MagicMock(read_session=MagicMock(return_value=None))
            mgr = MongoDBSessionManager(
                session_id="s1",
                connection_string="mongodb://localhost:27017/",
                feedback_hook=hook,
            )
        mgr.add_feedback({"rating": "down"})
        kwargs = hook.call_args[1]
        assert kwargs["session_manager"] is mgr


# ---------------------------------------------------------------------------
# get_metadata_tool
# ---------------------------------------------------------------------------


class TestGetMetadataTool:
    def test_returns_callable(self, manager):
        tool = manager.get_metadata_tool()
        assert callable(tool)

    def test_handles_get_action(self, manager, mock_repo):
        mock_repo.get_metadata.return_value = {"metadata": {"key": "val"}}
        tool = manager.get_metadata_tool()
        result = tool(action="get")
        assert "key" in result

    def test_handles_set_action(self, manager, mock_repo):
        mock_repo.reset_mock()
        tool = manager.get_metadata_tool()
        result = tool(action="set", metadata={"key": "val"})
        assert "Successfully" in result

    def test_handles_update_action(self, manager, mock_repo):
        mock_repo.reset_mock()
        tool = manager.get_metadata_tool()
        result = tool(action="update", metadata={"key": "val"})
        assert "Successfully" in result

    def test_handles_delete_action(self, manager, mock_repo):
        mock_repo.reset_mock()
        tool = manager.get_metadata_tool()
        result = tool(action="delete", keys=["key1"])
        assert "Successfully" in result

    def test_handles_unknown_action(self, manager):
        tool = manager.get_metadata_tool()
        result = tool(action="invalid")
        assert "Unknown action" in result

    def test_handles_json_string_metadata(self, manager, mock_repo):
        mock_repo.reset_mock()
        tool = manager.get_metadata_tool()
        result = tool(action="set", metadata='{"key": "val"}')
        assert "Successfully" in result

    def test_handles_json_string_keys(self, manager, mock_repo):
        mock_repo.reset_mock()
        tool = manager.get_metadata_tool()
        result = tool(action="delete", keys='["key1", "key2"]')
        assert "Successfully" in result

    def test_handles_invalid_json(self, manager):
        tool = manager.get_metadata_tool()
        result = tool(action="set", metadata="{invalid json")
        assert "Error" in result


# ---------------------------------------------------------------------------
# _parse_json_param
# ---------------------------------------------------------------------------


class TestParseJsonParam:
    def test_parses_valid_json_string(self, manager):
        val, err = manager._parse_json_param('{"key": "val"}', "test")
        assert val == {"key": "val"}
        assert err is None

    def test_returns_non_string_as_is(self, manager):
        val, err = manager._parse_json_param({"key": "val"}, "test")
        assert val == {"key": "val"}
        assert err is None

    def test_returns_error_on_invalid_json(self, manager):
        val, err = manager._parse_json_param("{bad", "test")
        assert val is None
        assert "Error" in err

    def test_returns_none_as_is(self, manager):
        val, err = manager._parse_json_param(None, "test")
        assert val is None
        assert err is None


# ---------------------------------------------------------------------------
# Agent config operations
# ---------------------------------------------------------------------------


class TestAgentConfigOperations:
    """Contra el doble in-memory: se comprueba el efecto, no el comando emitido."""

    def test_get_agent_config(self, agent_in_session, fake_repo):
        fake_repo.update_agent_fields(
            "test-session",
            "a1",
            {"agent_data.model": "claude-3", "agent_data.system_prompt": "helpful"},
        )

        result = agent_in_session.get_agent_config("a1")

        assert result["model"] == "claude-3"
        assert result["system_prompt"] == "helpful"

    def test_get_agent_config_returns_none(self, agent_in_session):
        assert agent_in_session.get_agent_config("missing") is None

    def test_update_agent_config_persists_the_model(self, agent_in_session):
        agent_in_session.update_agent_config("a1", model="new-model")

        assert agent_in_session.get_agent_config("a1")["model"] == "new-model"

    def test_update_agent_config_writes_only_what_it_is_given(self, agent_in_session):
        """Actualizar el modelo no puede borrar el system_prompt."""
        agent_in_session.update_agent_config("a1", system_prompt="original")
        agent_in_session.update_agent_config("a1", model="new-model")

        config = agent_in_session.get_agent_config("a1")
        assert config["model"] == "new-model"
        assert config["system_prompt"] == "original"

    def test_update_agent_config_raises_when_session_missing(
        self, agent_in_session, fake_repo
    ):
        fake_repo._sessions.clear()

        with pytest.raises(ValueError, match="Session test-session not found"):
            agent_in_session.update_agent_config("a1", model="x")

    def test_list_agents(self, agent_in_session, fake_repo):
        fake_repo.create_agent(
            "test-session",
            SessionAgent(agent_id="a2", state={}, conversation_manager_state={}),
        )

        assert len(agent_in_session.list_agents()) == 2

    def test_get_agent_config_includes_prompt_metadata(self, agent_in_session):
        metadata = {
            "prompt_id": "p1",
            "prompt_name": "Support",
            "prompt_version": "1.0.0",
            "deployment_id": "d1",
            "deployment_name": "prod",
            "temperature": 0.7,
        }
        agent_in_session.update_agent_config("a1", prompt_metadata=metadata)

        result = agent_in_session.get_agent_config("a1")

        assert result["prompt_metadata"]["prompt_id"] == "p1"
        assert result["prompt_metadata"]["prompt_version"] == "1.0.0"
        assert result["prompt_metadata"]["temperature"] == pytest.approx(0.7)

    def test_get_agent_config_prompt_metadata_none_when_absent(self, agent_in_session):
        agent_in_session.update_agent_config("a1", model="claude-3")

        assert agent_in_session.get_agent_config("a1")["prompt_metadata"] is None

    def test_update_agent_config_with_prompt_metadata(self, agent_in_session):
        metadata = {
            "prompt_id": "p1",
            "prompt_name": "Support",
            "prompt_version": "1.0.0",
            "deployment_id": "d1",
            "deployment_name": "prod",
            "temperature": 0.5,
        }

        agent_in_session.update_agent_config("a1", prompt_metadata=metadata)

        assert agent_in_session.get_agent_config("a1")["prompt_metadata"] == metadata

    def test_list_agents_includes_prompt_metadata(self, agent_in_session, fake_repo):
        fake_repo.create_agent(
            "test-session",
            SessionAgent(agent_id="a2", state={}, conversation_manager_state={}),
        )
        agent_in_session.update_agent_config("a1", prompt_metadata={"prompt_id": "p1"})

        result = agent_in_session.list_agents()

        a1 = next(a for a in result if a["agent_id"] == "a1")
        a2 = next(a for a in result if a["agent_id"] == "a2")
        assert a1["prompt_metadata"]["prompt_id"] == "p1"
        assert a2["prompt_metadata"] is None

    def test_get_message_count(self, agent_in_session, fake_repo):
        for index in range(3):
            fake_repo.create_message(
                "test-session",
                "a1",
                SessionMessage(
                    message_id=index,
                    message={"role": "user", "content": [{"text": "hi"}]},
                ),
            )

        assert agent_in_session.get_message_count("a1") == 3

    def test_get_message_count_is_zero_for_an_unknown_agent(self, agent_in_session):
        assert agent_in_session.get_message_count("ghost") == 0


# ---------------------------------------------------------------------------
# set_prompt_metadata
# ---------------------------------------------------------------------------


class TestSetPromptMetadata:
    def test_set_prompt_metadata_happy_path(self, agent_in_session):
        metadata = {
            "prompt_id": "p1",
            "prompt_name": "Support",
            "prompt_version": "1.0.0",
            "deployment_id": "d1",
            "deployment_name": "prod",
            "temperature": 0.7,
        }

        agent_in_session.set_prompt_metadata("a1", metadata)

        assert agent_in_session.get_agent_config("a1")["prompt_metadata"] == metadata

    def test_set_prompt_metadata_preserves_the_agent_config(self, agent_in_session):
        """Estampar el linaje del prompt no puede tocar modelo ni system_prompt."""
        agent_in_session.update_agent_config(
            "a1", model="claude-opus-5", system_prompt="original"
        )

        agent_in_session.set_prompt_metadata("a1", {"prompt_id": "p1"})

        config = agent_in_session.get_agent_config("a1")
        assert config["model"] == "claude-opus-5"
        assert config["system_prompt"] == "original"

    def test_set_prompt_metadata_raises_when_session_missing(
        self, agent_in_session, fake_repo
    ):
        fake_repo._sessions.clear()

        with pytest.raises(ValueError, match="Session test-session not found"):
            agent_in_session.set_prompt_metadata("a1", {"prompt_id": "p1"})


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    def test_delegates_to_repository(self, manager, mock_repo):
        manager.close()
        mock_repo.close.assert_called_once()


# ---------------------------------------------------------------------------
# Migrated from test_cache_metrics.py
# ---------------------------------------------------------------------------


class TestMetricsSummaryExtraction:
    """Migrated from test_cache_metrics.py: TestMetricsSummaryExtraction."""

    def test_extracts_basic_token_metrics(self, mock_agent):
        agent = mock_agent(input_tokens=500, output_tokens=200, total_tokens=700)
        summary = agent.event_loop_metrics.get_summary()
        usage = summary["accumulated_usage"]
        assert usage["inputTokens"] == 500
        assert usage["outputTokens"] == 200
        assert usage["totalTokens"] == 700

    def test_extracts_cache_metrics(self, mock_agent):
        agent = mock_agent(cache_read_tokens=450, cache_write_tokens=50)
        summary = agent.event_loop_metrics.get_summary()
        usage = summary["accumulated_usage"]
        assert usage.get("cacheReadInputTokens", 0) == 450
        assert usage.get("cacheWriteInputTokens", 0) == 50

    def test_extracts_latency_metrics(self, mock_agent):
        agent = mock_agent(latency_ms=1500, time_to_first_byte_ms=250)
        summary = agent.event_loop_metrics.get_summary()
        metrics = summary["accumulated_metrics"]
        assert metrics["latencyMs"] == 1500
        assert metrics.get("timeToFirstByteMs", 0) == 250

    def test_extracts_cycle_metrics(self, mock_agent):
        agent = mock_agent(cycle_count=3, total_duration=4.5, average_cycle_time=1.5)
        summary = agent.event_loop_metrics.get_summary()
        assert summary["total_cycles"] == 3
        assert summary["total_duration"] == pytest.approx(4.5)
        assert summary["average_cycle_time"] == pytest.approx(1.5)

    def test_extracts_tool_usage_metrics(self, mock_agent):
        tool_usage = {
            "search_documents": {
                "tool_info": {"name": "search_documents"},
                "execution_stats": {
                    "call_count": 5,
                    "success_count": 4,
                    "error_count": 1,
                    "total_time": 2.5,
                    "average_time": 0.5,
                    "success_rate": 0.8,
                },
            }
        }
        agent = mock_agent(tool_usage=tool_usage)
        summary = agent.event_loop_metrics.get_summary()
        stats = summary["tool_usage"]["search_documents"]["execution_stats"]
        assert stats["call_count"] == 5
        assert stats["success_rate"] == pytest.approx(0.8)

    def test_handles_empty_tool_usage(self, mock_agent):
        agent = mock_agent(tool_usage={})
        summary = agent.event_loop_metrics.get_summary()
        assert summary["tool_usage"] == {}


class TestCacheHitRateCalculation:
    """Migrated from test_cache_metrics.py: TestCacheHitRateCalculation."""

    def test_cache_hit_rate_90_percent(self):
        cache_read, cache_write = 450, 50
        total = cache_read + cache_write
        rate = (cache_read / total * 100) if total > 0 else 0
        assert rate == pytest.approx(90.0)

    def test_cache_hit_rate_zero_when_no_cache(self):
        cache_read = 0
        rate = (cache_read / 1 * 100) if cache_read > 0 else 0
        assert rate == 0

    def test_cache_miss_first_request(self):
        cache_read, cache_write = 0, 1000
        total = cache_read + cache_write
        rate = (cache_read / total * 100) if total > 0 else 0
        assert rate == 0


# ---------------------------------------------------------------------------
# redact_latest_message / guardrail events
# ---------------------------------------------------------------------------


class TestRedactLatestMessage:
    """Contra el doble: se comprueba el evento almacenado, no el comando emitido."""

    @staticmethod
    def _redact(manager, **kwargs):
        """Redact through the manager, stubbing the parent's own bookkeeping."""
        agent = MagicMock()
        agent.agent_id = "a1"
        with patch.object(MongoDBSessionManager.__bases__[0], "redact_latest_message"):
            manager.redact_latest_message(REDACTED, agent, **kwargs)
        return agent

    @staticmethod
    def _event_on_message(fake_repo):
        return fake_repo.message("test-session", "a1", 5)["guardrail_event"]

    def test_redact_latest_message_calls_super(self, stored_message):
        agent = MagicMock()
        agent.agent_id = "a1"
        with patch.object(
            MongoDBSessionManager.__bases__[0], "redact_latest_message"
        ) as mock_super:
            stored_message.redact_latest_message(REDACTED, agent)
            mock_super.assert_called_once_with(REDACTED, agent)

    def test_records_guardrail_event_on_message(self, stored_message, fake_repo):
        self._redact(stored_message)

        event = self._event_on_message(fake_repo)
        assert event["action"] == "BLOCKED"
        assert "timestamp" in event

    def test_records_guardrail_event_on_session(self, stored_message, fake_repo):
        self._redact(stored_message)

        events = guardrail_events(fake_repo)
        assert len(events) == 1
        assert events[0]["message_id"] == 5
        assert events[0]["agent_id"] == "a1"
        assert events[0]["action"] == "BLOCKED"

    def test_custom_action(self, stored_message, fake_repo):
        self._redact(stored_message, action="ANONYMIZED")

        assert self._event_on_message(fake_repo)["action"] == "ANONYMIZED"

    def test_no_messages_is_rejected_by_the_parent(self, agent_in_session, fake_repo):
        """Sin mensaje que redactar, quien corta es la clase padre.

        Aquí no se parchea `super()`, porque el contrato real es que lanza: este
        override nunca llega a anotar un evento sin mensaje. Fijarlo evita
        defenderse de un caso que no ocurre —y creerse defendido.
        """
        agent = MagicMock()
        agent.agent_id = "a1"
        agent_in_session._latest_agent_message["a1"] = None

        with pytest.raises(SessionException, match="No message to redact"):
            agent_in_session.redact_latest_message(REDACTED, agent)

        assert guardrail_events(fake_repo) == []

    def test_guardrail_trace_stores_enriched_event(self, stored_message, fake_repo):
        trace = {
            "inputAssessment": {
                "contentPolicy": {
                    "filters": [
                        {"type": "HATE", "confidence": "HIGH"},
                        {"type": "VIOLENCE", "confidence": "MEDIUM"},
                    ]
                }
            },
            "outputAssessments": [],
        }

        self._redact(stored_message, guardrail_trace=trace)

        event = self._event_on_message(fake_repo)
        assert event["trace"] == trace
        assert "HATE/HIGH" in event["policies_triggered"]["contentPolicy"]
        assert "VIOLENCE/MEDIUM" in event["policies_triggered"]["contentPolicy"]

    def test_session_event_excludes_full_trace(self, stored_message, fake_repo):
        """El array de sesión se lee entero para auditar: el trace no cabe ahí."""
        trace = {
            "inputAssessment": {
                "contentPolicy": {"filters": [{"type": "HATE", "confidence": "HIGH"}]}
            },
            "outputAssessments": [],
        }

        self._redact(stored_message, guardrail_trace=trace)

        event = guardrail_events(fake_repo)[0]
        assert "trace" not in event
        assert "HATE/HIGH" in event["policies_triggered"]["contentPolicy"]

    def test_stop_reason_reaches_both_levels(self, stored_message, fake_repo):
        self._redact(stored_message, stop_reason="guardrail_intervened")

        assert (
            self._event_on_message(fake_repo)["stop_reason"] == "guardrail_intervened"
        )
        assert guardrail_events(fake_repo)[0]["stop_reason"] == "guardrail_intervened"

    def test_without_trace_is_backward_compatible(self, stored_message, fake_repo):
        """Una intervención pelada sigue siendo solo action y timestamp."""
        self._redact(stored_message)

        assert set(self._event_on_message(fake_repo).keys()) == {"action", "timestamp"}


# ---------------------------------------------------------------------------
# Message identity (#78)
# ---------------------------------------------------------------------------


class TestDuplicatedMessageIndex:
    """Dos managers sobre el mismo agente pueden producir el mismo message_id.

    Strands deriva el índice en memoria, así que dos managers que restauran el
    agente a la vez calculan el mismo. Todo lo que este manager anota sobre su
    turno —métricas, redacción y evento de guardarraíl— tiene que aterrizar en
    el mensaje que él añadió, no en el que casualmente comparte índice y va
    primero en el array. Es el caso de la issue #78.
    """

    @pytest.fixture
    def duplicated(self, agent_in_session, fake_repo, syncable_agent):
        """Otro manager añadió el mensaje 0; este añade el suyo, también 0."""
        fake_repo.create_message(
            "test-session",
            "a1",
            SessionMessage(
                message_id=0,
                message={"role": "user", "content": [{"text": "del otro manager"}]},
            ),
        )

        agent = syncable_agent()
        agent_in_session._latest_agent_message["a1"] = None
        agent_in_session.append_message(
            {"role": "user", "content": [{"text": "de este manager"}]}, agent
        )

        return agent_in_session, agent

    @staticmethod
    def _messages(fake_repo):
        return fake_repo.session("test-session")["agents"]["a1"]["messages"]

    def test_both_messages_share_the_index(self, duplicated, fake_repo):
        """El escenario es real solo si los dos índices coinciden de verdad."""
        first, second = self._messages(fake_repo)

        assert first["message_id"] == second["message_id"] == 0
        assert first["storage_id"] != second["storage_id"]

    def test_metrics_annotate_its_own_message(self, duplicated, fake_repo):
        manager, agent = duplicated

        manager.sync_agent(agent)

        first, second = self._messages(fake_repo)
        assert "event_loop_metrics" not in first
        assert second["event_loop_metrics"]["accumulated_usage"]["totalTokens"] == 700

    def test_redaction_lands_on_its_own_message(self, duplicated, fake_repo):
        """La cara grave del bug: redactar contenido inocente y dejar visible el otro."""
        manager, agent = duplicated

        manager.redact_latest_message(REDACTED, agent)

        first, second = self._messages(fake_repo)
        assert first["redact_message"] is None
        assert second["redact_message"] == REDACTED

    def test_guardrail_event_lands_on_its_own_message(self, duplicated, fake_repo):
        manager, agent = duplicated

        manager.redact_latest_message(REDACTED, agent)

        first, second = self._messages(fake_repo)
        assert "guardrail_event" not in first
        assert second["guardrail_event"]["action"] == "BLOCKED"

    def test_session_audit_points_at_its_own_message(self, duplicated, fake_repo):
        """El array de sesión es lo que lee un auditor: debe decir cuál fue."""
        manager, agent = duplicated

        manager.redact_latest_message(REDACTED, agent)

        _, second = self._messages(fake_repo)
        event = guardrail_events(fake_repo)[0]
        assert event["message_id"] == 0
        assert event["storage_id"] == second["storage_id"]


# ---------------------------------------------------------------------------
# _extract_guardrail_summary
# ---------------------------------------------------------------------------


class TestExtractGuardrailSummary:
    def test_content_policy(self, manager):
        trace = {
            "inputAssessment": {
                "contentPolicy": {
                    "filters": [
                        {"type": "HATE", "confidence": "HIGH"},
                        {"type": "VIOLENCE", "confidence": "MEDIUM"},
                    ]
                }
            },
            "outputAssessments": [],
        }
        result = manager._extract_guardrail_summary(trace)
        assert result["contentPolicy"] == ["HATE/HIGH", "VIOLENCE/MEDIUM"]

    def test_multiple_policies(self, manager):
        trace = {
            "inputAssessment": {
                "contentPolicy": {"filters": [{"type": "HATE", "confidence": "HIGH"}]},
                "topicPolicy": {
                    "topics": [{"name": "financial-advice", "action": "DENY"}]
                },
                "sensitiveInformationPolicy": {
                    "piiEntities": [{"type": "EMAIL", "action": "ANONYMIZED"}],
                    "regexes": [],
                },
            },
            "outputAssessments": [],
        }
        result = manager._extract_guardrail_summary(trace)
        assert "HATE/HIGH" in result["contentPolicy"]
        assert "financial-advice/DENY" in result["topicPolicy"]
        assert "EMAIL/ANONYMIZED" in result["sensitiveInformationPolicy"]

    def test_empty_trace(self, manager):
        assert manager._extract_guardrail_summary({}) == {}

    def test_none_trace(self, manager):
        assert manager._extract_guardrail_summary(None) == {}

    def test_contextual_grounding_policy(self, manager):
        trace = {
            "inputAssessment": {},
            "outputAssessments": [
                {
                    "contextualGroundingPolicy": {
                        "filters": [
                            {"type": "GROUNDING", "score": 0.3, "threshold": 0.7}
                        ]
                    }
                }
            ],
        }
        result = manager._extract_guardrail_summary(trace)
        assert "GROUNDING/0.3/0.7" in result["contextualGroundingPolicy"]

    def test_word_policy(self, manager):
        trace = {
            "inputAssessment": {
                "wordPolicy": {
                    "customWords": [{"match": "badword"}],
                    "managedWordLists": [{"type": "PROFANITY", "match": "damnit"}],
                }
            },
            "outputAssessments": [],
        }
        result = manager._extract_guardrail_summary(trace)
        assert "badword" in result["wordPolicy"]
        assert "PROFANITY/damnit" in result["wordPolicy"]


class TestToolUsageProcessing:
    """Migrated from test_cache_metrics.py: TestToolUsageProcessing."""

    def test_processes_tool_metrics_correctly(self, manager):
        raw = {
            "search_documents": {
                "tool_info": {"tool_use_id": "123", "name": "search_documents"},
                "execution_stats": {
                    "call_count": 5,
                    "success_count": 4,
                    "error_count": 1,
                    "total_time": 2.5,
                    "average_time": 0.5,
                    "success_rate": 0.8,
                },
            }
        }
        result = manager._extract_tool_usage(raw)
        assert result["search_documents"]["call_count"] == 5
        assert result["search_documents"]["success_rate"] == pytest.approx(0.8)
        assert "tool_info" not in result["search_documents"]


# ---------------------------------------------------------------------------
# Names inside paths (#79)
# ---------------------------------------------------------------------------


class TestNamesInPaths:
    def test_an_invalid_agent_id_fails_the_same_way_every_time(
        self, manager_fake, fake_repo, mock_agent
    ):
        """Rejected before Strands registers the id, so a retry does not lie.

        Strands records the agent_id in `_latest_agent_message` before it touches
        the repository. Failing after that would turn the second attempt into a
        misleading "agent_id must be unique" SessionException.

        Un solo camino desde strands 1.56: el SDK borró `initialize_bidi_agent()`
        y manda también el `BidiAgent` por aquí (#69).
        """
        agent = mock_agent(agent_id="a.b")

        for _ in range(2):
            with pytest.raises(ValueError, match="agent_id"):
                manager_fake.initialize(agent)

        assert "a.b" not in manager_fake._latest_agent_message
        assert fake_repo.session("test-session")["agents"] == {}

    @pytest.mark.parametrize(
        "call",
        [
            lambda m: m.update_metadata({"ok": 1, "$where": 1}),
            lambda m: m.delete_metadata(["a..b"]),
        ],
        ids=["update", "delete"],
    )
    def test_a_metadata_hook_never_sees_an_invalid_key(self, fake_repo, call):
        """A custom hook may publish what it receives before calling the original."""
        hook = MagicMock()
        manager = MongoDBSessionManager(
            session_id="test-session", session_repository=fake_repo, metadata_hook=hook
        )

        with pytest.raises(ValueError, match="metadata key"):
            call(manager)

        hook.assert_not_called()

    def test_the_metadata_tool_tells_the_agent_why(self, manager_fake, fake_repo):
        tool = manager_fake.get_metadata_tool()

        result = tool(action="set", metadata={"tags.$[]": "x"})

        assert "metadata key 'tags.$[]'" in result
        assert fake_repo.session("test-session")["metadata"] == {}
