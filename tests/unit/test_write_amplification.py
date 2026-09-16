"""Tests de amplificación de escrituras (issue #54).

Cuentan el NÚMERO de operaciones contra MongoDB, que es la métrica que gobierna
la latencia en DocumentDB: allí cada `update` cuesta 40-55 ms sea cual sea su
tamaño.

Dos tipos de test conviven aquí:

- **Regresión de conteo**: fallan contra v0.9.1 porque documentan el
  comportamiento actual como no deseado.
- **Guardarraíl**: `TestRootUpdatedAtInvariant` pasa desde el primer día. No es
  un test inútil: fija un contrato del que dependen dos consumidores externos
  («Fin» y «Duración» en el Session Viewer y en el informe de auditoría) para
  que ninguna optimización futura pueda romperlo por descuido.
"""

from unittest.mock import MagicMock, patch

import pytest
from pymongo.errors import PyMongoError
from strands.hooks import AfterInvocationEvent, HookRegistry, MessageAddedEvent
from strands.interrupt import _InterruptState
from strands.types.session import SessionAgent, SessionMessage

from mongodb_session_manager.message_identity import MessageRef, attach_storage_id
from mongodb_session_manager.mongodb_session_manager import MongoDBSessionManager
from mongodb_session_manager.mongodb_session_repository import (
    MongoDBSessionRepository,
    _reset_index_registry,
)


@pytest.fixture(autouse=True)
def clean_index_registry():
    """Aísla el registro de índices entre tests."""
    _reset_index_registry()
    yield
    _reset_index_registry()


def make_client():
    """MongoClient falso con su propia colección, distinguible de otros."""
    collection = MagicMock()
    collection.find_one.return_value = None
    collection.update_one.return_value = MagicMock(matched_count=1, modified_count=1)
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=collection)
    client = MagicMock()
    client.__getitem__ = MagicMock(return_value=db)
    return client, collection


def make_manager(client, session_id="s1", **kwargs):
    """Manager real sobre un cliente falso, con la sesión ya existente."""
    mgr = MongoDBSessionManager(
        session_id=session_id,
        client=client,
        database_name="db",
        collection_name="coll",
        **kwargs,
    )
    return mgr


# ---------------------------------------------------------------------------
# 1. Índices: idempotentes por cliente
# ---------------------------------------------------------------------------


class TestIndexCreationIsIdempotent:
    def test_second_manager_on_same_client_creates_no_indexes(self):
        """Segundo manager del mismo proceso: 0 createIndexes.

        Hoy son 4 por cada create_session_manager(): 8 por turno con supervisor
        + sub-agente.
        """
        client, collection = make_client()

        make_manager(client, "s1")
        first_call_count = collection.create_index.call_count
        collection.create_index.reset_mock()

        make_manager(client, "s2")

        assert first_call_count > 0, "el primer manager sí debe crear los índices"
        assert collection.create_index.call_count == 0

    def test_different_clients_each_create_indexes(self):
        """Dos clusters distintos con los mismos nombres: ambos indexan.

        Keyear el registro solo por (db, colección) dejaría el segundo cluster
        sin índices.
        """
        client_a, collection_a = make_client()
        client_b, collection_b = make_client()

        make_manager(client_a, "s1")
        make_manager(client_b, "s1")

        assert collection_a.create_index.call_count > 0
        assert collection_b.create_index.call_count > 0

    def test_new_metadata_fields_trigger_reindex(self):
        """Pedir un metadata_field nuevo sobre la misma colección sí reindexa."""
        client, collection = make_client()

        make_manager(client, "s1", metadata_fields=["status"])
        collection.create_index.reset_mock()

        make_manager(client, "s2", metadata_fields=["status", "priority"])

        assert collection.create_index.call_count > 0

    def test_index_failure_does_not_poison_registry(self):
        """Si create_index falla, el siguiente manager debe reintentarlo."""
        client, collection = make_client()
        collection.create_index.side_effect = PyMongoError("boom")

        make_manager(client, "s1")

        collection.create_index.side_effect = None
        collection.create_index.reset_mock()
        make_manager(client, "s2")

        assert collection.create_index.call_count > 0


