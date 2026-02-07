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
    metadata_hook: Optional[Callable[[Dict[str, Any]], None]] = None,
    feedback_hook: Optional[Callable[[Dict[str, Any]], None]] = None,
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

- **kwargs** (`Any`): Additional keyword arguments. MongoDB client options (e.g., `maxPoolSize`, `minPoolSize`) are passed to `MongoClient`. Other arguments are passed to the parent `RepositorySessionManager` class.

#### Supported MongoDB Client Options

The following MongoDB client options can be passed via `kwargs`:
- `maxPoolSize`: Maximum number of connections in the pool (default: 100)
- `minPoolSize`: Minimum number of connections to maintain (default: 10)
- `maxIdleTimeMS`: Close idle connections after this many milliseconds
- `waitQueueTimeoutMS`: Timeout waiting for connection from pool
- `serverSelectionTimeoutMS`: Timeout for server selection
- `connectTimeoutMS`: Initial connection timeout
- `socketTimeoutMS`: Socket operation timeout
- `compressors`: List of compression algorithms
- `retryWrites`: Enable automatic retry for write operations
- `retryReads`: Enable automatic retry for read operations
- `w`: Write concern
- `journal`: Journal write concern
- `fsync`: Fsync write concern
- `authSource`: Authentication database
- `authMechanism`: Authentication mechanism
- `tlsAllowInvalidCertificates`: Allow invalid TLS certificates

#### Example

```python
from mongodb_session_manager import MongoDBSessionManager

# Basic usage with new connection
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    collection_name="sessions"
)

# With connection pooling and custom options
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    collection_name="sessions",
    maxPoolSize=50,
    minPoolSize=5,
    retryWrites=True
)

# With existing client (recommended for FastAPI)
from pymongo import MongoClient
client = MongoClient("mongodb://localhost:27017/", maxPoolSize=100)

manager = MongoDBSessionManager(
    session_id="user-123",
    client=client,  # Reuse existing connection
    database_name="chat_db",
    collection_name="sessions"
)

# With metadata indexing
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    metadata_fields=["priority", "status", "category"]
)

# With hooks for audit and notifications
def audit_metadata(original_func, action, session_id, **kwargs):
    logger.info(f"Metadata {action} on {session_id}")
    return original_func(**kwargs) if kwargs else original_func()

def notify_feedback(original_func, action, session_id, **kwargs):
    result = original_func(kwargs["feedback"])
    send_notification(session_id, kwargs["feedback"])
    return result

manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    metadata_hook=audit_metadata,
    feedback_hook=notify_feedback
)
```

---

## Session Message Methods

### `append_message`

```python
def append_message(self, message: Message, agent: Agent) -> None
```

Append a message to the session for the specified agent.

This method adds a new message to the agent's conversation history in MongoDB. Messages are stored in chronological order with auto-incrementing message IDs.

#### Parameters

- **message** (`Message`): The message to append. Typically contains `role` ("user" or "assistant") and `content` fields.

- **agent** (`Agent`): The Strands Agent instance associated with this message.

#### Example

```python
from strands import Agent
from strands.types.content import Message

agent = Agent(model="claude-3-sonnet", session_manager=manager)

# Append user message
user_message = Message(role="user", content="Hello, how are you?")
manager.append_message(user_message, agent)

# Append assistant message
assistant_message = Message(role="assistant", content="I'm doing well, thank you!")
manager.append_message(assistant_message, agent)
```

### `redact_latest_message`

```python
def redact_latest_message(
    self, redact_message: Message, agent: Agent, **kwargs: Any
) -> None
```

Redact the latest message in the conversation for the specified agent.

This method updates the most recent message for an agent, typically used for content moderation or to correct mistakes. The message's `updated_at` timestamp is automatically updated while preserving the original `created_at`.

#### Parameters

- **redact_message** (`Message`): The redacted version of the message with updated content.

- **agent** (`Agent`): The Strands Agent instance whose message should be redacted.

- **kwargs** (`Any`): Additional keyword arguments passed to the underlying repository.

