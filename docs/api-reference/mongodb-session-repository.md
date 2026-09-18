# MongoDBSessionRepository API Reference

## Overview

`MongoDBSessionRepository` is the low-level MongoDB implementation of the `SessionRepository` interface from the Strands SDK. It handles all database operations for session persistence, including CRUD operations for sessions, agents, and messages.

This class provides:
- Document-based storage with embedded agents and messages
- Smart connection management (owns vs borrows MongoDB client)
- Automatic index creation for optimized queries
- Datetime serialization/deserialization for MongoDB compatibility
- Metadata field indexing with partial updates support
- Thread-safe operations with proper error handling
- Feedback storage and retrieval

**Note**: Most users should use `MongoDBSessionManager` instead of directly using this repository class. The repository is used internally by the session manager.

## Class Definition

```python
class MongoDBSessionRepository(SessionRepository):
    """MongoDB implementation of SessionRepository interface for persistent session storage."""
```

**Inheritance**: `strands.session.session_repository.SessionRepository`

**Module**: `mongodb_session_manager.mongodb_session_repository`

---

## MongoDB Schema

Session documents are stored with the following structure:

```json
{
    "_id": "session-id",
    "session_id": "session-id",
    "session_type": "default",
    "created_at": ISODate("2024-01-26T10:30:45.123Z"),
    "updated_at": ISODate("2024-01-26T10:35:12.456Z"),
    "metadata": {
        "user_name": "Alice",
        "priority": "high",
        "custom_field": "value"
    },
    "feedbacks": [
        {
            "rating": "up",
            "comment": "Great response!",
            "created_at": ISODate("2024-01-26T10:36:00.000Z")
        }
    ],
    "agents": {
        "agent-id-1": {
            "agent_data": {
                "agent_id": "agent-id-1",
                "model": "claude-3-sonnet",
                "system_prompt": "You are a helpful assistant",
                "created_at": "2024-01-26T10:30:45.123456Z",
                "updated_at": "2024-01-26T10:35:12.456789Z"
            },
            "created_at": ISODate("2024-01-26T10:30:45.123Z"),
            "updated_at": ISODate("2024-01-26T10:35:12.456Z"),
            "messages": [
                {
                    "message_id": 1,
                    "storage_id": "9f1c4b2e7a0d4e1fa3c85d6b2e7a0d4e",
                    "role": "user",
                    "content": "Hello!",
                    "created_at": ISODate("2024-01-26T10:30:50.000Z"),
                    "updated_at": ISODate("2024-01-26T10:30:50.000Z")
                },
                {
                    "message_id": 2,
                    "storage_id": "3c5dfcb905834110ba08b3ba92a7a543",
                    "role": "assistant",
                    "content": "Hi! How can I help you?",
                    "created_at": ISODate("2024-01-26T10:30:55.000Z"),
                    "updated_at": ISODate("2024-01-26T10:30:55.000Z"),
                    "event_loop_metrics": {
                        "accumulated_metrics": {
                            "latencyMs": 1234
                        },
                        "accumulated_usage": {
                            "inputTokens": 45,
                            "outputTokens": 78,
                            "totalTokens": 123
                        }
                    }
                }
            ]
        }
    }
}
```

### Indexes

The following indexes are automatically created:
- `created_at`: For chronological queries
- `updated_at`: For finding recently modified sessions
- `metadata.<field>`: For each field in `metadata_fields` parameter

### Names that become paths