# ---------------------------------------------------------------------------
# 2. Último message_id: desde memoria, no desde la base de datos
# ---------------------------------------------------------------------------


class TestLastMessageRefFromMemory:
    def test_no_find_when_message_in_memory(self, mock_agent):
        """El camino caliente no lee: el dato ya está en _latest_agent_message.

        Además de ahorrar un find, elimina un read-after-write sobre un
        secundario que puede atribuir las métricas al mensaje equivocado.
        """
        client, collection = make_client()
        mgr = make_manager(client)
        agent = mock_agent(agent_id="a1", latency_ms=100)

        message = SessionMessage(
            message_id=7, message={"role": "assistant", "content": [{"text": "hi"}]}
        )
        attach_storage_id(message, "9f1c")
        mgr._latest_agent_message["a1"] = message
        collection.find_one.reset_mock()

        assert mgr._get_last_message_ref(agent) == MessageRef(7, "9f1c")
        assert collection.find_one.call_count == 0

    def test_falls_back_to_find_when_not_in_memory(self, mock_agent):
        """Sin dato en memoria, se sigue leyendo (sesión restaurada)."""
        client, collection = make_client()
        mgr = make_manager(client)
        agent = mock_agent(agent_id="a1")

        mgr._latest_agent_message["a1"] = None
        collection.find_one.return_value = {
            "agents": {"a1": {"messages": [{"message_id": 3, "storage_id": "9f1c"}]}}
        }
        collection.find_one.reset_mock()

        assert mgr._get_last_message_ref(agent) == MessageRef(3, "9f1c")
        assert collection.find_one.call_count == 1

    def test_falls_back_when_agent_unknown(self, mock_agent):
        """Agente que no está en el dict: fallback, no KeyError."""
        client, collection = make_client()
        mgr = make_manager(client)
        agent = mock_agent(agent_id="desconocido")

        collection.find_one.return_value = None
        assert mgr._get_last_message_ref(agent) is None

    def test_unmatched_metrics_update_is_logged(self, mock_agent, caplog):
        """Si el update de métricas no casa, debe dejar rastro, no desaparecer."""
        client, collection = make_client()
        mgr = make_manager(client)
        agent = mock_agent(agent_id="a1", latency_ms=100)
        mgr._latest_agent_message["a1"] = SessionMessage(
            message_id=7, message={"role": "assistant", "content": [{"text": "x"}]}
        )
        collection.update_one.return_value = MagicMock(matched_count=0)

        with caplog.at_level("WARNING"):
            mgr._update_last_message_metrics(agent, {}, {}, {}, {})

        assert any(
            "7" in r.message or "metrics" in r.message.lower() for r in caplog.records
        )


# ---------------------------------------------------------------------------
# 3. update_agent sin lectura previa
# ---------------------------------------------------------------------------


class TestUpdateAgentDoesNotRead:
    def test_no_find_before_update(self, sample_session_agent):
        """Preservar created_at no requiere leerlo: $set no toca lo que no nombra."""
        client, collection = make_client()
        with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
            repo = MongoDBSessionRepository(
                client=client, database_name="db", collection_name="coll"
            )
        collection.find_one.reset_mock()

        repo.update_agent("s1", sample_session_agent)

        assert collection.find_one.call_count == 0
        assert collection.update_one.call_count == 1

    def test_does_not_overwrite_created_at(self, sample_session_agent):
        """El $set no debe mencionar el created_at del agente."""
        client, collection = make_client()
        with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
            repo = MongoDBSessionRepository(
                client=client, database_name="db", collection_name="coll"
            )

        repo.update_agent("s1", sample_session_agent)

        set_keys = collection.update_one.call_args[0][1]["$set"].keys()
        agent_id = sample_session_agent.agent_id
        assert f"agents.{agent_id}.created_at" not in set_keys


