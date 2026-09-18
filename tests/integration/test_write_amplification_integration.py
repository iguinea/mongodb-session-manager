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


def scripted_agent(manager, agent_id: str, model_id: str, reply: str) -> Agent:
    """Un agente sin tools que responde siempre `reply`."""
    return Agent(
        agent_id=agent_id,
        model=ScriptedModel([list(text_stream(reply))], model_id),
        system_prompt=SYSTEM_PROMPT,
        session_manager=manager,
    )


def run_turn(factory, session_id: str, prompt: str) -> None:
    """Un turno completo: supervisor + sub-agente, con una llamada a tool."""
    supervisor_manager = factory.create_session_manager(session_id)

    @tool(name="info_suministro_agent", description="Consulta datos de suministro")
    def info_suministro_agent(query: str) -> str:
        sub_manager = factory.create_session_manager(session_id)
        sub_agent = scripted_agent(
            sub_manager, "info_suministro_agent", "sub", "Datos del suministro: OK"
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
        createIndexes), con #65 a 19, con #67 a 16, con #66 a 14 y con #53 a 10.

        El presupuesto de 4 se desglosa así, medido con este mismo listener
        (6 mensajes en total: 4 del supervisor, 2 del sub-agente):
          2  la pregunta que abre cada invocación, escrita al llegar
          2  el cierre de cada invocación: sus demás mensajes y sus métricas

        Eran 8: un `$push` por mensaje más una escritura de métricas por agente.
        Desde #53 los mensajes que produce el event loop esperan al cierre de
        su invocación y salen en un solo `$push`, con las métricas ya dentro
        del último -- que es cuando el event loop las tiene acumuladas (#66).
        Solo la pregunta del usuario no espera: es lo único del turno que nada
        puede volver a producir.

        Las métricas llegaron a ser 4: el supervisor las escribía también en el
        sync del toolResult y en el de su mensaje final, y esa segunda llevaba
        las del ciclo anterior, porque Strands dispara MessageAddedEvent antes
        de acumularlas (#66). La configuración no viaja: cada manager la conoce
        desde read_agent() (#65). Antes eran 2 escrituras más, de ~14 KB cada
        una. El estado del agente tampoco (#67): ninguno de los dos cambia en
        el turno, y eran 3 update_agent, el primer sync de cada manager y el
        del supervisor tras la tool, porque Strands sube la versión de
        interrupt_state sin cambiar su contenido. El presupuesto de cada hito
        se sigue en la issue maestra #56.
        """
        factory, _, counter = turn_factory

        # Turno 0: crea la sesión y calienta el registro de índices.
        run_turn(factory, unique_session_id, "hola")

        counter.enabled = True
        run_turn(factory, unique_session_id, "y el mes pasado?")
        counter.enabled = False

        counts = counter.counts()
        assert counts["update"] <= 4, f"{counts['update']} updates: {counts}"
        assert counts["createIndexes"] == 0, "los índices ya estaban asegurados"
        assert counts["find"] <= 6, f"{counts['find']} finds: {counts}"
        rewritten = [
            field
            for field in counter.set_fields
            if field.endswith((".agent_data.system_prompt", ".agent_data.state"))
        ]
        assert not rewritten, (
            "el turno caliente reescribió configuración o estado que no cambió; "
            f"¿read_agent() dejó de recordar lo leído? {rewritten}"
        )

    def test_an_unchanged_agent_does_not_overwrite_another_manager(
        self, turn_factory, unique_session_id
    ):
        """Dos requests sobre el mismo agente: la que no lo cambia no pisa a la otra.

        Antes de #67 la segunda reescribía en su primer sync el estado que había
        restaurado, y deshacía en silencio lo que la primera acababa de guardar.
        """
        factory, collection, _ = turn_factory
        run_turn(factory, unique_session_id, "hola")

        idle_manager = factory.create_session_manager(unique_session_id)
        idle = scripted_agent(idle_manager, "info_suministro_agent", "sub", "ok")

        busy_manager = factory.create_session_manager(unique_session_id)
        busy = scripted_agent(busy_manager, "info_suministro_agent", "sub", "ok")
        busy.state.set("contrato", "ES-001")
        busy("guarda el contrato")

        idle("otra pregunta")
        idle_manager.close()
        busy_manager.close()

        agents = collection.find_one({"_id": unique_session_id})["agents"]
        state = agents["info_suministro_agent"]["agent_data"]["state"]
        assert state == {"contrato": "ES-001"}

    def test_state_set_in_one_turn_is_restored_in_the_next(
        self, turn_factory, unique_session_id
    ):
        """Guardarraíl: saltarse lo que no cambia no puede saltarse un cambio."""
        factory, _, _ = turn_factory
        run_turn(factory, unique_session_id, "hola")

        manager = factory.create_session_manager(unique_session_id)
        agent = scripted_agent(manager, "supervisor", "supervisor", "anotado")
        agent.state.set("idioma", "euskera")
        agent("recuerda mi idioma")
        manager.close()

        manager = factory.create_session_manager(unique_session_id)
        restored = scripted_agent(manager, "supervisor", "supervisor", "ok")
        manager.close()

        assert restored.state.get("idioma") == "euskera"

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

    def test_intermediate_messages_carry_no_metrics(
        self, turn_factory, unique_session_id
    ):
        """Solo el último mensaje de cada invocación lleva métricas (#66).

        El sync de cada MessageAddedEvent ve las métricas del ciclo anterior: el
        toolResult se llevaba las del primer ciclo y el mensaje final, durante un
        instante, unas obsoletas. Lo escribe el cierre, una vez.
        """
        factory, collection, _ = turn_factory

        run_turn(factory, unique_session_id, "hola")

        agents = collection.find_one({"_id": unique_session_id})["agents"]
        for agent_id, agent in agents.items():
            *intermediate, last = agent["messages"]
            carrying = [
                m["message_id"] for m in intermediate if "event_loop_metrics" in m
            ]
            assert not carrying, (
                f"{agent_id}: métricas en mensajes intermedios {carrying}"
            )
            assert "event_loop_metrics" in last, (
                f"{agent_id}: último mensaje sin métricas"
            )

        supervisor_metrics = agents["supervisor"]["messages"][-1]["event_loop_metrics"]
        assert supervisor_metrics["cycle_metrics"]["cycle_count"] == 2
        assert "info_suministro_agent" in supervisor_metrics["tool_usage"]

    def test_each_message_carries_the_sdk_attribution(
        self, turn_factory, unique_session_id
    ):
        """Strands 1.56 atribuye cada ciclo a su mensaje, y viaja gratis (#69).

        `Message` gana dos campos: `tracking_id`, un uuid4 estable que el SDK
        pone en los mensajes que añade él —todos los de este turno—, y
        `metadata`, con el `usage` y las `metrics` del ciclo que produjo el
        mensaje `assistant`. Van dentro de `message`, así que los escribe el
        mismo `$push` de `create_message()`: es la atribución por mensaje que
        #66 no podía dar, sin ninguna escritura extra. El presupuesto del turno
        lo fija `test_turn_stays_within_write_budget`.

        No sustituye a `event_loop_metrics`: eso es lo acumulado de la
        invocación, y esto el coste de un ciclo. Ni a `storage_id`, que es lo
        que identifica un mensaje: un mensaje añadido a mano por la aplicación
        se guarda sin `tracking_id`.
        """
        factory, collection, _ = turn_factory

        run_turn(factory, unique_session_id, "hola")

        agents = collection.find_one({"_id": unique_session_id})["agents"]
        for agent_id, agent in agents.items():
            without_id = [
                m["message_id"]
                for m in agent["messages"]
                if not m["message"].get("tracking_id")
            ]
            assert not without_id, f"{agent_id}: mensajes sin tracking_id {without_id}"

        last = agents["supervisor"]["messages"][-1]["message"]
        assert last["metadata"]["usage"]["totalTokens"] > 0
        assert "latencyMs" in last["metadata"]["metrics"]

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


class TestWhatABatchMayNotCost:
    """Los invariantes que #53 tenía que demostrar antes de agrupar mensajes.

    Bufferizar difiere la durabilidad de un mensaje hasta el cierre de su
    invocación. Estos casos fijan hasta dónde llega esa ventana, contra un
    MongoDB real: lo que se escribe al momento, lo que sobrevive a un turno que
    revienta, y lo que ve quien lee la colección por su cuenta.
    """

    def test_the_question_is_stored_before_the_model_answers(
        self, turn_factory, unique_session_id
    ):
        """La pregunta del usuario está en disco mientras el modelo responde.

        Es la razón de que el lote no sea el turno entero: una tool que tarda
        medio minuto es medio minuto en el que un proceso puede morir, y la
        pregunta es lo único que nadie puede volver a producir.
        """
        factory, collection, _ = turn_factory
        stored_while_answering: list[list[str]] = []

        @tool(name="lenta", description="Tarda")
        def lenta(query: str) -> str:
            doc = collection.find_one({"_id": unique_session_id}) or {}
            messages = doc.get("agents", {}).get("supervisor", {}).get("messages", [])
            stored_while_answering.append(
                [m["message"]["content"][0].get("text", "") for m in messages]
            )
            return "ok"

        manager = factory.create_session_manager(unique_session_id)
        supervisor = Agent(
            agent_id="supervisor",
            model=ScriptedModel(
                [
                    list(tool_stream("lenta", "tu-1", '{"query": "x"}')),
                    list(text_stream("listo")),
                ],
                "supervisor",
            ),
            system_prompt=SYSTEM_PROMPT,
            tools=[lenta],
            session_manager=manager,
        )
        supervisor("cuanto he gastado?")
        manager.close()

        assert stored_while_answering == [["cuanto he gastado?"]]

    def test_a_turn_that_blows_up_keeps_its_messages(
        self, turn_factory, unique_session_id
    ):
        """Una invocación que revienta escribe su lote igual.

        `AfterInvocationEvent` sale de un `finally` en `strands/agent/agent.py`,
        así que el cierre corre también cuando el modelo falla. Sin esa
        garantía, agrupar mensajes sería cambiar escrituras por pérdidas.
        """
        factory, collection, _ = turn_factory
        manager = factory.create_session_manager(unique_session_id)

        @tool(name="rota", description="Falla")
        def rota(query: str) -> str:
            raise RuntimeError("la tool se cayó")

        class ExplodingModel(ScriptedModel):
            """Pide la tool y se cae en el ciclo siguiente, con el toolResult ya dentro."""

            async def stream(self, *args: Any, **kwargs: Any):
                if self._index:
                    raise RuntimeError("modelo caído")
                async for event in super().stream(*args, **kwargs):
                    yield event

        supervisor = Agent(
            agent_id="supervisor",
            model=ExplodingModel(
                [list(tool_stream("rota", "tu-1", '{"query": "x"}'))], "supervisor"
            ),
            system_prompt=SYSTEM_PROMPT,
            tools=[rota],
            session_manager=manager,
        )

        with pytest.raises(Exception, match="modelo caído"):
            supervisor("hola")
        manager.close()

        messages = collection.find_one({"_id": unique_session_id})["agents"][
            "supervisor"
        ]["messages"]
        roles = [m["message"]["role"] for m in messages]
        assert roles == ["user", "assistant", "user"], roles
        assert [m["message_id"] for m in messages] == [0, 1, 2]

    def test_the_history_keeps_its_order_across_turns(
        self, turn_factory, unique_session_id
    ):
        """Tres turnos seguidos: el array es la conversación, en su orden.

        Un lote entra con `$each` al final del array, y un mensaje inmediato
        vuelca antes lo que haya pendiente. Si alguna de las dos cosas fallara,
        el historial restaurado contaría otra cosa que la conversación.
        """
        factory, collection, _ = turn_factory

        for prompt in ("una", "dos", "tres"):
            run_turn(factory, unique_session_id, prompt)

        messages = collection.find_one({"_id": unique_session_id})["agents"][
            "supervisor"
        ]["messages"]
        assert [m["message_id"] for m in messages] == list(range(len(messages)))
        prompts = [
            m["message"]["content"][0].get("text")
            for m in messages
            if m["message"]["role"] == "user" and "text" in m["message"]["content"][0]
        ]
        assert prompts == ["una", "dos", "tres"]

    def test_a_restored_manager_reads_the_batch_of_the_previous_turn(
        self, turn_factory, unique_session_id
    ):
        """El turno siguiente restaura lo que el lote del anterior escribió."""
        factory, _, _ = turn_factory
        run_turn(factory, unique_session_id, "hola")

        manager = factory.create_session_manager(unique_session_id)
        restored = scripted_agent(manager, "supervisor", "supervisor", "ok")
        manager.close()

        assert [m["role"] for m in restored.messages] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]
