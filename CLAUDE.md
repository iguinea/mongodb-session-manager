# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MongoDB Session Manager - A MongoDB session manager library for Strands Agents that provides persistent storage for agent conversations and state, with connection pooling optimized for stateless environments.

**Tech Stack:** Python 3.12+, UV package manager, MongoDB, Strands Agents SDK

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
   - `sync_agent()`: Captures metrics via `agent.event_loop_metrics.get_summary()` including tokens, latency, TTFB, cycle metrics, tool usage
   - `get_metadata_tool()`: Returns Strands tool for agent metadata management
   - Metadata/Feedback hooks for intercepting operations
   - Agent config persistence (model, system_prompt)

2. **MongoDBSessionRepository** (`mongodb_session_repository.py`): Implements `SessionRepository` interface
   - All MongoDB CRUD operations for sessions, agents, messages
   - Smart connection lifecycle (owns vs borrowed client)

3. **MongoDBConnectionPool** (`mongodb_connection_pool.py`): Singleton for connection reuse
   - Thread-safe, configurable pool sizes

4. **MongoDBSessionManagerFactory** (`mongodb_session_factory.py`): Factory for stateless environments
   - Global factory functions: `initialize_global_factory()`, `get_global_factory()`, `close_global_factory()`

5. **Hooks** (`hooks/`): Optional AWS integrations
   - `FeedbackSNSHook`: SNS notifications with configurable templates
   - `MetadataSQSHook`: SQS propagation for SSE
   - `MetadataWebSocketHook`: Real-time WebSocket push

### MongoDB Schema

Sessions stored as single documents with embedded data:
```
{
  session_id, application_name, session_viewer_password, created_at, updated_at,
  agents: { agent_id: { agent_data: {model, system_prompt, prompt_metadata?, state}, messages: [...] } },
  metadata: {...},
  feedbacks: [{rating, comment, created_at}],
  guardrail_events: [{message_id, agent_id, action, timestamp, stop_reason?, policies_triggered?}]
}
```

**Note:** `application_name` is a top-level immutable field set at session creation. Use it to categorize sessions by application (e.g., "customer-support-bot", "sales-assistant").

Messages include `event_loop_metrics` with: `accumulated_usage` (tokens, cache), `accumulated_metrics` (latency, TTFB), `cycle_metrics`, `tool_usage`. Redacted messages may include `guardrail_event` with `action`, `timestamp`, and optionally `stop_reason`, `policies_triggered`, and `trace` (full GuardrailTrace).

## Key Usage Patterns

### Basic Pattern
```python
from mongodb_session_manager import create_mongodb_session_manager

manager = create_mongodb_session_manager(
    session_id="test",
    connection_string="mongodb://...",
    database_name="my_db",
    application_name="my-bot"  # Optional: categorize sessions
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
    maxPoolSize=100
)

# Per request - uses factory default application_name
manager = get_global_factory().create_session_manager(session_id)

# Or override per session
manager = get_global_factory().create_session_manager(
    session_id,
    application_name="special-app"  # Override factory default
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
    metadata_hook=my_hook,    # For metadata operations
    feedback_hook=my_hook     # For feedback operations
)
```

### AWS SNS Feedback Hook
```python
from mongodb_session_manager import create_feedback_sns_hook

hook = create_feedback_sns_hook(
    topic_arn_good="arn:aws:sns:...:feedback-good",
    topic_arn_bad="arn:aws:sns:...:feedback-bad",
    topic_arn_neutral="arn:aws:sns:...:feedback-neutral",
    subject_prefix_bad="[URGENT] "  # Template support
)

session_manager = MongoDBSessionManager(
    session_id="...",
    feedback_hook=hook  # Pass hook to session manager
)
```


### Prompt Metadata
```python
# After sync_agent(), stamp prompt lineage on the agent
manager.set_prompt_metadata("agent-id", {
    "prompt_id": "prompt-123",
    "prompt_name": "Customer Support V2",
    "prompt_version": "1.2.0",
    "deployment_id": "deploy-abc",
    "deployment_name": "production",
    "temperature": 0.7,  # optional
})
# Retrieve: manager.get_agent_config("agent-id")["prompt_metadata"]
```


## Version Management

When releasing, update version in **three places**:
1. `src/mongodb_session_manager/__init__.py` (`__version__`)
2. `pyproject.toml` (`version`)
3. `CHANGELOG.md` (add release entry)

Current version: **0.9.1**

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