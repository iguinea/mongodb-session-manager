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
from strands.types.session import Session, SessionAgent, SessionMessage

from mongodb_session_manager.mongodb_session_factory import (
    MongoDBSessionManagerFactory,
)
from mongodb_session_manager.mongodb_session_repository import (
    MongoDBSessionRepository,
    _reset_index_registry,
)
from tests.support.scripted_model import ScriptedModel, text_stream, tool_stream

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


class CommandCounter(monitoring.CommandListener):
    """Registra los comandos enviados al servidor y los campos de cada $set."""

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.set_fields: list[str] = []
        self.enabled = False

    def started(self, event: Any) -> None:
        if self.enabled and event.command_name not in _IGNORED_COMMANDS:
            self.commands.append(event.command_name)
            if event.command_name == "update":
                for update in event.command.get("updates", []):
                    self.set_fields.extend(update["u"].get("$set", {}))

    def succeeded(self, event: Any) -> None:
        # Solo interesa cuántos comandos se envían, no su resultado: los
        # comandos se cuentan en started(). La interfaz CommandListener obliga
        # a implementar los tres métodos.
        pass

    def failed(self, event: Any) -> None:
        # Un comando fallido también viajó por el cable y ya está contado en
        # started(); si además hace fallar el test, lo dirá el assert.
        pass

    def counts(self) -> Counter:
        return Counter(self.commands)


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


@pytest.fixture
def turn_factory(counting_client, unique_session_id, cleanup_session):
    """Factoría sobre el cliente contador; la sesión del test se limpia al final.

    Devuelve (factoría, colección, contador). La colección sale de la propia
    factoría, para que el test lea y limpie justo donde ella escribe.
    """
    client, counter = counting_client
    factory = MongoDBSessionManagerFactory(
        client=client,
        database_name="test_write_amplification",
        collection_name="sessions",
        application_name="test",
    )
    collection = client[factory.database_name][factory.collection_name]
    cleanup_session(collection, unique_session_id)
    return factory, collection, counter


def run_turn(factory, session_id: str, prompt: str) -> None:
    """Un turno completo: supervisor + sub-agente, con una llamada a tool."""
    supervisor_manager = factory.create_session_manager(session_id)

    @tool(name="info_suministro_agent", description="Consulta datos de suministro")
    def info_suministro_agent(query: str) -> str:
        sub_manager = factory.create_session_manager(session_id)
        sub_agent = Agent(
            agent_id="info_suministro_agent",
            model=ScriptedModel([list(text_stream("Datos del suministro: OK"))], "sub"),
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
                    tool_stream("info_suministro_agent", "tu-1", '{"query": "consumo"}')
                ),
                list(text_stream("Tu consumo del ultimo mes es de 312 kWh.")),
            ],
            "supervisor",
        ),
        system_prompt=SYSTEM_PROMPT,
        tools=[info_suministro_agent],
        session_manager=supervisor_manager,
    )
    supervisor(prompt)
    supervisor_manager.close()


class TestRedactionCost:
    def test_redaction_costs_one_write_and_no_read(
        self, counting_client, unique_session_id, cleanup_session
    ):
        """Redactar cuesta una escritura y ninguna lectura (#64).

        Antes se leía el historial completo del agente para calcular en el
        cliente el índice del mensaje: un round-trip por redacción que además
        crecía con la sesión.
        """
        client, counter = counting_client
        repo = MongoDBSessionRepository(
            client=client,
            database_name="test_write_amplification",
            collection_name="sessions",
        )
        cleanup_session(repo.collection, unique_session_id)
        repo.create_session(
            Session(session_id=unique_session_id, session_type="default")
        )
        repo.create_agent(
            unique_session_id,
            SessionAgent(agent_id="a1", state={}, conversation_manager_state={}),
        )
        original = {"role": "user", "content": [{"text": "sensitive"}]}
        repo.create_message(
            unique_session_id,
            "a1",
            SessionMessage(message_id=1, message=original),
        )

        counter.enabled = True
        repo.update_message(
            unique_session_id,
            "a1",
            SessionMessage(
                message_id=1,
                message=original,
                redact_message={"role": "user", "content": [{"text": "***"}]},
            ),
        )
        counter.enabled = False

        counts = counter.counts()
        assert counts["find"] == 0, f"la redacción leyó el historial: {counts}"
        assert counts["update"] == 1, f"{counts['update']} updates: {counts}"


