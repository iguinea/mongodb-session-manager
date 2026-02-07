"""Unit tests for FeedbackSNSHook."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from mongodb_session_manager.hooks.feedback_sns_hook import (
    FeedbackSNSHook,
    create_feedback_hook,
)


@pytest.fixture
def sns_hook():
    """Create a FeedbackSNSHook with mocked publish_message."""
    with patch(
        "mongodb_session_manager.hooks.feedback_sns_hook.publish_message"
    ) as mock_pub:
        mock_pub.return_value = {"MessageId": "123"}
        hook = FeedbackSNSHook(
            topic_arn_good="arn:good",
            topic_arn_bad="arn:bad",
            topic_arn_neutral="arn:neutral",
        )
        yield hook, mock_pub


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestFeedbackSNSHookInit:
    def test_stores_arns(self):
        with patch("mongodb_session_manager.hooks.feedback_sns_hook.publish_message"):
            hook = FeedbackSNSHook("arn:g", "arn:b", "arn:n")
        assert hook.topic_arn_good == "arn:g"
        assert hook.topic_arn_bad == "arn:b"
        assert hook.topic_arn_neutral == "arn:n"

    def test_stores_templates(self):
        with patch("mongodb_session_manager.hooks.feedback_sns_hook.publish_message"):
            hook = FeedbackSNSHook(
                "arn:g",
                "arn:b",
                "arn:n",
                subject_prefix_good="[GOOD] ",
                body_prefix_bad="ALERT: ",
            )
        assert hook.subject_prefix_good == "[GOOD] "
        assert hook.body_prefix_bad == "ALERT: "

    def test_raises_import_error(self):
        with patch(
            "mongodb_session_manager.hooks.feedback_sns_hook.publish_message", None
        ):
            with pytest.raises(ImportError, match="SNS utilities not available"):
                FeedbackSNSHook("arn:g", "arn:b", "arn:n")


# ---------------------------------------------------------------------------
# _apply_template
# ---------------------------------------------------------------------------


class TestApplyTemplate:
    def test_applies_variables(self, sns_hook):
        hook, _ = sns_hook
        result = hook._apply_template(
            "Session: {session_id} Rating: {rating}",
            {"session_id": "s1", "rating": "positive", "timestamp": "2024-01-01"},
        )
        assert "s1" in result
        assert "positive" in result

    def test_returns_empty_for_none(self, sns_hook):
        hook, _ = sns_hook
        assert hook._apply_template(None, {}) == ""

    def test_handles_missing_variable(self, sns_hook):
        hook, _ = sns_hook
        result = hook._apply_template("{missing_var}", {})
        assert result == "{missing_var}"


# ---------------------------------------------------------------------------
# on_feedback_add
# ---------------------------------------------------------------------------


class TestOnFeedbackAdd:
    def test_routes_positive(self, sns_hook):
        hook, mock_pub = sns_hook
        session_mgr = MagicMock()
        session_mgr.get_session_viewer_password.return_value = "pwd123"
        asyncio.run(
            hook.on_feedback_add(
                "s1", {"rating": "up", "comment": "great"}, session_manager=session_mgr
            )
        )
        mock_pub.assert_called_once()
        call_kwargs = mock_pub.call_args[1]
        assert call_kwargs["topic_arn"] == "arn:good"

    def test_routes_negative(self, sns_hook):
        hook, mock_pub = sns_hook
        session_mgr = MagicMock()
        session_mgr.get_session_viewer_password.return_value = "pwd123"
        asyncio.run(
            hook.on_feedback_add(
                "s1", {"rating": "down", "comment": "bad"}, session_manager=session_mgr
            )
        )
        assert mock_pub.call_args[1]["topic_arn"] == "arn:bad"

    def test_routes_neutral(self, sns_hook):
        hook, mock_pub = sns_hook
        session_mgr = MagicMock()
        session_mgr.get_session_viewer_password.return_value = "pwd123"
        asyncio.run(
            hook.on_feedback_add(
                "s1", {"rating": None, "comment": "meh"}, session_manager=session_mgr
            )
        )
        assert mock_pub.call_args[1]["topic_arn"] == "arn:neutral"

    def test_includes_subject_prefix(self):
        with patch(
            "mongodb_session_manager.hooks.feedback_sns_hook.publish_message"
        ) as mock_pub:
            hook = FeedbackSNSHook(
                "arn:g",
                "arn:b",
                "arn:n",
                subject_prefix_bad="[URGENT] ",
            )
            session_mgr = MagicMock()
            session_mgr.get_session_viewer_password.return_value = "pwd"
            asyncio.run(
                hook.on_feedback_add(
                    "s1", {"rating": "down"}, session_manager=session_mgr
                )
            )
            subject = mock_pub.call_args[1]["subject"]
            assert subject.startswith("[URGENT] ")

    def test_skips_when_topic_none(self, sns_hook):
        hook, mock_pub = sns_hook
        hook.topic_arn_neutral = "none"
        session_mgr = MagicMock()
        session_mgr.get_session_viewer_password.return_value = "pwd"
        asyncio.run(
            hook.on_feedback_add("s1", {"rating": None}, session_manager=session_mgr)
        )
        mock_pub.assert_not_called()

    def test_includes_password_in_message(self, sns_hook):
        hook, mock_pub = sns_hook
        session_mgr = MagicMock()
        session_mgr.get_session_viewer_password.return_value = "secret-pwd"
        asyncio.run(
            hook.on_feedback_add("s1", {"rating": "up"}, session_manager=session_mgr)
        )
        message = mock_pub.call_args[1]["message"]
        assert "secret-pwd" in message

    def test_includes_message_attributes(self, sns_hook):
        hook, mock_pub = sns_hook
        session_mgr = MagicMock()
        session_mgr.get_session_viewer_password.return_value = "pwd"
        asyncio.run(
            hook.on_feedback_add("s1", {"rating": "up"}, session_manager=session_mgr)
        )
        attrs = mock_pub.call_args[1]["message_attributes"]
        assert attrs["session_id"]["StringValue"] == "s1"

    def test_handles_error_gracefully(self, sns_hook):
        hook, mock_pub = sns_hook
        mock_pub.side_effect = Exception("SNS error")
        session_mgr = MagicMock()
        session_mgr.get_session_viewer_password.return_value = "pwd"
        # Should not raise
        asyncio.run(
            hook.on_feedback_add("s1", {"rating": "up"}, session_manager=session_mgr)
        )

    def test_handles_no_session_manager(self, sns_hook):
        hook, mock_pub = sns_hook
        # No session_manager kwarg - should handle gracefully
        asyncio.run(hook.on_feedback_add("s1", {"rating": "up"}))
        message = mock_pub.call_args[1]["message"]
        assert "N/A" in message


# ---------------------------------------------------------------------------
# create_feedback_hook
# ---------------------------------------------------------------------------


class TestCreateFeedbackHook:
    def test_returns_callable(self):
        with patch("mongodb_session_manager.hooks.feedback_sns_hook.publish_message"):
            hook = create_feedback_hook("arn:g", "arn:b", "arn:n")
        assert callable(hook)

    def test_calls_original_func_first(self):
        with patch("mongodb_session_manager.hooks.feedback_sns_hook.publish_message"):
            hook = create_feedback_hook("arn:g", "arn:b", "arn:n")

        original = MagicMock()
        hook(original, "add", "s1", feedback={"rating": "up"})
        original.assert_called_once_with({"rating": "up"})

    def test_handles_non_add_action(self):
        with patch("mongodb_session_manager.hooks.feedback_sns_hook.publish_message"):
            hook = create_feedback_hook("arn:g", "arn:b", "arn:n")

        original = MagicMock()
        hook(original, "get", "s1")
        original.assert_called_once()

    def test_returns_none_on_creation_error(self):
        with patch(
            "mongodb_session_manager.hooks.feedback_sns_hook.publish_message", None
        ):
            hook = create_feedback_hook("arn:g", "arn:b", "arn:n")
        assert hook is None

    def test_passes_session_manager_to_hook(self):
        with patch("mongodb_session_manager.hooks.feedback_sns_hook.publish_message"):
            hook = create_feedback_hook("arn:g", "arn:b", "arn:n")

        original = MagicMock()
        session_mgr = MagicMock()
        hook(
            original,
            "add",
            "s1",
            feedback={"rating": "up"},
            session_manager=session_mgr,
        )
        original.assert_called_once()