#### Example

```python
# Redact the last message
redacted = Message(
    role="assistant",
    content="[Content removed for privacy]"
)
manager.redact_latest_message(redacted, agent)
```

---

## Agent Synchronization Methods

### `sync_agent`

```python
def sync_agent(self, agent: Agent, **kwargs: Any) -> None
```

Synchronize agent data and automatically capture event loop metrics and agent configuration.

This method performs three key operations:
1. Saves the current agent state to MongoDB
2. **NEW v0.5.0**: Captures and persists agent configuration (model, system_prompt)
3. Captures and stores event loop metrics (latency, token usage) from the agent's most recent interaction

The metrics are automatically extracted from `agent.event_loop_metrics.accumulated_metrics` and `agent.event_loop_metrics.accumulated_usage`, and stored in the `event_loop_metrics` field of the latest assistant message.

The agent configuration (model and system_prompt) is automatically extracted from the Agent object and stored in `agents.{agent_id}.agent_data` for later retrieval via `get_agent_config()`.

#### Parameters

- **agent** (`Agent`): The Strands Agent instance to synchronize.

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

agent = Agent(
    model="claude-3-sonnet",
    session_manager=manager
)

# Use the agent
response = agent("What is the capital of France?")

# Sync to capture metrics
manager.sync_agent(agent)
# Metrics are now stored in MongoDB with the assistant message

# Check metrics were captured
print(f"Latency: {agent.event_loop_metrics.accumulated_metrics['latencyMs']}ms")
print(f"Tokens: {agent.event_loop_metrics.accumulated_usage['totalTokens']}")
```

### `initialize`

```python
def initialize(self, agent: Agent, **kwargs: Any) -> None
```

Initialize an agent with the session, loading conversation history.

This method loads the existing conversation history from MongoDB and populates the agent's context with previous messages. This enables agents to resume conversations across different sessions or restarts.

#### Parameters

- **agent** (`Agent`): The Strands Agent instance to initialize with session history.

- **kwargs** (`Any`): Additional keyword arguments passed to the parent class.

#### Example

```python
# First conversation
agent1 = Agent(model="claude-3-sonnet", session_manager=manager)
manager.initialize(agent1)
response1 = agent1("My name is Alice")
manager.sync_agent(agent1)

# Later, resume conversation (even after restart)
agent2 = Agent(model="claude-3-sonnet", session_manager=manager)
manager.initialize(agent2)  # Loads previous messages
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
- Can update nested fields using dot notation

#### Example

```python
# Initial metadata
manager.update_metadata({
    "user_name": "Alice",
    "priority": "high",
    "category": "support"
})

# Partial update - only changes priority
manager.update_metadata({"priority": "low"})
# Result: user_name="Alice", priority="low", category="support"

# Add new field
manager.update_metadata({"agent_state": "thinking"})
# Result: All previous fields + agent_state="thinking"

# Update multiple fields
manager.update_metadata({
    "status": "active",
    "last_interaction": "2024-01-26T10:30:00"
})
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
manager.update_metadata({
    "user_name": "Alice",
    "priority": "high",
    "topic": "AI"
})

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
manager.update_metadata({
    "user_name": "Alice",
    "temp_data": "xyz",
    "session_token": "abc123",
    "priority": "high"
})

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
- `action="get", keys=["field1", "field2"]`: Returns only specified fields

**Set/Update Metadata**:
- `action="set", metadata={"key": "value"}`: Updates specified metadata fields
- `action="update", metadata={"key": "value"}`: Alias for set (same behavior)

**Delete Metadata**:
- `action="delete", keys=["field1", "field2"]`: Deletes specified fields

#### Example

```python
from strands import Agent

# Get the metadata tool
metadata_tool = manager.get_metadata_tool()

# Create agent with metadata capabilities
agent = Agent(
    model="claude-3-sonnet",
    session_manager=manager,
    tools=[metadata_tool]
)

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
manager.add_feedback({
    "rating": "up",
    "comment": "Great response, very helpful!"
})

