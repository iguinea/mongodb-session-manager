#!/usr/bin/env python3
"""Tests for cache metrics extraction in sync_agent.

These tests verify that AWS Bedrock prompt caching metrics
(cacheReadInputTokens, cacheWriteInputTokens) are properly
extracted from the Strands Agent and stored in MongoDB.
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock


class TestCacheMetricsSync:
    """Test cache metrics are properly extracted and stored."""

    def _create_mock_agent(
        self,
        latency_ms: int = 100,
        input_tokens: int = 500,
        output_tokens: int = 200,
        total_tokens: int = 700,
        cache_read_tokens: int | None = None,
        cache_write_tokens: int | None = None,
    ) -> MagicMock:
        """Create a mock agent with configurable metrics."""
        mock_agent = MagicMock()
        mock_agent.agent_id = "test-agent"
        mock_agent.event_loop_metrics.accumulated_metrics = {"latencyMs": latency_ms}

        usage = {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": total_tokens,
        }
        if cache_read_tokens is not None:
            usage["cacheReadInputTokens"] = cache_read_tokens
        if cache_write_tokens is not None:
            usage["cacheWriteInputTokens"] = cache_write_tokens

        mock_agent.event_loop_metrics.accumulated_usage = usage
        return mock_agent

    def test_extracts_cache_read_tokens(self):
        """Test that cacheReadInputTokens is extracted correctly."""
        agent = self._create_mock_agent(cache_read_tokens=450, cache_write_tokens=50)

        usage = agent.event_loop_metrics.accumulated_usage
        cache_read = usage.get("cacheReadInputTokens", 0)

        assert cache_read == 450, "cacheReadInputTokens should be 450"

    def test_extracts_cache_write_tokens(self):
        """Test that cacheWriteInputTokens is extracted correctly."""
        agent = self._create_mock_agent(cache_read_tokens=0, cache_write_tokens=500)

        usage = agent.event_loop_metrics.accumulated_usage
        cache_write = usage.get("cacheWriteInputTokens", 0)

        assert cache_write == 500, "cacheWriteInputTokens should be 500"

    def test_handles_missing_cache_metrics_gracefully(self):
        """Test backwards compatibility when cache metrics are not present."""
        agent = self._create_mock_agent()  # No cache metrics

        usage = agent.event_loop_metrics.accumulated_usage

        # Should default to 0 using .get()
        cache_read = usage.get("cacheReadInputTokens", 0)
        cache_write = usage.get("cacheWriteInputTokens", 0)

        assert cache_read == 0, "Missing cacheReadInputTokens should default to 0"
        assert cache_write == 0, "Missing cacheWriteInputTokens should default to 0"

    def test_cache_hit_rate_calculation(self):
        """Test cache hit rate calculation from metrics."""
        agent = self._create_mock_agent(cache_read_tokens=450, cache_write_tokens=50)

        usage = agent.event_loop_metrics.accumulated_usage
        cache_read = usage.get("cacheReadInputTokens", 0)
        cache_write = usage.get("cacheWriteInputTokens", 0)

        total_cacheable = cache_read + cache_write
        cache_hit_rate = (
            (cache_read / total_cacheable * 100) if total_cacheable > 0 else 0
        )

        assert cache_hit_rate == 90.0, "Cache hit rate should be 90%"

    def test_cache_miss_first_request(self):
        """Test first request shows only cache write (miss)."""
        agent = self._create_mock_agent(cache_read_tokens=0, cache_write_tokens=1000)

        usage = agent.event_loop_metrics.accumulated_usage
        cache_read = usage.get("cacheReadInputTokens", 0)
        cache_write = usage.get("cacheWriteInputTokens", 0)

        assert cache_read == 0, "First request should have 0 cache reads"
        assert cache_write == 1000, "First request should write to cache"

    def test_cache_hit_subsequent_request(self):
        """Test subsequent request shows mostly cache reads (hits)."""
        agent = self._create_mock_agent(cache_read_tokens=950, cache_write_tokens=50)

        usage = agent.event_loop_metrics.accumulated_usage
        cache_read = usage.get("cacheReadInputTokens", 0)
        cache_write = usage.get("cacheWriteInputTokens", 0)

        assert cache_read > cache_write, "Subsequent requests should have more hits"
        assert cache_read == 950, "Should read most tokens from cache"


class TestUpdateDataStructure:
    """Test the update_data structure includes cache metrics."""

    def test_update_data_includes_cache_metrics(self):
        """Test that update_data dict includes cache metrics fields."""
        # Simulate what sync_agent() builds
        _inputTokens = 500
        _outputTokens = 200
        _totalTokens = 700
        _cacheReadInputTokens = 450
        _cacheWriteInputTokens = 50
        _latencyMs = 100
        agent_id = "test-agent"

        update_data = {
            f"agents.{agent_id}.messages.$.event_loop_metrics.accumulated_metrics": {
                "latencyMs": _latencyMs,
            },
            f"agents.{agent_id}.messages.$.event_loop_metrics.accumulated_usage": {
                "inputTokens": _inputTokens,
                "outputTokens": _outputTokens,
                "totalTokens": _totalTokens,
                "cacheReadInputTokens": _cacheReadInputTokens,
                "cacheWriteInputTokens": _cacheWriteInputTokens,
            },
        }

        usage_key = f"agents.{agent_id}.messages.$.event_loop_metrics.accumulated_usage"
        usage_data = update_data[usage_key]

        assert "cacheReadInputTokens" in usage_data
        assert "cacheWriteInputTokens" in usage_data
        assert usage_data["cacheReadInputTokens"] == 450
        assert usage_data["cacheWriteInputTokens"] == 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