# ---------------------------------------------------------------------------
# 3b. update_agent: un agente sin cambios no viaja (issue #67)
# ---------------------------------------------------------------------------


def repository_with_stored_agent():
    """Repositorio sobre un cliente falso que ya ha leído el agente a1 con state {}.

    Devuelve (repositorio, colección), con los contadores a cero.
    """
    client, collection = make_client()
    with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
        repo = MongoDBSessionRepository(
            client=client, database_name="db", collection_name="coll"
        )
    collection.find_one.return_value = {
        "agents": {
            "a1": {
                "agent_data": {
                    "agent_id": "a1",
                    "state": {},
                    "conversation_manager_state": {},
                    "_internal_state": {},
                }
            }
        }
    }
    repo.read_agent("s1", "a1")
    collection.reset_mock()
    return repo, collection


class TestUpdateAgentSkipsUnchangedContent:
    def test_unchanged_agent_costs_no_round_trip(self):
        """El primer sync de cada manager reescribía lo que acababa de leer."""
        repo, collection = repository_with_stored_agent()

        repo.update_agent("s1", SessionAgent("a1", {}, {}))

        assert collection.update_one.call_count == 0

    def test_a_failed_write_is_not_remembered(self):
        """Si la escritura lanza, lo persistido sigue siendo lo leído: se reintenta."""
        repo, collection = repository_with_stored_agent()
        changed = SessionAgent("a1", {"k": "v"}, {})
        collection.update_one.side_effect = PyMongoError("boom")
        with pytest.raises(PyMongoError):
            repo.update_agent("s1", changed)

        collection.update_one.side_effect = None
        repo.update_agent("s1", changed)

        assert collection.update_one.call_count == 2

    def test_an_unmatched_write_is_not_remembered(self):
        """Sin documento no hay nada persistido que recordar: se reintenta."""
        repo, collection = repository_with_stored_agent()
        changed = SessionAgent("a1", {"k": "v"}, {})
        collection.update_one.return_value = MagicMock(matched_count=0)
        with pytest.raises(ValueError, match="not found"):
            repo.update_agent("s1", changed)

        collection.update_one.return_value = MagicMock(matched_count=1)
        repo.update_agent("s1", changed)

        assert collection.update_one.call_count == 2

    def test_an_agent_no_longer_found_is_forgotten(self):
        """Si otra lectura ya no lo encuentra, no se da nada por persistido."""
        repo, collection = repository_with_stored_agent()
        collection.find_one.return_value = {"agents": {}}
        assert repo.read_agent("s1", "a1") is None

        repo.update_agent("s1", SessionAgent("a1", {}, {}))

        assert collection.update_one.call_count == 1


# ---------------------------------------------------------------------------
# 4. Configuración del agente: solo cuando cambia
# ---------------------------------------------------------------------------


class TestAgentConfigWrittenOnlyOnChange:
    def test_second_identical_capture_writes_nothing(self, mock_agent):
        client, collection = make_client()
        mgr = make_manager(client)
        agent = mock_agent(
            agent_id="a1", system_prompt="eres un asistente", model_id="m1"
        )

        mgr._capture_agent_config(agent)
        collection.update_one.reset_mock()
        mgr._capture_agent_config(agent)

        assert collection.update_one.call_count == 0

    def test_changed_system_prompt_writes_again(self, mock_agent):
        client, collection = make_client()
        mgr = make_manager(client)
        agent = mock_agent(agent_id="a1", system_prompt="v1", model_id="m1")

        mgr._capture_agent_config(agent)
        agent.system_prompt = "v2"
        collection.update_one.reset_mock()
        mgr._capture_agent_config(agent)

        assert collection.update_one.call_count == 1

    def test_cache_is_per_agent(self, mock_agent):
        """Dos agentes alternando en el mismo manager no se pisan la caché.

        Con un único slot, cada alternancia invalidaría la entrada anterior y
        volvería a escribir siempre.
        """
        client, collection = make_client()
        mgr = make_manager(client)
        a1 = mock_agent(agent_id="a1", system_prompt="p1", model_id="m1")
        a2 = mock_agent(agent_id="a2", system_prompt="p2", model_id="m2")

        mgr._capture_agent_config(a1)
        mgr._capture_agent_config(a2)
        collection.update_one.reset_mock()

        mgr._capture_agent_config(a1)
        mgr._capture_agent_config(a2)
        mgr._capture_agent_config(a1)

        assert collection.update_one.call_count == 0


