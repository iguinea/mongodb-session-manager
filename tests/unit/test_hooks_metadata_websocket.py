"""Unit tests for MetadataWebSocketHook."""

import asyncio
import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from mongodb_session_manager.hooks.metadata_websocket_hook import (
    MetadataWebSocketHook,
    _build_delete_metadata,
    create_metadata_hook,
)
from mongodb_session_manager.mongodb_session_manager import MongoDBSessionManager
from tests.support.in_memory_session_repository import InMemorySessionRepository


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
            call = mock_boto.client.call_args
            assert call.args == ("apigatewaymanagementapi",)
            assert call.kwargs["endpoint_url"] == "https://api.example.com"
            assert call.kwargs["region_name"] == "eu-west-1"

    def test_raises_import_error(self):
        with (
            patch("mongodb_session_manager.hooks.metadata_websocket_hook.boto3", None),
            pytest.raises(ImportError, match="boto3 module not available"),
        ):
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

    def test_delete_keeps_deleted_keys_when_fields_configured(self, ws_hook):
        """A delete of a configured field travels as null (#120).

        Exact equality also pins the discriminator against the naive fix of
        just not filtering Nones on delete: `progress` is configured but not
        deleted, so it must not appear as deleted.
        """
        hook, mock_client = ws_hook
        asyncio.run(
            hook.on_metadata_change(
                "s1", {"connection_id": "c1", "status": None}, "delete"
            )
        )
        data = json.loads(
            mock_client.post_to_connection.call_args[1]["Data"].decode("utf-8")
        )
        assert data["metadata"] == {"status": None}

    def test_delete_ignores_unconfigured_keys(self, ws_hook):
        """Deleting a field nobody subscribes to publishes no tombstone."""
        hook, mock_client = ws_hook
        asyncio.run(
            hook.on_metadata_change(
                "s1", {"connection_id": "c1", "unrelated": None}, "delete"
            )
        )
        data = json.loads(
            mock_client.post_to_connection.call_args[1]["Data"].decode("utf-8")
        )
        assert data["metadata"] == {}

    def test_delete_mixed_batch_keeps_only_configured_deleted(self, ws_hook):
        hook, mock_client = ws_hook
        asyncio.run(
            hook.on_metadata_change(
                "s1", {"connection_id": "c1", "status": None, "other": None}, "delete"
            )
        )
        data = json.loads(
            mock_client.post_to_connection.call_args[1]["Data"].decode("utf-8")
        )
        assert data["metadata"] == {"status": None}

    def test_delete_keeps_every_key_without_fields(self):
        with patch(
            "mongodb_session_manager.hooks.metadata_websocket_hook.boto3"
        ) as mock_boto:
            mock_client = MagicMock()
            mock_boto.client.return_value = mock_client
            hook = MetadataWebSocketHook("https://api.example.com")

            asyncio.run(
                hook.on_metadata_change(
                    "s1",
                    {"connection_id": "c1", "status": None, "other": None},
                    "delete",
                )
            )
            data = json.loads(
                mock_client.post_to_connection.call_args[1]["Data"].decode("utf-8")
            )
            assert data["metadata"] == {"status": None, "other": None}

    def test_update_still_filters_none_values(self, ws_hook):
        """The delete selection must not leak into updates (#120)."""
        hook, mock_client = ws_hook
        asyncio.run(
            hook.on_metadata_change(
                "s1",
                {"connection_id": "c1", "status": None, "progress": "p"},
                "update",
            )
        )
        data = json.loads(
            mock_client.post_to_connection.call_args[1]["Data"].decode("utf-8")
        )
        assert data["metadata"] == {"progress": "p"}

    def test_a_gone_connection_is_a_normal_outcome(self, ws_hook, caplog):
        """The client disconnected. Nothing was delivered, and nothing failed.

        The one AWS error this hook still absorbs: it is how a WebSocket
        session ends, not a fault to report.
        """
        hook, mock_client = ws_hook
        from botocore.exceptions import ClientError

        error_response = {"Error": {"Code": "GoneException", "Message": "gone"}}
        mock_client.post_to_connection.side_effect = ClientError(
            error_response, "PostToConnection"
        )

        with caplog.at_level(logging.INFO):
            asyncio.run(
                hook.on_metadata_change(
                    "s1", {"connection_id": "c1", "status": "x"}, "update"
                )
            )

        assert "GoneException" in caplog.text
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    def test_any_other_client_error_reaches_the_dispatcher(self, ws_hook):
        hook, mock_client = ws_hook
        from botocore.exceptions import ClientError

        error_response = {"Error": {"Code": "InternalError", "Message": "bad"}}
        mock_client.post_to_connection.side_effect = ClientError(
            error_response, "PostToConnection"
        )

        with pytest.raises(ClientError):
            asyncio.run(
                hook.on_metadata_change(
                    "s1", {"connection_id": "c1", "status": "x"}, "update"
                )
            )

    def test_a_generic_error_reaches_the_dispatcher(self, ws_hook):
        hook, mock_client = ws_hook
        mock_client.post_to_connection.side_effect = Exception("network error")

        with pytest.raises(Exception, match="network error"):
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
        """`get_metadata()` returns the projected document, not flat metadata.

        The mock used to be the flat `{"connection_id": "c1"}`, which no real
        `get_metadata()` returns — it hid that the routing id was always read
        as absent and the delete was never sent (#120).
        """
        original_func = MagicMock()
        original_func.__self__ = MagicMock()
        original_func.__self__.get_metadata.return_value = {
            "_id": "s1",
            "metadata": {"connection_id": "c1"},
        }
        result = _build_delete_metadata(original_func, ["key1"])
        assert result["connection_id"] == "c1"
        assert result["key1"] is None

    def test_without_connection_id_only_tombstones(self):
        original_func = MagicMock()
        original_func.__self__ = MagicMock()
        original_func.__self__.get_metadata.return_value = {
            "_id": "s1",
            "metadata": {},
        }
        result = _build_delete_metadata(original_func, ["key1"])
        assert result == {"key1": None}

    def test_handles_no_document(self):
        original_func = MagicMock()
        original_func.__self__ = MagicMock()
        original_func.__self__.get_metadata.return_value = None
        result = _build_delete_metadata(original_func, ["key1"])
        assert result == {"key1": None}

    def test_deleting_the_connection_id_itself_keeps_the_routing(self):
        """Routing wins over the tombstone: the event must still be sent.

        Deleting `connection_id` leaves the session without a destination, and
        an event nobody can deliver is worth less than one delivered to the
        connection that just unbound itself (#120).
        """
        original_func = MagicMock()
        original_func.__self__ = MagicMock()
        original_func.__self__.get_metadata.return_value = {
            "_id": "s1",
            "metadata": {"connection_id": "c1"},
        }
        result = _build_delete_metadata(original_func, ["connection_id"])
        assert result == {"connection_id": "c1"}

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

    def test_handles_update_action(self, captured_dispatch):
        with patch(
            "mongodb_session_manager.hooks.metadata_websocket_hook.boto3"
        ) as mock_boto:
            mock_boto.client.return_value = MagicMock()
            hook = create_metadata_hook("https://api.example.com")

        original = MagicMock()
        hook(original, "update", "s1", metadata={"key": "val"})
        original.assert_called_once_with({"key": "val"})
        assert len(captured_dispatch) == 1

    def test_handles_delete_action(self, captured_dispatch):
        with patch(
            "mongodb_session_manager.hooks.metadata_websocket_hook.boto3"
        ) as mock_boto:
            mock_boto.client.return_value = MagicMock()
            hook = create_metadata_hook("https://api.example.com")

        original = MagicMock()
        hook(original, "delete", "s1", keys=["k1"])
        original.assert_called_once_with(["k1"])
        assert len(captured_dispatch) == 1

    def test_returns_none_on_creation_error(self):
        with patch("mongodb_session_manager.hooks.metadata_websocket_hook.boto3", None):
            hook = create_metadata_hook("https://api.example.com")
        assert hook is None


