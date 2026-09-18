# MongoDBSessionManager API Reference

## Overview

`MongoDBSessionManager` is the primary interface for managing persistent agent sessions with MongoDB storage. It extends `RepositorySessionManager` from the Strands SDK to provide MongoDB-specific functionality with automatic metrics tracking, metadata management, and feedback collection.

This class serves as the high-level API for session persistence, providing features like:
- Persistent storage of agent conversations and state
- Automatic capture of event loop metrics (tokens, latency)
- Partial metadata updates that preserve existing fields
- Built-in metadata tool for agent integration
- Feedback system for user ratings and comments
- Hook system for intercepting metadata and feedback operations
- Smart connection management with support for connection pooling

## Class Definition

```python
class MongoDBSessionManager(RepositorySessionManager):
    """MongoDB Session Manager for Strands Agents with comprehensive session persistence."""
```

**Inheritance**: `strands.session.repository_session_manager.RepositorySessionManager`

**Module**: `mongodb_session_manager.mongodb_session_manager`

---

## Constructor

### `__init__`

```python
def __init__(
    self,
    session_id: str,
    connection_string: Optional[str] = None,
    database_name: str = "database_name",
    collection_name: str = "collection_name",
    client: Optional[MongoClient] = None,
    metadata_fields: Optional[List[str]] = None,
    metadata_hook: Optional[Callable[..., Any]] = None,
    feedback_hook: Optional[Callable[..., Any]] = None,
    application_name: Optional[str] = None,
    session_repository: Optional[Any] = None,
    **kwargs: Any,
) -> None
```

Initialize MongoDB Session Manager with connection details and configuration.

#### Parameters

- **session_id** (`str`, required): Unique identifier for the session. This ID is used to store and retrieve session data from MongoDB.

- **connection_string** (`Optional[str]`, default: `None`): MongoDB connection string (e.g., `"mongodb://localhost:27017/"`). Ignored if `client` parameter is provided. Required if `client` is not provided.

- **database_name** (`str`, default: `"database_name"`): Name of the MongoDB database to use for session storage.

- **collection_name** (`str`, default: `"collection_name"`): Name of the MongoDB collection where session documents will be stored.

- **client** (`Optional[MongoClient]`, default: `None`): Pre-configured `MongoClient` instance for connection reuse. When provided, the session manager will use this client instead of creating a new one. The session manager will not close a borrowed client.

- **metadata_fields** (`Optional[List[str]]`, default: `None`): List of metadata field names to be indexed in MongoDB for optimized queries. These fields will have indexes created automatically.