# ---------------------------------------------------------------------------
# 5. sync_agent: una sola escritura nuestra
# ---------------------------------------------------------------------------


def _manager_over_mock_repo():
    """Manager sobre un repositorio mockeado, inyectado sin parchear la clase.

    Se cuentan las escrituras que el manager PIDE al repositorio, que es el
    contrato que defiende la optimización. Lo que `super().sync_agent()` escriba
    por su cuenta no entra en la cuenta.
    """
    mock_repo = MagicMock(spec=MongoDBSessionRepository)
    mock_repo.read_session.return_value = None
    mock_repo.update_message_fields.return_value = True
    mock_repo.update_agent_fields.return_value = True
    mgr = MongoDBSessionManager(session_id="s1", session_repository=mock_repo)
    return mgr, mock_repo


def _manager_writes(mock_repo):
    """Count the writes the manager asked the repository for."""
    return (
        mock_repo.update_message_fields.call_count
        + mock_repo.update_agent_fields.call_count
    )


def _ready_to_sync(mgr, mock_agent):
    """Build an agent with one tracked message, ready to be synced."""
    agent = mock_agent(agent_id="a1", latency_ms=100, system_prompt="p", model_id="m1")
    agent.state._get_version.return_value = 1
    agent._interrupt_state._get_version.return_value = 1
    agent.conversation_manager.get_state.return_value = {}
    mgr._latest_agent_message["a1"] = SessionMessage(
        message_id=2, message={"role": "assistant", "content": [{"text": "x"}]}
    )
    return agent


class TestSyncAgentWriteCount:
    def test_first_sync_issues_single_update(self, mock_agent):
        """Métricas y config van al mismo documento: una sola escritura."""
        mgr, mock_repo = _manager_over_mock_repo()
        agent = _ready_to_sync(mgr, mock_agent)

        mgr.sync_agent(agent)

        assert _manager_writes(mock_repo) == 1

    def test_first_sync_carries_the_config_along_with_the_metrics(self, mock_agent):
        """La config viaja de polizón en la escritura de métricas, no aparte."""
        mgr, mock_repo = _manager_over_mock_repo()
        agent = _ready_to_sync(mgr, mock_agent)

        mgr.sync_agent(agent)

        kwargs = mock_repo.update_message_fields.call_args.kwargs
        assert kwargs["agent_set_operations"]["agent_data.model"] == "m1"

    def test_second_sync_without_changes_issues_single_update(self, mock_agent):
        """El sync de cierre ya no reescribe la config, solo las métricas."""
        mgr, mock_repo = _manager_over_mock_repo()
        agent = _ready_to_sync(mgr, mock_agent)

        mgr.sync_agent(agent)
        mock_repo.reset_mock()
        mgr.sync_agent(agent)

        assert _manager_writes(mock_repo) == 1
        assert (
            mock_repo.update_message_fields.call_args.kwargs["agent_set_operations"]
            is None
        )


# ---------------------------------------------------------------------------
# 5b. El guardarraíl también cuesta una sola escritura
# ---------------------------------------------------------------------------


