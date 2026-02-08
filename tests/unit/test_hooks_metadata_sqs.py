"""Unit tests for MetadataSQSHook."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from mongodb_session_manager.hooks.metadata_sqs_hook import (
    MetadataSQSHook,
    create_metadata_hook,
    _dispatch_async,
)


@pytest.fixture
def sqs_hook():
    """Create a MetadataSQSHook with mocked send_message."""
    with patch(
        "mongodb_session_manager.hooks.metadata_sqs_hook.send_message"
    ) as mock_send:
        mock_send.return_value = {"MessageId": "123"}
        hook = MetadataSQSHook(
            queue_url="https://sqs.example.com/queue",
            metadata_fields=["status", "priority"],
        )
        yield hook, mock_send


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestMetadataSQSHookInit:
    def test_stores_queue_url(self):
        with patch("mongodb_session_manager.hooks.metadata_sqs_hook.send_message"):
            hook = MetadataSQSHook("https://sqs.example.com/q", ["f1"])
        assert hook.queue_url == "https://sqs.example.com/q"

    def test_stores_metadata_fields(self):
        with patch("mongodb_session_manager.hooks.metadata_sqs_hook.send_message"):
            hook = MetadataSQSHook("https://sqs.example.com/q", ["status", "priority"])
        assert hook.metadata_fields == ["status", "priority"]

    def test_raises_import_error(self):
        with patch(
            "mongodb_session_manager.hooks.metadata_sqs_hook.send_message", None
        ):
            with pytest.raises(ImportError, match="SQS utilities not available"):
                MetadataSQSHook("https://sqs.example.com/q", [])


# ---------------------------------------------------------------------------
# on_metadata_change
# ---------------------------------------------------------------------------


class TestOnMetadataChange:
    def test_sends_to_sqs(self, sqs_hook):
        hook, mock_send = sqs_hook
        asyncio.run(
            hook.on_metadata_change(
                "s1", {"status": "active", "priority": "high"}, "update"
            )
        )
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["queue_url"] == "https://sqs.example.com/queue"

    def test_filters_fields(self, sqs_hook):
        hook, mock_send = sqs_hook
        asyncio.run(
            hook.on_metadata_change(
                "s1", {"status": "active", "other": "ignored"}, "update"
            )
        )
        import json

        body = json.loads(mock_send.call_args[1]["message_body"])
        assert "status" in body["metadata"]
        assert "other" not in body["metadata"]

    def test_sends_all_without_filter(self):
        with patch(
            "mongodb_session_manager.hooks.metadata_sqs_hook.send_message"
        ) as mock_send:
            hook = MetadataSQSHook("https://sqs.example.com/q", [])
            asyncio.run(hook.on_metadata_change("s1", {"any_field": "val"}, "update"))
            import json

            body = json.loads(mock_send.call_args[1]["message_body"])
            assert "any_field" in body["metadata"]

    def test_removes_none_values(self, sqs_hook):
        hook, mock_send = sqs_hook
        asyncio.run(
            hook.on_metadata_change(
                "s1", {"status": None, "priority": "high"}, "update"
            )
        )
        import json

        body = json.loads(mock_send.call_args[1]["message_body"])
        assert "status" not in body["metadata"]
        assert "priority" in body["metadata"]

    def test_handles_error_gracefully(self, sqs_hook):
        hook, mock_send = sqs_hook
        mock_send.side_effect = Exception("SQS error")
        # Should not raise
        asyncio.run(hook.on_metadata_change("s1", {"status": "x"}, "update"))


# ---------------------------------------------------------------------------
# create_metadata_hook
# ---------------------------------------------------------------------------


class TestCreateMetadataHook:
    def test_returns_callable(self):
        with patch("mongodb_session_manager.hooks.metadata_sqs_hook.send_message"):
            hook = create_metadata_hook("https://sqs.example.com/q", ["status"])
        assert callable(hook)

    def test_handles_update_action(self):
        with patch("mongodb_session_manager.hooks.metadata_sqs_hook.send_message"):
            hook = create_metadata_hook("https://sqs.example.com/q")

        original = MagicMock()
        hook(original, "update", "s1", metadata={"key": "val"})
        original.assert_called_once_with({"key": "val"})

    def test_handles_delete_action(self):
        with patch("mongodb_session_manager.hooks.metadata_sqs_hook.send_message"):
            hook = create_metadata_hook("https://sqs.example.com/q")

        original = MagicMock()
        hook(original, "delete", "s1", keys=["k1", "k2"])
        original.assert_called_once_with(["k1", "k2"])

    def test_handles_get_action(self):
        with patch("mongodb_session_manager.hooks.metadata_sqs_hook.send_message"):
            hook = create_metadata_hook("https://sqs.example.com/q")

        original = MagicMock()
        hook(original, "get", "s1")
        original.assert_called_once()

    def test_returns_none_on_creation_error(self):
        with patch(
            "mongodb_session_manager.hooks.metadata_sqs_hook.send_message", None
        ):
            hook = create_metadata_hook("https://sqs.example.com/q")
        assert hook is None


# ---------------------------------------------------------------------------
# _dispatch_async
# ---------------------------------------------------------------------------


class TestDispatchAsync:
    def test_sync_context_uses_thread(self):
        """In sync context (no running loop), should use a thread."""
        executed = []

        async def coro():
            executed.append(True)

        _dispatch_async(coro(), "test")
        import time

        time.sleep(0.1)
        assert len(executed) == 1

    def test_async_context_uses_task(self):
        """In async context, should create a task."""
        executed = []

        async def coro():
            executed.append(True)

        async def run():
            _dispatch_async(coro(), "test")
            await asyncio.sleep(0.05)

        asyncio.run(run())
        assert len(executed) == 1
