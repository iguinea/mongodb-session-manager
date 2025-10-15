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
                    "role": "user",
                    "content": "Hello!",
                    "created_at": ISODate("2024-01-26T10:30:50.000Z"),
                    "updated_at": ISODate("2024-01-26T10:30:50.000Z")
                },
                {
                    "message_id": 2,
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

- **metadata_fields** (`Optional[List[str]]`, default: `None`): List of metadata field names to index for optimized queries.

- **kwargs** (`Any`): Additional arguments for `MongoClient` (only used if `client` is not provided).

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
    collection_name="sessions"
)
# ... use repository ...
repo.close()  # Closes the connection

# Create repository with existing client (borrowed)
client = MongoClient("mongodb://localhost:27017/", maxPoolSize=100)
repo = MongoDBSessionRepository(
    client=client,  # Borrowed client
    database_name="chat_db",
    collection_name="sessions"
)
# ... use repository ...
repo.close()  # Does NOT close the client
client.close()  # You manage the client

# With metadata field indexing
repo = MongoDBSessionRepository(
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    collection_name="sessions",
    metadata_fields=["priority", "status", "category"]
)

# With custom MongoDB client options
repo = MongoDBSessionRepository(
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    collection_name="sessions",
    maxPoolSize=50,
    minPoolSize=10,
    retryWrites=True
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
session = Session(
    session_id="user-123",
    session_type="chat"
)

created_session = repo.create_session(session)
print(f"Created session: {created_session.session_id}")
```

### `read_session`

```python
def read_session(self, session_id: str, **kwargs: Any) -> Optional[Session]
```

Read a session from MongoDB by ID.

Retrieves session metadata (ID, type, timestamps) without loading agents or messages.

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
    system_prompt="You are a helpful assistant"
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

Read an agent from a session by agent ID.

Retrieves agent data including model, system prompt, and timestamps, but not messages.

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
    print(f"Model: {agent.model}")
    print(f"Agent ID: {agent.agent_id}")
else:
    print("Agent not found")
```

### `update_agent`

```python
def update_agent(
    self, session_id: str, session_agent: SessionAgent, **kwargs: Any
) -> None
```

Update an existing agent, preserving timestamps.

Updates agent data while preserving the original `created_at` timestamp and updating `updated_at` to the current time.

#### Parameters

- **session_id** (`str`): ID of the session containing the agent.

- **session_agent** (`SessionAgent`): The agent object with updated data.

- **kwargs** (`Any`): Additional keyword arguments (reserved for future use).

#### Raises

- `ValueError`: If the session does not exist.
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

## Message Operations

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

Appends a message to the agent's messages array with automatic timestamps.

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
user_msg = SessionMessage(
    message_id=1,
    role="user",
    content="Hello, how are you?"
)
repo.create_message("user-123", "assistant-1", user_msg)

# Create assistant message
assistant_msg = SessionMessage(
    message_id=2,
    role="assistant",
    content="I'm doing well, thank you!"
)
repo.create_message("user-123", "assistant-1", assistant_msg)
```

### `read_message`

```python
def read_message(
    self, session_id: str, agent_id: str, message_id: int, **kwargs: Any
) -> Optional[SessionMessage]
```

Read a specific message by ID.

Retrieves a message from an agent's message array. Note that `event_loop_metrics` are filtered out before returning the `SessionMessage`.

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

Updates an existing message while preserving its original `created_at` timestamp and updating `updated_at`.

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

# Modify content (e.g., for redaction)
message.content = "[Content removed for privacy]"

# Update in database
repo.update_message("user-123", "assistant-1", message)
```

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

List messages from an agent with pagination support.

Retrieves messages sorted chronologically (oldest first) with optional pagination. Note that `event_loop_metrics` are filtered out from the returned messages.

#### Parameters

- **session_id** (`str`): ID of the session.

- **agent_id** (`str`): ID of the agent.

- **limit** (`Optional[int]`, default: `None`): Maximum number of messages to return. If `None`, returns all messages.

- **offset** (`int`, default: `0`): Number of messages to skip (for pagination).

- **kwargs** (`Any`): Additional keyword arguments (reserved for future use).

#### Returns

`list[SessionMessage]`: List of messages in chronological order (oldest first).

#### Raises

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

- **metadata** (`Dict[str, Any]`): Dictionary of metadata fields to update.

#### Raises

- `PyMongoError`: If the database operation fails.

#### Example

```python
# Initial metadata
repo.update_metadata("user-123", {
    "user_name": "Alice",
    "priority": "high",
    "category": "support"
})

# Partial update - only changes priority
repo.update_metadata("user-123", {"priority": "low"})
# Result: user_name="Alice", priority="low", category="support"

# Add new fields
repo.update_metadata("user-123", {
    "status": "active",
    "last_interaction": "2024-01-26T10:30:00"
})
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

- **metadata_keys** (`List[str]`): List of metadata field names to delete.

#### Raises

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

- `PyMongoError`: If the database operation fails.

#### Example

```python
# Add positive feedback
repo.add_feedback("user-123", {
    "rating": "up",
    "comment": "Great response!"
})

# Add negative feedback with custom fields
repo.add_feedback("user-123", {
    "rating": "down",
    "comment": "Too slow",
    "category": "performance",
    "user_id": "alice"
})
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
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db"
)
# ... use repository ...
repo.close()  # Closes connection

# With borrowed connection
client = MongoClient("mongodb://localhost:27017/")
repo = MongoDBSessionRepository(
    client=client,
    database_name="chat_db"
)
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
    metadata_fields=["priority", "status"]
)

# Create a new session
session = Session(session_id="user-123", session_type="chat")
repo.create_session(session)

# Set metadata
repo.update_metadata("user-123", {
    "user_name": "Alice",
    "priority": "high"
})

# Create an agent
agent = SessionAgent(
    agent_id="assistant-1",
    model="claude-3-sonnet",
    system_prompt="You are a helpful assistant"
)
repo.create_agent("user-123", agent)

# Add messages
user_msg = SessionMessage(
    message_id=1,
    role="user",
    content="Hello!"
)
repo.create_message("user-123", "assistant-1", user_msg)

assistant_msg = SessionMessage(
    message_id=2,
    role="assistant",
    content="Hi! How can I help?"
)
repo.create_message("user-123", "assistant-1", assistant_msg)

# Add feedback
repo.add_feedback("user-123", {
    "rating": "up",
    "comment": "Great service!"
})

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
repo = MongoDBSessionRepository(
    client=client,
    database_name="chat_db"
)

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
