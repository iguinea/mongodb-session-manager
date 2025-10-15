# Design Decisions

## Table of Contents
- [Introduction](#introduction)
- [Document-Based Storage](#document-based-storage)
- [Singleton Connection Pool](#singleton-connection-pool)
- [Factory Pattern](#factory-pattern)
- [Smart Connection Management](#smart-connection-management)
- [Partial Metadata Updates](#partial-metadata-updates)
- [Hook System Design](#hook-system-design)
- [Timestamp Preservation](#timestamp-preservation)
- [Event Loop Metrics Capture](#event-loop-metrics-capture)
- [Error Handling Philosophy](#error-handling-philosophy)
- [Repository Pattern](#repository-pattern)
- [Async Hook Execution](#async-hook-execution)

## Introduction

This document explains the key design decisions made in the MongoDB Session Manager architecture. Each decision is presented with the problem context, considered alternatives, the chosen solution, and the rationale behind it.

## Document-Based Storage

### Problem Context

Strands Agents maintain complex session state including:
- Multiple agents per session
- Conversation history (messages)
- Agent state (key-value pairs)
- Metadata (user-defined fields)
- Event loop metrics (tokens, latency)
- User feedback

**Question**: Should we use normalized tables (relational) or embedded documents (MongoDB)?

### Alternatives Considered

#### Alternative 1: Normalized Relational Schema
```sql
-- Separate tables with foreign keys
CREATE TABLE sessions (
    session_id VARCHAR PRIMARY KEY,
    session_type VARCHAR,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE agents (
    agent_id VARCHAR PRIMARY KEY,
    session_id VARCHAR REFERENCES sessions,
    agent_data JSON,
    created_at TIMESTAMP
);

CREATE TABLE messages (
    message_id BIGINT PRIMARY KEY,
    agent_id VARCHAR REFERENCES agents,
    role VARCHAR,
    content TEXT,
    created_at TIMESTAMP
);

CREATE TABLE metadata (
    session_id VARCHAR REFERENCES sessions,
    key VARCHAR,
    value TEXT,
    PRIMARY KEY (session_id, key)
);
```

**Pros**:
- Strong consistency guarantees (ACID)
- Normalized data (no duplication)
- Complex joins possible
- Mature ecosystem

**Cons**:
- Multiple queries to fetch complete session
- JOIN overhead for full conversation history
- Foreign key constraints add complexity
- Schema migrations required for new fields
- Harder to shard/scale horizontally
- No native support for nested arrays (messages)

#### Alternative 2: Document-per-Message
```json
{
    "_id": "msg-1",
    "session_id": "session-123",
    "agent_id": "agent-A",
    "message_id": 1,
    "role": "user",
    "content": "Hello",
    "created_at": "2024-01-15T09:00:00Z"
}
```

**Pros**:
- Simple document structure
- Easy to query individual messages
- Easy to implement pagination

**Cons**:
- Fetching full conversation requires multiple queries
- No atomicity for multi-message operations
- Session state scattered across documents
- Higher storage overhead (repeated session_id)
- Slower conversation retrieval

#### Alternative 3: Embedded Document (Chosen)
```json
{
    "_id": "session-123",
    "session_id": "session-123",
    "agents": {
        "agent-A": {
            "agent_data": {...},
            "messages": [
                {"message_id": 1, "role": "user", "content": "Hello"},
                {"message_id": 2, "role": "assistant", "content": "Hi"}
            ]
        }
    },
    "metadata": {...},
    "feedbacks": [...]
}
```

**Pros**:
- Single query fetches entire session
- Atomic updates (all-or-nothing)
- No JOINs required
- Schema flexibility (add fields without migration)
- Natural fit for conversational data
- Excellent read performance
- Easy to shard by session_id

**Cons**:
- Document size limits (16MB in MongoDB)
- Potential for large documents with long conversations
- Updates require careful positional operators

### Chosen Solution: Embedded Documents

**Rationale**:

1. **Access Pattern Match**: Sessions are always accessed as complete units. When loading a conversation, you need all messages, not just one. Embedded documents optimize for this.

2. **Atomicity**: Strands SDK expects atomic operations. Updating agent state and appending a message should be a single transaction. Document-level atomicity in MongoDB provides this naturally.

3. **Performance**:
   - Fetching a session: 1 query vs. 3+ queries (normalized)
   - Appending a message: 1 update vs. 1 insert + 2 updates (normalized)
   - Loading conversation history: Instant vs. JOIN + ORDER BY

4. **Scalability**: Sharding by `session_id` is straightforward with document-per-session model. Each shard contains complete sessions.

5. **Schema Evolution**: Adding new fields to metadata or feedback doesn't require migrations. Just start using them.

**Mitigations for Cons**:

1. **Document Size Limits**:
   - 16MB limit = ~32,000 messages at 500 bytes each
   - Most conversations won't reach this
   - Future: Implement message archiving for very long sessions

2. **Large Documents**:
   - Use projection to fetch only needed fields
   - Repository filters out `event_loop_metrics` when returning SessionMessage
   - Consider implementing message pagination at repository level

**Code Reference**:
- Implementation: `/workspace/src/mongodb_session_manager/mongodb_session_repository.py` (lines 199-208)
- Schema creation in `create_session()` method

## Singleton Connection Pool

### Problem Context

In stateless environments (FastAPI, Lambda), each request could potentially:
- Create a new MongoDB connection
- Perform operations
- Close the connection

**Measured Impact**:
- Connection creation: 10-50ms overhead per request
- Under load: Connection exhaustion (MongoDB limits: 1,500-12,500)
- Resource waste: Most connection time is idle

### Alternatives Considered

#### Alternative 1: Connection per Request
```python
def handle_request(session_id):
    client = MongoClient(connection_string)  # 10-50ms overhead
    # ... use client ...
    client.close()
```

**Pros**:
- Simple implementation
- No shared state

**Cons**:
- High latency (10-50ms per request)
- Connection exhaustion under load
- Resource inefficient
- Poor scalability

#### Alternative 2: Connection per Session Manager
```python
class MongoDBSessionManager:
    def __init__(self, session_id, connection_string):
        self.client = MongoClient(connection_string)  # One per manager
```

**Pros**:
- Better than per-request
- Manager controls lifecycle

**Cons**:
- Still creates multiple clients in factory pattern
- Connection pool per manager (wasteful)
- Limited reuse

#### Alternative 3: Singleton Connection Pool (Chosen)
```python
class MongoDBConnectionPool:
    _instance: Optional[MongoDBConnectionPool] = None
    _lock: Lock = Lock()
    _client: Optional[MongoClient] = None

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
```

**Pros**:
- Zero connection overhead after initialization
- One pool shared across entire application
- Controlled connection count
- Excellent performance

**Cons**:
- Singleton pattern (global state)
- Thread synchronization needed
- Requires careful shutdown

### Chosen Solution: Singleton with Double-Checked Locking

**Rationale**:

1. **Performance**:
   - Benchmark: 10-50ms → 0ms per request (after first)
   - Throughput: 10x improvement in concurrent tests
   - See: `/workspace/examples/example_performance.py`

2. **Resource Efficiency**:
   - One MongoClient instance per application
   - PyMongo internally pools connections (configurable)
   - Controlled total connection count

3. **Scalability**:
   - Each FastAPI instance: 1 pool
   - Total connections = instances × maxPoolSize (predictable)
   - MongoDB handles load distribution

4. **Thread Safety**:
   - Double-checked locking pattern prevents race conditions
   - MongoClient itself is thread-safe (PyMongo guarantee)

**Implementation Details**:

```python
# Thread-safe initialization
def __new__(cls):
    if cls._instance is None:           # First check (no lock)
        with cls._lock:                 # Acquire lock
            if cls._instance is None:   # Second check (with lock)
                cls._instance = super().__new__(cls)
    return cls._instance
```

**Why Double-Checked Locking?**
- First check: Avoid lock acquisition on every call (performance)
- Second check: Prevent race condition between first check and lock acquisition
- Classic pattern for lazy initialization in concurrent environments

**Connection Pool Configuration**:
```python
{
    "maxPoolSize": 100,      # Maximum connections
    "minPoolSize": 10,       # Keep 10 warm
    "maxIdleTimeMS": 30000,  # Close idle after 30s
    "retryWrites": True,     # Automatic retry
    "retryReads": True
}
```

**Code Reference**:
- Implementation: `/workspace/src/mongodb_session_manager/mongodb_connection_pool.py` (lines 29-35)
- Usage: `/workspace/src/mongodb_session_manager/mongodb_session_factory.py` (line 53)

## Factory Pattern

### Problem Context

FastAPI applications need to create many session managers (one per request) while reusing the connection pool.

**Requirements**:
- Create managers without connection overhead
- Share configuration across managers
- Support lifecycle management (startup/shutdown)
- Enable global access for convenience

### Alternatives Considered

#### Alternative 1: Direct Instantiation
```python
# In each FastAPI endpoint
manager = MongoDBSessionManager(
    session_id=session_id,
    connection_string=mongodb_uri,  # Repeated everywhere
    database_name="mydb",           # Repeated everywhere
    collection_name="sessions"      # Repeated everywhere
)
```

**Pros**:
- Simple, direct
- No abstraction

**Cons**:
- Configuration duplication
- No connection reuse
- Hard to change configuration
- Lifecycle management unclear

#### Alternative 2: Dependency Injection
```python
# FastAPI dependency
def get_mongo_client():
    return MongoClient(mongodb_uri)

@app.post("/chat")
async def chat(
    session_id: str,
    client: MongoClient = Depends(get_mongo_client)
):
    manager = MongoDBSessionManager(session_id=session_id, client=client)
```

**Pros**:
- FastAPI-native pattern
- Explicit dependencies
- Testability

**Cons**:
- Still need to pass configuration
- Dependency boilerplate
- Client lifecycle unclear

#### Alternative 3: Factory Pattern (Chosen)
```python
# Global factory initialization
factory = initialize_global_factory(
    connection_string=mongodb_uri,
    database_name="mydb",
    maxPoolSize=100
)

# In endpoints
manager = factory.create_session_manager(session_id)
```

**Pros**:
- Configuration centralized
- Connection reuse automatic
- Clean endpoint code
- Lifecycle clear (startup/shutdown)

**Cons**:
- Additional abstraction layer
- Global state (factory instance)

### Chosen Solution: Factory with Global Singleton Option

**Rationale**:

1. **Configuration Management**:
   - Set once at application startup
   - All managers inherit configuration
   - Easy to modify in one place

2. **Connection Reuse**:
   - Factory owns the connection pool
   - All managers share the pool
   - Zero overhead per manager creation

3. **Lifecycle Management**:
   ```python
   @asynccontextmanager
   async def lifespan(app: FastAPI):
       # Startup
       factory = initialize_global_factory(...)
       yield
       # Shutdown
       close_global_factory()
   ```

4. **Flexibility**:
   - Global factory for convenience (FastAPI)
   - Local factory for isolation (testing)
   - Supports hook injection per manager

**Design Pattern Combination**:
- Factory Method: `create_session_manager()`
- Singleton: Global factory instance
- Lazy Initialization: Pool created on first use

**Usage Patterns**:

```python
# Pattern 1: Global factory (recommended for FastAPI)
factory = initialize_global_factory(connection_string="mongodb://...")
manager = get_global_factory().create_session_manager("session-123")

# Pattern 2: Local factory (testing, isolation)
factory = MongoDBSessionManagerFactory(connection_string="mongodb://...")
manager = factory.create_session_manager("session-123")

# Pattern 3: Per-request factory (maximum flexibility)
@app.post("/chat")
async def chat(request: Request):
    factory = request.app.state.session_factory
    manager = factory.create_session_manager(session_id)
```

**Code Reference**:
- Implementation: `/workspace/src/mongodb_session_manager/mongodb_session_factory.py`
- Global helpers: Lines 124-193
- Usage example: `/workspace/examples/example_fastapi_streaming.py`

## Smart Connection Management

### Problem Context

Different use cases require different connection ownership models:
- **Use Case 1**: Simple script (owns connection)
- **Use Case 2**: FastAPI with factory (borrows from pool)
- **Use Case 3**: Testing with mocked client (borrows from test)

**Question**: Who owns the MongoDB client, and who should close it?

### Alternatives Considered

#### Alternative 1: Always Own
```python
class MongoDBSessionRepository:
    def __init__(self, connection_string):
        self.client = MongoClient(connection_string)
        self._owns_client = True
```

**Pros**:
- Simple
- Clear ownership

**Cons**:
- Can't reuse external clients
- Factory pattern inefficient
- Testing harder (real connections)

#### Alternative 2: Never Own
```python
class MongoDBSessionRepository:
    def __init__(self, client: MongoClient):
        self.client = client
        self._owns_client = False
```

**Pros**:
- No cleanup needed
- Clear dependency

**Cons**:
- Can't use connection string directly
- Less convenient for simple cases
- Breaks backward compatibility

#### Alternative 3: Smart Ownership (Chosen)
```python
class MongoDBSessionRepository:
    def __init__(self, connection_string=None, client=None):
        if client is not None:
            self.client = client
            self._owns_client = False  # Borrowed
        elif connection_string is not None:
            self.client = MongoClient(connection_string)
            self._owns_client = True   # Owned
        else:
            raise ValueError("Provide client or connection_string")

    def close(self):
        if self._owns_client:
            self.client.close()
        else:
            # Don't close borrowed client
            pass
```

**Pros**:
- Flexible (both patterns supported)
- Backward compatible
- Safe cleanup (only closes owned clients)
- Factory pattern efficient

**Cons**:
- Two code paths
- Ownership tracking needed

### Chosen Solution: Conditional Ownership with Flag

**Rationale**:

1. **Flexibility**:
   - Simple scripts: Pass connection string
   - Factory pattern: Pass shared client
   - Testing: Pass mock client

2. **Safety**:
   - `_owns_client` flag prevents double-close
   - Borrowed clients not closed (could be in use elsewhere)
   - Owned clients always cleaned up

3. **Backward Compatibility**:
   - Existing code with connection strings works
   - New code can use factory pattern

4. **Clear Semantics**:
   ```python
   # I create it, I own it
   manager = MongoDBSessionManager(connection_string="mongodb://...")
   manager.close()  # Closes the connection

   # I receive it, I borrow it
   manager = MongoDBSessionManager(client=shared_client)
   manager.close()  # Does NOT close the connection
   ```

**Implementation**:

```python
# In MongoDBSessionRepository.__init__
if client is not None:
    self.client = client
    self._owns_client = False
    logger.info("Using provided MongoDB client")
else:
    if connection_string is None:
        raise ValueError("Connection string is required")
    self.client = MongoClient(connection_string, **kwargs)
    self._owns_client = True
    logger.info("Created new MongoDB client")

# In close()
def close(self):
    if self._owns_client:
        self.client.close()
        logger.info("MongoDB connection closed")
    else:
        logger.info("Skipping close - using shared MongoDB client")
```

**Code Reference**:
- Implementation: `/workspace/src/mongodb_session_manager/mongodb_session_repository.py` (lines 157-169, 569-575)
- Used by manager: `/workspace/src/mongodb_session_manager/mongodb_session_manager.py` (lines 152-160)

## Partial Metadata Updates

### Problem Context

Sessions have user-defined metadata that evolves over time:
```python
# Initial state
{"user_id": "123", "language": "en"}

# Later, add priority
{"priority": "high"}

# Expected result
{"user_id": "123", "language": "en", "priority": "high"}
```

**Question**: Should updates replace all metadata or merge with existing?

### Alternatives Considered

#### Alternative 1: Full Replacement
```python
def update_metadata(self, session_id, metadata):
    self.collection.update_one(
        {"_id": session_id},
        {"$set": {"metadata": metadata}}  # Replaces entire object
    )
```

**Pros**:
- Simple implementation
- Predictable (explicit)
- No merge logic needed

**Cons**:
- Loses existing metadata
- Requires reading current metadata first
- Race conditions in concurrent updates
- Poor user experience

#### Alternative 2: Read-Modify-Write
```python
def update_metadata(self, session_id, metadata):
    current = self.get_metadata(session_id)
    merged = {**current, **metadata}
    self.collection.update_one(
        {"_id": session_id},
        {"$set": {"metadata": merged}}
    )
```

**Pros**:
- Preserves existing data
- User-friendly

**Cons**:
- Race condition window
- Extra read operation
- Not atomic

#### Alternative 3: Partial Update with Dot Notation (Chosen)
```python
def update_metadata(self, session_id, metadata):
    set_operations = {
        f"metadata.{key}": value
        for key, value in metadata.items()
    }
    self.collection.update_one(
        {"_id": session_id},
        {"$set": set_operations}
    )
```

**Pros**:
- Atomic operation
- Preserves existing fields
- No race conditions
- Single database operation
- Efficient

**Cons**:
- Slightly more complex code
- Requires understanding of dot notation

### Chosen Solution: MongoDB $set with Dot Notation

**Rationale**:

1. **Atomicity**: Single update operation, no read required
2. **Preservation**: Existing fields remain untouched
3. **Performance**: One database operation vs. two
4. **Correctness**: No race conditions in concurrent scenarios

**Example**:

```python
# Initial state in MongoDB
{
    "_id": "session-123",
    "metadata": {
        "user_id": "alice",
        "language": "en",
        "theme": "dark"
    }
}

# Update call
session_manager.update_metadata({
    "priority": "high",
    "status": "active"
})

# MongoDB operation
db.sessions.update_one(
    {"_id": "session-123"},
    {
        "$set": {
            "metadata.priority": "high",
            "metadata.status": "active"
        }
    }
)

# Final state
{
    "_id": "session-123",
    "metadata": {
        "user_id": "alice",      # Preserved
        "language": "en",         # Preserved
        "theme": "dark",          # Preserved
        "priority": "high",       # Added
        "status": "active"        # Added
    }
}
```

**Deletion Support**:

Complementary operation using `$unset`:
```python
def delete_metadata(self, session_id, metadata_keys):
    unset_operations = {
        f"metadata.{key}": ""
        for key in metadata_keys
    }
    self.collection.update_one(
        {"_id": session_id},
        {"$unset": unset_operations}
    )
```

**Code Reference**:
- Implementation: `/workspace/src/mongodb_session_manager/mongodb_session_repository.py` (lines 578-592, 598-614)
- Usage: `/workspace/README.md` (metadata management section)

## Hook System Design

### Problem Context

Users need to extend session manager behavior without modifying core code:
- Audit logging for compliance
- Validation of metadata/feedback
- Notifications (SNS, webhooks)
- Caching for performance
- Custom business logic

**Question**: How to make the system extensible without tight coupling?

### Alternatives Considered

#### Alternative 1: Inheritance
```python
class AuditedSessionManager(MongoDBSessionManager):
    def update_metadata(self, metadata):
        self.audit_log("update_metadata", metadata)
        super().update_metadata(metadata)
```

**Pros**:
- Object-oriented approach
- Type safety

**Cons**:
- Inheritance explosion (one subclass per variant)
- Can't combine behaviors easily
- Hard to enable/disable at runtime
- Tight coupling

#### Alternative 2: Event System
```python
class MongoDBSessionManager:
    def __init__(self):
        self.events = EventEmitter()

    def update_metadata(self, metadata):
        self.events.emit("before_update", metadata)
        # ... update logic ...
        self.events.emit("after_update", metadata)

# Usage
manager.events.on("before_update", audit_handler)
manager.events.on("after_update", notification_handler)
```

**Pros**:
- Decoupled (listeners don't know about each other)
- Multiple handlers per event
- Dynamic registration

**Cons**:
- Can't modify behavior (only observe)
- No control over execution
- Complex event hierarchy
- Debugging harder

#### Alternative 3: Hook Decorator Pattern (Chosen)
```python
def metadata_hook(original_func, action, session_id, **kwargs):
    # Pre-processing
    logger.info(f"[AUDIT] {action} on {session_id}")

    # Call original
    if action == "update":
        result = original_func(kwargs["metadata"])
    elif action == "delete":
        result = original_func(kwargs["keys"])
    else:
        result = original_func()

    # Post-processing
    notify_system(action, result)

    return result

# Application
manager = MongoDBSessionManager(
    session_id="session-123",
    metadataHook=metadata_hook
)
```

**Pros**:
- Clean interface
- Can modify behavior
- Single hook combines pre/post processing
- Easy to enable/disable (pass hook or not)
- Composable (hooks can call other hooks)

**Cons**:
- Hook signature must be known
- One hook per operation type
- Hook errors affect main operation

### Chosen Solution: Decorator Pattern with Wrapper Functions

**Rationale**:

1. **Simplicity**: One function wraps original behavior
2. **Power**: Full control over execution (before, during, after)
3. **Flexibility**: Hook can decide whether to call original
4. **Testability**: Easy to test hooks independently
5. **Composability**: Hooks can be chained

**Hook Signature Design**:

```python
def hook_function(
    original_func: Callable,   # The method being wrapped
    action: str,               # Operation type ("update", "get", "delete")
    session_id: str,           # Context (which session)
    **kwargs                   # Operation-specific args
) -> Any:                      # Return value of operation
```

**Why this signature?**
- `original_func`: Allows hook to call (or not call) original
- `action`: One hook handles multiple operations
- `session_id`: Context for logging, routing, etc.
- `**kwargs`: Flexible for different operations
- Return value: Hook can modify result

**Implementation Pattern**:

```python
def _apply_metadata_hook(self, hook: Callable) -> None:
    # Wrap update_metadata
    original_update = self.update_metadata
    def wrapped_update(metadata: Dict[str, Any]) -> None:
        return hook(original_update, "update", self.session_id, metadata=metadata)
    self.update_metadata = wrapped_update

    # Wrap get_metadata
    original_get = self.get_metadata
    def wrapped_get() -> Dict[str, Any]:
        return hook(original_get, "get", self.session_id)
    self.get_metadata = wrapped_get

    # Wrap delete_metadata
    original_delete = self.delete_metadata
    def wrapped_delete(metadata_keys: List[str]) -> None:
        return hook(original_delete, "delete", self.session_id, keys=metadata_keys)
    self.delete_metadata = wrapped_delete
```

**Use Cases**:

1. **Audit Logging**:
   ```python
   def audit_hook(original_func, action, session_id, **kwargs):
       logger.info(f"[AUDIT] {action} on {session_id}: {kwargs}")
       return original_func(...)
   ```

2. **Validation**:
   ```python
   def validation_hook(original_func, action, session_id, **kwargs):
       if action == "update":
           validate_metadata(kwargs["metadata"])
       return original_func(...)
   ```

3. **Caching**:
   ```python
   cache = {}
   def cache_hook(original_func, action, session_id, **kwargs):
       if action == "get":
           if session_id in cache:
               return cache[session_id]
           result = original_func()
           cache[session_id] = result
           return result
       else:
           cache.pop(session_id, None)  # Invalidate
           return original_func(...)
   ```

4. **Notifications (AWS SNS)**:
   ```python
   def sns_hook(original_func, action, session_id, **kwargs):
       result = original_func(...)
       if action == "add":  # Feedback
           asyncio.create_task(send_to_sns(kwargs["feedback"]))
       return result
   ```

**Error Handling in Hooks**:

```python
def safe_hook(original_func, action, session_id, **kwargs):
    try:
        # Pre-processing
        logger.info(f"Processing {action}")

        # Always call original (critical)
        result = original_func(...)

        # Post-processing (non-critical)
        try:
            send_notification(action, result)
        except Exception as e:
            logger.error(f"Notification failed: {e}")
            # Don't raise - notification failure shouldn't fail operation

        return result
    except Exception as e:
        logger.error(f"Hook error: {e}")
        raise  # Re-raise if original failed
```

**Code Reference**:
- Metadata hook: `/workspace/src/mongodb_session_manager/mongodb_session_manager.py` (lines 179-204)
- Feedback hook: Lines 383-396
- AWS hooks: `/workspace/src/mongodb_session_manager/hooks/`

## Timestamp Preservation

### Problem Context

MongoDB operations can update timestamps unintentionally:
```python
# Initial agent
{
    "agent_id": "agent-A",
    "created_at": "2024-01-15T09:00:00Z",
    "updated_at": "2024-01-15T09:00:00Z"
}

# Update agent (e.g., change system prompt)
# Should preserve created_at, update updated_at
```

**Question**: How to preserve `created_at` while updating `updated_at`?

### Alternatives Considered

#### Alternative 1: Client-Side Timestamps
```python
# Client provides both timestamps
session_agent.created_at = "2024-01-15T09:00:00Z"  # From client
session_agent.updated_at = datetime.now(UTC)       # Now

# Update operation
db.update_one(
    {"_id": session_id},
    {"$set": {
        f"agents.{agent_id}.created_at": session_agent.created_at,
        f"agents.{agent_id}.updated_at": session_agent.updated_at
    }}
)
```

**Pros**:
- Simple
- Client controls all timestamps

**Cons**:
- Client can provide wrong created_at
- No enforcement of immutability
- Relies on client behavior

#### Alternative 2: Read-Before-Write
```python
# Read current timestamps
current = db.find_one({"_id": session_id}, {"agents.{agent_id}.created_at": 1})
created_at = current["agents"][agent_id]["created_at"]

# Update with preserved timestamp
db.update_one(
    {"_id": session_id},
    {"$set": {
        f"agents.{agent_id}.created_at": created_at,  # Preserved
        f"agents.{agent_id}.updated_at": datetime.now(UTC)
    }}
)
```

**Pros**:
- Guarantees preservation
- Server controls timestamps

**Cons**:
- Extra read operation
- Race condition window
- Performance overhead

#### Alternative 3: $setOnInsert for Create, Preserve on Update (Chosen)
```python
# On update, read existing created_at first
existing = self.collection.find_one(
    {"_id": session_id},
    {f"agents.{agent_id}.created_at": 1}
)

# Preserve if exists, or use current time
created_at = datetime.now(UTC)
if existing and "agents" in existing and agent_id in existing["agents"]:
    created_at = existing["agents"][agent_id].get("created_at", created_at)

# Update with preserved timestamp
self.collection.update_one(
    {"_id": session_id},
    {"$set": {
        f"agents.{agent_id}.created_at": created_at,  # Preserved or new
        f"agents.{agent_id}.updated_at": datetime.now(UTC)
    }}
)
```

**Pros**:
- Guaranteed preservation
- Server-side enforcement
- Handles edge cases (missing timestamp)

**Cons**:
- Extra read (small projection)
- Slightly more complex

### Chosen Solution: Read-and-Preserve on Update

**Rationale**:

1. **Correctness**: `created_at` is immutable by design
2. **Reliability**: Server enforces preservation (client can't override)
3. **Edge Case Handling**: Works even if timestamp missing
4. **Performance**: Projection limits data transfer

**Implementation**:

```python
def update_agent(self, session_id, session_agent, **kwargs):
    # Convert Strands SDK timestamps to datetime
    agent_data = session_agent.__dict__
    agent_data["created_at"] = datetime.fromisoformat(
        session_agent.created_at.replace("Z", "+00:00")
    )
    agent_data["updated_at"] = datetime.fromisoformat(
        session_agent.updated_at.replace("Z", "+00:00")
    )

    # Fetch existing created_at (small projection)
    existing = self.collection.find_one(
        {"_id": session_id},
        {f"agents.{session_agent.agent_id}.created_at": 1}
    )

    # Preserve original or use current
    created_at = datetime.now(UTC)
    if (existing and "agents" in existing and
        session_agent.agent_id in existing["agents"]):
        created_at = existing["agents"][session_agent.agent_id].get(
            "created_at", created_at
        )

    # Update with preservation
    result = self.collection.update_one(
        {"_id": session_id},
        {"$set": {
            f"agents.{session_agent.agent_id}.agent_data": agent_data,
            f"agents.{session_agent.agent_id}.created_at": created_at,  # Preserved
            f"agents.{session_agent.agent_id}.updated_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC)  # Session also updated
        }}
    )
```

**Same Pattern for Messages**:

```python
# In update_message
for i, msg in enumerate(messages):
    if msg.get("message_id") == session_message.message_id:
        message_index = i
        # Preserve created_at
        message_data["created_at"] = msg.get("created_at", datetime.now(UTC))
        message_data["updated_at"] = datetime.now(UTC)
        break
```

**Why Preserve?**

1. **Audit Trail**: Know when entity was truly created
2. **Analytics**: Accurate session duration, message timing
3. **Compliance**: Immutable creation timestamp for regulations
4. **Data Integrity**: Updates don't corrupt historical data

**Code Reference**:
- Agent update: `/workspace/src/mongodb_session_manager/mongodb_session_repository.py` (lines 328-342)
- Message update: Lines 468-477

## Event Loop Metrics Capture

### Problem Context

Strands SDK agents populate `agent.event_loop_metrics` during execution:
```python
agent.event_loop_metrics.accumulated_metrics = {"latencyMs": 250}
agent.event_loop_metrics.accumulated_usage = {
    "inputTokens": 10,
    "outputTokens": 20,
    "totalTokens": 30
}
```

**Question**: How should session manager capture and store these metrics?

### Alternatives Considered

#### Alternative 1: Automatic Capture in append_message
```python
def append_message(self, message, agent):
    # Augment message with current metrics
    message["event_loop_metrics"] = agent.event_loop_metrics.to_dict()
    super().append_message(message, agent)
```

**Pros**:
- Fully automatic
- No extra method calls

**Cons**:
- Metrics might not be ready yet
- User message gets metrics too (incorrect)
- Couples message creation to metrics

#### Alternative 2: Separate Method (store_metrics)
```python
# After agent call
response = agent("Hello")
session_manager.store_metrics(agent)  # Explicit
```

**Pros**:
- Explicit control
- Clear intention

**Cons**:
- Extra method for users to remember
- Not integrated with existing Strands SDK patterns

#### Alternative 3: Capture in sync_agent (Chosen)
```python
def sync_agent(self, agent, **kwargs):
    # Call parent (syncs agent state)
    super().sync_agent(agent, **kwargs)

    # Extract metrics from agent
    latencyMs = agent.event_loop_metrics.accumulated_metrics["latencyMs"]
    inputTokens = agent.event_loop_metrics.accumulated_usage["inputTokens"]
    # ...

    # Update last message with metrics
    if latencyMs > 0:
        # Find last message
        # Update with metrics
```

**Pros**:
- Natural integration with Strands SDK
- Users already call sync_agent
- Metrics ready by sync time
- Only updates when metrics present

**Cons**:
- Metrics stored separately from message creation
- Requires understanding of sync_agent purpose

### Chosen Solution: Automatic Capture in sync_agent

**Rationale**:

1. **Strands SDK Integration**: `sync_agent` is the standard method for persisting agent state. Natural place for metrics too.

2. **Metrics Availability**: By the time `sync_agent` is called, agent has completed execution and metrics are populated.

3. **Zero User Burden**: Users already call `sync_agent` (or it's called automatically). No new methods to learn.

4. **Conditional Logic**: `if latencyMs > 0` ensures we only update when metrics are actually present.

**Implementation**:

```python
def sync_agent(self, agent: Agent, **kwargs: Any) -> None:
    # First, sync agent state (parent class)
    super().sync_agent(agent, **kwargs)

    # Extract metrics from agent's event loop
    _latencyMs = agent.event_loop_metrics.accumulated_metrics["latencyMs"]
    _inputTokens = agent.event_loop_metrics.accumulated_usage["inputTokens"]
    _outputTokens = agent.event_loop_metrics.accumulated_usage["outputTokens"]
    _totalTokens = agent.event_loop_metrics.accumulated_usage["totalTokens"]

    # Only update if metrics present
    if _latencyMs > 0:
        # Fetch last message
        doc = self.session_repository.collection.find_one(
            {"_id": self.session_id},
            {f"agents.{agent.agent_id}.messages": {"$slice": -1}}
        )

        if doc and "agents" in doc and agent.agent_id in doc["agents"]:
            messages = doc["agents"][agent.agent_id].get("messages", [])
            if messages:
                last_message_id = messages[-1]["message_id"]

                # Build update operation
                update_data = {
                    f"agents.{agent.agent_id}.messages.$.event_loop_metrics.accumulated_metrics": {
                        "latencyMs": _latencyMs,
                    },
                    f"agents.{agent.agent_id}.messages.$.event_loop_metrics.accumulated_usage": {
                        "inputTokens": _inputTokens,
                        "outputTokens": _outputTokens,
                        "totalTokens": _totalTokens,
                    },
                }

                # Update last message with metrics
                self.session_repository.collection.update_one(
                    {
                        "_id": self.session_id,
                        f"agents.{agent.agent_id}.messages.message_id": last_message_id,
                    },
                    {"$set": update_data},
                )
```

**Why Last Message?**

Metrics represent the work done for the last response (assistant message):
1. User sends message
2. `append_message(user_message)`
3. Agent processes (populates metrics)
4. `append_message(assistant_message)`
5. `sync_agent()` → metrics added to assistant message

**Filtering on Read**:

Repository filters out metrics when returning SessionMessage objects (which don't have event_loop_metrics field):

```python
def read_message(self, session_id, agent_id, message_id, **kwargs):
    # ... fetch message data ...

    # Filter out metrics fields that SessionMessage doesn't accept
    metrics_fields = ["event_loop_metrics"]
    filtered_msg_data = {
        k: v for k, v in msg_data.items() if k not in metrics_fields
    }
    return SessionMessage(**filtered_msg_data)
```

**Code Reference**:
- Capture: `/workspace/src/mongodb_session_manager/mongodb_session_manager.py` (lines 216-254)
- Filter: `/workspace/src/mongodb_session_manager/mongodb_session_repository.py` (lines 428-433, 549-553)

## Error Handling Philosophy

### Problem Context

Errors can occur at multiple levels:
- Network failures (MongoDB unreachable)
- Data errors (invalid document structure)
- Business logic errors (session not found)
- Hook errors (SNS notification failed)

**Question**: How should errors be handled at each level?

### Principles

#### 1. Fail Fast for Critical Errors

**Critical errors** = errors that prevent core functionality

```python
def create_session(self, session: Session, **kwargs):
    try:
        self.collection.insert_one(session_doc)
        logger.info(f"Created session: {session.session_id}")
    except PyMongoError as e:
        logger.error(f"Failed to create session {session.session_id}: {e}")
        raise  # Re-raise - caller must handle
```

**Rationale**: If we can't create a session, the application can't function. Caller should know immediately.

#### 2. Graceful Degradation for Non-Critical Features

**Non-critical** = features that enhance but aren't required

```python
async def on_feedback_add(self, session_id, feedback):
    try:
        await asyncio.to_thread(
            publish_message,
            topic_arn=self.topic_arn,
            message=message
        )
    except Exception as e:
        # Log error but don't raise
        logger.error(f"Error sending feedback to SNS: {e}", exc_info=True)
        # Feedback is still stored in MongoDB
```

**Rationale**: If SNS notification fails, that's unfortunate but feedback is still saved. Don't fail the whole operation.

#### 3. Comprehensive Logging

```python
logger.info(f"Created session: {session_id}")          # Success
logger.warning(f"Session not found: {session_id}")     # Expected errors
logger.error(f"Failed to create session: {e}")         # Unexpected errors
logger.debug(f"Message structure: {msg_data.keys()}")  # Debugging
```

**Log Levels**:
- `DEBUG`: Detailed information for debugging
- `INFO`: Normal operations (created, updated, etc.)
- `WARNING`: Expected errors (not found, validation)
- `ERROR`: Unexpected errors (network, database)

#### 4. Specific Exception Types

```python
# Bad: Generic exception
def read_session(self, session_id):
    doc = self.collection.find_one({"_id": session_id})
    if not doc:
        raise Exception("Not found")  # Too generic

# Good: Specific handling
def read_session(self, session_id):
    try:
        doc = self.collection.find_one({"_id": session_id})
        if not doc:
            logger.debug(f"Session not found: {session_id}")
            return None  # Expected case
    except PyMongoError as e:
        logger.error(f"Failed to read session {session_id}: {e}")
        raise  # Unexpected error
```

#### 5. Hook Error Isolation

```python
def metadata_hook_wrapper(original_func, action, session_id, **kwargs):
    # Always call original function
    if action == "update":
        result = original_func(kwargs["metadata"])

    # Non-critical hook logic
    try:
        send_to_sqs(session_id, kwargs["metadata"])
    except Exception as e:
        logger.error(f"Error sending to SQS: {e}")
        # Don't raise - metadata update succeeded

    return result
```

**Rationale**: Original operation must succeed even if hook fails.

### Error Handling Matrix

| Error Type | Strategy | Example |
|-----------|----------|---------|
| Connection failure | Raise | MongoDB unreachable |
| Session not found | Return None | Expected case |
| Invalid data | Raise | Malformed document |
| Hook failure | Log, don't raise | SNS notification failed |
| Index creation failure | Log warning | Index already exists |
| Metrics missing | Skip silently | Agent didn't populate metrics |

### Code Reference

- Critical errors: `/workspace/src/mongodb_session_manager/mongodb_session_repository.py` (lines 214-219)
- Hook errors: `/workspace/src/mongodb_session_manager/hooks/feedback_sns_hook.py` (lines 194-202)
- Graceful degradation: `/workspace/src/mongodb_session_manager/hooks/metadata_sqs_hook.py` (lines 202-210)

## Repository Pattern

### Problem Context

Strands SDK defines a `SessionRepository` interface. We need MongoDB implementation.

**Question**: Should we implement interface directly or add custom methods?

### Decision: Interface + Extensions

**Base Interface** (from Strands SDK):
```python
class SessionRepository:
    def create_session(self, session: Session, **kwargs) -> Session
    def read_session(self, session_id: str, **kwargs) -> Optional[Session]
    def create_agent(self, session_id: str, session_agent: SessionAgent, **kwargs)
    def read_agent(self, session_id: str, agent_id: str, **kwargs) -> Optional[SessionAgent]
    # ... more standard methods ...
```

**Our Implementation**:
```python
class MongoDBSessionRepository(SessionRepository):
    # Implement all interface methods
    def create_session(self, session: Session, **kwargs) -> Session:
        # MongoDB-specific implementation

    # Add custom methods
    def update_metadata(self, session_id: str, metadata: Dict[str, Any]):
        # Not in base interface, but needed for our features

    def add_feedback(self, session_id: str, feedback: Dict[str, Any]):
        # Custom feature
```

**Rationale**:

1. **Compatibility**: Implements interface completely (can swap implementations)
2. **Extensions**: Adds methods for features not in base SDK
3. **Encapsulation**: All MongoDB logic in one place
4. **Testability**: Easy to mock interface methods

**Code Reference**:
- Interface implementation: `/workspace/src/mongodb_session_manager/mongodb_session_repository.py` (class definition)
- Custom methods: Lines 577-653

## Async Hook Execution

### Problem Context

Hook operations (SNS, SQS) are I/O-bound and slow. They shouldn't block the main thread.

**Question**: How to execute hooks asynchronously without complicating the sync API?

### Solution: Thread-Safe Async Detection

```python
def feedback_hook_wrapper(original_func, action, session_id, **kwargs):
    # Call original first (synchronous)
    result = original_func(kwargs["feedback"])

    # Send notification asynchronously
    try:
        # Detect if we're in an async context
        try:
            loop = asyncio.get_running_loop()
            # We're in async context - create task
            loop.create_task(
                sns_hook.on_feedback_add(session_id, kwargs["feedback"])
            )
        except RuntimeError:
            # No running loop - create thread with new loop
            import threading

            def run_hook():
                asyncio.run(
                    sns_hook.on_feedback_add(session_id, kwargs["feedback"])
                )

            thread = threading.Thread(target=run_hook, daemon=True)
            thread.start()
    except Exception as e:
        logger.error(f"Error sending feedback notification: {e}")

    return result
```

**Why This Design?**

1. **Async-Aware**: Uses event loop if available (FastAPI, async apps)
2. **Sync-Compatible**: Falls back to threading for sync contexts
3. **Non-Blocking**: Original operation completes immediately
4. **Daemon Thread**: Won't block application shutdown
5. **Error Isolation**: Hook errors don't affect main operation

**Execution Contexts**:

| Context | Detection | Execution |
|---------|-----------|-----------|
| FastAPI async endpoint | `get_running_loop()` succeeds | `create_task()` in existing loop |
| Sync script | `RuntimeError` | New thread with `asyncio.run()` |
| Jupyter notebook | `get_running_loop()` succeeds | `create_task()` in notebook loop |

**Code Reference**:
- SNS hook: `/workspace/src/mongodb_session_manager/hooks/feedback_sns_hook.py` (lines 236-256)
- SQS hook: `/workspace/src/mongodb_session_manager/hooks/metadata_sqs_hook.py` (lines 268-289)

---

## Summary

The design decisions in MongoDB Session Manager prioritize:

1. **Performance**: Connection pooling, partial updates, atomic operations
2. **Correctness**: Timestamp preservation, atomic metadata updates, transaction safety
3. **Flexibility**: Smart connection management, hook system, multiple deployment patterns
4. **Reliability**: Comprehensive error handling, graceful degradation
5. **Usability**: Simple API, automatic metrics, sensible defaults
6. **Extensibility**: Hook system for custom behavior without modifying core

Each decision was made with production use cases in mind, balancing simplicity with power, and providing clear upgrade paths for future enhancements.