class TestWebSocketDeleteRealPath:
    """The delete through the whole chain: manager, wrapper, dispatch, send.

    The `on_metadata_change()` tests hand it a flat dict that already carries
    the routing id — not what the wrapper builds. `TestBuildDeleteMetadata`
    mocked `get_metadata()` with that same flat shape and hid the real one:
    the projected session document (`{"_id", "metadata"}`). Through the real
    path a delete used to send nothing at all (#120).
    """

    @pytest.fixture
    def run_dispatch_now(self, monkeypatch):
        """Run the dispatched coroutine in place, so the send is assertable."""
        from mongodb_session_manager.hooks import metadata_websocket_hook

        monkeypatch.setattr(
            metadata_websocket_hook,
            "dispatch_async",
            lambda coro, error_context, loop=None, **kwargs: asyncio.run(coro),
        )

    @staticmethod
    def _manager_with_hook(mock_boto, sent):
        client = MagicMock()
        client.post_to_connection.side_effect = lambda ConnectionId, Data: sent.append(
            (ConnectionId, json.loads(Data.decode("utf-8")))
        )
        mock_boto.client.return_value = client
        return MongoDBSessionManager(
            session_id="s1",
            session_repository=InMemorySessionRepository(),
            metadata_hook=create_metadata_hook(
                "https://api.example.com/prod", metadata_fields=["status"]
            ),
        )

    def test_delete_reaches_the_connection(self, run_dispatch_now):
        sent = []
        with patch(
            "mongodb_session_manager.hooks.metadata_websocket_hook.boto3"
        ) as mock_boto:
            manager = self._manager_with_hook(mock_boto, sent)
            manager.update_metadata({"connection_id": "c1", "status": "x"})
            manager.delete_metadata(["status"])

        assert len(sent) == 2
        connection_id, body = sent[1]
        assert connection_id == "c1"
        assert body["operation"] == "delete"
        assert body["metadata"] == {"status": None}

    def test_deleting_the_connection_id_still_routes(self, run_dispatch_now):
        """The routing id is read before the delete: the event has a destination."""
        sent = []
        with patch(
            "mongodb_session_manager.hooks.metadata_websocket_hook.boto3"
        ) as mock_boto:
            manager = self._manager_with_hook(mock_boto, sent)
            manager.update_metadata({"connection_id": "c1", "status": "x"})
            manager.delete_metadata(["connection_id"])

        assert len(sent) == 2
        connection_id, body = sent[1]
        assert connection_id == "c1"
        assert body["operation"] == "delete"