class TestGuardrailEventWriteCount:
    def test_guardrail_event_costs_one_write(self, mock_agent):
        """La anotación del mensaje y la de la sesión comparten round-trip.

        Guardarraíl explícito: separar el $set del $push «por limpieza»
        duplicaría el coste de cada intervención.
        """
        client, collection = make_client()
        mgr = make_manager(client)
        agent = mock_agent(agent_id="a1")
        collection.update_one.reset_mock()

        mgr._record_guardrail_event(
            agent,
            MessageRef(5, "9f1c"),
            stop_reason="guardrail_intervened",
            guardrail_trace={"inputAssessment": {}, "outputAssessments": []},
        )

        assert collection.update_one.call_count == 1
        update = collection.update_one.call_args[0][1]
        assert "$set" in update
        assert "$push" in update


class TestUnmatchedSyncDoesNotCacheConfig:
    def test_config_is_not_cached_when_the_write_missed(self, mock_agent):
        """Si la escritura no casó, la config no está persistida.

        Cachearla igualmente la haría desaparecer para siempre: cada sync
        posterior la daría por escrita y no volvería a intentarlo.
        """
        mgr, mock_repo = _manager_over_mock_repo()
        mock_repo.update_message_fields.return_value = False
        mock_repo.update_agent_fields.return_value = False
        agent = _ready_to_sync(mgr, mock_agent)

        mgr.sync_agent(agent)

        assert "a1" not in mgr._agent_config_cache

    def test_the_next_sync_writes_the_config_again(self, mock_agent):
        """Y por eso el sync siguiente vuelve a intentar escribirla."""
        mgr, mock_repo = _manager_over_mock_repo()
        mock_repo.update_message_fields.return_value = False
        mock_repo.update_agent_fields.return_value = False
        agent = _ready_to_sync(mgr, mock_agent)

        mgr.sync_agent(agent)
        mock_repo.update_message_fields.reset_mock()
        mgr.sync_agent(agent)

        assert (
            mock_repo.update_message_fields.call_args.kwargs["agent_set_operations"]
            is not None
        )


# ---------------------------------------------------------------------------
# 6. Guardarraíl: el updated_at raíz (contrato externo)
# ---------------------------------------------------------------------------


class TestRootUpdatedAtInvariant:
    """Dos consumidores externos calculan «Fin» y «Duración» con este campo.

    Si dejara de refrescarse al cierre del turno, las sesiones mostrarían una
    duración corta de menos, en silencio.
    """

    def test_create_message_refreshes_root_updated_at(self, sample_session_message):
        client, collection = make_client()
        with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
            repo = MongoDBSessionRepository(
                client=client, database_name="db", collection_name="coll"
            )

        repo.create_message("s1", "a1", sample_session_message)

        assert "updated_at" in collection.update_one.call_args[0][1]["$set"]

    def test_update_agent_refreshes_root_updated_at(self, sample_session_agent):
        client, collection = make_client()
        with patch.object(MongoDBSessionRepository, "_ensure_indexes"):
            repo = MongoDBSessionRepository(
                client=client, database_name="db", collection_name="coll"
            )

        repo.update_agent("s1", sample_session_agent)

        assert "updated_at" in collection.update_one.call_args[0][1]["$set"]

    def test_manager_own_writes_never_touch_root_updated_at(self, mock_agent):
        """Las escrituras del manager no tocan el raíz — y no deben empezar.

        Si alguna lo hiciera, el razonamiento de que recortarlas es seguro
        dejaría de ser válido.
        """
        client, collection = make_client()
        mgr = make_manager(client)
        agent = mock_agent(
            agent_id="a1", latency_ms=100, system_prompt="p", model_id="m"
        )
        mgr._latest_agent_message["a1"] = SessionMessage(
            message_id=1, message={"role": "assistant", "content": [{"text": "x"}]}
        )
        collection.update_one.reset_mock()

        mgr._update_last_message_metrics(agent, {}, {}, {}, {})
        mgr._capture_agent_config(agent)

        for call in collection.update_one.call_args_list:
            assert "updated_at" not in call[0][1].get("$set", {})


