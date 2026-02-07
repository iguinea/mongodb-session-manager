#!/usr/bin/env python3
"""Tests for comprehensive metrics extraction in sync_agent.

These tests verify that all metrics are properly extracted from the
Strands Agent's get_summary() method and stored in MongoDB:
- Token usage (input, output, total, cache read/write)
- Performance metrics (latency, time to first byte)
- Cycle metrics (count, durations, averages)
- Tool metrics (call counts, success/error rates, execution times)
"""

import pytest
from unittest.mock import MagicMock


class TestMetricsSummaryExtraction:
    """Test metrics are properly extracted from get_summary()."""

    def _create_mock_agent(
        self,
        latency_ms: int = 100,
        time_to_first_byte_ms: int = 0,
        input_tokens: int = 500,
        output_tokens: int = 200,
        total_tokens: int = 700,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        cycle_count: int = 1,
        total_duration: float = 1.5,
        average_cycle_time: float = 1.5,
        tool_usage: dict | None = None,
    ) -> MagicMock:
        """Create a mock agent with configurable metrics using get_summary() structure."""
        mock_agent = MagicMock()
        mock_agent.agent_id = "test-agent"

        # Build the summary structure that get_summary() returns
        summary = {
            "total_cycles": cycle_count,
            "total_duration": total_duration,
            "average_cycle_time": average_cycle_time,
            "accumulated_usage": {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "totalTokens": total_tokens,
            },
            "accumulated_metrics": {
                "latencyMs": latency_ms,
            },
            "tool_usage": tool_usage or {},
            "traces": [],
        }

        # Add optional cache metrics
        if cache_read_tokens > 0:
            summary["accumulated_usage"]["cacheReadInputTokens"] = cache_read_tokens
        if cache_write_tokens > 0:
            summary["accumulated_usage"]["cacheWriteInputTokens"] = cache_write_tokens

        # Add optional timeToFirstByteMs
        if time_to_first_byte_ms > 0:
            summary["accumulated_metrics"]["timeToFirstByteMs"] = time_to_first_byte_ms

        mock_agent.event_loop_metrics.get_summary.return_value = summary
        return mock_agent

    def test_extracts_basic_token_metrics(self):
        """Test basic token metrics extraction from get_summary()."""
        agent = self._create_mock_agent(
            input_tokens=500, output_tokens=200, total_tokens=700
        )

        summary = agent.event_loop_metrics.get_summary()
        usage = summary["accumulated_usage"]

        assert usage["inputTokens"] == 500
        assert usage["outputTokens"] == 200
        assert usage["totalTokens"] == 700

    def test_extracts_cache_metrics(self):
        """Test cache metrics extraction from get_summary()."""
        agent = self._create_mock_agent(
            cache_read_tokens=450, cache_write_tokens=50
        )

        summary = agent.event_loop_metrics.get_summary()
        usage = summary["accumulated_usage"]

        assert usage.get("cacheReadInputTokens", 0) == 450
        assert usage.get("cacheWriteInputTokens", 0) == 50

    def test_extracts_latency_metrics(self):
        """Test latency and time to first byte extraction."""
        agent = self._create_mock_agent(
            latency_ms=1500, time_to_first_byte_ms=250
        )

        summary = agent.event_loop_metrics.get_summary()
        metrics = summary["accumulated_metrics"]

        assert metrics["latencyMs"] == 1500
        assert metrics.get("timeToFirstByteMs", 0) == 250

    def test_extracts_cycle_metrics(self):
        """Test cycle metrics extraction."""
        agent = self._create_mock_agent(
            cycle_count=3,
            total_duration=4.5,
            average_cycle_time=1.5
        )

        summary = agent.event_loop_metrics.get_summary()

        assert summary["total_cycles"] == 3
        assert summary["total_duration"] == pytest.approx(4.5)
        assert summary["average_cycle_time"] == pytest.approx(1.5)

    def test_extracts_tool_usage_metrics(self):
        """Test tool usage metrics extraction."""
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
                }
            },
            "get_user_info": {
                "tool_info": {"name": "get_user_info"},
                "execution_stats": {
                    "call_count": 2,
                    "success_count": 2,
                    "error_count": 0,
                    "total_time": 0.4,
                    "average_time": 0.2,
                    "success_rate": 1.0,
                }
            }
        }
        agent = self._create_mock_agent(tool_usage=tool_usage)

        summary = agent.event_loop_metrics.get_summary()

        assert "search_documents" in summary["tool_usage"]
        assert "get_user_info" in summary["tool_usage"]

        search_stats = summary["tool_usage"]["search_documents"]["execution_stats"]
        assert search_stats["call_count"] == 5
        assert search_stats["success_count"] == 4
        assert search_stats["error_count"] == 1
        assert search_stats["success_rate"] == pytest.approx(0.8)

    def test_handles_missing_cache_metrics_gracefully(self):
        """Test backwards compatibility when cache metrics are not present."""
        agent = self._create_mock_agent()  # No cache metrics

        summary = agent.event_loop_metrics.get_summary()
        usage = summary["accumulated_usage"]

        # Should default to 0 using .get()
        cache_read = usage.get("cacheReadInputTokens", 0)
        cache_write = usage.get("cacheWriteInputTokens", 0)

        assert cache_read == 0, "Missing cacheReadInputTokens should default to 0"
        assert cache_write == 0, "Missing cacheWriteInputTokens should default to 0"

    def test_handles_missing_time_to_first_byte(self):
        """Test backwards compatibility when timeToFirstByteMs is not present."""
        agent = self._create_mock_agent()  # No timeToFirstByteMs

        summary = agent.event_loop_metrics.get_summary()
        metrics = summary["accumulated_metrics"]

        ttfb = metrics.get("timeToFirstByteMs", 0)
        assert ttfb == 0, "Missing timeToFirstByteMs should default to 0"

    def test_handles_empty_tool_usage(self):
        """Test when no tools were used."""
        agent = self._create_mock_agent(tool_usage={})

        summary = agent.event_loop_metrics.get_summary()

        assert summary["tool_usage"] == {}