The repository reaches each agent as `agents.<agent_id>` and each metadata key as `metadata.<key>`, with dot notation. MongoDB reads those names as syntax, so the repository checks them first and raises `ValueError` **before any round-trip** ([#79](https://github.com/iguinea/mongodb-session-manager/issues/79)). The rule lives in `mongodb_session_manager.field_names`:

- **A segment** is non-empty, does not start with `$` and holds no NUL byte. A `$` anywhere else is plain data: `a$b` works.
- **A path** is segments separated by `.`. Metadata keys (`update_metadata`, `delete_metadata`), `metadata_fields` and the relative keys of `update_message_fields` / `update_agent_fields` are paths: `user.name` is a nested field and `tags.0` an array element.
- **An `agent_id`** is a single segment, so it cannot contain `.` either. With `a.b` the agent landed nested under `agents.a.b`, where no read looks, and every request created it again with an empty history.

A batch is all or nothing: one invalid key and nothing is written. Limits that are not about syntax are not checked here and still come back as server errors, such as `{"a": 1, "a.b": 2}` in the same update (conflicting paths) or more than 100 levels of nesting.

!!! warning "Breaking change in v0.13.0"
    Metadata keys with a segment starting with `$` (`$where`, `x.$y`) used to be stored as literal fields. They are now rejected. Keys already stored stay in the document and `get_metadata()` still returns them, but removing them takes `repo.collection`, since `delete_metadata()` applies the same rule.

---

## Constructor

### `__init__`

```python
def __init__(
    self,
    connection_string: Optional[str] = None,
    database_name: str = "database_name",
    collection_name: str = "collection_name",
    client: Optional[MongoClient] = None,
    metadata_fields: Optional[List[str]] = None,
    **kwargs: Any,
) -> None
```

Initialize MongoDB Session Repository.

#### Parameters

- **connection_string** (`Optional[str]`, default: `None`): MongoDB connection string (e.g., `"mongodb://localhost:27017/"`). Required if `client` is not provided. Ignored if `client` is provided.

- **database_name** (`str`, default: `"database_name"`): Name of the MongoDB database to use.

- **collection_name** (`str`, default: `"collection_name"`): Name of the collection for session documents.

- **client** (`Optional[MongoClient]`, default: `None`): Pre-configured `MongoClient` instance. When provided, the repository will use this client instead of creating a new one. The repository will not close a borrowed client.

- **metadata_fields** (`Optional[List[str]]`, default: `None`): List of metadata field names to index for optimized queries. Each one is a [path](#names-that-become-paths).

- **kwargs** (`Any`): Additional arguments for `MongoClient`. They are only used when the repository creates its own client; with `client` provided they are ignored and logged as a `WARNING` that names them.

#### Raises

- `ValueError`: If a metadata field is not a valid [path](#names-that-become-paths). Checked before any client is created: MongoDB cannot index such a field, and that failure used to be swallowed together with every index created after it, `application_name` included.

#### Connection Lifecycle Management

The repository implements smart connection management:

- **Owned Client** (`_owns_client = True`): When created via `connection_string`, the repository creates and owns the client. It will close the client when `close()` is called.

- **Borrowed Client** (`_owns_client = False`): When an external `client` is provided, the repository borrows it and will NOT close it. The caller is responsible for client lifecycle.

#### Example

```python
from mongodb_session_manager import MongoDBSessionRepository
from pymongo import MongoClient

# Create repository with new connection (owned)
repo = MongoDBSessionRepository(
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    collection_name="sessions",
)
# ... use repository ...
repo.close()  # Closes the connection

# Create repository with existing client (borrowed)
client = MongoClient("mongodb://localhost:27017/", maxPoolSize=100)
repo = MongoDBSessionRepository(
    client=client,  # Borrowed client
    database_name="chat_db",
    collection_name="sessions",
)
# ... use repository ...
repo.close()  # Does NOT close the client
client.close()  # You manage the client

# With metadata field indexing
repo = MongoDBSessionRepository(
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    collection_name="sessions",
    metadata_fields=["priority", "status", "category"],
)

# With custom MongoDB client options
repo = MongoDBSessionRepository(
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    collection_name="sessions",
    maxPoolSize=50,
    minPoolSize=10,
    retryWrites=True,
)
```

---

## Session Operations

### `create_session`

```python
def create_session(self, session: Session, **kwargs: Any) -> Session
```

Create a new session document in MongoDB.

Initializes a new session with empty agents, metadata, and feedbacks arrays. Automatically sets `created_at` and `updated_at` timestamps.

#### Parameters

- **session** (`Session`): The session object to create, containing `session_id` and `session_type`.

- **kwargs** (`Any`): Additional keyword arguments (reserved for future use).

#### Returns

`Session`: The created session object (same as input).

#### Raises

- `PyMongoError`: If the database operation fails (e.g., duplicate session_id).

#### Example

```python
from strands.types.session import Session

# Create a new session
session = Session(session_id="user-123", session_type="chat")

created_session = repo.create_session(session)
print(f"Created session: {created_session.session_id}")
```

### `read_session`

```python
def read_session(self, session_id: str, **kwargs: Any) -> Optional[Session]
```

Read a session header from MongoDB by ID.

The MongoDB query projects exactly `session_id`, `session_type`, `created_at` and
`updated_at`. Embedded agents, messages, metadata, feedback and guardrail events
do not travel over the wire merely to determine whether the session exists and
reconstruct the Strands `Session` object.

#### Parameters

- **session_id** (`str`): Unique identifier of the session to read.

- **kwargs** (`Any`): Additional keyword arguments (reserved for future use).

#### Returns

`Optional[Session]`: The session object if found, `None` otherwise.

#### Raises

- `PyMongoError`: If the database operation fails.

#### Example

```python
# Read existing session
session = repo.read_session("user-123")
if session:
    print(f"Session type: {session.session_type}")
    print(f"Created: {session.created_at}")
    print(f"Updated: {session.updated_at}")
else:
    print("Session not found")
```

---

## Agent Operations

!!! note "Every method that takes an `agent_id` checks it first"
    Agent and message operations raise `ValueError` for an `agent_id` that is not a single [segment](#names-that-become-paths), before any round-trip and before an empty write returns early. `_agent_path()` is the only place that builds `agents.<agent_id>`.

### `create_agent`

```python
def create_agent(
    self, session_id: str, session_agent: SessionAgent, **kwargs: Any
) -> None
```

Create a new agent within a session document.

Adds an agent to the session's `agents` object with empty messages array and timestamps.

#### Parameters

- **session_id** (`str`): ID of the session to add the agent to.

- **session_agent** (`SessionAgent`): The agent object to create.

- **kwargs** (`Any`): Additional keyword arguments (reserved for future use).

#### Raises

- `ValueError`: If the session does not exist.
- `PyMongoError`: If the database operation fails.

#### Example

```python
from strands.types.session import SessionAgent

agent = SessionAgent(
    agent_id="assistant-1",
    model="claude-3-sonnet",
    system_prompt="You are a helpful assistant",
)

repo.create_agent("user-123", agent)
print(f"Created agent: {agent.agent_id}")
```

### `read_agent`

```python
def read_agent(
    self, session_id: str, agent_id: str, **kwargs: Any
) -> Optional[SessionAgent]
```

Read an agent from a session by agent ID without loading its messages.

The query projects `agents.<agent_id>.agent_data`; `list_messages()` is the only
restoration read that transfers the history. The method returns the Strands SDK
fields of `agent_data` (`agent_id`, `state`, `conversation_manager_state`,
`_internal_state` and timestamps). The `model` and `system_prompt` stored next to
them do not fit in a `SessionAgent`: the repository keeps the last ones read for
`MongoDBSessionManager.initialize()`, which uses them to avoid rewriting an
unchanged config. `prompt_metadata` is left out; read it with
`MongoDBSessionManager.get_agent_config()`.

#### Parameters

- **session_id** (`str`): ID of the session containing the agent.

- **agent_id** (`str`): ID of the agent to read.

- **kwargs** (`Any`): Additional keyword arguments (reserved for future use).

#### Returns

`Optional[SessionAgent]`: The agent object if found, `None` otherwise.

#### Raises

- `PyMongoError`: If the database operation fails.

#### Example

```python
agent = repo.read_agent("user-123", "assistant-1")
if agent:
    print(f"Agent ID: {agent.agent_id}")
    print(f"State: {agent.state}")
else:
    print("Agent not found")
```

### `update_agent`

```python
def update_agent(
    self, session_id: str, session_agent: SessionAgent, **kwargs: Any
) -> None
```

Update an existing agent, preserving timestamps and the stored agent config.

Each `SessionAgent` field is written on its own path (`agents.<agent_id>.agent_data.<field>`), so the `model`, `system_prompt` and `prompt_metadata` that the session manager stores in `agent_data` survive the update. Every field is still replaced whole: keys removed from the agent state disappear. The agent's `created_at` is left untouched, and `updated_at` is set to the current time on the agent and at the session root.

**An unchanged agent is not written** ([#67](https://github.com/iguinea/mongodb-session-manager/issues/67)). The repository remembers the content of every agent it reads (`read_agent`), creates (`create_agent`) or successfully updates, for the last session it touched (one repository per session manager, as the factory builds them, never needs more). When `update_agent` receives an agent whose fields, `created_at` and `updated_at` aside, are equal to that content, it returns without a round-trip: nothing in the document changes, no `updated_at` is refreshed, and a missing session is not reported. Strands sends exactly that on the first sync of every session manager and after every tool run, where it bumps the interrupt state's version without changing its content; in the reference turn (supervisor, sub-agent and one tool) it saves 3 of 13 writes.

The comparison is on content, not on versions, so no change is lost however the agent got there: `agent.state.set()`, a hook that replaces `agent.state` whole, or a conversation manager that migrates its state on restore are all written. Fields a newer Strands adds are compared too. What the repository cannot see is a write that did not go through it — another process, or `update_agent_fields` on an SDK field — and an agent that has not changed will not overwrite it. A write that raises or matches no session is not remembered, so the next sync retries it.

#### Parameters

- **session_id** (`str`): ID of the session containing the agent.

- **session_agent** (`SessionAgent`): The agent object with updated data.

- **kwargs** (`Any`): Additional keyword arguments (reserved for future use).

#### Raises

- `ValueError`: If the session does not exist and the agent has changed.
- `PyMongoError`: If the database operation fails.

#### Example

```python
# Read agent
agent = repo.read_agent("user-123", "assistant-1")

# Modify agent data
agent.system_prompt = "You are an expert coding assistant"

# Update in database
repo.update_agent("user-123", agent)
```

---

### `update_agent_fields`

```python
def update_agent_fields(
    self, session_id: str, agent_id: str, set_operations: Mapping[str, Any]
) -> bool
```

Write fields under `agents.<agent_id>` without touching its messages.

The non-positional sibling of [`update_message_fields`](#update_message_fields): the filter names the session and requires `agents.<agent_id>` to exist, but does not require a message. Used when there is no message to point at — for instance the first sync of an agent that has not appended anything yet. The `$exists` guard prevents MongoDB's dotted `$set` from creating a half-built agent when the ID is unknown (#119).

#### Parameters

- **session_id** (`str`): ID of the session.

- **agent_id** (`str`): ID of the agent.

- **set_operations** (`Mapping[str, Any]`): Keys **relative to the agent document**, such as `"agent_data.model"`. The repository prefixes them; callers never write `agents.<id>.` themselves. Each key is a [path](#names-that-become-paths).

#### Returns

`bool`: `True` when the session and the agent were found. An empty `set_operations` returns `False` without a round-trip.

#### Raises

- `ValueError`: If the `agent_id` or a key is not a valid name, even when `set_operations` is empty.

#### Example

```python
repo.update_agent_fields(
    "user-123", "assistant-1", {"agent_data.model": "claude-opus-5"}
)
```

### `get_agent_config`

```python
def get_agent_config(self, session_id: str, agent_id: str) -> dict[str, Any] | None
```

Read the stored configuration of one agent: `agent_id`, `model`, `system_prompt` and `prompt_metadata`. Returns `None` when the session or the agent does not exist.

Projects only `agent_data`, so it never drags the agent's message history over the wire. Unlike [`pop_read_agent_config`](#pop_read_agent_config), this is a standalone read that consumes nothing.

### `list_agent_configs`

```python
def list_agent_configs(self, session_id: str) -> list[dict[str, Any]]
```

Same shape as `get_agent_config`, one entry per agent in the session. Returns `[]` when the session has no agents.

The server converts the dynamic `agents` document with `$objectToArray` and
`$map`. Only `agent_id`, `model`, `system_prompt` and `prompt_metadata` cross the
wire; message arrays and agent state do not.

## Message Operations

### Message identity

`message_id` is an *index*, not an identity: Strands derives it in memory
(`RepositorySessionManager.append_message`: `latest.message_id + 1`) and each manager
restores its counter from the last stored message. Two managers restoring the same agent at
once compute the same index, so the array can hold two messages numbered alike — and
MongoDB's positional operator updates the first one that matches, which is how a redaction
used to land on the wrong message ([issue #78](https://github.com/iguinea/mongodb-session-manager/issues/78)).

Since v0.12.0 every message carries a `storage_id`: a uuid4 written once by
`create_message()`, never derived, never rewritten. Writes name a message with a
`MessageRef`:

```python
from mongodb_session_manager import MessageRef

MessageRef(message_id=7, storage_id="9f1c...")  # names one message
MessageRef(message_id=7)  # pre-v0.12.0 message: located by index
```

You rarely build one by hand. The identity travels on the `SessionMessage` — attached by
`create_message()`, `read_message()` and `list_messages()` — and
`get_last_message_ref()` returns it ready to use.

!!! info "No migration needed"
    Messages stored before v0.12.0 have no `storage_id` and keep being located by
    `message_id`, exactly as they always were. The exposure of #78 ends for each
    conversation as its agents append new messages.

### `create_message`

```python
def create_message(
    self,
    session_id: str,
    agent_id: str,
    session_message: SessionMessage,
    **kwargs: Any,
) -> None
```

Create a new message for an agent.

Appends a message to the agent's messages array with automatic timestamps and a
`storage_id`: the message's stable identity, a uuid4 that does not come from its index.
The same value is attached to the `SessionMessage` passed in, which Strands keeps for the
rest of the turn and hands back for the redaction — that is what lets later writes name
*this* message. See [Message identity](#message-identity).

#### Parameters

- **session_id** (`str`): ID of the session.

- **agent_id** (`str`): ID of the agent receiving the message.

- **session_message** (`SessionMessage`): The message to create.

- **kwargs** (`Any`): Additional keyword arguments (reserved for future use).

#### Raises

- `ValueError`: If the session does not exist.
- `PyMongoError`: If the database operation fails.

#### Example

```python
from strands.types.session import SessionMessage

# Create user message
user_msg = SessionMessage(message_id=1, role="user", content="Hello, how are you?")
repo.create_message("user-123", "assistant-1", user_msg)

# Create assistant message
assistant_msg = SessionMessage(
    message_id=2, role="assistant", content="I'm doing well, thank you!"
)
repo.create_message("user-123", "assistant-1", assistant_msg)
```

### `create_messages`

```python
def create_messages(
    self,
    session_id: str,
    agent_id: str,
    session_messages: Sequence[SessionMessage],
    fields_on_last: Mapping[str, Any] | None = None,
    agent_set_operations: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> None
```

Append several messages to an agent, in order, in a **single write**.

The sibling of `create_message()` for a whole batch — in fact `create_message()`
is this method with a list of one. `$each` preserves the order of the list and
the array only ever grows at its end, so a batch is indistinguishable from the
same messages pushed one by one, except in the number of round-trips. On
DocumentDB each of those costs 40-55 ms regardless of its size, which is why the
session manager groups the messages of an invocation
([issue #53](https://github.com/iguinea/mongodb-session-manager/issues/53)).

Every message is born with its own `storage_id`, attached back onto the
`SessionMessage` passed in, exactly as in `create_message()`.

#### Parameters

- **session_id** (`str`): ID of the session.

- **agent_id** (`str`): ID of the agent receiving the messages.

- **session_messages** (`Sequence[SessionMessage]`): The messages, in
  conversation order. An empty sequence writes nothing.

- **fields_on_last** (`Mapping[str, Any] | None`): Fields to store on the last
  message of the batch, as dot-notation keys relative to its document
  (`"event_loop_metrics.cycle_metrics"`). They are nested into the document
  before it is pushed, because `$set` cannot reach a message the same write is
  creating. This is how the metrics of an invocation cost no write of their own.

- **agent_set_operations** (`Mapping[str, Any] | None`): Keys relative to the
  agent document (`"agent_data.model"`), to land in the same round-trip.

#### Raises

- `ValueError`: If the session does not exist, or if the `agent_id` or a field
  key would be parsed as MongoDB syntax. Names are checked before the early
  return for an empty batch.
- `PyMongoError`: If the database operation fails.

#### Example

```python
repo.create_messages(
    "user-123",
    "assistant-1",
    [tool_use_msg, tool_result_msg, answer_msg],
    fields_on_last={
        "event_loop_metrics.accumulated_usage": {"totalTokens": 1280},
    },
)
```

### `read_message`

```python
def read_message(
    self, session_id: str, agent_id: str, message_id: int, **kwargs: Any
) -> Optional[SessionMessage]
```

Read the first message with this `message_id`.

MongoDB searches the embedded array with `$filter` and returns at most one
element with `$arrayElemAt`; the rest of the history does not cross the wire.
The first physical match is deliberate because concurrent managers can produce
duplicate `message_id` values. `event_loop_metrics` and other repository-only
fields are filtered out before returning the `SessionMessage`.

`$elemMatch` projection is not used: MongoDB rejects it on the nested path
`agents.<id>.messages` with error 31275.

#### Parameters

- **session_id** (`str`): ID of the session.

- **agent_id** (`str`): ID of the agent.

- **message_id** (`int`): ID of the message to read.

- **kwargs** (`Any`): Additional keyword arguments (reserved for future use).

#### Returns

`Optional[SessionMessage]`: The message object if found, `None` otherwise.

#### Raises

- `PyMongoError`: If the database operation fails.

#### Example

```python
message = repo.read_message("user-123", "assistant-1", message_id=2)
if message:
    print(f"Role: {message.role}")
    print(f"Content: {message.content}")
    # Note: event_loop_metrics are not included in SessionMessage
else:
    print("Message not found")
```

### `update_message`

```python
def update_message(
    self,
    session_id: str,
    agent_id: str,
    session_message: SessionMessage,
    **kwargs: Any,
) -> None
```

Update a message (typically for redaction).

The message is located by its identity with MongoDB's positional operator (`$`), so the method performs **a single write and no reads**. The identity comes from the `SessionMessage` itself — `create_message()` and the read methods attach it — so a redaction lands on the message this process appended even if another manager appended one with the same `message_id`.

Only `message`, `redact_message` and `updated_at` are written, each on its own path. Fields that the session manager stores on the message but `SessionMessage` does not carry — `event_loop_metrics`, `guardrail_event` and the legacy counters — are **preserved**. `created_at` is never named, so it keeps its original value and type.

!!! note "`message_id` is not a unique key"
    Strands derives it in memory, so two concurrent session managers on the same agent can produce duplicates. Since v0.12.0 the selector uses `storage_id` instead ([issue #78](https://github.com/iguinea/mongodb-session-manager/issues/78)). A message stored before that has no `storage_id` and is still located by `message_id`, where a duplicate matches its **first** occurrence only.

#### Parameters

- **session_id** (`str`): ID of the session.

- **agent_id** (`str`): ID of the agent.

- **session_message** (`SessionMessage`): The message with updated content.

- **kwargs** (`Any`): Additional keyword arguments (reserved for future use).

#### Raises

- `ValueError`: If the session, agent, or message is not found.
- `PyMongoError`: If the database operation fails.

#### Example

```python
# Read message
message = repo.read_message("user-123", "assistant-1", message_id=2)

# Redact it: to_message() returns redact_message when it is set
message.redact_message = {
    "role": "user",
    "content": [{"text": "[Content removed for privacy]"}],
}

# Update in database (metrics and guardrail_event are preserved)
repo.update_message("user-123", "assistant-1", message)
```

### `update_message_fields`

```python
def update_message_fields(
    self,
    session_id: str,
    agent_id: str,
    ref: MessageRef,
    set_operations: Mapping[str, Any],
    agent_set_operations: Mapping[str, Any] | None = None,
) -> bool
```

Write fields on one message — and optionally on its agent — in a **single write**.

This is the public face of the only method in the project that builds the positional selector. `update_message()` and `record_guardrail_event()` go through the same primitive, so [message identity](#message-identity) lives in one place.

#### Parameters

- **session_id** (`str`): ID of the session.

- **agent_id** (`str`): ID of the agent.

- **ref** (`MessageRef`): Message to locate, server-side, with the positional operator. Comes from the message itself — `get_last_message_ref()` or the `SessionMessage` — so a caller cannot name a message by index and lose its identity on the way.

- **set_operations** (`Mapping[str, Any]`): Keys **relative to the message document**, such as `"event_loop_metrics.cycle_metrics"`.

- **agent_set_operations** (`Mapping[str, Any] | None`): Keys relative to the agent document. They travel in the **same round-trip**: on DocumentDB every write costs 40-55 ms regardless of size, so what drives latency is the number of round-trips, not the bytes.

!!! note "This method never moves the session clock"
    Refreshing `updated_at` is a decision of the private primitive, not of its callers: a redaction is a visible change to the session, but annotating a turn that already happened is not, and moving the clock for it would misreport session duration to its consumers.

#### Returns

`bool`: `True` when the filter matched a document. A no-match is **not** an error here — `update_message()` turns it into a `ValueError`, the agent sync logs it, and the guardrail event ignores it.

#### Raises

- `ValueError`: If the `agent_id` or a key of either mapping is not a valid [name](#names-that-become-paths). Nothing is written.

#### Example

```python
# None when the agent has no messages yet, so there is nowhere to write.
ref = repo.get_last_message_ref("user-123", "assistant-1")
if ref is not None:
    repo.update_message_fields(
        "user-123",
        "assistant-1",
        ref,
        set_operations={"event_loop_metrics.accumulated_usage": {"totalTokens": 900}},
        agent_set_operations={"agent_data.model": "claude-opus-5"},
    )
```

### `record_guardrail_event`

```python
def record_guardrail_event(
    self, session_id: str, agent_id: str, ref: MessageRef, event: Mapping[str, Any]
) -> bool
```

Record a guardrail intervention on its message **and** on the session, in a single write.

Only the message-level event is passed in. The session-level entry is *derived* from it: the same fields, plus `message_id`, `storage_id` and `agent_id`, minus the full `trace`. The identity travels with the index because `message_id` alone would point an auditor at two messages when it is duplicated. The session array is read whole to audit a session and grows with every intervention, so the `GuardrailTrace` stays on the message, where it is read only when someone opens that message.

#### Returns

`bool`: `True` when the message was found.

### `count_messages`

```python
def count_messages(self, session_id: str, agent_id: str) -> int
```

Count the messages stored for one agent. Returns `0` when the agent is unknown.

The count is computed by MongoDB with `$size` and `$ifNull`; the message array is
not returned to Python. A missing session, agent, or `messages` field yields 0.

### `get_last_message_ref`

```python
def get_last_message_ref(self, session_id: str, agent_id: str) -> MessageRef | None
```

Reference the agent's last message, or `None` when it has none.

Projects with `$slice: -1`, so only the last message travels over the wire. The session manager prefers the reference carried by the message it has in memory and falls back here only for a session restored in another process.

!!! warning "Breaking change in v0.12.0"
    Replaces `get_last_message_id()`, which returned a bare `int`. The reference carries the `storage_id` too, so a write built from it names a message rather than an index.

### `list_messages`

```python
def list_messages(
    self,
    session_id: str,
    agent_id: str,
    limit: Optional[int] = None,
    offset: int = 0,
    **kwargs: Any,
) -> list[SessionMessage]
```

List messages from an agent with server-side pagination.

MongoDB orders messages chronologically before applying `offset` and `limit`, so
the response size is proportional to the requested page. Ordering is stable:
the physical array index breaks equal timestamps, and messages whose
`created_at` is null or absent come last. This preserves the previous Python
sort semantics even when physical append order differs from chronological
order. `event_loop_metrics` are filtered out from returned messages.

A direct `$slice` is intentionally not used because it would paginate physical
array order before sorting and could return a different page.

The page is requested in a single cursor batch, so draining it costs one
`aggregate` and no `getMore`. The default batch of 101 documents applies to every
batch on DocumentDB, which made a 5,000-message restoration cost 49 extra
round-trips; the batch negotiated here is larger than any page a 16 MiB document
can hold. See
[Draining the history in one batch](../architecture/performance.md#draining-the-history-in-one-batch).

#### Parameters

- **session_id** (`str`): ID of the session.

- **agent_id** (`str`): ID of the agent.

- **limit** (`Optional[int]`, default: `None`): Maximum number of messages to return. If `None`, returns all messages. Must be non-negative.

- **offset** (`int`, default: `0`): Number of messages to skip (for pagination). Must be non-negative.

- **kwargs** (`Any`): Additional keyword arguments (reserved for future use).

#### Returns

`list[SessionMessage]`: List of messages in chronological order (oldest first).

#### Raises

- `ValueError`: If `limit` or `offset` is negative.
- `PyMongoError`: If the database operation fails.

#### Example

```python
# Get all messages
all_messages = repo.list_messages("user-123", "assistant-1")
print(f"Total messages: {len(all_messages)}")

# Get first 10 messages
first_page = repo.list_messages("user-123", "assistant-1", limit=10)

# Get next 10 messages (pagination)
second_page = repo.list_messages("user-123", "assistant-1", limit=10, offset=10)

# Print conversation
for msg in all_messages:
    print(f"{msg.role}: {msg.content}")
```

---

## Metadata Operations

### `update_metadata`

```python
def update_metadata(self, session_id: str, metadata: Dict[str, Any]) -> None
```

Update session metadata with partial updates.

Updates only the specified metadata fields while preserving all other existing fields. This is implemented using MongoDB's `$set` operator with dot notation.

#### Parameters

- **session_id** (`str`): ID of the session to update.

- **metadata** (`Dict[str, Any]`): Dictionary of metadata fields to update. Each key is a [path](#names-that-become-paths): `{"user.name": "Ana"}` writes the nested field and keeps its siblings.

#### Raises

- `ValueError`: If any key has an empty segment, a segment starting with `$` or a NUL byte. The whole dictionary is checked first, so nothing is written.
- `ValueError`: If the session does not exist.
- `PyMongoError`: If the database operation fails.

#### Example

```python
# Initial metadata
repo.update_metadata(
    "user-123", {"user_name": "Alice", "priority": "high", "category": "support"}
)

# Partial update - only changes priority
repo.update_metadata("user-123", {"priority": "low"})
# Result: user_name="Alice", priority="low", category="support"

# Add new fields
repo.update_metadata(
    "user-123", {"status": "active", "last_interaction": "2024-01-26T10:30:00"}
)
```

### `get_metadata`

```python
def get_metadata(self, session_id: str) -> Dict[str, Any]
```

Get metadata for a session.

Retrieves the complete metadata document for the session.

#### Parameters

- **session_id** (`str`): ID of the session.

#### Returns

`Dict[str, Any]`: Dictionary with a `"metadata"` key containing the metadata fields. Returns empty dict with metadata key if session exists but has no metadata.

#### Example

```python
metadata_doc = repo.get_metadata("user-123")
if metadata_doc and "metadata" in metadata_doc:
    metadata = metadata_doc["metadata"]
    print(f"User: {metadata.get('user_name')}")
    print(f"Priority: {metadata.get('priority')}")
```

### `delete_metadata`

```python
def delete_metadata(self, session_id: str, metadata_keys: List[str]) -> None
```

Delete specific metadata fields from a session.

Removes the specified metadata fields using MongoDB's `$unset` operator while preserving other fields.

#### Parameters

- **session_id** (`str`): ID of the session.

- **metadata_keys** (`List[str]`): List of metadata field names to delete. Each one is a [path](#names-that-become-paths).

#### Raises

- `ValueError`: Under the same rule as `update_metadata`, before anything is removed.
- `ValueError`: If the session does not exist.
- `PyMongoError`: If the database operation fails.

#### Example

```python
# Delete sensitive or temporary fields
repo.delete_metadata("user-123", ["temp_token", "session_secret"])

# Verify deletion
metadata_doc = repo.get_metadata("user-123")
# temp_token and session_secret are no longer in metadata
```

---

## Feedback Operations

### `add_feedback`

```python
def add_feedback(self, session_id: str, feedback: Dict[str, Any]) -> None
```

Add feedback to a session.

Appends a feedback entry to the session's feedbacks array with an automatic `created_at` timestamp.

#### Parameters

- **session_id** (`str`): ID of the session.

- **feedback** (`Dict[str, Any]`): Feedback dictionary (typically containing `rating` and `comment`).

#### Raises

- `ValueError`: If the session does not exist.
- `PyMongoError`: If the database operation fails.

#### Example

```python
# Add positive feedback
repo.add_feedback("user-123", {"rating": "up", "comment": "Great response!"})

# Add negative feedback with custom fields
repo.add_feedback(
    "user-123",
    {
        "rating": "down",
        "comment": "Too slow",
        "category": "performance",
        "user_id": "alice",
    },
)
```

### `get_feedbacks`

```python
def get_feedbacks(self, session_id: str) -> List[Dict[str, Any]]
```

Get all feedback entries for a session.

Retrieves all feedback that has been added to the session.

#### Parameters

- **session_id** (`str`): ID of the session.

#### Returns

`List[Dict[str, Any]]`: List of feedback dictionaries with `created_at` timestamps. Returns empty list if no feedback exists or session doesn't exist.

#### Raises

- `PyMongoError`: If the database operation fails.

#### Example

```python
feedbacks = repo.get_feedbacks("user-123")
print(f"Total feedback: {len(feedbacks)}")

for fb in feedbacks:
    print(f"Rating: {fb['rating']}")
    print(f"Comment: {fb.get('comment', 'No comment')}")
    print(f"Submitted: {fb['created_at']}")
```

---

## Resource Management

### `close`

```python
def close(self) -> None
```

Close the MongoDB connection.

Only closes the connection if it was created by this repository (owned client). If an external client was provided during initialization, the connection is not closed.

#### Example

```python
# With owned connection
repo = MongoDBSessionRepository(
    connection_string="mongodb://localhost:27017/", database_name="chat_db"
)
# ... use repository ...
repo.close()  # Closes connection

# With borrowed connection
client = MongoClient("mongodb://localhost:27017/")
repo = MongoDBSessionRepository(client=client, database_name="chat_db")
# ... use repository ...
repo.close()  # Does NOT close connection
client.close()  # You must close it yourself
```

---

## Internal Methods

### `_ensure_indexes`

```python
def _ensure_indexes(self) -> None
```

Ensure necessary indexes exist on the collection.

This method is called automatically during initialization. It creates indexes on:
- `created_at`
- `updated_at`
- `metadata.<field>` for each field in `metadata_fields`

Errors during index creation are logged but do not raise exceptions.

### `pop_read_agent_config`

```python
def pop_read_agent_config(
    self, session_id: str, agent_id: str
) -> dict[str, Any] | None
```

Return, and forget, the `model` and `system_prompt` found by the last `read_agent()` for this session and agent.

`MongoDBSessionManager.initialize()` calls it right after the Strands SDK restores an agent, to learn which config is already persisted without a second read. Only the last read is kept, so a long-lived repository does not accumulate system prompts. The narrow `read_agent()` projection includes all of `agent_data`, and therefore keeps `model` and `system_prompt` while excluding the sibling `messages` array.

It is public because the manager calls it: any repository passed as `session_repository=` has to provide it, or `initialize()` raises `AttributeError`.

---

## Complete Usage Example

```python
from mongodb_session_manager import MongoDBSessionRepository
from strands.types.session import Session, SessionAgent, SessionMessage
from pymongo import MongoClient

# Create repository with connection pooling
client = MongoClient("mongodb://localhost:27017/", maxPoolSize=50)
repo = MongoDBSessionRepository(
    client=client,
    database_name="chat_db",
    collection_name="sessions",
    metadata_fields=["priority", "status"],
)

# Create a new session
session = Session(session_id="user-123", session_type="chat")
repo.create_session(session)

# Set metadata
repo.update_metadata("user-123", {"user_name": "Alice", "priority": "high"})

# Create an agent
agent = SessionAgent(
    agent_id="assistant-1",
    model="claude-3-sonnet",
    system_prompt="You are a helpful assistant",
)
repo.create_agent("user-123", agent)

# Add messages
user_msg = SessionMessage(message_id=1, role="user", content="Hello!")
repo.create_message("user-123", "assistant-1", user_msg)

assistant_msg = SessionMessage(
    message_id=2, role="assistant", content="Hi! How can I help?"
)
repo.create_message("user-123", "assistant-1", assistant_msg)

# Add feedback
repo.add_feedback("user-123", {"rating": "up", "comment": "Great service!"})

# Retrieve data
messages = repo.list_messages("user-123", "assistant-1")
metadata = repo.get_metadata("user-123")
feedbacks = repo.get_feedbacks("user-123")

print(f"Messages: {len(messages)}")
print(f"Metadata: {metadata}")
print(f"Feedbacks: {len(feedbacks)}")

# Clean up (repository doesn't close borrowed client)
repo.close()
client.close()
```

---

## Thread Safety

The repository is thread-safe when used with MongoDB's connection pool. Multiple threads can safely share the same repository instance as long as the underlying MongoDB client is properly configured with connection pooling.

```python
from concurrent.futures import ThreadPoolExecutor
from pymongo import MongoClient

# Create shared client with pool
client = MongoClient("mongodb://localhost:27017/", maxPoolSize=100)

# Create shared repository
repo = MongoDBSessionRepository(client=client, database_name="chat_db")


# Safe to use from multiple threads
def process_session(session_id):
    session = repo.read_session(session_id)
    # ... process session ...


with ThreadPoolExecutor(max_workers=10) as executor:
    session_ids = ["user-1", "user-2", "user-3"]
    executor.map(process_session, session_ids)
```

---

## Performance Considerations

1. **Index Usage**: Ensure `metadata_fields` includes frequently queried fields for optimal performance.

2. **Connection Pooling**: Always use connection pooling for production deployments.

3. **Batch Operations**: For bulk operations, consider using MongoDB's bulk write APIs (not currently exposed by this class).

4. **Message Pagination**: Use `limit` and `offset` when dealing with large message arrays to avoid loading too much data.

5. **Document Size**: MongoDB has a 16MB document size limit. Sessions with very large message histories may need to be archived periodically.

---

## See Also

- [MongoDBSessionManager](./mongodb-session-manager.md) - High-level session manager (recommended for most use cases)
- [MongoDBConnectionPool](./mongodb-connection-pool.md) - Connection pool singleton
- [MongoDBSessionManagerFactory](./mongodb-session-factory.md) - Factory for efficient session manager creation
- [User Guide - Session Persistence](../user-guide/session-persistence.md)