# ---------------------------------------------------------------------------
# 7. Configuración hidratada al restaurar el agente (issue #65)
# ---------------------------------------------------------------------------


def persisted_agent():
    """Agente guardado en un turno anterior, con su configuración y dos mensajes.

    Lleva el `_internal_state` que Strands escribe, para que el agente
    restaurado sea, campo a campo, el mismo que se leyó (#67).
    """
    return {
        "agent_data": {
            "agent_id": "a1",
            "state": {},
            "conversation_manager_state": {},
            "_internal_state": {"interrupt_state": _InterruptState().to_dict()},
            "model": "m1",
            "system_prompt": "p1",
        },
        "messages": [
            {"message_id": 0, "message": {"role": "user", "content": [{"text": "a"}]}},
            {
                "message_id": 1,
                "message": {"role": "assistant", "content": [{"text": "b"}]},
            },
        ],
    }


def restored_manager(mock_agent, stored_agents, system_prompt="p1"):
    """Manager nuevo sobre una sesión existente, con el agente a1 ya inicializado.

    El agente usa el modelo m1 y aún no tiene métricas. Devuelve
    (manager, agente, colección), con los contadores de la colección a cero.
    """
    client, collection = make_client()
    collection.find_one.return_value = {
        "_id": "s1",
        "session_id": "s1",
        "session_type": "AGENT",
        "agents": stored_agents,
    }
    mgr = make_manager(client)
    agent = mock_agent(
        agent_id="a1", latency_ms=0, model_id="m1", system_prompt=system_prompt
    )
    # Real, not a mock: update_agent() compares what the agent would write with
    # what was read, and a MagicMock only ever equals itself.
    agent._interrupt_state = _InterruptState()
    agent.conversation_manager.restore_from_session.return_value = None
    agent.conversation_manager.removed_message_count = 0
    agent.conversation_manager.get_state.return_value = {}

    mgr.initialize(agent)
    collection.update_one.reset_mock()
    collection.find_one.reset_mock()
    return mgr, agent, collection


def written_fields(collection):
    """Todo lo escrito con $set en las llamadas a update_one, fusionado."""
    written = {}
    for call in collection.update_one.call_args_list:
        written.update(call[0][1].get("$set", {}))
    return written


class TestAgentConfigHydratedOnRestore:
    def test_same_config_is_not_rewritten(self, mock_agent):
        """Nuevo manager sobre la sesión, misma configuración: no se reescribe.

        read_agent() ya trae model y system_prompt. Sin aprovecharlos, el
        primer sync de cada request reescribía el system prompt entero.
        """
        mgr, agent, collection = restored_manager(mock_agent, {"a1": persisted_agent()})

        mgr.sync_agent(agent)

        written = written_fields(collection)
        assert "agents.a1.agent_data.model" not in written
        assert "agents.a1.agent_data.system_prompt" not in written

    def test_changed_config_is_rewritten(self, mock_agent):
        """Prompt cambiado entre despliegues: sí se escribe.

        Guardarraíl: pasa también sin hidratar. Está para que la caché
        hidratada no se trague un cambio real de configuración.
        """
        mgr, agent, collection = restored_manager(
            mock_agent, {"a1": persisted_agent()}, system_prompt="p2"
        )

        mgr.sync_agent(agent)

        written = written_fields(collection)
        assert written["agents.a1.agent_data.system_prompt"] == "p2"

    def test_new_agent_in_existing_session_writes_config(self, mock_agent):
        """Agente nuevo en una sesión existente: su primer sync escribe la config.

        Guardarraíl: read_agent() no encuentra nada que hidratar. Es el caso
        del sub-agente invocado por primera vez en una conversación empezada.
        """
        mgr, agent, collection = restored_manager(mock_agent, {})

        mgr.sync_agent(agent)

        written = written_fields(collection)
        assert written["agents.a1.agent_data.model"] == "m1"
        assert written["agents.a1.agent_data.system_prompt"] == "p1"


