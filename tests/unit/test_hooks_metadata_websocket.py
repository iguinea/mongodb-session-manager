"""Unit tests for MetadataWebSocketHook."""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from mongodb_session_manager.hooks.metadata_websocket_hook import (
    MetadataWebSocketHook,
    create_metadata_hook,
    _dispatch_async,
    _build_delete_metadata,
)


@pytest.fixture
def ws_hook():
    """Create a MetadataWebSocketHook with mocked boto3 client."""
    with patch(
        "mongodb_session_manager.hooks.metadata_websocket_hook.boto3"
    ) as mock_boto:
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        hook = MetadataWebSocketHook(
            api_gateway_endpoint="https://api.example.com/prod",
            metadata_fields=["status", "progress"],
            region="us-east-1",
        )
        yield hook, mock_client


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestMetadataWebSocketHookInit:
    def test_creates_boto3_client(self):
        with patch(
            "mongodb_session_manager.hooks.metadata_websocket_hook.boto3"
        ) as mock_boto:
            mock_boto.client.return_value = MagicMock()
            MetadataWebSocketHook("https://api.example.com", region="eu-west-1")
            mock_boto.client.assert_called_once_with(
                "apigatewaymanagementapi",
                endpoint_url="https://api.example.com",
                region_name="eu-west-1",
            )

    def test_raises_import_error(self):
        with patch("mongodb_session_manager.hooks.metadata_websocket_hook.boto3", None):
            with pytest.raises(ImportError, match="boto3 module not available"):
                MetadataWebSocketHook("https://api.example.com")

    def test_stores_metadata_fields(self):
        with patch(
            "mongodb_session_manager.hooks.metadata_websocket_hook.boto3"
        ) as mock_boto:
            mock_boto.client.return_value = MagicMock()
            hook = MetadataWebSocketHook(
                "https://api.example.com",
                metadata_fields=["status", "progress"],
            )
        assert hook.metadata_fields == ["status", "progress"]


# ---------------------------------------------------------------------------
# on_metadata_change
# ---------------------------------------------------------------------------


class TestOnMetadataChange:
    def test_sends_to_websocket(self, ws_hook):
        hook, mock_client = ws_hook
        asyncio.run(
            hook.on_metadata_change(
                "s1",
                {"connection_id": "conn123", "status": "active"},
                "update",
            )
        )
        mock_client.post_to_connection.assert_called_once()
        call_kwargs = mock_client.post_to_connection.call_args[1]
        assert call_kwargs["ConnectionId"] == "conn123"

    def test_skips_without_connection_id(self, ws_hook):
        hook, mock_client = ws_hook
        asyncio.run(hook.on_metadata_change("s1", {"status": "active"}, "update"))
        mock_client.post_to_connection.assert_not_called()

    def test_filters_fields(self, ws_hook):
        hook, mock_client = ws_hook
        asyncio.run(
            hook.on_metadata_change(
                "s1",
                {"connection_id": "c1", "status": "ok", "other": "ignored"},
                "update",
            )
        )
        data = json.loads(
            mock_client.post_to_connection.call_args[1]["Data"].decode("utf-8")
        )
        assert "status" in data["metadata"]
        assert "other" not in data["metadata"]

    def test_sends_all_without_filter(self):
        with patch(
            "mongodb_session_manager.hooks.metadata_websocket_hook.boto3"
        ) as mock_boto:
            mock_client = MagicMock()
            mock_boto.client.return_value = mock_client
            hook = MetadataWebSocketHook("https://api.example.com")

            asyncio.run(
                hook.on_metadata_change(
                    "s1",
                    {"connection_id": "c1", "any_field": "val"},
                    "update",
                )
            )
            data = json.loads(
                mock_client.post_to_connection.call_args[1]["Data"].decode("utf-8")
            )
            assert "any_field" in data["metadata"]
            assert "connection_id" not in data["metadata"]

    def test_handles_gone_exception(self, ws_hook):
        hook, mock_client = ws_hook
        from botocore.exceptions import ClientError

        error_response = {"Error": {"Code": "GoneException", "Message": "gone"}}
        mock_client.post_to_connection.side_effect = ClientError(
            error_response, "PostToConnection"
        )
        # Should not raise
        asyncio.run(
            hook.on_metadata_change(
                "s1", {"connection_id": "c1", "status": "x"}, "update"
            )
        )

    def test_handles_other_client_error(self, ws_hook):
        hook, mock_client = ws_hook
        from botocore.exceptions import ClientError

        error_response = {"Error": {"Code": "InternalError", "Message": "bad"}}
        mock_client.post_to_connection.side_effect = ClientError(
            error_response, "PostToConnection"
        )
        # Should not raise
        asyncio.run(
            hook.on_metadata_change(
                "s1", {"connection_id": "c1", "status": "x"}, "update"
            )
        )

    def test_handles_generic_error(self, ws_hook):
        hook, mock_client = ws_hook
        mock_client.post_to_connection.side_effect = Exception("network error")
        # Should not raise
        asyncio.run(
            hook.on_metadata_change(
                "s1", {"connection_id": "c1", "status": "x"}, "update"
            )
        )


