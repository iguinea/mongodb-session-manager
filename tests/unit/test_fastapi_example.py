"""The non-streaming FastAPI example must not pin the server event loop (#61)."""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from examples import example_fastapi


class FakeMetrics:
    def get_summary(self) -> dict[str, Any]:
        return {
            "total_cycles": 2,
            "accumulated_usage": {"totalTokens": 42},
            "accumulated_metrics": {"latencyMs": 80},
        }


class FakeManager:
    def __init__(self) -> None:
        self.closed = threading.Event()

    def close(self) -> None:
        self.closed.set()


class FakeFactory:
    def __init__(self) -> None:
        self.manager = FakeManager()

    def create_session_manager(self, _session_id: str) -> FakeManager:
        return self.manager


def request_for(factory: FakeFactory) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(session_factory=factory))
    )


class TestThreadOffload:
    @pytest.mark.asyncio
    async def test_blocking_agent_does_not_block_the_server_loop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        invocation_threads: list[int] = []

        class BlockingAgent:
            def __init__(self, **_kwargs: Any) -> None:
                self.agent_id = "agent"
                self.messages = ["user", "assistant"]
                self.event_loop_metrics = FakeMetrics()

            def __call__(self, _prompt: str) -> str:
                invocation_threads.append(threading.get_ident())
                time.sleep(0.15)
                return "ok"

        monkeypatch.setattr(example_fastapi, "Agent", BlockingAgent)
        factory = FakeFactory()
        ticks = 0
        finished = False

        async def heartbeat() -> None:
            nonlocal ticks
            while not finished:
                ticks += 1
                await asyncio.sleep(0.01)

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            response = await example_fastapi.chat(
                request_for(factory),
                example_fastapi.ChatRequest(prompt="hello"),
                "session-1",
            )
        finally:
            finished = True
            await heartbeat_task

        assert response.response == "ok"
        assert response.metrics == {
            "total_tokens": 42,
            "average_latency_ms": 40,
            "total_messages": 2,
        }
        assert ticks >= 5
        assert invocation_threads != [threading.get_ident()]
        assert factory.manager.closed.is_set()

    @pytest.mark.asyncio
    async def test_errors_propagate_and_the_manager_is_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FailingAgent:
            def __init__(self, **_kwargs: Any) -> None: ...

            def __call__(self, _prompt: str) -> str:
                raise RuntimeError("model failed")

        monkeypatch.setattr(example_fastapi, "Agent", FailingAgent)
        factory = FakeFactory()

        with pytest.raises(HTTPException, match="model failed") as raised:
            await example_fastapi.chat(
                request_for(factory),
                example_fastapi.ChatRequest(prompt="hello"),
                "session-1",
            )

        assert raised.value.status_code == 500
        assert factory.manager.closed.is_set()

    @pytest.mark.asyncio
    async def test_cancelling_the_waiter_does_not_abandon_manager_cleanup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        started = threading.Event()
        release = threading.Event()

        class SlowAgent:
            def __init__(self, **_kwargs: Any) -> None:
                self.messages = []
                self.event_loop_metrics = FakeMetrics()

            def __call__(self, _prompt: str) -> str:
                started.set()
                release.wait(timeout=2)
                return "late result"

        monkeypatch.setattr(example_fastapi, "Agent", SlowAgent)
        factory = FakeFactory()
        task = asyncio.create_task(
            example_fastapi.chat(
                request_for(factory),
                example_fastapi.ChatRequest(prompt="hello"),
                "session-1",
            )
        )

        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        release.set()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert await asyncio.to_thread(factory.manager.closed.wait, 1)
