"""The AWS clients of the hooks answer or give up; they do not hold a thread (#62).

botocore's defaults are 60 s to connect, 60 s to read and the legacy retry mode:
a notification against an unreachable endpoint keeps its thread for minutes,
and the thread is the resource the limit on work in flight is meant to protect.
"""

from unittest.mock import MagicMock, patch

import pytest

from mongodb_session_manager.hooks import utils_sns, utils_sqs
from mongodb_session_manager.hooks.aws_client_config import (
    CONNECT_TIMEOUT_SECONDS,
    READ_TIMEOUT_SECONDS,
    TOTAL_ATTEMPTS,
    notification_config,
    worst_case_seconds,
)

# The grace ECS gives a task between SIGTERM and SIGKILL, by default.
ECS_STOP_TIMEOUT_SECONDS = 30


class TestNotificationConfig:
    def test_bounds_how_long_a_notification_may_hold_its_thread(self):
        config = notification_config()

        assert config.connect_timeout == CONNECT_TIMEOUT_SECONDS
        assert config.read_timeout == READ_TIMEOUT_SECONDS
        # botocore's max_attempts counts retries, not attempts.
        assert config.retries == {
            "mode": "standard",
            "max_attempts": TOTAL_ATTEMPTS - 1,
        }

    def test_the_worst_case_fits_inside_the_shutdown_grace(self):
        """A stuck notification must not outlive the task it belongs to."""
        assert worst_case_seconds() < ECS_STOP_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    ("module", "getter", "cache", "service"),
    [
        (utils_sqs, "_get_sqs_client", "_sqs_clients", "sqs"),
        (utils_sns, "_get_sns_client", "_sns_clients", "sns"),
    ],
    ids=["sqs", "sns"],
)
class TestBundledClients:
    def test_the_client_is_built_with_the_bounded_config(
        self, module, getter, cache, service, monkeypatch
    ):
        monkeypatch.setattr(module, cache, {})

        client = getattr(module, getter)("eu-west-1")

        assert client.meta.config.connect_timeout == CONNECT_TIMEOUT_SECONDS
        assert client.meta.config.read_timeout == READ_TIMEOUT_SECONDS
        assert client.meta.config.retries["total_max_attempts"] == TOTAL_ATTEMPTS

    def test_clients_are_still_cached_per_region(
        self, module, getter, cache, service, monkeypatch
    ):
        monkeypatch.setattr(module, cache, {})

        first = getattr(module, getter)("eu-west-1")
        second = getattr(module, getter)("eu-west-1")

        assert first is second


class TestWebSocketClient:
    def test_the_api_gateway_client_is_built_with_the_bounded_config(self):
        from mongodb_session_manager.hooks import metadata_websocket_hook

        with patch.object(metadata_websocket_hook, "boto3") as mock_boto:
            mock_boto.client.return_value = MagicMock()
            metadata_websocket_hook.MetadataWebSocketHook("https://api.example.com")

        config = mock_boto.client.call_args.kwargs["config"]
        assert config.connect_timeout == CONNECT_TIMEOUT_SECONDS
        assert config.read_timeout == READ_TIMEOUT_SECONDS
