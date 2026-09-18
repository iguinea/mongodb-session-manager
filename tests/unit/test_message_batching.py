"""El lote de mensajes de una invocación (issue #53).

`append_message` escribía un `$push` por mensaje: 6 de las 8 escrituras del
turno de referencia. Aquí se agrupan en una sola, con una excepción deliberada:
**el mensaje que abre la invocación se escribe al llegar**.

Esa excepción es el contrato, no un detalle de implementación. Lo que un lote
difiere es lo que el event loop produce —`toolUse`, `toolResult`, la respuesta
final—, y eso se vuelca en `AfterInvocationEvent`, que Strands emite dentro de
un `finally` (`strands/agent/agent.py`): una invocación que revienta también
cierra, así que el lote sobrevive a un fallo del modelo o de una herramienta.
Lo que no sobrevive es el proceso muriendo de golpe, y por eso la pregunta del
usuario —lo único irrecuperable— no espera a nadie.

Los tests cuentan escrituras contra una colección falsa, como
`test_write_amplification.py`, y comprueban *qué* se escribió, no cómo.
"""

from unittest.mock import MagicMock

import pytest
from strands.hooks import AfterInvocationEvent, MessageAddedEvent

from tests.support.turn_events import (
    ANSWER,
    PROMPT,
    TOOL_RESULT,
    TOOL_USE,
    TURN,
    invoking,
    run_turn,
)

from .test_write_amplification import (  # noqa: F401  (clean_index_registry es autouse)
    clean_index_registry,
    make_client,
    make_manager,
    restored_manager,
    value_objects,
)


def pushed_messages(collection):
    """Todos los mensajes que llegaron a la colección, en orden de escritura."""
    messages = []
    for call in collection.update_one.call_args_list:
        push = call[0][1].get("$push", {})
        for path, value in push.items():
            if path.endswith(".messages"):
                messages.extend(value["$each"])
    return messages


class TestWhatWaitsAndWhatDoesNot:
    def test_the_prompt_is_written_when_it_arrives(self, mock_agent):
        """La pregunta del usuario es lo único que nadie puede reproducir."""
        mgr, agent, collection = restored_manager(mock_agent)
        registry = invoking(mgr, agent)

        registry.invoke_callbacks(MessageAddedEvent(agent=agent, message=PROMPT))

        assert [m["message"] for m in pushed_messages(collection)] == [PROMPT]

    @pytest.mark.parametrize(
        "message",
        [
            pytest.param(TOOL_USE, id="toolUse"),
            pytest.param(TOOL_RESULT, id="toolResult"),
        ],
    )
    def test_what_the_event_loop_produces_waits(self, mock_agent, message):
        """Un toolUse o un toolResult es reproducible: espera al cierre."""
        mgr, agent, collection = restored_manager(mock_agent)
        registry = invoking(mgr, agent)

        registry.invoke_callbacks(MessageAddedEvent(agent=agent, message=message))

        assert pushed_messages(collection) == []

    def test_the_batch_lands_on_the_closing_sync(self, mock_agent):
        """Al cerrar la invocación, el lote entero está almacenado y en orden."""
        mgr, agent, collection = restored_manager(mock_agent)

        run_turn(mgr, agent)

        assert [m["message"] for m in pushed_messages(collection)] == TURN

    def test_a_prompt_flushes_what_is_pending_first(self, mock_agent):
        """Un mensaje inmediato no puede adelantar a los que esperan.

        El orden del array es el orden de la conversación: si el prompt de una
        segunda vuelta se escribiera antes del lote de la primera, el historial
        restaurado contaría otra cosa.
        """
        mgr, agent, collection = restored_manager(mock_agent)
        registry = invoking(mgr, agent)

        for message in [PROMPT, TOOL_USE, TOOL_RESULT, ANSWER, PROMPT]:
            registry.invoke_callbacks(MessageAddedEvent(agent=agent, message=message))

        assert [m["message"] for m in pushed_messages(collection)] == [
            PROMPT,
            TOOL_USE,
            TOOL_RESULT,
            ANSWER,
            PROMPT,
        ]

    def test_message_ids_are_the_ones_strands_would_give(self, mock_agent):
        """Un mensaje que espera se numera igual que uno que no.

        `message_id` es el índice que Strands deriva en memoria y con el que
        restaura. El del prompt lo calcula `super().append_message()`; los tres
        siguientes, el lote: si contara de otra forma, el historial saldría
        desordenado o con huecos justo en el mensaje que no pasa por el SDK.
        """
        mgr, agent, collection = restored_manager(mock_agent)

        run_turn(mgr, agent)

        assert [m["message_id"] for m in pushed_messages(collection)] == [0, 1, 2, 3]

    def test_every_message_of_the_batch_gets_its_own_identity(self, mock_agent):
        """El storage_id de #78 no se lo pierde un mensaje por viajar en lote."""
        mgr, agent, collection = restored_manager(mock_agent)

        run_turn(mgr, agent)

        identities = [m["storage_id"] for m in pushed_messages(collection)]
        assert all(identities)
        assert len(set(identities)) == len(identities)


def with_metrics(agent, latency_ms=100):
    """Dale al agente métricas acumuladas, como tras un ciclo del modelo."""
    agent.event_loop_metrics.get_summary.return_value["accumulated_metrics"][
        "latencyMs"
    ] = latency_ms
    return agent