# Add negative feedback
manager.add_feedback({
    "rating": "down",
    "comment": "Response was too slow"
})

# Add neutral feedback
manager.add_feedback({
    "rating": None,
    "comment": "Just testing the system"
})

# Add feedback with custom fields
manager.add_feedback({
    "rating": "up",
    "comment": "Excellent!",
    "category": "accuracy",
    "user_id": "user-123"
})
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
manager.add_feedback({
    "rating": "up",
    "comment": "Great!"
})
manager.add_feedback({
    "rating": "down",
    "comment": "Too slow"
})

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

**NEW in v0.5.0**: These methods enable retrieval and management of agent configuration (model and system_prompt).

### `get_agent_config`

```python
def get_agent_config(self, agent_id: str) -> Optional[Dict[str, Any]]
```

Get configuration (model and system_prompt) for a specific agent.

This method retrieves the stored configuration for an agent, including the model identifier and system prompt that were automatically captured during `sync_agent()`.

#### Parameters

- **agent_id** (`str`, required): ID of the agent to retrieve configuration for.

#### Returns

`Optional[Dict[str, Any]]`: Dictionary containing:
- `agent_id`: The agent's ID
- `model`: The model identifier (e.g., "claude-3-sonnet")
- `system_prompt`: The system prompt text

Returns `None` if the agent doesn't exist in the session.

#### Example

```python
# Configuration is captured automatically during sync
agent = Agent(
    agent_id="support-agent",
    model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
    system_prompt="You are a friendly customer support agent.",
    session_manager=manager
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
    system_prompt: Optional[str] = None
) -> None
```

Update model or system_prompt for a specific agent.

This method allows you to modify an agent's stored configuration. You can update the model, system prompt, or both. This is useful for experimentation, A/B testing, or adjusting agent behavior without recreating the session.

#### Parameters

- **agent_id** (`str`, required): ID of the agent to update.
- **model** (`Optional[str]`, default: `None`): New model identifier. If `None`, model is not updated.
- **system_prompt** (`Optional[str]`, default: `None`): New system prompt text. If `None`, prompt is not updated.

#### Raises

- `ValueError`: If the session doesn't exist.
- `PyMongoError`: If the database operation fails.

#### Example

```python
# Update only the model (switch to faster model)
manager.update_agent_config(
    "support-agent",
    model="eu.anthropic.claude-haiku-4-20250514-v1:0"
)

# Update only the system prompt
manager.update_agent_config(
    "support-agent",
    system_prompt="You are a friendly and efficient customer support agent with 10 years of experience."
)

# Update both model and system prompt
manager.update_agent_config(
    "support-agent",
    model="eu.anthropic.claude-opus-4-20250514-v1:0",
    system_prompt="You are an expert customer support agent specializing in technical issues."
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

### `list_agents`

```python
def list_agents(self) -> List[Dict[str, Any]]
```

List all agents in the session with their configurations.

This method retrieves all agents that have been used in the current session along with their configurations (model and system_prompt if captured).

#### Returns

`List[Dict[str, Any]]`: List of dictionaries, each containing:
- `agent_id`: The agent's ID
- `model`: The model identifier (or `None` if not captured)
- `system_prompt`: The system prompt text (or `None` if not captured)

Returns empty list if no agents exist in the session.

#### Example

```python
# Create multiple agents in the session
translator = Agent(
    agent_id="translator",
    model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
    system_prompt="You are a translation specialist.",
    session_manager=manager
)

support = Agent(
    agent_id="support",
    model="eu.anthropic.claude-haiku-4-20250514-v1:0",
    system_prompt="You provide technical support.",
    session_manager=manager
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
    session_id="user-123",
    connection_string="mongodb://localhost:27017/"
)
# ... use manager ...
manager1.close()  # Connection is closed

# Manager with borrowed connection - won't be closed
client = MongoClient("mongodb://localhost:27017/")
manager2 = MongoDBSessionManager(
    session_id="user-456",
    client=client  # Borrowed client
)
# ... use manager ...
manager2.close()  # Connection is NOT closed
client.close()  # You manage the client's lifecycle

