"""Shared fixtures for MongoDB Session Manager tests."""

import asyncio
import os
import threading
import time
import uuid
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest
from strands.types.session import Session, SessionAgent, SessionMessage

# ---------------------------------------------------------------------------
# Waiting on background work, without sleeping a fixed time
# ---------------------------------------------------------------------------


def wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> bool:
    """Poll a predicate until it holds or the timeout expires.

    On a monotonic clock: these deadlines must not move when the wall clock
    does.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


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


# ---------------------------------------------------------------------------
# Unit-test fixtures (no MongoDB required)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mongo_collection():
    """MagicMock MongoDB collection with common operations."""
    collection = MagicMock()
    collection.find_one.return_value = None
    collection.insert_one.return_value = MagicMock(inserted_id="test-session")
    collection.update_one.return_value = MagicMock(matched_count=1, modified_count=1)
    collection.create_index.return_value = "index_name"
    return collection


@pytest.fixture
def mock_mongo_client(mock_mongo_collection):
    """MagicMock MongoClient with db/collection hierarchy."""
    client = MagicMock()
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=mock_mongo_collection)
    client.__getitem__ = MagicMock(return_value=db)
    return client


@pytest.fixture
def mock_repository(mock_mongo_client):
    """MongoDBSessionRepository with mocked MongoDB client."""
    from mongodb_session_manager.mongodb_session_repository import (
        MongoDBSessionRepository,
    )

    with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
        repo = MongoDBSessionRepository(
            client=mock_mongo_client,
            database_name="test_db",
            collection_name="test_sessions",
        )
    return repo


@pytest.fixture
def mock_agent():
    """Factory fixture for creating a mock Strands Agent with configurable metrics."""

    def _create(
        agent_id="test-agent",
        latency_ms=100,
        input_tokens=500,
        output_tokens=200,
        total_tokens=700,
        cache_read_tokens=0,
        cache_write_tokens=0,
        time_to_first_byte_ms=0,
        cycle_count=1,
        total_duration=1.5,
        average_cycle_time=1.5,
        tool_usage=None,
        system_prompt=None,
        model_id=None,
    ):
        agent = MagicMock()
        agent.agent_id = agent_id
        agent.messages = []

        summary = {
            "total_cycles": cycle_count,
            "total_duration": total_duration,
            "average_cycle_time": average_cycle_time,
            "accumulated_usage": {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "totalTokens": total_tokens,
                "cacheReadInputTokens": cache_read_tokens,
                "cacheWriteInputTokens": cache_write_tokens,
            },
            "accumulated_metrics": {
                "latencyMs": latency_ms,
                "timeToFirstByteMs": time_to_first_byte_ms,
            },
            "tool_usage": tool_usage or {},
            "traces": [],
        }
        agent.event_loop_metrics.get_summary.return_value = summary

        if system_prompt is not None:
            agent.system_prompt = system_prompt
        if model_id is not None:
            agent.model = MagicMock()
            agent.model.config = {"model_id": model_id}

        return agent

    return _create


@pytest.fixture
def captured_dispatch(monkeypatch):
    """Record what the hooks dispatch instead of running it.

    Without this, exercising a hook wrapper reaches the real boto3 client from
    a background thread, which outlives the test that patched it away.
    """
    from types import SimpleNamespace

    from mongodb_session_manager.hooks import (
        feedback_sns_hook,
        metadata_sqs_hook,
        metadata_websocket_hook,
    )

    calls = []

    def recorder(coro, error_context, loop=None, *, order_key=None, delivery=None):
        coro.close()  # never awaited: the recorder replaces the dispatch
        calls.append(
            SimpleNamespace(
                error_context=error_context,
                loop=loop,
                order_key=order_key,
                delivery=delivery,
            )
        )
        return None

    for module in (feedback_sns_hook, metadata_sqs_hook, metadata_websocket_hook):
        monkeypatch.setattr(module, "dispatch_async", recorder)

    return calls


@pytest.fixture
def sample_session():
    """Sample Session object for tests."""
    return Session(session_id="test-session-1", session_type="default")


@pytest.fixture
def sample_session_agent():
    """Sample SessionAgent object for tests."""
    return SessionAgent(
        agent_id="test-agent-1",
        state={},
        conversation_manager_state={},
    )


@pytest.fixture
def sample_session_message():
    """Sample SessionMessage object for tests."""
    return SessionMessage(
        message_id=1,
        message={"role": "user", "content": [{"text": "Hello"}]},
    )


# ---------------------------------------------------------------------------
# Integration-test fixtures (require MongoDB)
# ---------------------------------------------------------------------------


@pytest.fixture
def mongodb_connection():
    """Get MongoDB connection string from environment, skip if unavailable."""
    conn_str = os.environ.get("MONGODB_CONNECTION_STRING")
    if not conn_str:
        pytest.skip("MONGODB_CONNECTION_STRING not set")
    return conn_str


@pytest.fixture
def unique_session_id():
    """Generate a unique session ID per test."""
    return f"test-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def cleanup_session(mongodb_connection):
    """Yield a cleanup helper that deletes a session document after the test.

    Uses an independent MongoClient for teardown to avoid errors when
    the manager's client has already been closed.
    """
    created = []

    def _register(collection, session_id):
        db_name = collection.database.name
        col_name = collection.name
        created.append((db_name, col_name, session_id))

    yield _register

    if created:
        from pymongo import MongoClient

        client = MongoClient(mongodb_connection)
        try:
            for db_name, col_name, session_id in created:
                client[db_name][col_name].delete_one({"_id": session_id})
        finally:
            client.close()
