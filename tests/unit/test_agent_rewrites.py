"""Un agente que no ha cambiado no se reescribe; uno que ha cambiado, sí (issue #67).

Con un `Agent` de Strands real, el doble in-memory y un modelo guionizado: lo que
se decide aquí depende de cómo el SDK versiona `state`, `_interrupt_state` y el
conversation manager, y un `MagicMock` no sube ninguna versión.

Dos familias de test:

- **Ahorro**: el turno caliente de un agente sin cambios no toca su
  `agent_data`. Fallan contra v0.13.0, donde el primer sync de cada manager
  reescribía el estado que acababa de leer.
- **Guardarraíl**: cada forma de cambiar el agente se sigue persistiendo. Pasan
  desde el primer día. Son las que tumbaron la alternativa de sembrar la
  contabilidad de versiones de Strands (`features/7_skip_unchanged_agent_writes`):
  reasignar `agent.state` desde un hook o migrar el estado del conversation
  manager al restaurar no sube ninguna versión.
"""

from __future__ import annotations

from typing import Any

import pytest
from strands import Agent
from strands.agent.conversation_manager import ConversationManager
from strands.agent.state import AgentState
from strands.hooks import (
    AgentInitializedEvent,
    BeforeInvocationEvent,
    HookProvider,
    HookRegistry,
)
from strands.types.session import Session, SessionAgent, SessionType

from mongodb_session_manager.mongodb_session_manager import MongoDBSessionManager
from tests.support.in_memory_session_repository import InMemorySessionRepository
from tests.support.scripted_model import ScriptedModel, text_stream

SESSION = "s1"


@pytest.fixture
def repo() -> InMemorySessionRepository:
    return InMemorySessionRepository()


def new_agent(repo, **agent_kwargs) -> Agent:
    """El agente a1 con un manager nuevo, como en una request sin estado."""
    return Agent(
        agent_id="a1",
        model=ScriptedModel([list(text_stream("ok"))], "m1"),
        session_manager=MongoDBSessionManager(
            session_id=SESSION, session_repository=repo
        ),
        callback_handler=None,
        **agent_kwargs,
    )


def run_turn(repo, prompt="hola", **agent_kwargs) -> None:
    """Un turno completo de new_agent()."""
    new_agent(repo, **agent_kwargs)(prompt)


def agent_data(repo) -> dict[str, Any]:
    return repo.session(SESSION)["agents"]["a1"]["agent_data"]


class ReplaceStateOn(HookProvider):
    """Hook de usuario que reasigna `agent.state` entero en vez de usar `set()`."""

    def __init__(self, event_type: type, state: dict[str, Any]) -> None:
        self.event_type = event_type
        self.state = state

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(self.event_type, self.replace)

    def replace(self, event: Any) -> None:
        event.agent.state = AgentState(self.state)


class TestUnchangedAgentIsNotRewritten:
    def test_warm_turn_leaves_agent_data_alone(self, repo):
        """El estado restaurado no cambia en el turno: su agent_data tampoco.

        Solo update_agent() escribe agent_data.updated_at, así que si no se
        mueve no hubo escritura. Los mensajes sí se guardan.
        """
        run_turn(repo, "hola")
        before = agent_data(repo)

        run_turn(repo, "otra")

        assert agent_data(repo) == before
        assert len(repo.session(SESSION)["agents"]["a1"]["messages"]) == 4

    def test_first_turn_does_not_repeat_what_create_agent_stored(self, repo):
        """Agente nuevo: create_agent() ya lo guardó; el primer sync no lo repite.

        Se mira updated_at y no agent_data entero porque el manager sí escribe
        en ese sync el model, que create_agent() no conoce.
        """
        agent = new_agent(repo)
        created = agent_data(repo)

        agent("hola")

        assert agent_data(repo)["updated_at"] == created["updated_at"]
        assert agent_data(repo)["model"] == "m1"


class TestAgentStoredByAnOlderSdk:
    """Subir el SDK cuesta una escritura por sesión, y solo una (#69)."""

    def test_an_internal_state_without_model_state_is_rewritten_once(self, repo):
        """strands 1.34 añadió `model_state` al snapshot interno del agente.

        Una sesión escrita por una versión anterior no lo lleva, así que el
        primer sync tras el bump ve un contenido distinto y escribe. El
        documento ya lo lleva en el turno siguiente, y la deduplicación vuelve a
        saltarse el sync: no es un coste por turno.
        """
        run_turn(repo, "hola")
        stored = agent_data(repo)["_internal_state"]
        assert "model_state" in stored, "el SDK dejó de guardar model_state"

        # El snapshot tal y como lo habría dejado un SDK anterior a 1.34.
        legacy = {k: v for k, v in stored.items() if k != "model_state"}
        repo.update_agent_fields(SESSION, "a1", {"agent_data._internal_state": legacy})
        before_upgrade = agent_data(repo)["updated_at"]

        run_turn(repo, "otra")
        migrated = agent_data(repo)["updated_at"]

        run_turn(repo, "y otra")

        assert migrated > before_upgrade, "el snapshot antiguo no se migró"
        assert agent_data(repo)["updated_at"] == migrated, (
            "el turno siguiente reescribió un agente que ya no cambiaba"
        )


class TestChangedAgentIsPersisted:
    def test_state_set(self, repo):
        run_turn(repo, "hola")

        agent = new_agent(repo)
        agent.state.set("idioma", "euskera")
        agent("otra")

        assert agent_data(repo)["state"] == {"idioma": "euskera"}

    @pytest.mark.parametrize(
        "event_type", [AgentInitializedEvent, BeforeInvocationEvent]
    )
    def test_a_hook_that_replaces_the_state(self, repo, event_type):
        """El AgentState nuevo nace en versión 0, la misma que el restaurado.

        Comparar versiones no lo ve; comparar contenido, sí. El hook de usuario
        corre después del initialize() del session manager.
        """
        run_turn(repo, "hola", state={"origen": "turno 1"})

        run_turn(repo, "otra", hooks=[ReplaceStateOn(event_type, {"origen": "hook"})])

        assert agent_data(repo)["state"] == {"origen": "hook"}

    def test_a_conversation_manager_that_migrates_its_state_on_restore(self, repo):
        """Restaurar no sube versiones: la migración solo se ve en el contenido."""

        class MigratingConversationManager(ConversationManager):
            def __init__(self) -> None:
                super().__init__()
                self.schema = 2

            def restore_from_session(self, state: dict[str, Any]) -> None:
                super().restore_from_session(state)
                self.schema = state["schema"] + 1

            def get_state(self) -> dict[str, Any]:
                return {**super().get_state(), "schema": self.schema}

            def apply_management(self, agent: Any, **kwargs: Any) -> None:
                # Abstract in ConversationManager; this test never trims history.
                pass

            def reduce_context(self, agent: Any, e: Any = None, **kwargs: Any) -> None:
                # Abstract too; the scripted model never overflows the context.
                pass

        repo.create_session(Session(session_id=SESSION, session_type=SessionType.AGENT))
        repo.create_agent(
            SESSION,
            SessionAgent(
                agent_id="a1",
                state={},
                conversation_manager_state={
                    "__name__": "MigratingConversationManager",
                    "removed_message_count": 0,
                    "schema": 1,
                },
            ),
        )

        run_turn(repo, "hola", conversation_manager=MigratingConversationManager())

        assert agent_data(repo)["conversation_manager_state"]["schema"] == 2
