"""The AWS clients of the hooks answer or give up; they do not hold a thread (#62).

botocore's defaults are 60 s to connect, 60 s to read and the legacy retry mode:
a notification against an unreachable endpoint keeps its thread for minutes,
and the thread is the resource the limit on work in flight is meant to protect.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest
from botocore.retries.standard import ExponentialBackoff

from mongodb_session_manager.hooks import utils_sns, utils_sqs
from mongodb_session_manager.hooks.aws_client_config import (
    CONNECT_TIMEOUT_SECONDS,
    MAX_BACKOFF_SECONDS,
    READ_TIMEOUT_SECONDS,
    RETRY_AFTER_ALLOWANCE_SECONDS,
    TOTAL_ATTEMPTS,
    backoff_seconds,
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


class TestTheBackoffBudgetIsBotocoreS:
    """The numbers are copied from botocore; an upgrade that moves them fails here.

    The worst case is what keeps a notification inside the shutdown grace, so it
    cannot be a guess. `AWS_NEW_RETRIES_2026` turns on a path that honours
    `x-amz-retry-after`, which adds seconds the old path never did — this asks
    botocore itself what the longest wait is.
    """

    @staticmethod
    def _throttled_delay(retry: int) -> float:
        """The longest botocore waits before `retry`, throttled and told to wait."""
        throttling = Mock()
        throttling.is_throttling_error_from_context.return_value = True
        backoff = ExponentialBackoff(
            random=lambda: 1.0,  # worst-case jitter
            throttling_detector=throttling,
        )
        context = Mock(attempt_number=retry)
        context.http_response.headers = {"x-amz-retry-after": "600"}
        return backoff.delay_amount(context)

    @pytest.mark.parametrize("retry", range(1, TOTAL_ATTEMPTS))
    def test_the_allowance_covers_what_botocore_can_wait(self, retry, monkeypatch):
        monkeypatch.setattr(
            "botocore.retries.standard.NEW_RETRIES_ENABLED", True, raising=False
        )

        assert self._throttled_delay(retry) <= backoff_seconds(retry)

    def test_the_constants_are_the_ones_botocore_holds(self):
        assert (
            RETRY_AFTER_ALLOWANCE_SECONDS
            == ExponentialBackoff._RETRY_AFTER_MAX_ADDITIONAL
        )
        assert MAX_BACKOFF_SECONDS == ExponentialBackoff._MAX_BACKOFF


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
