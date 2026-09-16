"""La etiqueta que distingue el sync de un mensaje recién añadido (issue #66).

Strands registra el mismo `sync_agent` para `MessageAddedEvent` y para
`AfterInvocationEvent`, sin decir de cuál viene. `MessageAddedTagging` envuelve el
registry que recibe `register_hooks()` y marca, mientras corren, los callbacks de
`MessageAddedEvent`.
"""

from __future__ import annotations

import inspect
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from strands.hooks import AfterInvocationEvent, HookRegistry, MessageAddedEvent
from strands.session.repository_session_manager import RepositorySessionManager
from strands.types.content import Message

from mongodb_session_manager.mongodb_session_manager import MongoDBSessionManager
from mongodb_session_manager.sync_origin import (
    MessageAddedTagging,
    syncing_added_message,
)
from tests.support.in_memory_session_repository import InMemorySessionRepository

MESSAGE: Message = {"role": "user", "content": [{"text": "hola"}]}


@pytest.fixture
def registry() -> HookRegistry:
    return HookRegistry()


def test_the_tag_is_set_only_inside_message_added_callbacks(registry):
    seen: list[tuple[str, bool]] = []
    tagging = MessageAddedTagging(registry)
    tagging.add_callback(
        MessageAddedEvent, lambda e: seen.append(("added", syncing_added_message()))
    )
    tagging.add_callback(
        AfterInvocationEvent, lambda e: seen.append(("after", syncing_added_message()))
    )

    agent = MagicMock()
    registry.invoke_callbacks(MessageAddedEvent(agent=agent, message=MESSAGE))
    registry.invoke_callbacks(AfterInvocationEvent(agent=agent))

    assert seen == [("added", True), ("after", False)]
    assert syncing_added_message() is False


def test_the_tag_is_restored_when_a_callback_raises(registry):
    def fail(event: Any) -> None:
        raise RuntimeError("callback caído")

    MessageAddedTagging(registry).add_callback(MessageAddedEvent, fail)

    with pytest.raises(RuntimeError, match="callback caído"):
        registry.invoke_callbacks(MessageAddedEvent(agent=MagicMock(), message=MESSAGE))

    assert syncing_added_message() is False


def test_registration_arguments_and_the_rest_of_the_registry_pass_through():
    """Strands 1.56 añade `order=`; lo que no es add_callback va al registry real."""
    real = MagicMock()
    tagging = MessageAddedTagging(real)

    def callback(event: Any) -> None:
        # Never invoked: the test only checks that this same object is registered.
        pass

    tagging.add_callback(AfterInvocationEvent, callback, order=5)

    real.add_callback.assert_called_once_with(AfterInvocationEvent, callback, order=5)
    assert tagging.has_callbacks is real.has_callbacks


def test_strands_registers_only_synchronous_message_added_callbacks():
    """La etiqueta solo cubre callbacks síncronos: uno async correría ya sin ella.

    Registra los callbacks del SessionManager de Strands tal cual, sin el
    envoltorio, y comprueba los de MessageAddedEvent. Si una versión nueva del SDK
    registra uno async, este test falla antes que las métricas.
    """
    recorded: list[tuple[Any, Any]] = []

    class Recording:
        def add_callback(self, event_type: Any, callback: Any, *a: Any, **k: Any):
            recorded.append((event_type, callback))

    manager = MongoDBSessionManager(
        session_id="s1", session_repository=InMemorySessionRepository()
    )
    RepositorySessionManager.register_hooks(manager, cast(HookRegistry, Recording()))

    message_added = [cb for event, cb in recorded if event is MessageAddedEvent]
    assert message_added, "Strands dejó de sincronizar en MessageAddedEvent"
    assert not any(inspect.iscoroutinefunction(cb) for cb in message_added)