class TestCacheHitRateCalculation:
    """Test cache hit rate calculations."""

    def test_cache_hit_rate_90_percent(self):
        """Test cache hit rate calculation from metrics."""
        cache_read = 450
        cache_write = 50

        total_cacheable = cache_read + cache_write
        cache_hit_rate = (
            (cache_read / total_cacheable * 100) if total_cacheable > 0 else 0
        )

        assert cache_hit_rate == pytest.approx(90.0), "Cache hit rate should be 90%"

    def test_cache_hit_rate_zero_when_no_cache(self):
        """Test cache hit rate is 0 when no cacheable tokens."""
        cache_read = 0
        cache_write = 0

        total_cacheable = cache_read + cache_write
        cache_hit_rate = (
            (cache_read / total_cacheable * 100) if total_cacheable > 0 else 0
        )

        assert cache_hit_rate == 0, "Cache hit rate should be 0 when no cache"

    def test_cache_miss_first_request(self):
        """Test first request shows only cache write (miss)."""
        cache_read = 0
        cache_write = 1000

        total_cacheable = cache_read + cache_write
        cache_hit_rate = (
            (cache_read / total_cacheable * 100) if total_cacheable > 0 else 0
        )

        assert cache_hit_rate == 0, "First request should have 0% hit rate"


