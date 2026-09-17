"""The real work whose cost the harness reports.

Turns run through a real Strands `Agent` against a real MongoDB; the only part
that does not leave the machine is the model, replayed by the same
`ScriptedModel` the integration tests use. That is deliberate: a benchmark turn
and a tested turn have to be the same turn, or the numbers describe something
nobody ships.

Concurrency runs as `asyncio.gather` over `invoke_async`, which is the shape of
production here — `examples/example_fastapi_streaming.py` awaits the agent
directly on the server loop. A thread pool would hide the thing worth measuring:
the blocking driver calls inside `sync_agent` stall that loop.

So "concurrency N" means N invocations in flight on one loop, the way N requests
share a FastAPI worker. It does not mean N parallel driver calls: pymongo is
synchronous, so those serialise — and the queue they form is precisely what the
event-loop lag measures.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from strands import Agent, tool
from strands.types.session import SessionMessage

from benchmarks.run_context import RunContext
from benchmarks.scenarios import Scenario
from tests.support.scripted_model import ScriptedModel, text_stream, tool_stream

# A production system prompt is several KB; a short one would make the config
# writes look cheap. Same shape the write-amplification test uses.
SYSTEM_PROMPT = "Eres un asistente de soporte. " + (
    "Instruccion detallada del prompt de produccion. " * 300
)
# 512 characters per message, the size the #57 and #58 measurements used.
MESSAGE_TEXT = "m" * 512
SUPERVISOR_ID = "supervisor"
SUB_AGENT_ID = "info_suministro_agent"
_SEED_BATCH = 500


def _seed_documents(start_index: int, count: int) -> list[dict[str, Any]]:
    """Synthetic messages shaped exactly as `create_message()` stores them."""
    base = datetime.now(UTC) - timedelta(seconds=count)
    documents = []
    for offset in range(count):
        index = start_index + offset
        stamp = base + timedelta(milliseconds=offset)
        message = SessionMessage(
            message_id=index,
            message={
                "role": "user" if index % 2 == 0 else "assistant",
                "content": [{"text": MESSAGE_TEXT}],
            },
        )
        document = message.__dict__.copy()
        document["storage_id"] = f"seed{index:012d}"
        document["created_at"] = stamp
        document["updated_at"] = stamp
        documents.append(document)
    return documents


def seed_history(collection: Any, session_id: str, agent_id: str, count: int) -> None:
    """Fills a session with `count` messages, in batches.

    Seeding through `create_message()` would cost one round-trip per message:
    5.000 of them against DocumentDB is four minutes of setup per scenario. The
    documents written here are byte-for-byte the ones that path produces.
    """
    if count <= 0:
        return
    path = f"agents.{agent_id}.messages"
    for start in range(0, count, _SEED_BATCH):
        batch = _seed_documents(start, min(_SEED_BATCH, count - start))
        collection.update_one({"_id": session_id}, {"$push": {path: {"$each": batch}}})


def scripted_agent(manager: Any, agent_id: str, model_id: str, reply: str) -> Agent:
    """An agent that always answers `reply`."""
    return Agent(
        agent_id=agent_id,
        model=ScriptedModel([list(text_stream(reply))], model_id),
        system_prompt=SYSTEM_PROMPT,
        session_manager=manager,
        # Printing the answer would put terminal I/O inside the measured window.
        callback_handler=None,
    )


def tool_agent(manager: Any, tools: list[Any]) -> Agent:
    """A supervisor that calls one tool and then answers."""
    return Agent(
        agent_id=SUPERVISOR_ID,
        model=ScriptedModel(
            [
                list(tool_stream(SUB_AGENT_ID, "tu-1", '{"query": "consumo"}')),
                list(text_stream("Tu consumo del ultimo mes es de 312 kWh.")),
            ],
            SUPERVISOR_ID,
        ),
        system_prompt=SYSTEM_PROMPT,
        tools=tools,
        session_manager=manager,
        callback_handler=None,
    )


def local_tool() -> Any:
    """A tool that answers on its own, without touching the database."""

    @tool(name=SUB_AGENT_ID, description="Consulta datos de suministro")
    def info_suministro_agent(query: str) -> str:
        return f"Datos del suministro para {query}: OK"

    return info_suministro_agent


def sub_agent_tool(factory: Any, session_id: str) -> Any:
    """A tool that runs a sub-agent with its own session manager.

    Blocking on purpose: the sub-agent's driver calls run inside the supervisor's
    invocation, on the same event loop, exactly as production does.
    """

    @tool(name=SUB_AGENT_ID, description="Consulta datos de suministro")
    def info_suministro_agent(query: str) -> str:
        sub_manager = factory.create_session_manager(session_id)
        sub = scripted_agent(
            sub_manager, SUB_AGENT_ID, "sub", "Datos del suministro: OK"
        )
        try:
            return str(sub(query))
        finally:
            sub_manager.close()

    return info_suministro_agent


class Workload:
    """Prepares and runs one scenario of the matrix.

    `prepare()` does everything that must not be measured: creating sessions,
    seeding histories and, for turns, restoring the agent. The measured window
    covers `run_repetition()` and nothing else.
    """

    def __init__(
        self,
        factory: Any,
        collection: Any,
        run: RunContext,
        scenario: Scenario,
    ) -> None:
        self._factory = factory
        self._collection = collection
        self._run = run
        self._scenario = scenario
        self._session_ids: list[str] = []
        self._created_sessions = 0

    def prepare(self) -> None:
        """Sessions, histories and warm managers — all outside the window."""
        if self._scenario.operation == "create":
            return
        for slot_index in range(self._scenario.concurrency):
            session_id = self._run.session_id(self._scenario.key, slot_index)
            manager = self._factory.create_session_manager(session_id)
            scripted_agent(manager, SUPERVISOR_ID, "bench-model", "ok")
            manager.close()
            seed_history(
                self._collection, session_id, SUPERVISOR_ID, self._scenario.history
            )
            self._session_ids.append(session_id)

    def _new_session_id(self) -> str:
        session_id = self._run.session_id(
            f"{self._scenario.key}-new", self._created_sessions
        )
        self._created_sessions += 1
        self._session_ids.append(session_id)
        return session_id

    def _build_agent(self, session_id: str) -> tuple[Agent, Any]:
        """A freshly restored agent, with the manager that has to be closed."""
        manager = self._factory.create_session_manager(session_id)
        operation = self._scenario.operation
        if operation == "turn.tool":
            agent = tool_agent(manager, [local_tool()])
        elif operation == "turn.supervisor":
            agent = tool_agent(manager, [sub_agent_tool(self._factory, session_id)])
        else:
            agent = scripted_agent(manager, SUPERVISOR_ID, "bench-model", "ok")
        return agent, manager

    async def run_repetition(self) -> list[float]:
        """One repetition of the scenario. Returns the latency of each turn."""
        operation = self._scenario.operation
        if operation == "restore":
            return await self._run_restores()
        return await self._run_turns()

    async def _run_restores(self) -> list[float]:
        """Restoring is building the manager and the agent: the reads of a request."""
        loop = asyncio.get_running_loop()
        latencies = []
        for session_id in self._session_ids:
            started = loop.time()
            _, manager = self._build_agent(session_id)
            latencies.append((loop.time() - started) * 1000)
            manager.close()
        return latencies

    async def _run_turns(self) -> list[float]:
        session_ids = (
            [self._new_session_id() for _ in range(self._scenario.concurrency)]
            if self._scenario.operation == "create"
            else list(self._session_ids)
        )
        built = [self._build_agent(session_id) for session_id in session_ids]

        async def one_turn(agent: Agent) -> float:
            loop = asyncio.get_running_loop()
            started = loop.time()
            await agent.invoke_async("y el mes pasado?")
            return (loop.time() - started) * 1000

        try:
            return list(await asyncio.gather(*(one_turn(a) for a, _ in built)))
        finally:
            for _, manager in built:
                manager.close()

    def persisted_messages(self) -> int:
        """Messages stored across every session of this run, counted server-side.

        The caller takes this before and after the window: the difference is what
        the measured work actually wrote. Pulling the documents to count them
        client-side would drag 5.000-message histories over the wire.
        """
        pipeline = [
            {"$match": self._run_query()},
            {"$project": {"agents": {"$objectToArray": {"$ifNull": ["$agents", {}]}}}},
            {"$unwind": "$agents"},
            {
                "$group": {
                    "_id": None,
                    "total": {
                        "$sum": {"$size": {"$ifNull": ["$agents.v.messages", []]}}
                    },
                }
            },
        ]
        for document in self._collection.aggregate(pipeline):
            return int(document["total"])
        return 0

    def last_messages_have_metrics(self) -> bool:
        """Every agent that ran closed its invocation and stamped its metrics (#66).

        Only the last message of each agent crosses the wire: `$objectToArray`,
        `$map` and `$arrayElemAt` are the operators the repository already uses,
        validated against DocumentDB in #58.
        """
        pipeline = [
            {"$match": self._run_query()},
            {
                "$project": {
                    "last_messages": {
                        "$map": {
                            "input": {"$objectToArray": {"$ifNull": ["$agents", {}]}},
                            "as": "agent",
                            "in": {
                                "$arrayElemAt": [
                                    {"$ifNull": ["$$agent.v.messages", []]},
                                    -1,
                                ]
                            },
                        }
                    }
                }
            },
        ]
        seen = False
        for document in self._collection.aggregate(pipeline):
            for last in document.get("last_messages") or []:
                if not last:
                    continue
                seen = True
                if "event_loop_metrics" not in last:
                    return False
        return seen

    def _run_query(self) -> dict[str, Any]:
        """Only the sessions of this scenario.

        A query by run prefix would also sweep in the seeded sessions of other
        scenarios, whose last message is synthetic and carries no metrics.
        """
        return {"_id": {"$in": list(self._session_ids)}}
