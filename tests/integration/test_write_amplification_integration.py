"""Conteo de operaciones Mongo reales por turno (issue #54).

Ejerce el escenario del runtime de producción —supervisor que llama a una tool
que a su vez crea un sub-agente con su propio session manager— contra un
MongoDB real, contando los comandos con un CommandListener de pymongo.

Es el test que valida el criterio de aceptación principal. El unitario cuenta
llamadas a un doble; este cuenta comandos que salen por el cable.
"""

from collections import Counter
from typing import Any

import pytest
from pymongo import MongoClient, monitoring
from strands import Agent, tool
from strands.models.model import Model

from mongodb_session_manager.mongodb_session_factory import (
    MongoDBSessionManagerFactory,
)
from mongodb_session_manager.mongodb_session_repository import _reset_index_registry

pytestmark = pytest.mark.integration

# Comandos de infraestructura del driver, no del session manager.
_IGNORED_COMMANDS = frozenset(
    {
        "ping",
        "hello",
        "ismaster",
        "buildInfo",
        "endSessions",
        "saslStart",
        "saslContinue",
        "getnonce",
        "drop",
        "listIndexes",
    }
)

_USAGE = {"inputTokens": 1200, "outputTokens": 80, "totalTokens": 1280}
_METRICS = {"latencyMs": 900}


class CommandCounter(monitoring.CommandListener):
    """Registra los comandos enviados al servidor."""

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.enabled = False

    def started(self, event: Any) -> None:
        if self.enabled and event.command_name not in _IGNORED_COMMANDS:
            self.commands.append(event.command_name)

    def succeeded(self, event: Any) -> None:
        pass

    def failed(self, event: Any) -> None:
        pass

    def counts(self) -> Counter:
        return Counter(self.commands)


def _text_stream(text: str):
    yield {"messageStart": {"role": "assistant"}}
    yield {"contentBlockDelta": {"delta": {"text": text}}}
    yield {"contentBlockStop": {}}
    yield {"messageStop": {"stopReason": "end_turn"}}
    yield {"metadata": {"usage": _USAGE, "metrics": _METRICS}}


def _tool_stream(name: str, tool_use_id: str, payload: str):
    yield {"messageStart": {"role": "assistant"}}
    yield {
        "contentBlockStart": {
            "start": {"toolUse": {"name": name, "toolUseId": tool_use_id}}
        }
    }
    yield {"contentBlockDelta": {"delta": {"toolUse": {"input": payload}}}}
    yield {"contentBlockStop": {}}
    yield {"messageStop": {"stopReason": "tool_use"}}
    yield {"metadata": {"usage": _USAGE, "metrics": _METRICS}}


class ScriptedModel(Model):
    """Modelo que reproduce una secuencia fija de respuestas."""

    def __init__(
        self, scripted: list[list[dict]], model_id: str = "test-model"
    ) -> None:
        self.config = {"model_id": model_id}
        self._scripted = scripted
        self._index = 0

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> Any:
        return self.config

    def structured_output(self, *args: Any, **kwargs: Any):
        raise NotImplementedError

    async def stream(self, *args: Any, **kwargs: Any):
        for event in self._scripted[min(self._index, len(self._scripted) - 1)]:
            yield event
        self._index += 1


# Un system prompt realista: en producción son varios KB.
SYSTEM_PROMPT = "Eres un asistente de soporte. " + (
    "Instruccion detallada del prompt de produccion. " * 300
)


@pytest.fixture
def counting_client(mongodb_connection):
    """MongoClient con un contador de comandos asociado solo a él."""
    counter = CommandCounter()
    client = MongoClient(mongodb_connection, event_listeners=[counter])
    _reset_index_registry()
    yield client, counter
    client.close()
    _reset_index_registry()


def run_turn(factory, session_id: str, prompt: str) -> None:
    """Un turno completo: supervisor + sub-agente, con una llamada a tool."""
    supervisor_manager = factory.create_session_manager(session_id)

    @tool(name="info_suministro_agent", description="Consulta datos de suministro")
    def info_suministro_agent(query: str) -> str:
        sub_manager = factory.create_session_manager(session_id)
        sub_agent = Agent(
            agent_id="info_suministro_agent",
            model=ScriptedModel(
                [list(_text_stream("Datos del suministro: OK"))], "sub"
            ),
            system_prompt=SYSTEM_PROMPT,
            session_manager=sub_manager,
        )
        result = str(sub_agent(query))
        sub_manager.close()
        return result

    supervisor = Agent(
        agent_id="supervisor",
        model=ScriptedModel(
            [
                list(
                    _tool_stream(
                        "info_suministro_agent", "tu-1", '{"query": "consumo"}'
                    )
                ),
                list(_text_stream("Tu consumo del ultimo mes es de 312 kWh.")),
            ],
            "supervisor",
        ),
        system_prompt=SYSTEM_PROMPT,
        tools=[info_suministro_agent],
        session_manager=supervisor_manager,
    )
    supervisor(prompt)
    supervisor_manager.close()


