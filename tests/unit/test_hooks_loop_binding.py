"""The three AWS hooks bind an event loop and dispatch to it (#95).

A hook built inside a running loop (a FastAPI lifespan, say) remembers that
loop, so dispatching from a worker thread goes back to it instead of starting a
daemon thread per event. The loop can also be passed explicitly.
"""

import asyncio
import threading
from unittest.mock import MagicMock, patch

import pytest
from starlette.concurrency import run_in_threadpool

from mongodb_session_manager.hooks import (
    feedback_sns_hook,
    metadata_sqs_hook,
    metadata_websocket_hook,
)


@pytest.fixture
def server_loop():
    """An event loop running in its own thread, like a server's main loop."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, name="server-loop", daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


def _build_sqs_hook(**kwargs):
    with patch("mongodb_session_manager.hooks.metadata_sqs_hook.send_message"):
        return metadata_sqs_hook.create_metadata_hook(
            "https://sqs.example.com/q", ["status"], **kwargs
        )


def _build_websocket_hook(**kwargs):
    with patch("mongodb_session_manager.hooks.metadata_websocket_hook.boto3"):
        return metadata_websocket_hook.create_metadata_hook(
            "https://api.example.com", ["status"], **kwargs
        )


def _build_sns_hook(**kwargs):
    with patch("mongodb_session_manager.hooks.feedback_sns_hook.publish_message"):
        return feedback_sns_hook.create_feedback_hook(
            "arn:good", "arn:bad", "arn:neutral", **kwargs
        )


def _fire_metadata(hook):
    hook(MagicMock(), "update", "s1", metadata={"status": "active"})


def _fire_feedback(hook):
    hook(MagicMock(), "add", "s1", feedback={"rating": "up", "comment": "ok"})


HOOKS = [
    pytest.param(_build_sqs_hook, _fire_metadata, id="sqs"),
    pytest.param(_build_websocket_hook, _fire_metadata, id="websocket"),
    pytest.param(_build_sns_hook, _fire_feedback, id="sns"),
]


@pytest.mark.parametrize(("build", "fire"), HOOKS)
class TestHookLoopBinding:
    def test_explicit_loop_is_forwarded_to_the_dispatch(
        self, build, fire, server_loop, captured_dispatch
    ):
        fire(build(loop=server_loop))

        assert [call.loop for call in captured_dispatch] == [server_loop]

    def test_loop_running_at_construction_is_captured(
        self, build, fire, captured_dispatch
    ):
        built = {}

        async def construct():
            built["hook"] = build()
            built["loop"] = asyncio.get_running_loop()

        asyncio.run(construct())
        # Fired from a plain thread, like Starlette's run_in_threadpool.
        thread = threading.Thread(target=fire, args=(built["hook"],))
        thread.start()
        thread.join(timeout=5)

        assert [call.loop for call in captured_dispatch] == [built["loop"]]

    def test_without_a_loop_the_dispatch_decides(self, build, fire, captured_dispatch):
        fire(build())

        assert [call.loop for call in captured_dispatch] == [None]


@pytest.mark.asyncio
async def test_metadata_write_from_the_threadpool_notifies_on_the_server_loop(
    monkeypatch,
):
    """End to end: the #61 integration must not leave the server loop (#95)."""
    ran_on = {}
    notified = threading.Event()

    async def fake_change(self, session_id, metadata, operation):
        ran_on["loop"] = asyncio.get_running_loop()
        notified.set()

    monkeypatch.setattr(
        metadata_sqs_hook.MetadataSQSHook, "on_metadata_change", fake_change
    )
    # Built inside the running loop, as a FastAPI lifespan would.
    hook = _build_sqs_hook()
    server_loop = asyncio.get_running_loop()

    def sync_path():
        # Starlette's worker thread: this is where the metadata write happens.
        _fire_metadata(hook)

    await run_in_threadpool(sync_path)
    await asyncio.sleep(0.05)

    assert notified.is_set()
    assert ran_on["loop"] is server_loop
