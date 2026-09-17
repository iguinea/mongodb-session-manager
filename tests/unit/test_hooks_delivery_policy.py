"""What each bundled hook is willing to lose, and what it needs in order (#62).

The metadata hooks refresh a view: losing one update is corrected by the next,
but delivering an old one after a new one leaves the view wrong for good, so
they order their work by session. A feedback notification carries a customer
complaint that nothing produces again, so it is never dropped to respect a
limit.
"""

import pytest

from mongodb_session_manager.hooks.background_work import Delivery
from tests.support.hook_builders import (
    METADATA_HOOKS,
    build_sns_hook,
    fire_feedback,
    fire_metadata,
    fire_metadata_delete,
)


@pytest.mark.parametrize("build", METADATA_HOOKS)
class TestMetadataOrdersBySession:
    def test_an_update_is_ordered_by_its_session(self, build, captured_dispatch):
        fire_metadata(build(), "session-7")

        assert captured_dispatch[0].order_key.endswith(":session-7")

    def test_a_delete_is_ordered_by_its_session(self, build, captured_dispatch):
        fire_metadata_delete(build(), "session-7")

        assert captured_dispatch[0].order_key.endswith(":session-7")

    def test_updates_of_different_sessions_do_not_share_a_key(
        self, build, captured_dispatch
    ):
        hook = build()
        fire_metadata(hook, "session-1")
        fire_metadata(hook, "session-2")

        first, second = (call.order_key for call in captured_dispatch)
        assert first != second
        assert first.endswith(":session-1") and second.endswith(":session-2")

    def test_the_key_is_namespaced_per_hook(self, build, captured_dispatch):
        """Two hooks on one session must not serialise against each other."""
        fire_metadata(build(), "session-7")

        namespace = captured_dispatch[0].order_key.split(":")[0]
        assert namespace in {"sqs", "websocket"}

    def test_metadata_is_best_effort(self, build, captured_dispatch):
        fire_metadata(build(), "session-7")

        assert [call.delivery for call in captured_dispatch] == [None]


class TestFeedbackIsGuaranteed:
    def test_a_feedback_notification_is_not_dropped_on_overflow(
        self, captured_dispatch
    ):
        fire_feedback(build_sns_hook(), "session-7", rating="down")

        assert [call.delivery for call in captured_dispatch] == [Delivery.GUARANTEED]

    def test_feedback_is_not_ordered_by_session(self, captured_dispatch):
        """One feedback per conversation: serialising it would buy nothing."""
        fire_feedback(build_sns_hook(), "session-7")

        assert [call.order_key for call in captured_dispatch] == [None]