- **metadata_hook** (`Optional[Callable]`, default: `None`): Hook function to intercept metadata operations (update, get, delete). See [Hooks](#metadata-hooks) section for details.

- **feedback_hook** (`Optional[Callable]`, default: `None`): Hook function to intercept feedback operations (add). See [Hooks](#feedback-hooks) section for details.

- **application_name** (`Optional[str]`, default: `None`): Application name used to categorise sessions. Immutable: it is written when the session is created and read back with `get_application_name()`.

- **session_repository** (`Optional[Any]`, default: `None`): Repository to store sessions in. Defaults to a `MongoDBSessionRepository` built from the arguments above. Its purpose is to seat a test double, so the manager can be exercised without MongoDB — see [Testing](../development/testing.md#testing-without-mongodb-the-in-memory-repository). When provided, the MongoDB-specific arguments are ignored.

    !!! warning "Not a declared extension point"
        The expected contract is not published as a `Protocol`; it is the union of the Strands `SessionRepository` interface and the custom methods this repository adds, and it is only written down as executable cases in `tests/support/repository_contract.py`. Substituting another store is possible but unsupported: the contract can change in a minor release.

- **kwargs** (`Any`): MongoDB client options, passed to `MongoClient`. See below.

#### MongoDB Client Options

Any keyword option `MongoClient` accepts can be passed via `kwargs`: `maxPoolSize`, `readPreference`, `appname`, `tls`, `tlsCAFile`, `retryWrites` and the rest of [pymongo's options](https://pymongo.readthedocs.io/en/stable/api/pymongo/mongo_client.html). As in pymongo, the case of the name does not matter. pymongo validates the values, so an invalid one raises when the manager is built.

They apply when the manager creates its own client, from `connection_string`. Nothing passed here is dropped silently ([issue #111](https://github.com/iguinea/mongodb-session-manager/issues/111)). Each of these cases logs a `WARNING` that names the argument:

| Case | What happens |
|---|---|
| `client=` was given, as the factory does | The options are ignored. Configure them where that client is created: `initialize_global_factory()` or `MongoDBConnectionPool.initialize()` |
| `session_repository=` was injected | The options are ignored: there is no client to apply them to |
| The name is not a `MongoClient` option (a typo such as `metadata_hooks=`) | The argument is ignored |

Before 1.0.0 only sixteen option names reached the client; any other, `tls` and `readPreference` included, was dropped without a warning.

#### Example

```python
from mongodb_session_manager import MongoDBSessionManager

# Basic usage with new connection
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    collection_name="sessions",
)

# With connection pooling and custom options
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    collection_name="sessions",
    maxPoolSize=50,
    minPoolSize=5,
    retryWrites=True,
)

# With existing client (recommended for FastAPI)
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017/", maxPoolSize=100)

manager = MongoDBSessionManager(
    session_id="user-123",
    client=client,  # Reuse existing connection
    database_name="chat_db",
    collection_name="sessions",
)

# With metadata indexing
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    metadata_fields=["priority", "status", "category"],
)


# With hooks for audit and notifications.
# The hook receives the argument under its own name (metadata= on update,
# keys= on delete), which is not the parameter name of the wrapped method
# (delete_metadata(metadata_keys)), so pass it on positionally.
def audit_metadata(original_func, action, session_id, **kwargs):
    logger.info(f"Metadata {action} on {session_id}")
    if action == "update":
        return original_func(kwargs["metadata"])
    if action == "delete":
        return original_func(kwargs["keys"])
    return original_func()  # get


def notify_feedback(original_func, action, session_id, **kwargs):
    result = original_func(kwargs["feedback"])
    send_notification(session_id, kwargs["feedback"])
    return result


manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    metadata_hook=audit_metadata,
    feedback_hook=notify_feedback,
)
```

---

## Session Message Methods

### `append_message`

```python
def append_message(self, message: Message, agent: LocalAgent, **kwargs: Any) -> None
```

Persist a message of the agent's conversation.

**You do not call it yourself.** When an `Agent` is created with `session_manager=...`, Strands calls it for every message added to `agent.messages` (`MessageAddedEvent`): the prompt, each `toolUse` and `toolResult`, and the answer. Calling it by hand for an agent wired that way stores the message twice.

When a message reaches MongoDB depends on what it is:

| Message | Written |
|---|---|
| The prompt that opens an invocation (a `user` message with no `toolResult`) | Immediately, as it arrives: nothing can produce it again |
| What the event loop produces (`toolUse`, `toolResult`, the answer) | In the write that closes the invocation (`AfterInvocationEvent`): one `$push` with `$each` for the whole batch, with the invocation's `event_loop_metrics` inside the last message |
| A message appended outside an invocation | Immediately, since nothing is bound to flush it later |

`AfterInvocationEvent` fires from a `finally` in the SDK, so an invocation that raises still writes its batch. A batch whose write fails is not retried (the write may have been applied, and pushing it again would duplicate the turn); `close()` writes a batch whose invocation never closed ([issue #53](https://github.com/iguinea/mongodb-session-manager/issues/53)).

Each message is stored with the `message_id` Strands assigns (the previous one plus one) and a `storage_id` of its own, which is what later writes use to find it.

#### Parameters

- **message** (`Message`): The message added to the agent.

- **agent** (`LocalAgent`): The agent the message belongs to.

#### Example

```python
from strands import Agent

agent = Agent(model="claude-3-sonnet", session_manager=manager)

# The prompt is written as it arrives; the answer, with the metrics, in the
# write that closes the invocation.
agent("Hello, how are you?")

# 2 on a new session with no tool calls
print(manager.get_message_count(agent.agent_id))
```

### `redact_latest_message`

```python
def redact_latest_message(
    self, redact_message: Message, agent: Agent, **kwargs: Any
) -> None
```

Redact the latest message and record a guardrail event for auditing.

**NEW in v0.6.0**: This method now automatically records guardrail intervention events at both the message level (`guardrail_event` field) and the session level (`guardrail_events[]` array). This provides a complete audit trail of content moderation actions.

#### Parameters

- **redact_message** (`Message`): The redacted version of the message with updated content.

- **agent** (`Agent`): The Strands Agent instance whose message should be redacted.

- **kwargs** (`Any`): Additional keyword arguments:
  - **action** (`str`, default: `"BLOCKED"`): The guardrail action to record. Use the `GUARDRAIL_ACTION_BLOCKED` constant or any custom string (e.g., `"ANONYMIZED"`, `"FILTERED"`).
  - **stop_reason** (`str`, optional): Stored on the event when given (e.g., `"guardrail_intervened"`).
  - **guardrail_trace** (`dict`, optional): The Bedrock `GuardrailTrace`. The full trace is stored on the message, and a `policies_triggered` summary is derived from it for both levels.

Strands calls this method itself, with no keyword arguments, when the model provider asks to redact the user's input (a `redactContent` stream event, as Bedrock Guardrails emit). It only ever reaches the **latest** message of that agent: there is no API to redact an arbitrary message after the fact.

#### Guardrail Event Recording

When called, the method:
1. Writes the invocation's pending batch first, so the message being redacted is already in MongoDB
2. Delegates to the parent `RepositorySessionManager.redact_latest_message()` to persist the redacted message
3. Records a `guardrail_event` on the message document: `{"action": "BLOCKED", "timestamp": "..."}`, plus `stop_reason`, `policies_triggered` and `trace` when available
4. Pushes an entry to the session-level `guardrail_events[]` array: the same fields minus `trace`, plus `message_id`, `storage_id` and `agent_id`

Steps 3 and 4 are performed in a single MongoDB operation.

#### Example

```python
from mongodb_session_manager.mongodb_session_manager import GUARDRAIL_ACTION_BLOCKED

# Redact with default action (BLOCKED)
redacted = {"role": "assistant", "content": [{"text": "[Content removed for privacy]"}]}
manager.redact_latest_message(redacted, agent)

# Redact with custom action
manager.redact_latest_message(redacted, agent, action="ANONYMIZED")

# Using the constant
manager.redact_latest_message(redacted, agent, action=GUARDRAIL_ACTION_BLOCKED)
```

---

## Agent Synchronization Methods

### `sync_agent`

```python
def sync_agent(self, agent: LocalAgent, **kwargs: Any) -> None
```

Synchronize agent data and automatically capture event loop metrics and agent configuration.

**Calling it yourself is optional.** Strands already calls it through the hooks the `Agent` registers (see the table below), and the call that closes each invocation is the one that writes the invocation's messages with their metrics. An explicit call after `agent(...)` returns costs one more write, which rewrites the metrics on the last message.

This method performs three key operations:
1. Saves the current agent state to MongoDB, when it differs from what the repository last read or wrote for that agent (see [`update_agent`](mongodb-session-repository.md#update_agent))
2. Captures and persists agent configuration (model, system_prompt)
3. Captures and stores event loop metrics (latency, token usage) from the agent's most recent interaction

The metrics are automatically extracted from `agent.event_loop_metrics.get_summary()` and stored in the `event_loop_metrics` field of the agent's last message. They are the values accumulated over the life of the `Agent` object: with one `Agent` per request, as the factory pattern does, they are that invocation's.

Strands calls `sync_agent()` on its own at two points, and they do not write the same thing:

| When | Metrics |
|---|---|
| After each message is added (`MessageAddedEvent`) | **Not written.** The event fires before the event loop accumulates the usage and metrics of the model call behind the message, so they would still be the previous cycle's |
| At the end of the invocation (`AfterInvocationEvent`) | Written once, on the last message of the invocation |
| When a bidirectional agent stops (`BidiAgentStopEvent`) | **Not written.** A `BidiAgent` has no event loop, so there are no metrics to take. Its state and config still sync |
| Any explicit call to `sync_agent()` | Written, with the values at that moment |

So only the last message of each invocation carries `event_loop_metrics`; tool use, tool results and the next prompt carry none. An explicit call still writes, which is what lets an application add a value to the metrics after the invocation (for instance a time-to-first-token it measured) and then sync. If an invocation does not reach its closing sync -- a hook registered for `AfterInvocationEvent` or the conversation manager raising first -- it is left without metrics. Before v0.15.0 every sync wrote them, and intermediate messages got the previous cycle's values (issue #66).

!!! warning "A hook registered with `HookOrder.SDK_LAST`"
    Strands runs priority groups in ascending order, in reverse-order events too, so a hook registered for `AfterInvocationEvent` with `order=HookOrder.SDK_LAST` (100) runs *after* the closing sync of this manager (`DEFAULT`, 0). A message that such a hook appends is stored, but it carries no `event_loop_metrics`: the metrics stay on the previous message, which is the cycle they belong to. A hook at the default order runs before the closing sync and its message does get them. Both orders are pinned by `tests/unit/test_invocation_metrics.py` ([issue #69](https://github.com/iguinea/mongodb-session-manager/issues/69)).

    **This only applies where the `Agent` was built with `session_manager=`.** An application that builds a manager to call `update_metadata()` or `add_feedback()`, and does not hand it to the `Agent`, has no `SessionManager` lifecycle in that agent at all: there is no closing sync for a hook to get ahead of, whatever the plugins registered. The guarantee comes from the wiring, not from the hook configuration — so it disappears the day that agent is given a `session_manager=`.

Since strands 1.56 every `assistant` message also carries the SDK's own per-cycle attribution in `message.metadata`, which is finer-grained and costs no extra write. See [`message.metadata`](../architecture/data-model.md#metadata-optional).

The agent configuration (model and system_prompt) is automatically extracted from the Agent object and stored in `agents.{agent_id}.agent_data` for later retrieval via `get_agent_config()`. It is only written when it differs from the config already persisted for that agent, as known from this manager's previous writes or from the restore read (see [`initialize`](#initialize)).

#### Parameters

- **agent** (`LocalAgent`): The Strands agent to synchronize -- an `Agent` or, since strands 1.56, a `BidiAgent`.

- **kwargs** (`Any`): Additional keyword arguments passed to the parent class.

#### Captured Metrics

The following metrics are automatically captured and stored:
- `latencyMs`: Total latency in milliseconds for the agent interaction
- `inputTokens`: Number of input tokens processed
- `outputTokens`: Number of output tokens generated
- `totalTokens`: Total tokens (input + output)

#### Example

```python
from strands import Agent

agent = Agent(model="claude-3-sonnet", session_manager=manager)

# Use the agent
response = agent("What is the capital of France?")

# The closing sync already stored the metrics on the last message.
# An explicit sync writes them again, with whatever the agent holds now.
manager.sync_agent(agent)

# Check metrics were captured
print(f"Latency: {agent.event_loop_metrics.accumulated_metrics['latencyMs']}ms")
print(f"Tokens: {agent.event_loop_metrics.accumulated_usage['totalTokens']}")
```

### `register_hooks`

```python
def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None
```

Registers Strands' session hooks. The `Agent` calls it when it is created with `session_manager=...`.

It registers exactly what Strands' `SessionManager` does, through a wrapper around `registry` (`sync_origin.MessageAddedTagging`). The callbacks for `MessageAddedEvent` run with a context tag set, and that tag is how `sync_agent()` knows to leave the metrics out. The tag is a `ContextVar`: it is restored even when a callback raises, and a `sync_agent()` called from another thread does not see it. Every other registration, arguments included, reaches `registry` unchanged. A subclass that overrides `register_hooks()` should call `super()` to keep that behaviour.

### `initialize`

```python
def initialize(self, agent: LocalAgent, **kwargs: Any) -> None
```

Initialize an agent with the session, loading conversation history.

Strands calls this method automatically when an `Agent` is created with `session_manager=...`, so there is no need to call it yourself: a second call for the same `agent_id` raises `SessionException`.

If the agent already exists in the session, its state and conversation history are restored from MongoDB, which lets agents resume conversations across requests or restarts. The same read tells the manager which model and system prompt are already persisted for the agent, so the first `sync_agent()` of each request does not rewrite an unchanged configuration.

#### Parameters

- **agent** (`LocalAgent`): The Strands agent to initialize with session history -- an `Agent` or, since strands 1.56, a `BidiAgent`.

- **kwargs** (`Any`): Additional keyword arguments passed to the parent class.

#### Raises

- `ValueError`: If the `agent_id` cannot be stored as `agents.<agent_id>`: it contains `.`, starts with `$`, is empty or holds a NUL byte (see [names that become paths](mongodb-session-repository.md#names-that-become-paths)). The error surfaces when the `Agent` is created, and it is raised before Strands registers the id, so retrying on the same manager fails the same way instead of with `SessionException`.

!!! note "Bidirectional agents"
    Since strands 1.56 a `BidiAgent` is initialized here too: the SDK dropped `initialize_bidi_agent()` and fires `AgentInitializedEvent` for both kinds of agent, so the check above covers both. Versions of this library before 0.21.0 overrode `initialize_bidi_agent()`, which no longer exists on the base class ([issue #69](https://github.com/iguinea/mongodb-session-manager/issues/69)).

#### Example

```python
# First request: initialize() runs inside Agent(...)
agent1 = Agent(model="claude-3-sonnet", session_manager=manager)
response1 = agent1("My name is Alice")

# A later request (even after a restart) uses a new manager for the same session
manager2 = create_mongodb_session_manager(
    session_id=manager.session_id,
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
)
# Creating the agent restores the history
agent2 = Agent(model="claude-3-sonnet", session_manager=manager2)
response2 = agent2("What's my name?")  # Agent remembers: "Alice"
```

---

## Metadata Management Methods

### `update_metadata`

```python
def update_metadata(self, metadata: Dict[str, Any]) -> None
```

Update session metadata with partial updates that preserve existing fields.

This method performs a partial update of metadata, meaning only the specified fields are updated while other existing metadata fields remain unchanged. This is implemented using MongoDB's `$set` operator with dot notation.

#### Parameters

- **metadata** (`Dict[str, Any]`): Dictionary of metadata fields to update. Keys are field names, values are the new values.

#### Behavior

- Only updates the specified fields
- Preserves all other existing metadata fields
- Creates new fields if they don't exist
- Can update nested fields using dot notation (`{"user.name": "Ana"}`)
- Raises `ValueError`, writing nothing, if any key has an empty segment, a segment starting with `$` or a NUL byte (see [names that become paths](mongodb-session-repository.md#names-that-become-paths)). The `manage_metadata` tool returns that message to the agent as text

#### Example

```python
# Initial metadata
manager.update_metadata(
    {"user_name": "Alice", "priority": "high", "category": "support"}
)

# Partial update - only changes priority
manager.update_metadata({"priority": "low"})
# Result: user_name="Alice", priority="low", category="support"

# Add new field
manager.update_metadata({"agent_state": "thinking"})
# Result: All previous fields + agent_state="thinking"

# Update multiple fields
manager.update_metadata({"status": "active", "last_interaction": "2024-01-26T10:30:00"})
```

#### Hook Integration

If a `metadata_hook` was provided during initialization, it will be called with:
- `action`: `"update"`
- `session_id`: Current session ID
- `metadata`: The metadata dictionary being updated

### `get_metadata`

```python
def get_metadata(self) -> Dict[str, Any]
```

Retrieve all metadata for the current session.

Returns the complete metadata document for the session, including all fields that have been set.

#### Returns

`Dict[str, Any]`: Dictionary containing the session's metadata. Returns a dictionary with a `"metadata"` key containing the metadata fields, or an empty dict if no metadata exists.

#### Example

```python
# Set some metadata
manager.update_metadata({"user_name": "Alice", "priority": "high", "topic": "AI"})

# Retrieve metadata
metadata = manager.get_metadata()
print(metadata)
# Output: {"metadata": {"user_name": "Alice", "priority": "high", "topic": "AI"}}

# Access specific fields
if "metadata" in metadata:
    user_name = metadata["metadata"].get("user_name")
    print(f"User: {user_name}")  # Output: User: Alice
```

#### Hook Integration

If a `metadata_hook` was provided during initialization, it will be called with:
- `action`: `"get"`
- `session_id`: Current session ID

### `delete_metadata`

```python
def delete_metadata(self, metadata_keys: List[str]) -> None
```

Delete specific metadata fields from the session.

This method removes the specified metadata fields from the session document using MongoDB's `$unset` operator. Other metadata fields are preserved.

#### Parameters

- **metadata_keys** (`List[str]`): List of metadata field names to delete.

#### Example

```python
# Initial metadata
manager.update_metadata(
    {
        "user_name": "Alice",
        "temp_data": "xyz",
        "session_token": "abc123",
        "priority": "high",
    }
)

# Delete sensitive or temporary fields
manager.delete_metadata(["temp_data", "session_token"])

# Verify deletion
metadata = manager.get_metadata()
# Result: Only user_name and priority remain
print(metadata["metadata"])
# Output: {"user_name": "Alice", "priority": "high"}
```

#### Hook Integration

If a `metadata_hook` was provided during initialization, it will be called with:
- `action`: `"delete"`
- `session_id`: Current session ID
- `keys`: List of keys being deleted

### `get_metadata_tool`

```python
def get_metadata_tool(self)
```

Get a Strands tool that agents can use to manage metadata autonomously.

This method returns a Strands `@tool` decorated function that enables agents to manage session metadata directly. The tool supports get, set/update, and delete operations, allowing agents to maintain session state independently.

#### Returns

A Strands tool function with the following signature:

```python
def manage_metadata(
    action: str,
    metadata: Optional[Dict[str, Any]] = None,
    keys: Optional[List[str]] = None,
) -> str
```

#### Tool Parameters

- **action** (`str`, required): The action to perform - `"get"`, `"set"`, `"update"`, or `"delete"`
- **metadata** (`Optional[Dict[str, Any]]`): For set/update actions, the metadata to set
- **keys** (`Optional[List[str]]`): For get action, specific keys to retrieve. For delete action, keys to remove.

#### Tool Actions

**Get Metadata**:
- `action="get"`: Returns all metadata
- `action="get", keys=["field1", "field2"]`: Returns only specified fields, and **names any of them that are not stored** (`Not found: ['field2']`). An absence the agent cannot see is one it cannot act on: it can neither retry with another name nor conclude the data does not live in metadata
- `action="get", keys=["user.name", "tags.0"]`: A key is a path, so it reads the nested field a dotted key wrote

**Set/Update Metadata**:
- `action="set", metadata={"key": "value"}`: Updates specified metadata fields
- `action="update", metadata={"key": "value"}`: Alias for set (same behavior)
- `action="set", metadata={"user.name": "Ana"}`: Updates one nested field and keeps its siblings
- `action="set", metadata={"user": {"name": "Ana"}}`: **Replaces** the whole document stored under `user`. The reply says so, naming the keys it replaced, because that is all the agent gets to notice it

**Delete Metadata**:
- `action="delete", keys=["field1", "field2"]`: Deletes specified fields

#### Keys Are Paths, In The Three Actions

A dot in a key addresses a field inside a stored document, the same way in `get`, `set` and `delete`. Before v0.22.0 only the writes took it that way: `get` filtered the top-level keys, so an agent that had just stored `user.name` was told there was no such metadata (#47).

The rule, and what is rejected before anything is written, is in [names that become paths](mongodb-session-repository.md#names-that-become-paths).

!!! note "The tool spec was malformed before v0.22.0, and the SDK repaired it"
    `inputSchema` was hand-written and assigned verbatim, without the `{"json": ...}` wrapper that `ToolSpec` declares. **Nothing broke:** `ToolRegistry.validate_tool_spec()` wraps a bare schema with `normalize_schema()` before it reaches any provider, in every strands release from 1.25 to 1.56. What it cost is that `normalize_schema()` invents the missing descriptions, so the model was handed `"Property action"`, `"Property metadata"` and `"Property keys"` under a one-line tool description. The spec is now built by Strands from the function's signature and docstring, which is what puts the rule above in front of the model. Outside the tool registry the bare schema *is* rejected by botocore, which is what the regression test pins.

#### Example

```python
from strands import Agent

# Get the metadata tool
metadata_tool = manager.get_metadata_tool()

# Create agent with metadata capabilities
agent = Agent(model="claude-3-sonnet", session_manager=manager, tools=[metadata_tool])

# Agent can now manage metadata autonomously
response = agent("Store my preference for email notifications as enabled")
# Agent uses the tool to: manage_metadata("set", {"email_notifications": "enabled"})

response = agent("What are my current preferences?")
# Agent uses the tool to: manage_metadata("get")

# Direct tool usage (without agent)
result = metadata_tool(action="get")
print(result)  # "All metadata: {...}"

result = metadata_tool(action="set", metadata={"priority": "high"})
print(result)  # "Successfully updated metadata fields: ['priority']"

result = metadata_tool(action="set", metadata={"user.name": "Ana"})
result = metadata_tool(action="get", keys=["user.name"])
print(result)  # 'Metadata retrieved: {"user.name": "Ana"}'

# A whole document replaces what was stored under the key, and the reply says so
result = metadata_tool(action="set", metadata={"user": {"name": "Eva"}})
print(result)
# Successfully updated metadata fields: ['user']. Careful: ['user'] received a
# whole document, which replaces what was stored under it. Use dot notation in
# the key ("user.<field>") to update one field and keep the rest

result = metadata_tool(action="delete", keys=["old_field"])
print(result)  # "Successfully deleted metadata fields: ['old_field']"
```

---

## Feedback Management Methods

### `add_feedback`

```python
def add_feedback(self, feedback: Dict[str, Any]) -> None
```

Add user feedback to the session.

This method stores feedback data in the session document, typically containing a rating and optional comment. A `created_at` timestamp is automatically added to each feedback entry.

#### Parameters

- **feedback** (`Dict[str, Any]`): Feedback dictionary containing:
  - `rating` (optional): User rating, typically `"up"`, `"down"`, or `None`
  - `comment` (optional): User's feedback comment as a string
  - Any other custom fields as needed

#### Behavior

- Appends feedback to the `feedbacks` array in the session document
- Automatically adds `created_at` timestamp
- Updates session's `updated_at` timestamp
- Does not modify existing feedback entries

#### Example

```python
# Add positive feedback
manager.add_feedback({"rating": "up", "comment": "Great response, very helpful!"})

# Add negative feedback
manager.add_feedback({"rating": "down", "comment": "Response was too slow"})

# Add neutral feedback
manager.add_feedback({"rating": None, "comment": "Just testing the system"})

# Add feedback with custom fields
manager.add_feedback(
    {
        "rating": "up",
        "comment": "Excellent!",
        "category": "accuracy",
        "user_id": "user-123",
    }
)
```

#### Hook Integration

If a `feedback_hook` was provided during initialization, it will be called with:
- `action`: `"add"`
- `session_id`: Current session ID
- `feedback`: The feedback dictionary being added

### `get_feedbacks`

```python
def get_feedbacks(self) -> List[Dict[str, Any]]
```

Get all feedback entries for the session.

Returns all feedback that has been added to the session, in the order it was submitted.

#### Returns

`List[Dict[str, Any]]`: List of feedback dictionaries. Each dictionary contains the feedback data plus the automatically added `created_at` timestamp. Returns empty list if no feedback exists.

#### Example

```python
# Add some feedback
manager.add_feedback({"rating": "up", "comment": "Great!"})
manager.add_feedback({"rating": "down", "comment": "Too slow"})

# Retrieve all feedback
feedbacks = manager.get_feedbacks()
print(f"Total feedback entries: {len(feedbacks)}")

for fb in feedbacks:
    print(f"Rating: {fb['rating']}")
    print(f"Comment: {fb['comment']}")
    print(f"Submitted: {fb['created_at']}")
    print("---")

# Output:
# Total feedback entries: 2
# Rating: up
# Comment: Great!
# Submitted: 2024-01-26 10:30:45.123456+00:00
# ---
# Rating: down
# Comment: Too slow
# Submitted: 2024-01-26 10:35:12.654321+00:00
```

---

## Agent Configuration Methods

These methods enable retrieval and management of agent configuration (model, system_prompt, and prompt_metadata).

### `get_agent_config`

```python
def get_agent_config(self, agent_id: str) -> Optional[Dict[str, Any]]
```

Get configuration (model, system_prompt, and prompt_metadata) for a specific agent.

This method retrieves the stored configuration for an agent, including the model identifier, system prompt (automatically captured during `sync_agent()`), and prompt metadata (set via `set_prompt_metadata()`).

#### Parameters

- **agent_id** (`str`, required): ID of the agent to retrieve configuration for.

#### Returns

`Optional[Dict[str, Any]]`: Dictionary containing:
- `agent_id`: The agent's ID
- `model`: The model identifier (e.g., "claude-3-sonnet")
- `system_prompt`: The system prompt text
- `prompt_metadata`: Prompt lineage dict (or `None` if not set). Contains: `prompt_id`, `prompt_name`, `prompt_version`, `deployment_id`, `deployment_name`.

Returns `None` if the agent doesn't exist in the session.

#### Example

```python
# Configuration is captured automatically during sync
agent = Agent(
    agent_id="support-agent",
    model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
    system_prompt="You are a friendly customer support agent.",
    session_manager=manager,
)

response = agent("Hello!")  # sync_agent() called automatically

# Retrieve agent configuration
config = manager.get_agent_config("support-agent")
if config:
    print(f"Agent ID: {config['agent_id']}")
    print(f"Model: {config['model']}")
    print(f"System Prompt: {config['system_prompt'][:50]}...")

# Output:
# Agent ID: support-agent
# Model: eu.anthropic.claude-sonnet-4-20250514-v1:0
# System Prompt: You are a friendly customer support agent.
```

#### Use Cases

- **Auditing**: Track which models were used for regulatory compliance
- **Debugging**: Reproduce agent behavior with exact configuration
- **Analytics**: Analyze model usage patterns and associated costs
- **Documentation**: Generate reports on agent configurations

### `update_agent_config`

```python
def update_agent_config(
    self,
    agent_id: str,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    prompt_metadata: Optional[Dict[str, str]] = None
) -> None
```

Update model or system_prompt for a specific agent.

This method allows you to modify an agent's stored configuration. You can update the model, system prompt, or both. This is useful for experimentation, A/B testing, or adjusting agent behavior without recreating the session.

#### Parameters

- **agent_id** (`str`, required): ID of the agent to update.
- **model** (`Optional[str]`, default: `None`): New model identifier. If `None`, model is not updated.
- **system_prompt** (`Optional[str]`, default: `None`): New system prompt text. If `None`, prompt is not updated.
- **prompt_metadata** (`Optional[Dict[str, str]]`, default: `None`): Prompt lineage metadata. If `None`, metadata is not updated.

#### Raises

- `ValueError`: If the session or agent doesn't exist.
- `PyMongoError`: If the database operation fails.

#### Example

```python
# Update only the model (switch to faster model)
manager.update_agent_config(
    "support-agent", model="eu.anthropic.claude-haiku-4-20250514-v1:0"
)

# Update only the system prompt
manager.update_agent_config(
    "support-agent",
    system_prompt="You are a friendly and efficient customer support agent with 10 years of experience.",
)

# Update both model and system prompt
manager.update_agent_config(
    "support-agent",
    model="eu.anthropic.claude-opus-4-20250514-v1:0",
    system_prompt="You are an expert customer support agent specializing in technical issues.",
)

# Verify the update
config = manager.get_agent_config("support-agent")
print(f"New model: {config['model']}")
print(f"New prompt: {config['system_prompt'][:50]}...")
```

#### Use Cases

- **A/B Testing**: Compare different prompts or models for same conversations
- **Experimentation**: Try different configurations without losing session history
- **Optimization**: Upgrade to better models as they become available
- **Cost Management**: Switch to more economical models when appropriate

### `set_prompt_metadata`

```python
def set_prompt_metadata(
    self,
    agent_id: str,
    prompt_metadata: Dict[str, str]
) -> None
```

Set prompt lineage metadata for a specific agent.

Must be called after `sync_agent()` (the agent must already exist in the session). This enables tracing each system prompt back to its source: which prompt template, which version, and which deployment produced it.

#### Parameters

- **agent_id** (`str`, required): ID of the agent to set metadata for.
- **prompt_metadata** (`Dict[str, str]`, required): Dictionary with prompt lineage fields:
    - `prompt_id`: Unique identifier of the prompt template
    - `prompt_name`: Human-readable prompt name
    - `prompt_version`: Semver version string (e.g., "1.2.0")
    - `deployment_id`: UID of the deployment
    - `deployment_name`: Human-readable deployment name
    - `temperature` (optional, float): LLM temperature used with this prompt

#### Raises

- `ValueError`: If the session or agent doesn't exist.

#### Example

```python
# Sync the agent first
manager.sync_agent(agent)

# Stamp prompt lineage metadata
manager.set_prompt_metadata(
    "support-agent",
    {
        "prompt_id": "prompt-abc",
        "prompt_name": "Customer Support V2",
        "prompt_version": "1.2.0",
        "deployment_id": "deploy-xyz",
        "deployment_name": "production",
        "temperature": 0.7,
    },
)

# Verify
config = manager.get_agent_config("support-agent")
print(config["prompt_metadata"]["prompt_version"])  # "1.2.0"
```

#### Use Cases

- **Prompt Traceability**: Know exactly which prompt version generated each conversation
- **A/B Testing**: Compare metrics between sessions using different prompt versions
- **Debugging**: "This session gave a bad answer — which prompt version was it using?"
- **Auditing**: Track which deployment served which prompt and when

### `list_agents`

```python
def list_agents(self) -> List[Dict[str, Any]]
```

List all agents in the session with their configurations.

This method retrieves all agents that have been used in the current session along with their configurations (model, system_prompt, and prompt_metadata if captured).

#### Returns

`List[Dict[str, Any]]`: List of dictionaries, each containing:
- `agent_id`: The agent's ID
- `model`: The model identifier (or `None` if not captured)
- `system_prompt`: The system prompt text (or `None` if not captured)
- `prompt_metadata`: Prompt lineage dict (or `None` if not set)

Returns empty list if no agents exist in the session.

#### Example

```python
# Create multiple agents in the session
translator = Agent(
    agent_id="translator",
    model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
    system_prompt="You are a translation specialist.",
    session_manager=manager,
)

support = Agent(
    agent_id="support",
    model="eu.anthropic.claude-haiku-4-20250514-v1:0",
    system_prompt="You provide technical support.",
    session_manager=manager,
)

# Use both agents
translator("Translate: Hello")
support("How do I reset my password?")

# List all agents with configurations
agents = manager.list_agents()
print(f"Found {len(agents)} agents in session:\n")

for agent_info in agents:
    print(f"Agent: {agent_info['agent_id']}")
    print(f"  Model: {agent_info.get('model', 'Not captured')}")
    print(f"  Prompt: {agent_info.get('system_prompt', 'Not captured')[:50]}...")
    print()

# Output:
# Found 2 agents in session:
#
# Agent: translator
#   Model: eu.anthropic.claude-sonnet-4-20250514-v1:0
#   Prompt: You are a translation specialist.
#
# Agent: support
#   Model: eu.anthropic.claude-haiku-4-20250514-v1:0
#   Prompt: You provide technical support.
```

#### Use Cases

- **Session Overview**: Get a complete picture of all agents in a session
- **Auditing**: Review which agents and models were used
- **Analytics**: Aggregate data on agent usage patterns
- **Monitoring**: Track which agent types are most commonly used

---

## Resource Management Methods

### `close`

```python
def close(self) -> None
```

Close the underlying MongoDB connection and clean up resources.

This method closes the MongoDB connection if it was created by this session manager. If an external client was provided during initialization (via the `client` parameter), the connection is not closed.

#### Behavior

- Closes MongoDB connection if owned by this manager
- Skips closing if using a borrowed/external client
- Releases any other resources held by the manager
- Safe to call multiple times

#### Example

```python
# Manager with owned connection - will be closed
manager1 = MongoDBSessionManager(
    session_id="user-123", connection_string="mongodb://localhost:27017/"
)
# ... use manager ...
manager1.close()  # Connection is closed

# Manager with borrowed connection - won't be closed
client = MongoClient("mongodb://localhost:27017/")
manager2 = MongoDBSessionManager(
    session_id="user-456",
    client=client,  # Borrowed client
)
# ... use manager ...
manager2.close()  # Connection is NOT closed
client.close()  # You manage the client's lifecycle

# Context manager pattern (recommended)
manager = MongoDBSessionManager(
    session_id="user-789", connection_string="mongodb://localhost:27017/"
)
try:
    # Use manager
    pass
finally:
    manager.close()  # Always clean up
```

---

## Hook System

The session manager supports two types of hooks for intercepting and enhancing operations:

### Metadata Hooks

Metadata hooks intercept all metadata operations (update, get, delete) and can be used for:
- Audit logging
- Validation
- Caching
- Triggering external workflows
- Data transformation

#### Hook Signature

```python
def metadata_hook(
    original_func: Callable,
    action: str,
    session_id: str,
    **kwargs
) -> Any
```

**Parameters**:
- `original_func`: The original method being intercepted
- `action`: One of `"update"`, `"get"`, or `"delete"`
- `session_id`: The current session ID
- `**kwargs`: Additional arguments:
  - For `"update"`: `metadata` (dict)
  - For `"delete"`: `keys` (list)
  - For `"get"`: (no additional args)

Keys are validated **before** the hook is called: a hook never receives a metadata key the repository would reject, so it cannot publish one to an external system before the write fails.

#### Example Metadata Hooks

**Audit Hook**:
```python
def audit_metadata_hook(original_func, action, session_id, **kwargs):
    logger.info(f"[AUDIT] Metadata {action} on session {session_id}")

    if action == "update":
        logger.info(f"  Fields: {list(kwargs['metadata'].keys())}")
        return original_func(kwargs["metadata"])
    elif action == "delete":
        logger.info(f"  Deleting: {kwargs['keys']}")
        return original_func(kwargs["keys"])
    else:  # get
        result = original_func()
        logger.info(f"  Retrieved: {len(result.get('metadata', {}))} fields")
        return result


manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    metadata_hook=audit_metadata_hook,
)
```

**Validation Hook**:
```python
def validation_metadata_hook(original_func, action, session_id, **kwargs):
    if action == "update":
        metadata = kwargs["metadata"]

        # Validate priority field
        if "priority" in metadata:
            allowed = ["low", "medium", "high", "critical"]
            if metadata["priority"] not in allowed:
                raise ValueError(f"Invalid priority. Must be one of: {allowed}")

        # Validate email format
        if "email" in metadata:
            if "@" not in metadata["email"]:
                raise ValueError("Invalid email format")

        return original_func(metadata)
    elif action == "delete":
        return original_func(kwargs["keys"])
    else:
        return original_func()


manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    metadata_hook=validation_metadata_hook,
)
```

### Feedback Hooks

Feedback hooks intercept feedback operations and can be used for:
- Audit logging
- Real-time notifications (e.g., alerts for negative feedback)
- Analytics and aggregation
- Data validation
- External integrations

#### Hook Signature

```python
def feedback_hook(
    original_func: Callable,
    action: str,
    session_id: str,
    **kwargs
) -> None
```

**Parameters**:
- `original_func`: The original method being intercepted
- `action`: Always `"add"` for feedback hooks
- `session_id`: The current session ID
- `**kwargs`: Contains `feedback` (dict) with the feedback data, and `session_manager` (the manager instance)

#### Example Feedback Hooks

**Notification Hook**:
```python
def notification_feedback_hook(original_func, action, session_id, **kwargs):
    # Store the feedback first
    result = original_func(kwargs["feedback"])

    # Send notification for negative feedback
    feedback = kwargs["feedback"]
    if feedback.get("rating") == "down":
        send_alert(
            f"Negative feedback on session {session_id}: "
            f"{feedback.get('comment', 'No comment')}"
        )

    return result


manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    feedback_hook=notification_feedback_hook,
)
```

**Analytics Hook**:
```python
def analytics_feedback_hook(original_func, action, session_id, **kwargs):
    feedback = kwargs["feedback"]

    # Store in MongoDB
    result = original_func(feedback)

    # Send to analytics service
    analytics.track(
        "feedback_submitted",
        {
            "session_id": session_id,
            "rating": feedback.get("rating"),
            "has_comment": bool(feedback.get("comment")),
            "timestamp": datetime.now(),
        },
    )

    return result


manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    feedback_hook=analytics_feedback_hook,
)
```

---

## Helper Function

### `create_mongodb_session_manager`

```python
def create_mongodb_session_manager(
    session_id: str,
    connection_string: Optional[str] = None,
    database_name: str = "database_name",
    collection_name: str = "collection_name",
    client: Optional[MongoClient] = None,
    **kwargs: Any,
) -> MongoDBSessionManager
```

Convenience factory function to create a MongoDB Session Manager with default settings.

This function is a simple wrapper around the `MongoDBSessionManager` constructor, providing a convenient way to create session managers with common configurations.

#### Parameters

Same as `MongoDBSessionManager.__init__()`.

#### Returns

`MongoDBSessionManager`: Configured session manager instance.

#### Example

```python
from mongodb_session_manager import create_mongodb_session_manager

# Simple creation
manager = create_mongodb_session_manager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    collection_name="sessions",
)

# With custom options
manager = create_mongodb_session_manager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    maxPoolSize=50,
    retryWrites=True,
)
```

---

## Complete Usage Example

```python
from datetime import datetime

from mongodb_session_manager import MongoDBSessionManager
from strands import Agent

# Initialize session manager
manager = MongoDBSessionManager(
    session_id="user-session-123",
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    collection_name="sessions",
    metadata_fields=["priority", "status"],
    maxPoolSize=50,
)

# Create agent with session persistence. Creating it restores any existing
# history: Strands calls manager.initialize(agent) itself.
agent = Agent(
    model="claude-3-sonnet",
    session_manager=manager,
    tools=[manager.get_metadata_tool()],
)

# Set initial metadata
manager.update_metadata(
    {
        "user_name": "Alice",
        "priority": "high",
        "session_start": datetime.now().isoformat(),
    }
)

# Have a conversation: messages, state and metrics are persisted as it goes
response = agent("Hello, I need help with my account")

# Update metadata during conversation
manager.update_metadata({"status": "active"})

# Continue conversation
response = agent("Can you check my balance?")

# Add user feedback
manager.add_feedback({"rating": "up", "comment": "Very helpful and quick response!"})

# Retrieve session information
metadata = manager.get_metadata()
feedbacks = manager.get_feedbacks()

print(f"Session metadata: {metadata}")
print(f"Total feedback entries: {len(feedbacks)}")

# Clean up
manager.close()
```

---

## See Also

- [MongoDBSessionRepository](./mongodb-session-repository.md) - Low-level repository implementation
- [MongoDBConnectionPool](./mongodb-connection-pool.md) - Connection pool for stateless environments
- [MongoDBSessionManagerFactory](./mongodb-session-factory.md) - Factory pattern for efficient session manager creation
- [Hooks](./hooks.md) - Comprehensive guide to hook system and AWS integrations
- [User Guide - Metadata Management](../user-guide/metadata-management.md)
- [User Guide - Feedback System](../user-guide/feedback-system.md)