# ---------------------------------------------------------------------------
# _build_delete_metadata
# ---------------------------------------------------------------------------


class TestBuildDeleteMetadata:
    def test_preserves_connection_id(self):
        original_func = MagicMock()
        original_func.__self__ = MagicMock()
        original_func.__self__.get_metadata.return_value = {"connection_id": "c1"}
        result = _build_delete_metadata(original_func, ["key1"])
        assert result["connection_id"] == "c1"
        assert result["key1"] is None

    def test_handles_missing_connection_id(self):
        original_func = MagicMock()
        original_func.__self__ = MagicMock()
        original_func.__self__.get_metadata.side_effect = Exception("no metadata")
        result = _build_delete_metadata(original_func, ["key1"])
        assert result == {"key1": None}


# ---------------------------------------------------------------------------
# create_metadata_hook
# ---------------------------------------------------------------------------


class TestCreateMetadataHookWebSocket:
    def test_returns_callable(self):
        with patch(
            "mongodb_session_manager.hooks.metadata_websocket_hook.boto3"
        ) as mock_boto:
            mock_boto.client.return_value = MagicMock()
            hook = create_metadata_hook("https://api.example.com")
        assert callable(hook)

    def test_handles_update_action(self):
        with patch(
            "mongodb_session_manager.hooks.metadata_websocket_hook.boto3"
        ) as mock_boto:
            mock_boto.client.return_value = MagicMock()
            hook = create_metadata_hook("https://api.example.com")

        original = MagicMock()
        hook(original, "update", "s1", metadata={"key": "val"})
        original.assert_called_once_with({"key": "val"})

    def test_handles_delete_action(self):
        with patch(
            "mongodb_session_manager.hooks.metadata_websocket_hook.boto3"
        ) as mock_boto:
            mock_boto.client.return_value = MagicMock()
            hook = create_metadata_hook("https://api.example.com")

        original = MagicMock()
        hook(original, "delete", "s1", keys=["k1"])
        original.assert_called_once_with(["k1"])

    def test_returns_none_on_creation_error(self):
        with patch("mongodb_session_manager.hooks.metadata_websocket_hook.boto3", None):
            hook = create_metadata_hook("https://api.example.com")
        assert hook is None


# ---------------------------------------------------------------------------
# _dispatch_async
# ---------------------------------------------------------------------------


class TestDispatchAsync:
    def test_sync_context(self):
        executed = []

        async def coro():
            executed.append(True)

        _dispatch_async(coro(), "test")
        import time

        time.sleep(0.1)
        assert len(executed) == 1

    def test_async_context(self):
        executed = []

        async def coro():
            executed.append(True)

        async def run():
            _dispatch_async(coro(), "test")
            await asyncio.sleep(0.05)

        asyncio.run(run())
        assert len(executed) == 1