class TestTheClosingWrite:
    def test_the_metrics_ride_with_the_batch(self, mock_agent):
        """Las métricas van dentro del `$push`, no en una escritura aparte.

        El event loop solo las tiene acumuladas cuando la invocación cierra
        (#66), que es justo cuando se vuelca el lote: el mensaje final se
        almacena ya con ellas.
        """
        mgr, agent, collection = restored_manager(mock_agent)

        run_turn(mgr, with_metrics(agent))

        last = pushed_messages(collection)[-1]
        assert last["event_loop_metrics"]["accumulated_usage"]["totalTokens"] == 700
        assert last["event_loop_metrics"]["accumulated_metrics"]["latencyMs"] == 100

    def test_intermediate_messages_carry_no_metrics(self, mock_agent):
        """La atribución por mensaje sigue siendo la de #66: solo el último."""
        mgr, agent, collection = restored_manager(mock_agent)

        run_turn(mgr, with_metrics(agent))

        assert ["event_loop_metrics" in m for m in pushed_messages(collection)] == [
            False,
            False,
            False,
            True,
        ]

    def test_a_warm_turn_costs_two_writes(self, mock_agent):
        """El turno de referencia: el prompt y el cierre.

        Eran 5 (#66): cuatro `create_message` y las métricas. Con N
        herramientas seguirán siendo 2, no 2N+1.
        """
        mgr, agent, collection = restored_manager(mock_agent)

        run_turn(mgr, with_metrics(agent))

        updates = collection.update_one.call_count
        assert updates == 2, f"{updates} escrituras en un turno caliente"

    def test_a_cold_turn_costs_four(self, mock_agent):
        """Un agente que no existía todavía. Eran 7.

          1  el prompt, escrito al llegar
          1  `update_agent`, el primer sync de este manager (#67)
          1  la configuración, en ese mismo primer sync (#65)
          1  el cierre: los otros tres mensajes y las métricas

        La configuración no viaja con el lote a propósito. Se escribe donde se
        detecta que no coincide con lo persistido, y de ahí no se mueve: hacer
        que `append_message` cargara con ella, para ahorrar una escritura que
        solo ocurre en el primer turno de cada agente, le daría una
        responsabilidad que no es suya.
        """
        client, collection = make_client()
        mgr = make_manager(client)
        agent = value_objects(
            mock_agent(agent_id="a1", latency_ms=100, system_prompt="p", model_id="m1")
        )
        mgr._latest_agent_message["a1"] = None
        collection.update_one.reset_mock()

        run_turn(mgr, agent)

        assert collection.update_one.call_count == 4
        config_writes = [
            call
            for call in collection.update_one.call_args_list
            if "agents.a1.agent_data.system_prompt" in call[0][1].get("$set", {})
        ]
        assert len(config_writes) == 1


class TestNothingIsLost:
    def test_close_flushes_what_never_closed(self, mock_agent):
        """Red de seguridad: una invocación que no llega a cerrar.

        `AfterInvocationEvent` sale de un `finally`, pero lo que corre antes en
        ese mismo `finally` —`conversation_manager.apply_management()`— puede
        lanzar y dejar la invocación sin cierre (#66). `close()` es la última
        oportunidad de que esos mensajes existan.
        """
        mgr, agent, collection = restored_manager(mock_agent)
        registry = invoking(mgr, agent)
        for message in [PROMPT, TOOL_USE, TOOL_RESULT]:
            registry.invoke_callbacks(MessageAddedEvent(agent=agent, message=message))
        collection.update_one.reset_mock()

        mgr.close()

        assert [m["message"] for m in pushed_messages(collection)] == [
            TOOL_USE,
            TOOL_RESULT,
        ]

    def test_a_failed_flush_is_not_retried(self, mock_agent):
        """Un lote que falla se pierde, no se reintenta.

        Una escritura que lanza puede haberse aplicado igualmente: un update
        que llega al servidor y pierde el ack es un caso real, y está en
        `test_invocation_metrics.py`. Reintentarlo duplicaría los mensajes del
        turno, que es peor que la pérdida que trataría de evitar. Perder el
        lote es lo que ya hacía un `create_message` fallido, de uno en uno.
        """
        mgr, agent, collection = restored_manager(mock_agent)
        registry = invoking(mgr, agent)
        registry.invoke_callbacks(MessageAddedEvent(agent=agent, message=TOOL_USE))
        collection.update_one.return_value = MagicMock(matched_count=0)

        with pytest.raises(ValueError):
            registry.invoke_callbacks(AfterInvocationEvent(agent=agent))

        collection.update_one.return_value = MagicMock(matched_count=1)
        collection.update_one.reset_mock()
        mgr.close()

        assert pushed_messages(collection) == []

    def test_a_redaction_waits_for_the_message_to_exist(self, mock_agent):
        """La redacción localiza el mensaje con el posicional: tiene que estar.

        Un guardrail interviene sobre el mensaje que se acaba de añadir, que es
        justo el que estaría esperando en el lote.
        """
        mgr, agent, collection = restored_manager(mock_agent)
        registry = invoking(mgr, agent)
        registry.invoke_callbacks(MessageAddedEvent(agent=agent, message=ANSWER))

        mgr.redact_latest_message(
            {"role": "assistant", "content": [{"text": "[redacted]"}]}, agent
        )

        assert [m["message"] for m in pushed_messages(collection)] == [ANSWER]

    def test_the_message_count_sees_what_is_pending(self, mock_agent):
        """Contar mensajes no puede ignorar los que este manager aún no ha volcado."""
        mgr, agent, collection = restored_manager(mock_agent)
        collection.aggregate.return_value = iter([{"count": 2}])
        registry = invoking(mgr, agent)
        registry.invoke_callbacks(MessageAddedEvent(agent=agent, message=TOOL_USE))

        assert mgr.get_message_count("a1") == 3
