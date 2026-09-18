"""Las métricas de una invocación, una sola vez y en su último mensaje (issue #66).

Con un `Agent` de Strands real, el doble in-memory y un modelo guionizado. Lo que
se prueba es el orden de los eventos del SDK, que un `MagicMock` no reproduce:
Strands dispara `MessageAddedEvent` *antes* de acumular el uso y las métricas del
ciclo (`event_loop.py:699-703` en 1.56), así que el sync de cada mensaje veía las
del ciclo anterior.

El contrato (`features/8_invocation_metrics_on_last_message/plan.md`):

- El sync de cierre (`AfterInvocationEvent`) escribe las métricas en el último
  mensaje de la invocación, y el sync de cada `MessageAddedEvent` no las toca.
- Una llamada explícita a `sync_agent()` las escribe siempre. Un consumidor escribe
  el TTFT en el agente y luego sincroniza a mano.
- Una invocación que no llega a cerrar se queda sin métricas. Es un límite
  documentado, no un descuido.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from strands import Agent, tool
from strands.hooks import (
    AfterInvocationEvent,
    BeforeToolCallEvent,
    HookOrder,
    HookProvider,
    HookRegistry,
    MessageAddedEvent,
)
from strands.types.content import Message

from mongodb_session_manager.mongodb_session_manager import MongoDBSessionManager
from tests.support.in_memory_session_repository import InMemorySessionRepository
from tests.support.scripted_model import (
    USAGE,
    ScriptedModel,
    text_stream,
    tool_stream,
)

SESSION = "s1"
TOKENS_PER_CYCLE = USAGE["totalTokens"]


class RecordingRepository(InMemorySessionRepository):
    """Doble que anota cada escritura de métricas: (message_id, tokens, hilo).

    Las métricas llegan por dos caminos, y los dos se anotan aquí: sobre un
    mensaje ya almacenado (`update_message_fields`) o dentro del mensaje que el
    lote de la invocación está creando (`create_messages`, #53). Lo que el
    contrato de #66 fija es *cuántas veces* y *sobre qué mensaje*, no por qué
    método viajan.
    """

    def __init__(self) -> None:
        super().__init__()
        self.metrics_writes: list[tuple[int, int, str]] = []

    def _record_metrics(self, message_id: int, usage: dict[str, Any] | None) -> None:
        if usage is not None:
            self.metrics_writes.append(
                (message_id, usage["totalTokens"], threading.current_thread().name)
            )

    def update_message_fields(
        self,
        session_id: str,
        agent_id: str,
        ref: Any,
        set_operations: dict[str, Any],
        agent_set_operations: dict[str, Any] | None = None,
    ) -> bool:
        self._record_metrics(
            ref.message_id, set_operations.get("event_loop_metrics.accumulated_usage")
        )
        return super().update_message_fields(
            session_id, agent_id, ref, set_operations, agent_set_operations
        )

    def create_messages(
        self,
        session_id: str,
        agent_id: str,
        session_messages: Any,
        fields_on_last: dict[str, Any] | None = None,
        agent_set_operations: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if session_messages:
            self._record_metrics(
                session_messages[-1].message_id,
                (fields_on_last or {}).get("event_loop_metrics.accumulated_usage"),
            )
        return super().create_messages(
            session_id,
            agent_id,
            session_messages,
            fields_on_last=fields_on_last,
            agent_set_operations=agent_set_operations,
            **kwargs,
        )


@tool
def consulta(q: str) -> str:
    """Devuelve siempre lo mismo."""
    return "ok"


def tool_turns(tools: int) -> list[list[dict]]:
    """Guion de `tools` llamadas a herramienta seguidas de una respuesta final."""
    turns = [
        list(tool_stream("consulta", f"tu-{i}", '{"q": "x"}')) for i in range(tools)
    ]
    return [*turns, list(text_stream("fin"))]


def new_manager(repo) -> MongoDBSessionManager:
    return MongoDBSessionManager(session_id=SESSION, session_repository=repo)


def new_agent(repo, scripted, **agent_kwargs) -> Agent:
    """El agente a1, con un manager nuevo si no se pasa uno: una request sin estado."""
    agent_kwargs.setdefault("session_manager", new_manager(repo))
    return Agent(
        agent_id="a1",
        model=ScriptedModel(scripted, "m1"),
        tools=[consulta],
        system_prompt="p1",
        callback_handler=None,
        **agent_kwargs,
    )


def stored_messages(repo) -> list[dict[str, Any]]:
    return repo.session(SESSION)["agents"]["a1"]["messages"]


def tokens_by_message(repo) -> list[tuple[int, int | None]]:
    """(message_id, totalTokens de sus métricas o None) de cada mensaje guardado."""
    return [
        (
            m["message_id"],
            m.get("event_loop_metrics", {})
            .get("accumulated_usage", {})
            .get("totalTokens"),
        )
        for m in stored_messages(repo)
    ]


def only_last_carries_metrics(repo) -> bool:
    *intermediate, last = stored_messages(repo)
    return "event_loop_metrics" in last and not any(
        "event_loop_metrics" in m for m in intermediate
    )


class FailingModel(ScriptedModel):
    """Modelo guionizado que lanza en su llamada número `fail_on_call` (desde 0).

    `on_call` corre al principio de cada llamada, antes de fallar o de responder.
    """

    def __init__(self, scripted, fail_on_call: int, on_call=None) -> None:
        super().__init__(scripted, "m1")
        self.fail_on_call = fail_on_call
        self.on_call = on_call

    async def stream(self, *args: Any, **kwargs: Any):
        if self.on_call:
            self.on_call()
        if self._index == self.fail_on_call:
            raise RuntimeError("modelo caído")
        async for event in super().stream(*args, **kwargs):
            yield event


class RaiseOn(HookProvider):
    """Hook de usuario que lanza al recibir `event_type`."""

    def __init__(self, event_type: type) -> None:
        self.event_type = event_type

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(self.event_type, self.fail)

    def fail(self, event: Any) -> None:
        raise RuntimeError("hook de usuario")


class TestOneWritePerInvocation:
    def test_only_the_last_message_of_the_invocation_carries_metrics(self):
        repo = RecordingRepository()

        new_agent(repo, tool_turns(1))("hola")

        assert only_last_carries_metrics(repo), tokens_by_message(repo)
        metrics = stored_messages(repo)[-1]["event_loop_metrics"]
        assert metrics["cycle_metrics"]["cycle_count"] == 2
        assert metrics["accumulated_usage"]["totalTokens"] == 2 * TOKENS_PER_CYCLE
        assert "consulta" in metrics["tool_usage"]

    @pytest.mark.parametrize("tools", [0, 1, 3])
    def test_metrics_are_written_once_per_invocation_with_their_final_values(
        self, tools
    ):
        """Hoy son 2N+1: un snapshot por toolResult y uno obsoleto por assistant."""
        repo = RecordingRepository()

        new_agent(repo, tool_turns(tools))("hola")

        last_id = stored_messages(repo)[-1]["message_id"]
        final_tokens = (tools + 1) * TOKENS_PER_CYCLE
        assert [(mid, tokens) for mid, tokens, _ in repo.metrics_writes] == [
            (last_id, final_tokens)
        ]

    def test_an_agent_that_lost_its_event_loop_fails_loudly(self):
        """La guarda que deja pasar al `BidiAgent` no puede tragarse un renombrado.

        `sync_agent()` admite desde strands 1.56 agentes sin event loop, porque
        un `BidiAgent` no lo tiene (#69). Un `Agent` sí, así que si un minor del
        SDK moviera `event_loop_metrics` el fallo tiene que salir: tragárselo
        dejaría de escribir métricas en todas las sesiones sin ninguna señal,
        que es el síntoma de #66 y peor, porque nadie lo vería.
        """
        repo = RecordingRepository()
        manager = new_manager(repo)
        agent = new_agent(repo, tool_turns(0), session_manager=manager)
        del agent.event_loop_metrics

        with pytest.raises(AttributeError, match="event_loop_metrics"):
            manager.sync_agent(agent)

    def test_a_new_prompt_does_not_inherit_the_previous_invocation_metrics(self):
        """Mismo Agent: su acumulado ya no es 0 cuando llega el segundo prompt."""
        repo = RecordingRepository()
        agent = new_agent(repo, [list(text_stream("uno")), list(text_stream("dos"))])

        agent("hola")
        agent("otra")

        assert tokens_by_message(repo) == [
            (0, None),
            (1, TOKENS_PER_CYCLE),
            (2, None),
            (3, 2 * TOKENS_PER_CYCLE),
        ]


class TestExplicitSync:
    def test_explicit_sync_agent_writes_the_current_metrics(self):
        """El flujo de un consumidor: TTFT escrito en el agente y sync a mano después.

        Es lo que descarta escribir las métricas solo desde AfterInvocationEvent.
        """
        repo = RecordingRepository()
        manager = new_manager(repo)
        agent = new_agent(repo, tool_turns(0), session_manager=manager)
        agent("hola")

        agent.event_loop_metrics.accumulated_metrics["timeToFirstByteMs"] = 321
        manager.sync_agent(agent)

        last = stored_messages(repo)[-1]["event_loop_metrics"]
        assert last["accumulated_metrics"]["timeToFirstByteMs"] == 321

    def test_explicit_sync_from_another_thread_does_not_steal_the_automatic_sync(
        self,
    ):
        """Un sync explícito concurrente no cambia qué hace el automático.

        El hilo del agente se detiene justo después de guardar el prompt de la
        segunda invocación, antes de su sync. El explícito escribe lo que se le
        pide; el automático, nada. Con una marca compartida por el manager, el
        explícito la consumía y el automático escribía métricas obsoletas.
        """

        class PausingRepository(RecordingRepository):
            stored = threading.Event()
            release = threading.Event()

            def create_message(self, session_id, agent_id, session_message, **kw):
                super().create_message(session_id, agent_id, session_message, **kw)
                if session_message.message_id == 2:
                    self.stored.set()
                    assert self.release.wait(timeout=5)

        repo = PausingRepository()
        manager = new_manager(repo)
        agent = new_agent(
            repo,
            [list(text_stream("uno")), list(text_stream("dos"))],
            session_manager=manager,
        )
        agent("hola")
        repo.metrics_writes.clear()

        second = threading.Thread(target=agent, args=("otra",), name="agent-thread")
        second.start()
        assert repo.stored.wait(timeout=5)
        manager.sync_agent(agent)
        repo.release.set()
        second.join(timeout=5)

        by_thread = [(mid, thread) for mid, _, thread in repo.metrics_writes]
        explicit = threading.current_thread().name
        agent_thread_writes = [mid for mid, thread in by_thread if thread != explicit]
        assert (2, explicit) in by_thread
        assert agent_thread_writes == [3], by_thread


class TestFailures:
    def test_a_failed_invocation_records_its_metrics_on_its_last_message(self):
        """El modelo falla en el ciclo 2: el cierre corre igual, en un finally."""
        repo = RecordingRepository()
        agent = new_agent(repo, [])
        agent.model = FailingModel(tool_turns(1), fail_on_call=1)

        with pytest.raises(Exception, match="modelo caído"):
            agent("hola")

        assert only_last_carries_metrics(repo), tokens_by_message(repo)
        assert tokens_by_message(repo)[-1][1] == TOKENS_PER_CYCLE

    def test_a_batch_stored_despite_a_failing_write_keeps_its_metrics(self):
        """El lote se aplica y lanza (el ack se pierde): lo escrito queda escrito.

        Era `create_message` quien se aplicaba y perdía el ack; desde #53 el que
        puede hacerlo es el `$push` del cierre, que lleva los mensajes y sus
        métricas dentro. Lo que fija este caso es que el error sube y que lo que
        llegó al almacén está completo -- y, sobre todo, que nadie lo reintenta:
        un segundo intento duplicaría el turno.
        """

        class AppliedThenRaises(RecordingRepository):
            def create_messages(self, session_id, agent_id, session_messages, **kw):
                super().create_messages(session_id, agent_id, session_messages, **kw)
                # Solo el del cierre: es el que lleva las métricas dentro. El
                # prompt también pasa por aquí, y tumbarlo dejaría el turno sin
                # llegar al modelo.
                if kw.get("fields_on_last"):
                    raise TimeoutError("ack perdido")

        repo = AppliedThenRaises()
        manager = new_manager(repo)

        with pytest.raises(Exception, match="ack perdido"):
            new_agent(repo, tool_turns(1), session_manager=manager)("hola")
        manager.close()

        assert only_last_carries_metrics(repo), tokens_by_message(repo)
        assert [m["message_id"] for m in stored_messages(repo)] == [0, 1, 2, 3]

    def test_a_failing_sync_on_a_message_does_not_cost_the_closing_metrics(self):
        """update_agent lanza en el sync del toolResult; el cierre escribe igual.

        El disparador es el segundo `update_agent` del turno, que es ese sync:
        el primero es el del prompt, y el del toolUse no llega aquí porque su
        contenido no ha cambiado (#67). Contarlos, en vez de reconocer el
        toolResult al almacenarlo, es lo que queda desde que ese mensaje espera
        en el lote (#53).

        Lo que se prueba no cambia -- un sync intermedio que falla no le cuesta
        las métricas al cierre -- y ahora también que no le cuesta los mensajes,
        que viajan con ellas: el `finally` del sync escribe el lote aunque
        super() haya lanzado.
        """

        class FailsOnTheSecondSync(RecordingRepository):
            updates = 0

            def update_agent(self, session_id, session_agent, **kw):
                self.updates += 1
                if self.updates == 2:
                    raise RuntimeError("update_agent caído")
                return super().update_agent(session_id, session_agent, **kw)

        repo = FailsOnTheSecondSync()

        with pytest.raises(Exception, match="update_agent caído"):
            new_agent(repo, tool_turns(1))("hola")

        assert tokens_by_message(repo) == [
            (0, None),
            (1, None),
            (2, TOKENS_PER_CYCLE),
        ]

    def test_config_of_a_new_agent_is_persisted_before_the_first_model_call(self):
        """El sync de cada mensaje deja las métricas, no la configuración."""
        repo = RecordingRepository()
        seen_by_model: list[Any] = []

        def record_persisted_prompt() -> None:
            agent_data = repo.session(SESSION)["agents"]["a1"]["agent_data"]
            seen_by_model.append(agent_data.get("system_prompt"))

        agent = new_agent(repo, [])
        agent.model = FailingModel([], fail_on_call=0, on_call=record_persisted_prompt)

        with pytest.raises(Exception, match="modelo caído"):
            agent("hola")

        assert seen_by_model == ["p1"]

    def test_an_invocation_that_does_not_close_leaves_no_metrics(self):
        """Límite documentado: un hook de usuario lanza antes del sync de cierre.

        AfterInvocationEvent corre en orden inverso, así que el hook de usuario va
        antes que el manager. Sin cierre no hay escritura de métricas. Antes
        quedaba el snapshot de un ciclo anterior, que tampoco era el total.
        """
        repo = RecordingRepository()

        with pytest.raises(RuntimeError, match="hook de usuario"):
            new_agent(repo, tool_turns(1), hooks=[RaiseOn(AfterInvocationEvent)])(
                "hola"
            )

        assert repo.metrics_writes == []


class TestInvocationShapes:
    def test_each_resumed_invocation_closes_with_its_metrics(self):
        """AfterInvocationEvent.resume relanza el agente: cada vuelta cierra."""

        class ResumeOnce(HookProvider):
            resumed = False

            def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
                registry.add_callback(AfterInvocationEvent, self.resume)

            def resume(self, event: AfterInvocationEvent) -> None:
                if not self.resumed:
                    self.resumed = True
                    event.resume = "segunda vuelta"

        repo = RecordingRepository()
        new_agent(
            repo,
            [list(text_stream("uno")), list(text_stream("dos"))],
            hooks=[ResumeOnce()],
        )("hola")

        assert tokens_by_message(repo) == [
            (0, None),
            (1, TOKENS_PER_CYCLE),
            (2, None),
            (3, 2 * TOKENS_PER_CYCLE),
        ]

    def test_a_message_added_by_a_closing_hook_gets_the_metrics(self):
        """Un hook añade un mensaje en el cierre; el manager cierra después."""

        class AppendOnClose(HookProvider):
            def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
                registry.add_callback(AfterInvocationEvent, self.append)

            def append(self, event: AfterInvocationEvent) -> None:
                message: Message = {
                    "role": "assistant",
                    "content": [{"text": "resumen"}],
                }
                event.agent.messages.append(message)
                event.agent.hooks.invoke_callbacks(
                    MessageAddedEvent(agent=event.agent, message=message)
                )

        repo = RecordingRepository()
        new_agent(repo, tool_turns(0), hooks=[AppendOnClose()])("hola")

        assert tokens_by_message(repo) == [(0, None), (1, None), (2, TOKENS_PER_CYCLE)]

    def test_a_message_added_by_an_sdk_last_hook_does_not_get_the_metrics(self):
        """El mismo hook en SDK_LAST corre después del cierre: el límite de #66.

        `HookOrder` llegó en strands 1.45, y los grupos de prioridad corren en
        orden ascendente también en los eventos de orden inverso
        (`hooks/registry.py`, `get_callbacks_for`). Un hook en `SDK_LAST` (100)
        va, por tanto, después del sync de cierre del manager (`DEFAULT`, 0), y
        el mensaje que añada se queda sin métricas: las tiene el anterior, que
        es el ciclo al que pertenecen.

        Es el escenario que quedó pendiente de comprobar en #66 y que aquí se
        fija con un `Agent` real (#69). No se corrige: mover nuestro sync a
        `SDK_LAST` dependería del orden de registro dentro del grupo.
        """

        class AppendLast(HookProvider):
            def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
                registry.add_callback(
                    AfterInvocationEvent, self.append, order=HookOrder.SDK_LAST
                )

            def append(self, event: AfterInvocationEvent) -> None:
                message: Message = {
                    "role": "assistant",
                    "content": [{"text": "resumen"}],
                }
                event.agent.messages.append(message)
                event.agent.hooks.invoke_callbacks(
                    MessageAddedEvent(agent=event.agent, message=message)
                )

        repo = RecordingRepository()
        new_agent(repo, tool_turns(0), hooks=[AppendLast()])("hola")

        assert tokens_by_message(repo) == [(0, None), (1, TOKENS_PER_CYCLE), (2, None)]

    def test_an_interrupted_invocation_puts_its_metrics_on_the_tool_use_message(
        self,
    ):
        """La interrupción cierra en el tool_use; la reanudación, en su final."""

        class InterruptOnce(HookProvider):
            def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
                registry.add_callback(BeforeToolCallEvent, self.approve)

            def approve(self, event: BeforeToolCallEvent) -> None:
                event.interrupt("approval", reason="¿seguro?")

        repo = RecordingRepository()
        agent = new_agent(repo, tool_turns(1), hooks=[InterruptOnce()])

        first = agent("hola")
        assert first.stop_reason == "interrupt"
        assert first.interrupts
        assert tokens_by_message(repo) == [(0, None), (1, TOKENS_PER_CYCLE)]

        agent(
            [
                {
                    "interruptResponse": {
                        "interruptId": first.interrupts[0].id,
                        "response": "sí",
                    }
                }
            ]
        )

        assert tokens_by_message(repo) == [
            (0, None),
            (1, TOKENS_PER_CYCLE),
            (2, None),
            (3, 2 * TOKENS_PER_CYCLE),
        ]
