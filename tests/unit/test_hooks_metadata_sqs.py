"""Unit tests for MetadataSQSHook."""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from mongodb_session_manager.hooks.metadata_sqs_hook import (
    MetadataSQSHook,
    create_metadata_hook,
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
        with (
            patch("mongodb_session_manager.hooks.metadata_sqs_hook.send_message", None),
            pytest.raises(ImportError, match="SQS utilities not available"),
        ):
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

    def test_delete_keeps_deleted_keys_when_fields_configured(self, sqs_hook):
        """A delete of a configured field travels as null (#120).

        Exact equality also pins the discriminator against the naive fix of
        just not filtering Nones on delete: `priority` is configured but not
        deleted, so it must not appear as deleted.
        """
        hook, mock_send = sqs_hook
        asyncio.run(hook.on_metadata_change("s1", {"status": None}, "delete"))

        body = json.loads(mock_send.call_args[1]["message_body"])
        assert body["metadata"] == {"status": None}

    def test_delete_ignores_unconfigured_keys(self, sqs_hook):
        """Deleting a field nobody subscribes to publishes no tombstone."""
        hook, mock_send = sqs_hook
        asyncio.run(hook.on_metadata_change("s1", {"unrelated": None}, "delete"))

        body = json.loads(mock_send.call_args[1]["message_body"])
        assert body["metadata"] == {}

    def test_delete_mixed_batch_keeps_only_configured_deleted(self, sqs_hook):
        hook, mock_send = sqs_hook
        asyncio.run(
            hook.on_metadata_change("s1", {"status": None, "other": None}, "delete")
        )

        body = json.loads(mock_send.call_args[1]["message_body"])
        assert body["metadata"] == {"status": None}

    def test_delete_keeps_every_key_without_fields(self):
        with patch(
            "mongodb_session_manager.hooks.metadata_sqs_hook.send_message"
        ) as mock_send:
            hook = MetadataSQSHook("https://sqs.example.com/q", [])
            asyncio.run(
                hook.on_metadata_change("s1", {"status": None, "other": None}, "delete")
            )

            body = json.loads(mock_send.call_args[1]["message_body"])
            assert body["metadata"] == {"status": None, "other": None}

    def test_an_sqs_error_reaches_the_dispatcher(self, sqs_hook):
        """The notification does not swallow it: nobody is waiting on this.

        By the time the coroutine runs, the metadata write has returned to its
        caller. Raising here reaches `BackgroundWork`, which counts it as
        failed and logs it once, with its context and its traceback.
        """
        hook, mock_send = sqs_hook
        mock_send.side_effect = Exception("SQS error")

        with pytest.raises(Exception, match="SQS error"):
            asyncio.run(hook.on_metadata_change("s1", {"status": "x"}, "update"))


# ---------------------------------------------------------------------------
# create_metadata_hook
# ---------------------------------------------------------------------------


class TestCreateMetadataHook:
    def test_returns_callable(self):
        with patch("mongodb_session_manager.hooks.metadata_sqs_hook.send_message"):
            hook = create_metadata_hook("https://sqs.example.com/q", ["status"])
        assert callable(hook)

    def test_handles_update_action(self, captured_dispatch):
        with patch("mongodb_session_manager.hooks.metadata_sqs_hook.send_message"):
            hook = create_metadata_hook("https://sqs.example.com/q")

        original = MagicMock()
        hook(original, "update", "s1", metadata={"key": "val"})
        original.assert_called_once_with({"key": "val"})

    def test_handles_delete_action(self, captured_dispatch):
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


class TestWrapperDeletePayload:
    """The wrapper → event → serialization chain, asserted end to end (#120).

    The wrapper tests above only count dispatches; the payload is what the
    consumer reads, and it is where the deleted keys were being lost.
    """

    @pytest.fixture
    def run_dispatch_now(self, monkeypatch):
        """Run the dispatched coroutine in place, so the payload is assertable."""
        from mongodb_session_manager.hooks import metadata_sqs_hook

        monkeypatch.setattr(
            metadata_sqs_hook,
            "dispatch_async",
            lambda coro, error_context, loop=None, **kwargs: asyncio.run(coro),
        )

    def test_delete_publishes_the_deleted_keys(self, run_dispatch_now):
        with patch(
            "mongodb_session_manager.hooks.metadata_sqs_hook.send_message"
        ) as mock_send:
            hook = create_metadata_hook("https://sqs.example.com/q", ["status"])
            original = MagicMock()
            hook(original, "delete", "s1", keys=["status"])

        body = json.loads(mock_send.call_args[1]["message_body"])
        assert body["operation"] == "delete"
        assert body["metadata"] == {"status": None}
        original.assert_called_once_with(["status"])

    def test_delete_without_fields_publishes_every_key_as_null(self, run_dispatch_now):
        with patch(
            "mongodb_session_manager.hooks.metadata_sqs_hook.send_message"
        ) as mock_send:
            hook = create_metadata_hook("https://sqs.example.com/q")
            hook(MagicMock(), "delete", "s1", keys=["status", "other"])

        body = json.loads(mock_send.call_args[1]["message_body"])
        assert body["operation"] == "delete"
        assert body["metadata"] == {"status": None, "other": None}
