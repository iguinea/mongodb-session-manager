"""Unit tests for MongoDBSessionManager."""

import warnings
from unittest.mock import MagicMock, patch

import pytest

from mongodb_session_manager.mongodb_session_manager import (
    MongoDBSessionManager,
    create_mongodb_session_manager,
)


@pytest.fixture
def mock_repo():
    """Create a MagicMock repository."""
    repo = MagicMock()
    repo.read_session.return_value = None
    repo.collection = MagicMock()
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
    def test_deprecation_warning_camelCase_metadataHook(self, mock_repo_cls):
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
    def test_deprecation_warning_camelCase_feedbackHook(self, mock_repo_cls):
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
    def test_extracts_usage_data(self, manager, mock_agent):
        agent = mock_agent(input_tokens=500, output_tokens=200, total_tokens=700)
        manager.session_repository.collection.find_one.return_value = {
            "agents": {"test-agent": {"messages": [{"message_id": 1}]}}
        }
        manager.sync_agent(agent)
        update_call = manager.session_repository.collection.update_one.call_args_list
        # Should have at least one update (metrics) + agent config update
        assert len(update_call) >= 1

    def test_skips_metrics_when_latency_zero(self, manager, mock_agent):
        agent = mock_agent(latency_ms=0)
        manager.sync_agent(agent)
        # Only agent config capture should happen, no metrics update
        # The collection update_one should only be called for config capture
        calls = manager.session_repository.collection.update_one.call_args_list
        # Verify no metrics update (which uses $ positional operator)
        for c in calls:
            set_data = c[0][1].get("$set", {})
            assert not any("event_loop_metrics" in k for k in set_data.keys())

    def test_captures_cycle_metrics(self, manager, mock_agent):
        agent = mock_agent(cycle_count=3, total_duration=4.5, average_cycle_time=1.5)
        manager.session_repository.collection.find_one.return_value = {
            "agents": {"test-agent": {"messages": [{"message_id": 1}]}}
        }
        manager.sync_agent(agent)
        update_call = manager.session_repository.collection.update_one.call_args_list[0]
        set_data = update_call[0][1]["$set"]
        cycle_key = "agents.test-agent.messages.$.event_loop_metrics.cycle_metrics"
        assert set_data[cycle_key]["cycle_count"] == 3

    def test_captures_tool_usage(self, manager, mock_agent):
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
        agent = mock_agent(tool_usage=tool_usage)
        manager.session_repository.collection.find_one.return_value = {
            "agents": {"test-agent": {"messages": [{"message_id": 1}]}}
        }
        manager.sync_agent(agent)
        update_call = manager.session_repository.collection.update_one.call_args_list[0]
        set_data = update_call[0][1]["$set"]
        tool_key = "agents.test-agent.messages.$.event_loop_metrics.tool_usage"
        assert "search" in set_data[tool_key]
        assert set_data[tool_key]["search"]["call_count"] == 5

    def test_captures_agent_config_model(self, manager, mock_agent):
        agent = mock_agent(model_id="claude-3-sonnet", latency_ms=0)
        manager.sync_agent(agent)
        calls = manager.session_repository.collection.update_one.call_args_list
        # Find the config capture call
        config_call = None
        for c in calls:
            set_data = c[0][1].get("$set", {})
            if any("agent_data.model" in k for k in set_data.keys()):
                config_call = c
                break
        assert config_call is not None

    def test_captures_agent_config_system_prompt(self, manager, mock_agent):
        agent = mock_agent(system_prompt="You are helpful", latency_ms=0)
        manager.sync_agent(agent)
        calls = manager.session_repository.collection.update_one.call_args_list
        config_call = None
        for c in calls:
            set_data = c[0][1].get("$set", {})
            if any("agent_data.system_prompt" in k for k in set_data.keys()):
                config_call = c
                break
        assert config_call is not None

    def test_no_update_when_no_agents(self, manager, mock_agent):
        agent = mock_agent()
        manager.session_repository.collection.find_one.return_value = None
        manager.sync_agent(agent)

    def test_no_update_when_no_messages(self, manager, mock_agent):
        agent = mock_agent()
        manager.session_repository.collection.find_one.return_value = {
            "agents": {"test-agent": {"messages": []}}
        }
        manager.sync_agent(agent)


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
    def test_get_agent_config(self, manager, mock_repo):
        mock_repo.collection.find_one.return_value = {
            "agents": {
                "a1": {"agent_data": {"model": "claude-3", "system_prompt": "helpful"}}
            }
        }
        result = manager.get_agent_config("a1")
        assert result["model"] == "claude-3"
        assert result["system_prompt"] == "helpful"

    def test_get_agent_config_returns_none(self, manager, mock_repo):
        mock_repo.collection.find_one.return_value = {"agents": {}}
        assert manager.get_agent_config("missing") is None

    def test_update_agent_config(self, manager, mock_repo):
        mock_repo.collection.update_one.return_value = MagicMock(matched_count=1)
        manager.update_agent_config("a1", model="new-model")
        mock_repo.collection.update_one.assert_called()

    def test_update_agent_config_raises_when_session_missing(self, manager, mock_repo):
        mock_repo.collection.update_one.return_value = MagicMock(matched_count=0)
        with pytest.raises(ValueError, match="Session test-session not found"):
            manager.update_agent_config("a1", model="x")

    def test_list_agents(self, manager, mock_repo):
        mock_repo.collection.find_one.return_value = {
            "agents": {
                "a1": {"agent_data": {"model": "m1"}},
                "a2": {"agent_data": {"model": "m2"}},
            }
        }
        result = manager.list_agents()
        assert len(result) == 2

    def test_get_message_count(self, manager, mock_repo):
        mock_repo.collection.find_one.return_value = {
            "agents": {"a1": {"messages": [{"id": 1}, {"id": 2}, {"id": 3}]}}
        }
        assert manager.get_message_count("a1") == 3


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
        rate = (0 / 1 * 100) if 0 > 0 else 0
        assert rate == 0

    def test_cache_miss_first_request(self):
        cache_read, cache_write = 0, 1000
        total = cache_read + cache_write
        rate = (cache_read / total * 100) if total > 0 else 0
        assert rate == 0


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
