"""What the counters say when AWS refuses a notification.

The rest of the hook tests either run the coroutine alone or replace the
dispatch with a recorder. Neither can see what `BackgroundWork` made of the
outcome, which is the only place a failed notification becomes visible to a
metric or a health endpoint.
"""

import logging

import pytest

from tests.conftest import wait_until
from tests.support.hook_builders import (
    LIVE_NOTIFICATIONS,
    client_error,
    websocket_notification,
)


@pytest.mark.parametrize("notification", LIVE_NOTIFICATIONS)
def test_an_aws_error_counts_as_failed(work, server_loop, notification):
    with notification(side_effect=client_error("InternalFailure")) as coro:
        work.submit(coro, "notifying for session s1", server_loop)
        assert wait_until(lambda: work.stats.failed == 1)

    assert work.stats.completed == 0
    assert work.stats.dispatched == 1


@pytest.mark.parametrize("notification", LIVE_NOTIFICATIONS)
def test_a_delivered_notification_counts_as_completed(work, server_loop, notification):
    with notification() as coro:
        work.submit(coro, "notifying for session s1", server_loop)
        assert wait_until(lambda: work.stats.completed == 1)

    assert work.stats.failed == 0


def test_a_gone_connection_counts_as_completed(work, server_loop):
    """The client hung up. Nothing was delivered, and nothing went wrong."""
    with websocket_notification(side_effect=client_error("GoneException")) as coro:
        work.submit(coro, "notifying for session s1", server_loop)
        assert wait_until(lambda: work.stats.completed == 1)

    assert work.stats.failed == 0


@pytest.mark.parametrize("notification", LIVE_NOTIFICATIONS)
def test_a_failure_is_logged_once_with_its_session(
    work, server_loop, notification, caplog
):
    with (
        caplog.at_level(logging.ERROR),
        notification(
            side_effect=client_error("InternalFailure"), session_id="sess-42"
        ) as coro,
    ):
        work.submit(coro, "sending a notification for session sess-42", server_loop)
        assert wait_until(lambda: work.stats.failed == 1)

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert "sess-42" in errors[0].getMessage()