# ---------------------------------------------------------------------------
# 8. Conteo de extremo a extremo
# ---------------------------------------------------------------------------


def run_hooked_turn(mgr, agent, on_message_added=None):
    """Dispara los eventos de un turno de 4 mensajes por el registry del manager.

    Pasan por `register_hooks()`, como en un Agent real, porque el sync de cada
    MessageAddedEvent no escribe lo mismo que el de cierre (issue #66). Llamar a
    `sync_agent()` a mano sería una llamada explícita, y esa sí escribe métricas.
    El orden de los eventos lo prueba `test_invocation_metrics.py` con un Agent
    real; aquí solo se cuenta.
    """
    registry = HookRegistry()
    mgr.register_hooks(registry)
    # user, assistant(toolUse), user(toolResult), assistant(final)
    for i in range(4):
        message = {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": [{"text": "m"}],
        }
        registry.invoke_callbacks(MessageAddedEvent(agent=agent, message=message))
        if on_message_added:
            on_message_added()
    registry.invoke_callbacks(AfterInvocationEvent(agent=agent))


class TestTurnWriteBudget:
    def test_warm_turn_stays_within_budget(self, mock_agent):
        """Un turno de 4 mensajes sobre una sesión existente: 5 escrituras.

        Es el turno de referencia: un manager por request sobre una sesión que
        ya existe. Presupuesto de 5:
          4  create_message ($push, uno por mensaje)
          1  métricas, en el cierre

        Las métricas se escribían en cada mensaje desde el segundo, más el
        cierre: 4. Las de cada mensaje eran las del ciclo anterior, porque
        Strands dispara MessageAddedEvent antes de acumularlas (issue #66). La
        configuración no se escribe: el agente se restaura con la misma que ya
        estaba persistida (issue #65). El estado tampoco: el primer sync del
        manager lleva justo lo que read_agent() acaba de leer (issue #67).
        """
        mgr, agent, collection = restored_manager(mock_agent, {"a1": persisted_agent()})
        summary = agent.event_loop_metrics.get_summary.return_value

        def first_cycle_done():
            # Only the user prompt arrives before the first model cycle.
            summary["accumulated_metrics"]["latencyMs"] = 100

        run_hooked_turn(mgr, agent, on_message_added=first_cycle_done)

        updates = collection.update_one.call_count
        finds = collection.find_one.call_count
        assert updates <= 5, f"{updates} updates en un turno caliente de 4 mensajes"
        assert finds == 0, f"{finds} finds evitables en el camino caliente"

    def test_turn_with_tool_call_stays_within_budget(self, mock_agent):
        """Un turno de 4 mensajes sobre un agente nuevo cabe en 7 escrituras.

        Presupuesto de 7, desglosado para que el número no sea mágico:
          4  create_message ($push, uno por mensaje)
          1  update_agent (el resto no cambia de contenido, issue #67)
          1  configuración, en el sync del primer mensaje
          1  métricas, en el cierre

        Contra v0.9.1 eran 15 updates y 6 finds: las métricas y la config iban
        por separado (5 + 5) y cada sync leía el último message_id.
        """
        client, collection = make_client()
        mgr = make_manager(client)

        agent = mock_agent(
            agent_id="a1", latency_ms=100, system_prompt="p", model_id="m1"
        )
        agent.state._get_version.return_value = 1
        agent._interrupt_state._get_version.return_value = 1
        agent.conversation_manager.get_state.return_value = {}
        mgr._latest_agent_message["a1"] = None
        mgr._last_synced_internal_state = {}

        collection.update_one.reset_mock()
        collection.find_one.reset_mock()

        run_hooked_turn(mgr, agent)

        updates = collection.update_one.call_count
        finds = collection.find_one.call_count
        assert updates <= 7, f"{updates} updates en un turno de 4 mensajes"
        assert finds == 0, f"{finds} finds evitables en el camino caliente"
