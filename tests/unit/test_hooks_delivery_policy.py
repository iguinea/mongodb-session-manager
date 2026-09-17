"""What each bundled hook is willing to lose, and what it needs in order (#62).

The metadata hooks refresh a view: losing one update is corrected by the next,
but delivering an old one after a new one leaves the view wrong for good, so
they order their work by session. A feedback notification carries a customer
complaint that nothing produces again, so it is never dropped to respect a
limit.
"""

from unittest.mock import MagicMock, patch

import pytest

from mongodb_session_manager.hooks import (
    feedback_sns_hook,
    metadata_sqs_hook,
    metadata_websocket_hook,
)
from mongodb_session_manager.hooks.background_work import Delivery


def _build_sqs_hook():
    with patch("mongodb_session_manager.hooks.metadata_sqs_hook.send_message"):
        return metadata_sqs_hook.create_metadata_hook(
            "https://sqs.example.com/q", ["status"]
        )


def _build_websocket_hook():
    with patch("mongodb_session_manager.hooks.metadata_websocket_hook.boto3"):
        return metadata_websocket_hook.create_metadata_hook(
            "https://api.example.com", ["status"]
        )


METADATA_HOOKS = [
    pytest.param(_build_sqs_hook, id="sqs"),
    pytest.param(_build_websocket_hook, id="websocket"),
]


@pytest.mark.parametrize("build", METADATA_HOOKS)
class TestMetadataOrdersBySession:
    def test_an_update_is_ordered_by_its_session(self, build, captured_dispatch):
        build()(MagicMock(), "update", "session-7", metadata={"status": "active"})

        assert [call.order_key for call in captured_dispatch] == ["session-7"]

    def test_a_delete_is_ordered_by_its_session(self, build, captured_dispatch):
        build()(MagicMock(), "delete", "session-7", keys=["status"])

        assert [call.order_key for call in captured_dispatch] == ["session-7"]

    def test_updates_of_different_sessions_do_not_share_a_key(
        self, build, captured_dispatch
    ):
        hook = build()
        hook(MagicMock(), "update", "session-1", metadata={"status": "active"})
        hook(MagicMock(), "update", "session-2", metadata={"status": "active"})

        assert [call.order_key for call in captured_dispatch] == [
            "session-1",
            "session-2",
        ]

    def test_metadata_is_best_effort(self, build, captured_dispatch):
        build()(MagicMock(), "update", "session-7", metadata={"status": "active"})

        assert [call.delivery for call in captured_dispatch] == [None]


class TestFeedbackIsGuaranteed:
    def test_a_feedback_notification_is_not_dropped_on_overflow(
        self, captured_dispatch
    ):
        with patch("mongodb_session_manager.hooks.feedback_sns_hook.publish_message"):
            hook = feedback_sns_hook.create_feedback_hook(
                "arn:good", "arn:bad", "arn:neutral"
            )

        hook(
            MagicMock(), "add", "session-7", feedback={"rating": "down", "comment": ""}
        )

        assert [call.delivery for call in captured_dispatch] == [Delivery.GUARANTEED]

    def test_feedback_is_not_ordered_by_session(self, captured_dispatch):
        """One feedback per conversation: serialising it would buy nothing."""
        with patch("mongodb_session_manager.hooks.feedback_sns_hook.publish_message"):
            hook = feedback_sns_hook.create_feedback_hook(
                "arn:good", "arn:bad", "arn:neutral"
            )

        hook(MagicMock(), "add", "session-7", feedback={"rating": "up", "comment": ""})

        assert [call.order_key for call in captured_dispatch] == [None]