# Context manager pattern (recommended)
manager = MongoDBSessionManager(
    session_id="user-789",
    connection_string="mongodb://localhost:27017/"
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

#### Example Metadata Hooks

**Audit Hook**:
```python
def audit_metadata_hook(original_func, action, session_id, **kwargs):
    logger.info(f"[AUDIT] Metadata {action} on session {session_id}")

    if action == "update":
        logger.info(f"  Fields: {list(kwargs['metadata'].keys())}")
        return original_func(kwargs['metadata'])
    elif action == "delete":
        logger.info(f"  Deleting: {kwargs['keys']}")
        return original_func(kwargs['keys'])
    else:  # get
        result = original_func()
        logger.info(f"  Retrieved: {len(result.get('metadata', {}))} fields")
        return result

manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    metadata_hook=audit_metadata_hook
)
```

**Validation Hook**:
```python
def validation_metadata_hook(original_func, action, session_id, **kwargs):
    if action == "update":
        metadata = kwargs['metadata']

        # Validate priority field
        if 'priority' in metadata:
            allowed = ['low', 'medium', 'high', 'critical']
            if metadata['priority'] not in allowed:
                raise ValueError(f"Invalid priority. Must be one of: {allowed}")

        # Validate email format
        if 'email' in metadata:
            if '@' not in metadata['email']:
                raise ValueError("Invalid email format")

        return original_func(metadata)
    elif action == "delete":
        return original_func(kwargs['keys'])
    else:
        return original_func()

manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    metadata_hook=validation_metadata_hook
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
- `**kwargs`: Contains `feedback` (dict) with the feedback data

#### Example Feedback Hooks

**Notification Hook**:
```python
def notification_feedback_hook(original_func, action, session_id, **kwargs):
    # Store the feedback first
    result = original_func(kwargs['feedback'])

    # Send notification for negative feedback
    feedback = kwargs['feedback']
    if feedback.get('rating') == 'down':
        send_alert(
            f"Negative feedback on session {session_id}: "
            f"{feedback.get('comment', 'No comment')}"
        )

    return result

manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    feedback_hook=notification_feedback_hook
)
```

**Analytics Hook**:
```python
def analytics_feedback_hook(original_func, action, session_id, **kwargs):
    feedback = kwargs['feedback']

    # Store in MongoDB
    result = original_func(feedback)

    # Send to analytics service
    analytics.track('feedback_submitted', {
        'session_id': session_id,
        'rating': feedback.get('rating'),
        'has_comment': bool(feedback.get('comment')),
        'timestamp': datetime.now()
    })

    return result

manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    feedback_hook=analytics_feedback_hook
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
    collection_name="sessions"
)

# With custom options
manager = create_mongodb_session_manager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    maxPoolSize=50,
    retryWrites=True
)
```

---

## Complete Usage Example

```python
from mongodb_session_manager import MongoDBSessionManager
from strands import Agent

# Initialize session manager
manager = MongoDBSessionManager(
    session_id="user-session-123",
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    collection_name="sessions",
    metadata_fields=["priority", "status"],
    maxPoolSize=50
)

# Create agent with session persistence
agent = Agent(
    model="claude-3-sonnet",
    session_manager=manager,
    tools=[manager.get_metadata_tool()]
)

# Initialize with existing history
manager.initialize(agent)

# Set initial metadata
manager.update_metadata({
    "user_name": "Alice",
    "priority": "high",
    "session_start": datetime.now().isoformat()
})

# Have a conversation
response = agent("Hello, I need help with my account")
manager.sync_agent(agent)  # Captures metrics

# Update metadata during conversation
manager.update_metadata({"status": "active"})

# Continue conversation
response = agent("Can you check my balance?")
manager.sync_agent(agent)

# Add user feedback
manager.add_feedback({
    "rating": "up",
    "comment": "Very helpful and quick response!"
})

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