class TestTurnOperationBudget:
    def test_turn_stays_within_write_budget(self, turn_factory, unique_session_id):
        """Un turno con supervisor y sub-agente cabe en el presupuesto.

        Contra v0.9.1 el mismo escenario producía 42 operaciones: 21 updates,
        13 finds y 8 createIndexes. Con #54 bajó a 21 (15 updates, 6 finds y 0
        createIndexes) y con #65 a 19.

        El presupuesto de 13 se desglosa así, medido con este mismo listener
        (6 mensajes en total: 4 del supervisor, 2 del sub-agente):
          6  create_message ($push, uno por mensaje)
          3  update_agent: el primer sync de cada manager, más el del
             supervisor tras ejecutar la tool (Strands sube la versión de
             interrupt_state)
          4  métricas del último mensaje

        La configuración no viaja: cada manager la conoce desde read_agent()
        (#65). Antes eran 2 escrituras más, de ~14 KB cada una. El presupuesto
        de cada hito se sigue en la issue maestra #56.
        """
        factory, _, counter = turn_factory

        # Turno 0: crea la sesión y calienta el registro de índices.
        run_turn(factory, unique_session_id, "hola")

        counter.enabled = True
        run_turn(factory, unique_session_id, "y el mes pasado?")
        counter.enabled = False

        counts = counter.counts()
        assert counts["update"] <= 13, f"{counts['update']} updates: {counts}"
        assert counts["createIndexes"] == 0, "los índices ya estaban asegurados"
        assert counts["find"] <= 6, f"{counts['find']} finds: {counts}"
        rewritten = [
            field
            for field in counter.set_fields
            if field.endswith(".agent_data.system_prompt")
        ]
        assert not rewritten, (
            "el turno caliente reescribió un system_prompt que no cambió; "
            f"¿read_agent() dejó de traer la configuración? {rewritten}"
        )

    def test_root_updated_at_advances_with_the_turn(
        self, turn_factory, unique_session_id
    ):
        """Guardarraíl del contrato externo.

        El Session Viewer y el informe de auditoría calculan «Fin» y «Duración»
        con el updated_at raíz. Si dejara de avanzar, las sesiones mostrarían
        una duración corta de menos, en silencio.
        """
        factory, collection, _ = turn_factory

        run_turn(factory, unique_session_id, "hola")
        after_first = collection.find_one({"_id": unique_session_id})["updated_at"]

        run_turn(factory, unique_session_id, "otra pregunta")
        after_second = collection.find_one({"_id": unique_session_id})["updated_at"]

        assert after_second > after_first

    def test_agent_created_at_survives_updates(self, turn_factory, unique_session_id):
        """El created_at del agente no se falsea al sincronizar."""
        factory, collection, _ = turn_factory

        run_turn(factory, unique_session_id, "hola")
        doc = collection.find_one({"_id": unique_session_id})
        original = doc["agents"]["supervisor"]["created_at"]

        run_turn(factory, unique_session_id, "otra")
        doc = collection.find_one({"_id": unique_session_id})

        assert doc["agents"]["supervisor"]["created_at"] == original

    def test_agent_config_survives_the_turn(self, turn_factory, unique_session_id):
        """Cada agente conserva model y system_prompt al terminar el turno.

        Strands vuelve a sincronizar el agente que ejecuta tools (sube la
        versión de interrupt_state) y update_agent reemplazaba agent_data
        entero. Con la caché de configuración ya llena nadie lo reescribía: el
        supervisor terminaba cada turno sin model ni system_prompt.
        """
        factory, collection, _ = turn_factory

        for prompt in ("hola", "y el mes pasado?"):
            run_turn(factory, unique_session_id, prompt)

            agents = collection.find_one({"_id": unique_session_id})["agents"]
            for agent_id, model_id in (
                ("supervisor", "supervisor"),
                ("info_suministro_agent", "sub"),
            ):
                agent_data = agents[agent_id]["agent_data"]
                assert agent_data.get("model") == model_id, (
                    f"{agent_id} sin model tras el turno '{prompt}'"
                )
                assert agent_data.get("system_prompt") == SYSTEM_PROMPT, (
                    f"{agent_id} sin system_prompt tras el turno '{prompt}'"
                )

    def test_metrics_land_on_the_last_message(self, turn_factory, unique_session_id):
        """Las métricas se escriben en el último mensaje, no en el anterior.

        Es la garantía que el read-after-write ponía en riesgo: si el
        message_id venía de una réplica atrasada, las métricas acababan en el
        mensaje N-1 y los agregados del visor leían 0.
        """
        factory, collection, _ = turn_factory

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