class TestTurnOperationBudget:
    def test_turn_stays_within_write_budget(
        self, counting_client, unique_session_id, cleanup_session
    ):
        """Un turno con supervisor y sub-agente cabe en el presupuesto.

        Contra v0.9.1 el mismo escenario producía 42 operaciones: 21 updates,
        13 finds y 8 createIndexes. Ahora son 21: 15 updates, 6 finds y 0
        createIndexes.

        El presupuesto de 15 se desglosa así (6 mensajes en total: 4 del
        supervisor, 2 del sub-agente):
          6  create_message ($push, uno por mensaje)
          8  sync fusionado (métricas + config en un solo update_one)
          1  update_agent del primer sync de cada manager

        No confundir con el objetivo de ≤12 de la issue: ese es para el turno
        real completo, que además incluye los ahorros del lado del consumidor
        (quitar el sync doble de `sync_and_track` en los sub-agentes y mover el
        TTFT del supervisor a un hook). Esta librería sola no puede bajar de
        aquí sin fusionar `create_message` con `update_agent`, que se descartó
        por depender de una invariante del SDK que no controlamos.
        """
        client, counter = counting_client
        factory = MongoDBSessionManagerFactory(
            client=client,
            database_name="test_write_amplification",
            collection_name="sessions",
            application_name="test",
        )
        collection = client["test_write_amplification"]["sessions"]
        cleanup_session(collection, unique_session_id)

        # Turno 0: crea la sesión y calienta el registro de índices.
        run_turn(factory, unique_session_id, "hola")

        counter.enabled = True
        run_turn(factory, unique_session_id, "y el mes pasado?")
        counter.enabled = False

        counts = counter.counts()
        assert counts["update"] <= 15, f"{counts['update']} updates: {counts}"
        assert counts["createIndexes"] == 0, "los índices ya estaban asegurados"
        assert counts["find"] <= 6, f"{counts['find']} finds: {counts}"

    def test_root_updated_at_advances_with_the_turn(
        self, counting_client, unique_session_id, cleanup_session
    ):
        """Guardarraíl del contrato externo.

        El Session Viewer y el informe de auditoría calculan «Fin» y «Duración»
        con el updated_at raíz. Si dejara de avanzar, las sesiones mostrarían
        una duración corta de menos, en silencio.
        """
        client, _ = counting_client
        factory = MongoDBSessionManagerFactory(
            client=client,
            database_name="test_write_amplification",
            collection_name="sessions",
            application_name="test",
        )
        collection = client["test_write_amplification"]["sessions"]
        cleanup_session(collection, unique_session_id)

        run_turn(factory, unique_session_id, "hola")
        after_first = collection.find_one({"_id": unique_session_id})["updated_at"]

        run_turn(factory, unique_session_id, "otra pregunta")
        after_second = collection.find_one({"_id": unique_session_id})["updated_at"]

        assert after_second > after_first

    def test_agent_created_at_survives_updates(
        self, counting_client, unique_session_id, cleanup_session
    ):
        """El created_at del agente no se falsea al sincronizar."""
        client, _ = counting_client
        factory = MongoDBSessionManagerFactory(
            client=client,
            database_name="test_write_amplification",
            collection_name="sessions",
            application_name="test",
        )
        collection = client["test_write_amplification"]["sessions"]
        cleanup_session(collection, unique_session_id)

        run_turn(factory, unique_session_id, "hola")
        doc = collection.find_one({"_id": unique_session_id})
        original = doc["agents"]["supervisor"]["created_at"]

        run_turn(factory, unique_session_id, "otra")
        doc = collection.find_one({"_id": unique_session_id})

        assert doc["agents"]["supervisor"]["created_at"] == original

    def test_metrics_land_on_the_last_message(
        self, counting_client, unique_session_id, cleanup_session
    ):
        """Las métricas se escriben en el último mensaje, no en el anterior.

        Es la garantía que el read-after-write ponía en riesgo: si el
        message_id venía de una réplica atrasada, las métricas acababan en el
        mensaje N-1 y los agregados del visor leían 0.
        """
        client, _ = counting_client
        factory = MongoDBSessionManagerFactory(
            client=client,
            database_name="test_write_amplification",
            collection_name="sessions",
            application_name="test",
        )
        collection = client["test_write_amplification"]["sessions"]
        cleanup_session(collection, unique_session_id)

        run_turn(factory, unique_session_id, "hola")

        doc = collection.find_one({"_id": unique_session_id})
        messages = doc["agents"]["supervisor"]["messages"]
        last_message = messages[-1]

        assert "event_loop_metrics" in last_message, (
            "el último mensaje se quedó sin métricas: los agregados del visor "
            "leerían 0 tokens para este agente"
        )
        usage = last_message["event_loop_metrics"]["accumulated_usage"]
        assert usage["totalTokens"] > 0