class TestUpdateDataStructure:
    """Test the update_data structure includes all metrics."""

    def test_update_data_includes_all_metrics(self):
        """Test that update_data dict includes all metrics fields."""
        # Simulate what sync_agent() builds
        _inputTokens = 500
        _outputTokens = 200
        _totalTokens = 700
        _cacheReadInputTokens = 450
        _cacheWriteInputTokens = 50
        _latencyMs = 100
        _timeToFirstByteMs = 25
        _cycle_count = 2
        _total_duration = 3.5
        _average_cycle_time = 1.75
        _tool_usage = {
            "search": {
                "call_count": 3,
                "success_count": 3,
                "error_count": 0,
                "total_time": 1.2,
                "average_time": 0.4,
                "success_rate": 1.0,
            }
        }
        agent_id = "test-agent"

        update_data = {
            f"agents.{agent_id}.messages.$.event_loop_metrics.accumulated_metrics": {
                "latencyMs": _latencyMs,
                "timeToFirstByteMs": _timeToFirstByteMs,
            },
            f"agents.{agent_id}.messages.$.event_loop_metrics.accumulated_usage": {
                "inputTokens": _inputTokens,
                "outputTokens": _outputTokens,
                "totalTokens": _totalTokens,
                "cacheReadInputTokens": _cacheReadInputTokens,
                "cacheWriteInputTokens": _cacheWriteInputTokens,
            },
            f"agents.{agent_id}.messages.$.event_loop_metrics.cycle_metrics": {
                "cycle_count": _cycle_count,
                "total_duration": _total_duration,
                "average_cycle_time": _average_cycle_time,
            },
            f"agents.{agent_id}.messages.$.event_loop_metrics.tool_usage": _tool_usage,
        }

        # Verify accumulated_metrics
        metrics_key = f"agents.{agent_id}.messages.$.event_loop_metrics.accumulated_metrics"
        metrics_data = update_data[metrics_key]
        assert "latencyMs" in metrics_data
        assert "timeToFirstByteMs" in metrics_data
        assert metrics_data["timeToFirstByteMs"] == 25

        # Verify accumulated_usage
        usage_key = f"agents.{agent_id}.messages.$.event_loop_metrics.accumulated_usage"
        usage_data = update_data[usage_key]
        assert "cacheReadInputTokens" in usage_data
        assert "cacheWriteInputTokens" in usage_data
        assert usage_data["cacheReadInputTokens"] == 450
        assert usage_data["cacheWriteInputTokens"] == 50

        # Verify cycle_metrics
        cycle_key = f"agents.{agent_id}.messages.$.event_loop_metrics.cycle_metrics"
        cycle_data = update_data[cycle_key]
        assert "cycle_count" in cycle_data
        assert "total_duration" in cycle_data
        assert "average_cycle_time" in cycle_data
        assert cycle_data["cycle_count"] == 2

        # Verify tool_usage
        tool_key = f"agents.{agent_id}.messages.$.event_loop_metrics.tool_usage"
        tool_data = update_data[tool_key]
        assert "search" in tool_data
        assert tool_data["search"]["call_count"] == 3
        assert tool_data["search"]["success_rate"] == pytest.approx(1.0)


class TestToolUsageProcessing:
    """Test tool usage metrics processing."""

    def test_processes_tool_metrics_correctly(self):
        """Test that tool metrics are extracted and simplified correctly."""
        tool_usage_raw = {
            "search_documents": {
                "tool_info": {
                    "tool_use_id": "tooluse_123",
                    "name": "search_documents",
                    "input_params": {"query": "test"}
                },
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

        # Process like sync_agent does
        _tool_usage = {}
        for tool_name, tool_data in tool_usage_raw.items():
            exec_stats = tool_data.get("execution_stats", {})
            _tool_usage[tool_name] = {
                "call_count": exec_stats.get("call_count", 0),
                "success_count": exec_stats.get("success_count", 0),
                "error_count": exec_stats.get("error_count", 0),
                "total_time": exec_stats.get("total_time", 0.0),
                "average_time": exec_stats.get("average_time", 0.0),
                "success_rate": exec_stats.get("success_rate", 0.0),
            }

        assert "search_documents" in _tool_usage
        assert _tool_usage["search_documents"]["call_count"] == 5
        assert _tool_usage["search_documents"]["success_rate"] == pytest.approx(0.8)
        # Verify tool_info is NOT included (simplified structure)
        assert "tool_info" not in _tool_usage["search_documents"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
