# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MongoDB Session Manager - A MongoDB session manager library for Strands Agents that provides persistent storage for agent conversations and state, with connection pooling optimized for stateless environments.

**Tech Stack:** Python 3.12+, UV package manager, MongoDB, Strands Agents SDK (`strands-agents>=1.56.0`)

## Development Commands

```bash
# Install dependencies
uv sync

# Run any example
uv run python examples/example_calculator_tool.py

# Run tests
uv run python -m pytest tests/ -v                          # All tests
uv run python -m pytest tests/unit/ -v                      # Unit tests only (no MongoDB needed)
uv run python -m pytest tests/ -m "not integration" -v      # Exclude integration tests
uv run python -m pytest tests/integration/ -v               # Integration only (requires MongoDB)

# Linting/formatting
uv run ruff check .
uv run ruff format .

# Build package
uv build

# Add dependencies
uv add <package-name>
uv add --dev <package-name>

# Run playground (chat interface)
cd playground/chat && make backend-fastapi-streaming  # Port 8880
cd playground/chat && make frontend                   # Port 8881

```

## Architecture

### Core Components (src/mongodb_session_manager/)

1. **MongoDBSessionManager** (`mongodb_session_manager.py`): Main class extending `RepositorySessionManager` from Strands SDK
   - `sync_agent()`: Captures metrics via `agent.event_loop_metrics.get_summary()` including tokens, latency, TTFB, cycle metrics, tool usage, and writes them on the agent's last message — **except in the sync Strands runs for each `MessageAddedEvent`**, which fires before the event loop accumulates that cycle's metrics. `register_hooks()` wraps the registry with `sync_origin.MessageAddedTagging`, so those callbacks run with a `ContextVar` tag set. The closing sync (`AfterInvocationEvent`) and any explicit call still write them: OV writes the TTFT on the agent and syncs by hand (#66)
   - `get_metadata_tool()`: Returns Strands tool for agent metadata management. Its **docstring is the contract**: Strands builds the description and the input schema from it, and that is all the model reads. Do not pass `description=` or `inputSchema=` to the decorator again — the hand-written schema was assigned to `ToolSpec.inputSchema` without the `{"json": ...}` wrapper every provider unwraps, so an agent holding the tool failed on its *first* call (botocore rejects the Converse request; the Anthropic provider raises `KeyError`). A key is a path in the three actions: `_handle_metadata_get()` resolves it with `field_names.resolve_path()` on the document the read already returned, and the reply of `set` names the keys whose value replaced a whole subdocument (#47)
   - Metadata/Feedback hooks for intercepting operations
   - Agent config persistence (model, system_prompt), written only when it changes; `initialize()` seeds the cache from `read_agent()`
   - `initialize()` validates the `agent_id` **before** `super()` (Strands registers the id before touching the repository), and the metadata hook wrappers validate keys before calling the hook (#79). Since strands 1.56 it is also the entry point of a `BidiAgent`: the SDK dropped `initialize_bidi_agent()`/`sync_bidi_agent()` and sends both kinds of agent through `initialize()` and `sync_agent()`. A `BidiAgent` has no event loop, so its sync writes state and config but no metrics — asking it for `event_loop_metrics` was an `AttributeError` at the end of every bidi session (#69)
   - **Never touches `session_repository.collection`**: every data access goes through the repository. Accepts `session_repository=` to inject the in-memory double in tests; a replacement must implement the whole repository surface (the contract lives in `tests/support/repository_contract.py`, not as a `Protocol`)

2. **MongoDBSessionRepository** (`mongodb_session_repository.py`): Implements `SessionRepository` interface
   - All MongoDB CRUD operations for sessions, agents, messages
   - `_update_message_document()` is the **only** place that builds the positional selector; `update_message()`, `update_message_fields()` and `record_guardrail_event()` all go through it, and all name the message with a `MessageRef` (#78)
   - `_agent_path()` is the **only** place that builds `agents.<agent_id>`, and `_prefixed()` the only one that joins a caller's keys to a path. No external name reaches a MongoDB path unchecked: `field_names.py` rejects, with `ValueError` and before any round-trip or early return, what MongoDB would read as syntax. A segment is non-empty, has no leading `$` and no NUL; an `agent_id` is one segment (so no `.`); metadata keys, `metadata_fields` and the relative keys of `update_*_fields()` are paths (`user.name`, `tags.0`). The in-memory double applies the same rule at the same point (#79)
   - `update_message_fields()` / `update_agent_fields()`: take keys relative to the message or the agent, and own the dot-notation paths. The agent config rides along with the metrics in a single write
   - `record_guardrail_event()`: derives the session-level event from the message one, minus the full `GuardrailTrace`
   - Domain reads: `get_agent_config()`, `list_agent_configs()`, `count_messages()`, `get_last_message_ref()`
   - Restore reads are bounded in MongoDB: `read_session()` fetches only the four `Session` header fields, `read_agent()` only `agent_data`, and `list_messages()` sorts stably by `created_at` before applying `offset`/`limit` in an aggregation. `read_message()`, `count_messages()` and `list_agent_configs()` also compute their result server-side. Do not replace the page pipeline with `$slice`: it slices physical order before chronological order and changes the contract (#57, #58)
   - `list_messages()` also negotiates the cursor batch (`_MESSAGE_BATCH_SIZE`), so the page is drained in the `aggregate` itself: one round-trip, no `getMore`. The default batch of 101 documents applies to **every** batch on DocumentDB, where a 5.000-message restore cost 49 `getMore` and 5,6 s; it now costs 3 commands and 525 ms. It must be **strictly** larger than the page — a batch of exactly its size returns the page with a live cursor. The history is deliberately **not** truncated: with the default `SlidingWindowConversationManager` the `offset` already bounds it, and truncating below what the caller asked for would change what the model sees (#92)
   - `pop_read_agent_config()`: hands over, once, the config found by the last `read_agent()`. Public because `initialize()` calls it — a method reached from another class is interface, underscore or not
   - `update_agent()` writes each `SessionAgent` field on its own path, so the manager's config fields in `agent_data` survive
   - `update_agent()` does not write an agent whose content (every `SessionAgent` field but `created_at`/`updated_at`) is what this repository last read, created or wrote: `agent_content.LastPersistedAgents`, shared with the in-memory double. It compares content, not Strands' versions, so a hook that replaces `agent.state` is still written. Saves the first sync of every manager and the post-tool sync (13 → 10 per reference turn) (#67)
   - `update_message()` locates the message with the positional `$` (no read first) and writes an allowlist of fields, so `event_loop_metrics` and `guardrail_event` survive a redaction
   - `_ensure_indexes()` creates each index in its **own** `try`, and `application_name` before the `metadata_fields` someone configures: they shared one `try`, so the first failure skipped every index after it (at MongoDB's 64-index limit, `application_name` and every `metadata.*` were silently never created). A permanent failure (`_PERMANENT_INDEX_ERRORS`: `CannotCreateIndex`, `Unauthorized`, index conflicts) is recorded so it is not retried; a transient one is not, so the next manager tries again — with a manager per request, retrying forever costs a round-trip per request, and an index costs 78-248 ms in DocumentDB (#59)
   - `create_session()` seeds `metadata_fields` **nested**, via `field_names.nested_document()`: a dot is a path here too, and the literal key `user.name` matched neither its own index (`metadata.user.name`) nor what `update_metadata()` writes. Two paths that cannot coexist (`user` and `user.name`) raise at construction, before connecting (#59)
   - `collection` stays public and supported for ad-hoc queries
   - Smart connection lifecycle (owns vs borrowed client)
   - **Log levels are contract**: the per-message and per-manager path is `DEBUG`; `INFO` is for events of the session (`Created session`, `Created agent`, `Added feedback`). A reference turn emitted 14 `INFO` records and 1.900 B, eight of them repeated per manager — and the factory builds one per request (#59)

3. **MongoDBConnectionPool** (`mongodb_connection_pool.py`): Singleton for connection reuse
   - `_POOL_DEFAULTS` applies **only to options the caller did not express**, by keyword or in the URI (`_resolve_options()`). pymongo gives the keyword precedence over the connection string, so the old defaults silently overruled it — and DocumentDB, which requires `retryWrites=false`, answered `OperationFailure 301` to every `update_one`. The default `minPoolSize` follows a smaller `maxPoolSize` the caller asked for, which pymongo would otherwise refuse. The singleton is still keyed on `_user_kwargs` (#59)
   - `maxIdleTimeMS` is 300.000: with `minPoolSize` refilling whatever the idle timer expires, 30 s meant an idle pool opening and closing ten connections every half minute, for ever — 33.596 a day per process **and per node** (#59)
   - `health_check(timeout_ms)`: `ping` under `pymongo.timeout()`, returns instead of raising. Without a timeout a health check took 20 s against a mute server with an open connection. `ping` and `server_info()` cost the same; `server_info()` is `buildInfo` pinned to the primary, which calls a cluster unhealthy during a failover (#59)
   - `get_pool_stats()` caches `server_version` and adds utilisation from `pool_telemetry.PoolTelemetry`, a CMAP listener — pymongo publishes no other way to know. 3,33 µs per command (#59)
   - Sizing: `maxPoolSize` is **per server**, plus two SDAM sockets per server. `nodes × (maxPoolSize + 2)` per process, against a ceiling of 1.000 on a DocumentDB `db.t4g.medium`. See `docs/user-guide/connection-pooling.md`

   - Thread-safe, configurable pool sizes

4. **MongoDBSessionManagerFactory** (`mongodb_session_factory.py`): Factory for stateless environments
   - Global factory functions: `initialize_global_factory()`, `get_global_factory()`, `close_global_factory()`

5. **Hooks** (`hooks/`): Optional AWS integrations
   - `FeedbackSNSHook`: SNS notifications with configurable templates
   - `MetadataSQSHook`: SQS propagation for SSE
   - `MetadataWebSocketHook`: Real-time WebSocket push
   - `dispatch_async()` no longer decides by the calling thread: the three factories take `loop=` and, failing that, capture the loop running when the hook is built, so a hook created in an async lifespan keeps notifying on the server loop from a worker thread. It keeps a strong reference to the work — the loop only holds weak ones — and logs how it ends, so a failed notification is an `ERROR` with context and not an absence (#95)
   - `background_work.py`: the notifications of every hook share one bounded pool. Without a loop to dispatch to they go to a **single reserve loop**, not a daemon thread per event (a burst of 200 went from 403 threads to 21). At most `max_in_flight` (64) run at once; past it, best-effort work is dropped with a `WARNING` and a counter. `order_key` serialises work per key — the metadata hooks pass `<hook>:<session_id>`, namespaced so two hooks on one session do not serialise against each other; what cannot start yet queues in order (`max_queued_per_key`, 8) and only overflow drops, the oldest, because the payload is a partial update and not the whole state. `Delivery.GUARANTEED` opts out of the limit: the feedback hook uses it because a feedback notification is a customer complaint nothing produces again. `shutdown_hooks(timeout)` drains, cancels the rest and returns the counters — from inside a loop (a FastAPI lifespan) call `shutdown_hooks_async()`, or the drain stops the very loop the notifications ride — and an orderly exit drains even without it: the close is registered with `threading._register_atexit()`, which runs *before* Python closes its thread pools — `atexit` runs after, too late for a hook whose AWS call lives on one (1 of 20 delivered vs 20 of 20). `SIGTERM` without a handler runs no Python at all, so ECS still needs one. A loop that stops without closing the work strands whatever was riding it: `_evict()` frees those keys, or that session goes mute for good. A `fork()` is the same failure on a bigger scale — the child inherits the loop object but not its thread — so the global dispatcher registers `reset_after_fork()` with `os.register_at_fork()`. `hooks_background_stats()` exposes the counters (#62)
   - The three bundled hooks **let their AWS error out** of the notification, so it lands in `failed` and in one `ERROR` with traceback, instead of an `ERROR` from the hook plus a `DEBUG` `Finished:` from the dispatcher and a `completed` that called a lost notification a delivered one. The `except` that swallowed it dated from when the coroutine ran in the caller's path; since #95 and #62 it runs after the MongoDB write returned, so there is nothing left to break. The `error_context` carries the `session_id` — it is the only log left. `GoneException` is **not** a failure: the WebSocket client hung up, which is how a session ends. A hook of your own that catches its own error still counts as `completed`, because that is all `BackgroundWork` can observe (#99)
   - `aws_client_config.notification_config()` is the **only** place the bundled hooks' boto3 clients get their timeouts: 3 s connect, 5 s read, 2 attempts (botocore's `max_attempts` counts retries, so it gets `TOTAL_ATTEMPTS - 1`). The defaults (60/60, legacy) let one stuck notification hold a thread for minutes. `worst_case_seconds()` (22 s) budgets botocore's own maximum backoff — `x-amz-retry-after` adds up to 5 s per retry on the path `AWS_NEW_RETRIES_2026` turns on — and a test asks botocore for those constants, so an upgrade that moves them fails. A third attempt would put the worst case at 37 s, past the ECS grace (#62)

### MongoDB Schema

Sessions stored as single documents with embedded data:
```
{
  session_id, application_name, session_viewer_password, created_at, updated_at,
  agents: { agent_id: { agent_data: {model, system_prompt, prompt_metadata?, state}, messages: [...] } },
  metadata: {...},
  feedbacks: [{rating, comment, created_at}],
  guardrail_events: [{message_id, storage_id?, agent_id, action, timestamp, stop_reason?, policies_triggered?}]
}
```

**Note:** `application_name` is a top-level immutable field set at session creation. Use it to categorize sessions by application (e.g., "customer-support-bot", "sales-assistant").

The last message of each invocation that closes carries `event_loop_metrics` with: `accumulated_usage` (tokens, cache), `accumulated_metrics` (latency, TTFB), `cycle_metrics`, `tool_usage`. Intermediate messages (`toolUse`, `toolResult`, the next prompt) carry none. The values accumulate over the life of the `Agent` object, so with the factory (one `Agent` per request) they are that invocation's. An invocation that does not close (a user hook or the conversation manager raising before the closing sync) is left without metrics (#66). Redacted messages may include `guardrail_event` with `action`, `timestamp`, and optionally `stop_reason`, `policies_triggered`, and `trace` (full GuardrailTrace).

Every message also carries a `storage_id` (uuid4 hex), its stable identity: `message_id` is an index Strands derives in memory, so two managers on the same agent can duplicate it. Writes name the message by `storage_id` (`message_identity.MessageRef`); messages stored before v0.12.0 have none and fall back to `message_id` (#78).

Inside `message`, strands 1.56 adds two fields of its own that are persisted verbatim and cost no extra write: `tracking_id` (uuid4, on the messages the SDK itself appends — one appended by application code has none, so `storage_id` is still what identifies a message) and `metadata` with the `usage` and `metrics` of **that cycle**, on each `assistant` message. It is the per-message attribution `event_loop_metrics` cannot give, which is the accumulated total of the invocation. A hook registered with `order=HookOrder.SDK_LAST` runs after the closing sync, so a message it appends is stored **without** metrics — they stay on the message of the cycle they belong to (#69).

## Key Usage Patterns

### Basic Pattern
```python
from mongodb_session_manager import create_mongodb_session_manager

manager = create_mongodb_session_manager(
    session_id="test",
    connection_string="mongodb://...",
    database_name="my_db",
    application_name="my-bot",  # Optional: categorize sessions
)

# Read application_name (immutable, read-only)
app_name = manager.get_application_name()
```

### Factory Pattern (Recommended for FastAPI)
```python
from mongodb_session_manager import initialize_global_factory, get_global_factory

# At startup - set default application_name for all sessions
factory = initialize_global_factory(
    connection_string="mongodb://...",
    application_name="my-fastapi-app",  # Default for all sessions
    maxPoolSize=100,
)

# Per request - uses factory default application_name
manager = get_global_factory().create_session_manager(session_id)

# Or override per session
manager = get_global_factory().create_session_manager(
    session_id,
    application_name="special-app",  # Override factory default
)
```

### Metadata Tool for Agents
```python
metadata_tool = session_manager.get_metadata_tool()
agent = Agent(model="...", tools=[metadata_tool], session_manager=session_manager)
# Agent can now autonomously manage session metadata
```

### Hooks Pattern
```python
def my_hook(original_func, action, session_id, **kwargs):
    # Intercept metadata/feedback operations
    return original_func(kwargs.get("metadata") or kwargs.get("feedback"))


session_manager = MongoDBSessionManager(
    session_id="...",
    metadata_hook=my_hook,  # For metadata operations
    feedback_hook=my_hook,  # For feedback operations
)
```

### AWS SNS Feedback Hook
```python
from mongodb_session_manager import create_feedback_sns_hook

hook = create_feedback_sns_hook(
    topic_arn_good="arn:aws:sns:...:feedback-good",
    topic_arn_bad="arn:aws:sns:...:feedback-bad",
    topic_arn_neutral="arn:aws:sns:...:feedback-neutral",
    subject_prefix_bad="[URGENT] ",  # Template support
)

session_manager = MongoDBSessionManager(
    session_id="...",
    feedback_hook=hook,  # Pass hook to session manager
)
```


### Prompt Metadata
```python
# After sync_agent(), stamp prompt lineage on the agent
manager.set_prompt_metadata(
    "agent-id",
    {
        "prompt_id": "prompt-123",
        "prompt_name": "Customer Support V2",
        "prompt_version": "1.2.0",
        "deployment_id": "deploy-abc",
        "deployment_name": "production",
        "temperature": 0.7,  # optional
    },
)
# Retrieve: manager.get_agent_config("agent-id")["prompt_metadata"]
```


## Version Management

When releasing, update version in **three places**:
1. `src/mongodb_session_manager/__init__.py` (`__version__`)
2. `pyproject.toml` (`version`)
3. `CHANGELOG.md` (add release entry)

Current version: **0.22.0**

## Workflow Rules

- **UV Environment**: All Python commands via `uv run`
- **Documentation Updates**: Update CLAUDE.md, README.md, and docs/ when implementing features
- **Changelog**: Update CHANGELOG.md after validated fixes/features (ask user for confirmation first)
- **Feature Plans**: Save accepted plans to `features/<n>_<short_description>/plan.md`
- **Documentation Index**: See `docs/README.md` for full documentation structure

## Branch Conventions

| Prefijo | Uso | Ejemplo |
|---------|-----|---------|
| `feature/` | Nueva funcionalidad | `feature/user-auth` |
| `fix/` | Corrección de bug | `fix/login-error` |
| `refactor/` | Refactorización | `refactor/api-client` |
| `docs/` | Documentación | `docs/api-readme` |
| `test/` | Añadir tests | `test/user-service` |
| `chore/` | Mantenimiento | `chore/update-deps` |

## Commit Conventions

```
Add:      nueva funcionalidad
Update:   mejora de funcionalidad existente
Fix:      corrección de bug
Refactor: refactorización sin cambio de comportamiento
Docs:     cambios en documentación
Test:     añadir o modificar tests
Chore:    tareas de mantenimiento (deps, config)
```

## Development Philosophy

### SOLID Principles

- **S - Single Responsibility**: Una clase/función debe tener una única razón para cambiar. Si la descripción incluye "Y", hay que separar.
- **O - Open/Closed**: Abierto para extensión, cerrado para modificación. Usar interfaces y estrategias en vez de `if/elif` crecientes.
- **L - Liskov Substitution**: Subtipos deben ser intercambiables por sus tipos base sin romper el contrato.
- **I - Interface Segregation**: Interfaces pequeñas y específicas. No obligar a implementar métodos que no se usan.
- **D - Dependency Inversion**: Depender de abstracciones (Protocol/ABC), no de implementaciones concretas. Inyectar dependencias.

### KISS & YAGNI

- No abstraer prematuramente. Tres líneas similares son mejor que una abstracción prematura.
- No añadir parámetros, configuración o features "por si acaso".
- No optimizar sin métricas que lo justifiquen.
- Soluciones directas y claras sobre patrones sofisticados innecesarios.

### DRY (Rule of Three)

- Abstraer solo cuando la misma lógica se repite **3+ veces**.
- Si la duplicación es **similar pero no idéntica**, mantener separado.

### TDD Workflow

1. **RED**: Escribir test que falla (función/clase no existe aún)
2. **GREEN**: Código mínimo para pasar el test
3. **REFACTOR**: Mejorar estructura sin romper tests

Orden de tests: Happy path > Edge cases > Error cases > Integration

### DDD (Domain-Driven Design)

- Organizar código por dominio de negocio, no por capa técnica
- Usar el lenguaje del negocio en nombres de clases, funciones y variables
- Cada contexto tiene su propio modelo aunque represente el mismo concepto

### Coverage Requirements

| Componente | Mínimo |
|------------|--------|
| Lógica de negocio / Services | 80% |
| Handlers / Controllers | 70% |
| Repository / Data Layer | 60% |
| Utilities / Helpers | 80% |

## Testing

Tests are organized in `tests/unit/` (no MongoDB needed) and `tests/integration/` (requires MongoDB).

```bash
# Unit tests (no MongoDB required)
uv run python -m pytest tests/unit/ -v

# Integration tests (requires MongoDB)
export MONGODB_CONNECTION_STRING="mongodb://<user>:<pass>@localhost:8550/"
uv run python -m pytest tests/integration/ -v

# All tests
uv run python -m pytest tests/ -v
```

**Default credentials for local development:**
- Host: `localhost:8550` (or `host.docker.internal:8550` from Docker)
- User: `mongodb`
- Password: `mongodb`

## Workflow Guidelines

Guias de workflow en `.claude/rules/workflow-*.md`. Ver detalle en cada fichero:

| Guia | Fichero |
|------|---------|
| Planning First | `workflow-planning.md` |
| Parallel Work | `workflow-parallel.md` |
| TDD Discipline | `workflow-tdd.md` |
| TDD Agent Pipeline | `workflow-tdd-pipeline.md` |
| Subagent Strategy | `workflow-subagents.md` |
| Self-Improvement | `workflow-self-improvement.md` |
| Code Review | `workflow-review.md` |
| Multi-model Research | `workflow-research.md` |
| Bug Fixing | `workflow-bugfix.md` |
| Diagrams | `workflow-diagrams.md` |
| Skills & Automation | `workflow-skills.md` |
| Dev Lifecycle | `workflow-dev-lifecycle.md` |
| Frontend First | `workflow-frontend-first.md` |
| Release & Ops | `workflow-release-ops.md` |
| Data Contracts | `workflow-contracts.md` |
| Project Documentation | `workflow-docs.md` |
| Persistence Agnostic | `workflow-persistence.md` |
| Issue-Driven Dev | `workflow-issue-driven.md` |

## Coding Rules

Reglas de programacion en `.claude/rules/coding-*.md`:

| Fichero | Contenido |
|---------|-----------|
| `coding-efficiency.md` | Memoria, pools, profiling |
| `coding-concurrency.md` | Race conditions, async, graceful shutdown |
| `coding-database.md` | Connection pooling, MongoDB, indices |
| `coding-errors.md` | Error handling, context, custom exceptions |
| `coding-testing.md` | pytest, coverage 80%+, regression tests |
| `coding-api-design.md` | REST, paginacion, middleware order |
| `coding-caching.md` | TTL, invalidacion, cache-aside |
| `coding-security.md` | OWASP, secrets, injection, CORS |
| `coding-observability.md` | Structured logging, tracing, metricas |
| `coding-architecture.md` | File limits, DI, docs actualizadas |
| `coding-dependencies.md` | Docs oficiales, version verification |
| `coding-python.md` | Async, Pydantic, ruff, pytest |
| `coding-checklist.md` | Checklist transversal de programacion |

## Spec-Driven Development (Spec Kit)

Workflow: Constitution -> Specify -> Plan -> Tasks -> Implement.

| Comando | Descripcion |
|---------|-------------|
| `/speckit.constitution` | Revisar principios del proyecto |
| `/speckit.specify` | Crear especificacion formal |
| `/speckit.plan` | Generar plan de implementacion |
| `/speckit.tasks` | Descomponer en tareas ejecutables |
| `/speckit.implement` | Implementar siguiendo la spec |

Constitucion en `.specify/memory/constitution.md` (9 articulos: SOLID + TDD + DDD + KISS + YAGNI).

## Agent Teams (Experimental)

| Setting | Valor | Ubicacion |
|---------|-------|-----------|
| Feature flag | `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` | `.claude/settings.local.json` |
| Teammate mode | `auto` | `.claude/settings.json` |

## Project Documentation

Documentacion en `docs/`, navegable con MkDocs Material.

```bash
mkdocs serve            # http://127.0.0.1:8000
```
