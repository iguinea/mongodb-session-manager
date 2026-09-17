"""Building and firing the three bundled hooks, without touching AWS.

Every test that exercises a hook wrapper needs the same two things: a hook
whose boto3 client is a mock, and a call that makes it dispatch. They live
here so the patch targets — module paths that move when a hook is renamed —
are written once.
"""

from unittest.mock import MagicMock, patch

import pytest

from mongodb_session_manager.hooks import (
    feedback_sns_hook,
    metadata_sqs_hook,
    metadata_websocket_hook,
)


def build_sqs_hook(**kwargs):
    """A metadata SQS hook, built without touching AWS.

    The patch covers construction only: `send_message` is looked up when the
    coroutine runs, which is later and on another thread. Fire this hook with
    the `captured_dispatch` fixture, or the notification reaches boto3 for
    real.
    """
    with patch("mongodb_session_manager.hooks.metadata_sqs_hook.send_message"):
        return metadata_sqs_hook.create_metadata_hook(
            "https://sqs.example.com/q", ["status"], **kwargs
        )


def build_websocket_hook(**kwargs):
    """A metadata WebSocket hook whose API Gateway client is a mock."""
    with patch("mongodb_session_manager.hooks.metadata_websocket_hook.boto3"):
        return metadata_websocket_hook.create_metadata_hook(
            "https://api.example.com", ["status"], **kwargs
        )


def build_sns_hook(**kwargs):
    """A feedback SNS hook, built without touching AWS.

    Same caveat as `build_sqs_hook()`: fire it with `captured_dispatch`.
    """
    with patch("mongodb_session_manager.hooks.feedback_sns_hook.publish_message"):
        return feedback_sns_hook.create_feedback_hook(
            "arn:good", "arn:bad", "arn:neutral", **kwargs
        )


def fire_metadata(hook, session_id: str = "s1") -> None:
    """Make a metadata hook dispatch an update."""
    hook(MagicMock(), "update", session_id, metadata={"status": "active"})


def fire_metadata_delete(hook, session_id: str = "s1") -> None:
    """Make a metadata hook dispatch a delete."""
    hook(MagicMock(), "delete", session_id, keys=["status"])


def fire_feedback(hook, session_id: str = "s1", rating: str = "up") -> None:
    """Make a feedback hook dispatch a notification."""
    hook(MagicMock(), "add", session_id, feedback={"rating": rating, "comment": "ok"})


# The metadata hooks share a policy, so most tests want both at once.
METADATA_HOOKS = [
    pytest.param(build_sqs_hook, id="sqs"),
    pytest.param(build_websocket_hook, id="websocket"),
]

# All three, with the call that makes each one dispatch.
ALL_HOOKS = [
    pytest.param(build_sqs_hook, fire_metadata, id="sqs"),
    pytest.param(build_websocket_hook, fire_metadata, id="websocket"),
    pytest.param(build_sns_hook, fire_feedback, id="sns"),
]
