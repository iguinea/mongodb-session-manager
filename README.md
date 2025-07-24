# MongoDB Session Manager

A MongoDB session manager for Strands Agents that provides persistent storage for agent conversations and state, with connection pooling optimized for stateless environments.

## 🚀 Features

### Core Session Management
- **MongoDB Persistence**: Complete session data stored in MongoDB documents
- **Session Resumption**: Continue conversations across sessions
- **Multiple Agents per Session**: Support for multiple agents in the same session
- **Connection Pooling**: Built-in MongoDB connection pooling for high performance
- **Automatic Indexing**: Optimized indexes for timestamp queries
- **Thread-safe**: Designed for concurrent operations

### Metrics Support
- **Event Loop Metrics**: Captures metrics from agent's event_loop_metrics during sync
- **Agent State Persistence**: Stores and retrieves agent state across sessions
- **Message History**: Complete conversation history with timestamps

### Production Features
- **Error Handling**: Comprehensive error handling and logging
- **Connection Management**: Smart connection lifecycle management (owned vs borrowed)
- **Clean API**: Simple, intuitive interface compatible with Strands SDK

### Performance Optimization
- **Connection Pool Singleton**: Reuse MongoDB connections across requests
- **Factory Pattern**: Efficient session manager creation without connection overhead
- **Stateless-Ready**: Optimized for FastAPI and other stateless frameworks
- **Reduced Connection Overhead**: Significant performance improvement over per-request connections

## 📦 Installation

```bash
# Install dependencies using UV
uv sync

# Or with pip
pip install pymongo strands-agents
```

## 🏃 Quick Start

```python
from strands import Agent
from mongodb_session_manager import create_mongodb_session_manager

# Create session manager
session_manager = create_mongodb_session_manager(
    session_id="customer-12345",
    connection_string="mongodb://user:pass@host:27017/",
    database_name="my_database",
    collection_name="agent_sessions"
)

# Create agent with session persistence
agent = Agent(
    model="eu.anthropic.claude-3-sonnet-20240229-v1:0",
    agent_id="support-agent",
    session_manager=session_manager,
    system_prompt="You are a helpful assistant."
)

# Use the agent - conversation is automatically persisted
response = agent("Hello, can you help me?")

# Sync agent to persist state and metrics
session_manager.sync_agent(agent)

# Clean up
session_manager.close()
```

## 📊 Event Loop Metrics

### Automatic Metrics Capture
The session manager automatically captures metrics from the agent's event loop during sync operations:

```python
# Use the agent
response = agent("Hello")

# Sync agent - this captures and stores event loop metrics
session_manager.sync_agent(agent)

# Metrics are automatically stored with the last message in MongoDB:
# - latencyMs: Response latency from agent's event loop
# - inputTokens: Input token count from agent
# - outputTokens: Output token count from agent  
# - totalTokens: Total tokens used
```

### How It Works
1. When you call `sync_agent()`, the manager reads metrics from `agent.event_loop_metrics`
2. If latency > 0, it updates the last message in MongoDB with these metrics
3. Metrics are stored in the `event_loop_metrics` field of the message document

### Accessing Metrics
Since metrics are stored in MongoDB, you can:
- Query the database directly to retrieve message metrics
- Use MongoDB aggregation pipelines for analytics
- Build custom reporting on top of the stored data
```

### Agent State Persistence
```python
# The session manager automatically captures and persists agent state
# Agent state is a key-value store for stateful information

# In your agent or tools:
agent.state.set("user_language", "euskera")
agent.state.set("translation_count", 42)
agent.state.set("preferences", {"tone": "formal", "dialect": "bizkaiera"})

# State is automatically saved to MongoDB in agent_data.state
# and restored when the session is resumed

# Agent state is persisted automatically during sync_agent()
# To view state, you need to query MongoDB directly or
# use the agent's state object:
print(f"Current state: {agent.state.to_dict()}")
# Output: {'user_language': 'euskera', 'translation_count': 42, ...}
```

### Session Persistence Example
```python
# First session - create and use agent
session_manager = create_mongodb_session_manager(
    session_id="user-session-001",
    connection_string="mongodb://...",
    database_name="my_database"
)

agent = Agent(
    agent_id="assistant",
    model="claude-3-sonnet",
    system_prompt="You are a helpful assistant",
    session_manager=session_manager
)

response = agent("Remember my name is Alice")
session_manager.sync_agent(agent)
session_manager.close()

# Later session - resume conversation
session_manager = create_mongodb_session_manager(
    session_id="user-session-001",  # Same session ID
    connection_string="mongodb://...",
    database_name="my_database"
)

# Recreate agent with same ID
agent = Agent(
    agent_id="assistant",  # Same agent ID
    model="claude-3-sonnet",
    session_manager=session_manager
)

# Agent has access to previous conversation
response = agent("What's my name?")
# Agent will remember "Alice" from previous session
```

## 🔄 Session Persistence

### Day 1: Start Conversation
```python
session_manager = create_mongodb_session_manager(
    session_id="user-maria-chat-001",  # Unique user session
    connection_string="mongodb://...",
    database_name="itzulbira_production"
)

agent = Agent(
    model="eu.anthropic.claude-3-sonnet-20240229-v1:0",
    agent_id="traductor-principal",
    session_manager=session_manager
)

# First interaction - automatically saved
session_manager.set_token_counts(input_tokens=20, output_tokens=45)
response = agent("Kaixo, lagundu ahal didazu euskeratik gaztelaniara itzultzen?")

session_manager.close()
```

### Day 7: Resume Conversation  
```python
# Same session_id to continue
session_manager = create_mongodb_session_manager(
    session_id="user-maria-chat-001",  # Same session ID
    connection_string="mongodb://...",
    database_name="itzulbira_production"
)

agent = Agent(
    model="eu.anthropic.claude-3-sonnet-20240229-v1:0", 
    agent_id="traductor-principal",  # Same agent ID
    session_manager=session_manager
)

# Agent has full conversation history
response = agent("Gogoratzen duzu zer galdetu nuen lehenengo aldiz?")
# Agent can reference previous conversation from day 1

# Metrics from event loop are stored with messages in MongoDB
# Access them via database queries or use factory pattern with caching
```

## 🔧 Production Configuration

### MongoDB Connection with Production Settings
```python
session_manager = MongoDBSessionManager(
    session_id="session-id",
    connection_string="mongodb://user:pass@replica1,replica2,replica3/db?replicaSet=rs0",
    database_name="itzulbira_production",
    collection_name="agent_sessions",
    # Note: TTL functionality not implemented yet
    
    # Production MongoDB settings
    maxPoolSize=100,
    minPoolSize=25,
    maxIdleTimeMS=45000,
    serverSelectionTimeoutMS=5000,
    w="majority",
    journal=True
)
```

### Multiple Agents in Production
```python
# One session can handle multiple specialized agents
session_manager = create_mongodb_session_manager(
    session_id=f"customer-{customer_id}-support",
    connection_string=mongo_uri,
    database_name="itzulbira"
)

# Translation agent
translator = Agent(
    model="eu.anthropic.claude-3-sonnet-20240229-v1:0",
    agent_id="euskera-translator",
    session_manager=session_manager,
    system_prompt="Especialista en traducción euskera-castellano"
)

# Technical support agent  
support = Agent(
    model="eu.anthropic.claude-3-haiku-20240307-v1:0",
    agent_id="tech-support",
    session_manager=session_manager,
    system_prompt="Soporte técnico para problemas de configuración"
)

# Use different agents with automatic separate metrics
translation = translator("Translate: 'Kaixo mundua'")  # Auto-metrics for translator
help_response = support("How do I configure API keys?")  # Auto-metrics for support

# Each agent's messages and event loop metrics are stored separately in MongoDB
```

## 🔍 Current Implementation Status

### ✅ Working Features
- **Full session persistence**: Messages, agents, and state stored in MongoDB
- **Connection pooling**: Singleton pattern for connection reuse
- **Factory pattern**: Efficient session manager creation
- **Automatic metrics capture**: Tokens and latency from agent's event loop
- **Message management**: Full CRUD operations for messages
- **Agent management**: Multiple agents per session with separate histories
- **Timestamp preservation**: Original creation times maintained
- **Thread-safe operations**: Designed for concurrent use
- **Smart connection handling**: Supports both owned and borrowed MongoDB clients

### ❌ Not Implemented
- **get_metrics_summary()**: Method referenced in docs but not implemented
- **check_session_exists()**: Method referenced in docs but not implemented
- **set_token_counts()**: Manual token setting not implemented
- **start_timing()**: Manual timing not implemented
- **TTL support**: Session expiration not implemented
- **Caching layer**: SessionMetadataCache referenced but not implemented

## 🧪 Testing

Run tests with UV:

```bash
# Run examples
uv run python examples/example_calculator_tool.py
uv run python examples/example_fastapi.py
uv run python examples/example_performance.py
uv run python examples/example_stream_async.py

# Run tests (when test suite is created)
uv run pytest tests/
```

Test suite will include:
- ⏳ Basic functionality testing
- ⏳ Metrics tracking validation  
- ⏳ Session persistence verification
- ⏳ Multiple agent scenarios
- ⏳ Latency measurement accuracy
- ⏳ Error handling and edge cases
- ⏳ Performance benchmarking
- ⏳ Connection pooling tests
- ⏳ Index creation verification

## 🚀 Performance Optimization for Stateless Environments

### The Problem: Stateless FastAPI
In a typical stateless FastAPI application, each request would:
- Create a new MongoDB connection
- Perform operations
- Close the connection

This leads to:
- **Connection overhead**: 10-50ms per request
- **Resource exhaustion**: Too many connections
- **Poor scalability**: Limited concurrent requests

### The Solution: Connection Pooling & Caching

#### 1. Using the Factory Pattern (Recommended)
```python
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
from mongodb_session_manager import initialize_global_factory, get_global_factory, close_global_factory

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize global factory once
    factory = initialize_global_factory(
        connection_string="mongodb://localhost:27017/",
        database_name="virtualagents",
        maxPoolSize=100,        # Connection pool size
        minPoolSize=10,         # Keep minimum connections ready
    )
    
    # Store factory in app state (recommended approach)
    app.state.session_factory = factory
    
    yield
    # Shutdown: Clean up connections
    close_global_factory()

app = FastAPI(lifespan=lifespan)

@app.post("/chat")
async def chat(request: Request, session_id: str):
    # Method 1: Get factory from app state (recommended - more explicit)
    factory = request.app.state.session_factory
    
    # Method 2: Get global factory (alternative - simpler but less flexible)
    # factory = get_global_factory()
    
    # Create session manager (reuses pooled connection)
    manager = factory.create_session_manager(session_id)
```

#### 2. Performance Benefits
- **Faster**: Connection reuse eliminates overhead
- **Higher throughput**: Handle more concurrent requests
- **Resource efficient**: Controlled connection pool

#### 3. Monitoring Performance
```python
@app.get("/metrics")
async def get_metrics():
    factory = get_global_factory()
    
    # Connection pool statistics
    pool_stats = factory.get_connection_stats()
    
    return {
        "pool": pool_stats
    }
```

### Advanced Configuration

#### High-Traffic Production Settings
```python
factory = MongoDBSessionManagerFactory(
    connection_string="mongodb://replica-set/",
    # Optimized for high concurrency
    maxPoolSize=200,
    minPoolSize=50,
    maxIdleTimeMS=30000,
    waitQueueTimeoutMS=5000
)
```


### Performance Comparison

See `examples/example_performance.py` for benchmarks showing:
- **Sequential operations**: Significant speedup
- **Concurrent requests**: Higher throughput with connection pooling

## 🌊 Async Streaming Support

### Real-time Streaming Responses
The session manager fully supports async streaming responses with automatic metrics tracking:

```python
# Create streaming-capable agent
async def stream_handler(session_manager, agent, prompt):
    # Start timing automatically
    session_manager.append_message({"role": "user", "content": prompt}, agent)
    
    response_chunks = []
    
    # Stream response tokens
    async for event in agent.stream_async(prompt):
        if "data" in event:
            response_chunks.append(event["data"])
            yield event["data"]  # Real-time streaming
    
    # Save complete response with metrics
    full_response = "".join(response_chunks)
    session_manager.append_message({"role": "assistant", "content": full_response}, agent)
    session_manager.sync_agent(agent)
```

### Features
- **Token-by-token streaming**: Process responses as they arrive
- **Automatic metrics**: Latency and tokens tracked during streaming
- **Concurrent streams**: Handle multiple streaming sessions simultaneously
- **Error recovery**: Graceful handling of streaming errors
- **Session persistence**: Resume streaming conversations

See `examples/example_stream_async.py` for complete streaming implementation.

## 🏗️ MongoDB Schema

Sessions are stored as nested documents with agents and messages:

```json
{
    "_id": "session-id",
    "session_id": "session-id",
    "session_type": "default",
    "created_at": ISODate("2024-01-15T09:00:00Z"),
    "updated_at": ISODate("2024-01-22T14:30:00Z"),
    "agents": {
        "agent-id": {
            "agent_data": {
                "agent_id": "agent-id",
                "state": {
                    "key": "value"
                },
                "conversation_manager_state": {},
                "created_at": "2024-01-15T09:00:00Z",
                "updated_at": "2024-01-22T14:30:00Z"
            },
            "created_at": ISODate("2024-01-15T09:00:00Z"),
            "updated_at": ISODate("2024-01-22T14:30:00Z"),
            "messages": [
                {
                    "message_id": 1,
                    "role": "user",
                    "content": "Hello",
                    "created_at": ISODate("2024-01-15T09:00:00Z"),
                    "updated_at": ISODate("2024-01-15T09:00:00Z")
                },
                {
                    "message_id": 2,
                    "role": "assistant",
                    "content": "Hi there!",
                    "created_at": ISODate("2024-01-15T09:00:02Z"),
                    "updated_at": ISODate("2024-01-15T09:00:02Z"),
                    "event_loop_metrics": {
                        "accumulated_metrics": {
                            "latencyMs": 250
                        },
                        "accumulated_usage": {
                            "inputTokens": 10,
                            "outputTokens": 20,
                            "totalTokens": 30
                        }
                    }
                }
            ]
        }
    }
}
```

## 🔐 Best Practices

### Session ID Patterns
```python
# Customer support
session_id = f"customer-{customer_id}-support-{date}"

# Translation sessions  
session_id = f"user-{user_id}-translation-{thread_id}"

# Long-term user sessions
session_id = f"user-{user_id}-main-{year}-{month}"
```

### Error Handling
```python
try:
    session_manager = create_mongodb_session_manager(
        session_id=session_id,
        connection_string=mongo_uri,
        database_name="itzulbira"
    )
    
    agent = Agent(session_manager=session_manager, ...)
    response = agent(user_input)
    
except Exception as e:
    logger.error(f"Session error: {e}")
    # Fallback behavior
    
finally:
    if session_manager:
        session_manager.close()
```

### Production Integration
```python
class ItzulbiraService:
    def __init__(self, mongo_uri: str):
        self.mongo_uri = mongo_uri
        
    def create_agent_session(self, user_id: str, agent_type: str = "general"):
        """Create production-ready agent session."""
        session_id = f"user-{user_id}-{agent_type}-{datetime.now().strftime('%Y%m')}"
        
        session_manager = create_mongodb_session_manager(
            session_id=session_id,
            connection_string=self.mongo_uri,
            database_name="itzulbira_production",
            # ttl_hours=168  # TTL not implemented yet
        )
        
        return Agent(
            model="eu.anthropic.claude-3-sonnet-20240229-v1:0",
            agent_id=f"{agent_type}-agent",
            session_manager=session_manager,
            system_prompt=self._get_system_prompt(agent_type)
        )
    
    def chat_with_metrics(self, agent, user_input: str):
        """Production chat with fully automatic metrics."""
        # No setup needed - everything is automatic!
        return agent(user_input)
```

## 📋 API Reference

### Core Classes

#### MongoDBSessionRepository
MongoDB implementation of the `SessionRepository` interface from Strands SDK.

**Implemented Methods:**
- `create_session(session, **kwargs)`: Create a new session in MongoDB
- `read_session(session_id, **kwargs)`: Read a session from MongoDB
- `create_agent(session_id, session_agent, **kwargs)`: Create an agent in a session
- `read_agent(session_id, agent_id, **kwargs)`: Read an agent from a session
- `update_agent(session_id, session_agent, **kwargs)`: Update an agent in a session
- `create_message(session_id, agent_id, session_message, **kwargs)`: Create a message for an agent
- `read_message(session_id, agent_id, message_id, **kwargs)`: Read a specific message
- `update_message(session_id, agent_id, session_message, **kwargs)`: Update a message (for redaction)
- `list_messages(session_id, agent_id, limit, offset, **kwargs)`: List messages with pagination
- `close()`: Close the MongoDB connection (if owned)

**Key Features:**
- Smart connection management (owns vs borrows client)
- Automatic index creation on timestamps
- Filters out `event_loop_metrics` when returning messages
- Preserves original timestamps during updates

#### MongoDBSessionManager
Main session management class extending RepositorySessionManager from Strands SDK.

**Implemented Methods:**
- `__init__()`: Initialize with MongoDB connection options
- `append_message(message, agent)`: Store message in session
- `redact_latest_message(redact_message, agent)`: Redact the latest message
- `sync_agent(agent)`: Sync agent data and capture event loop metrics
- `initialize(agent)`: Initialize an agent with the session
- `close()`: Close database connections

**Automatic Features:**
- Captures metrics from `agent.event_loop_metrics` during `sync_agent()`
- Updates last message with token counts and latency
- Handles MongoDB connection lifecycle intelligently

#### MongoDBSessionManagerFactory
Factory for creating session managers with connection pooling.

**Implemented Methods:**
- `__init__(connection_string, database_name, collection_name, client, **kwargs)`: Initialize factory
- `create_session_manager(session_id, database_name, collection_name, **kwargs)`: Create manager with pooled connection
- `get_connection_stats()`: Get MongoDB connection pool statistics
- `close()`: Clean up factory resources

**Global Factory Functions:**
- `initialize_global_factory(...)`: Set up singleton factory for application
- `get_global_factory()`: Access the global factory instance
- `close_global_factory()`: Clean up global resources

#### MongoDBConnectionPool
Singleton connection pool for MongoDB client reuse.

**Implemented Methods:**
- `initialize(connection_string, **kwargs)`: Initialize the pool with smart defaults
- `get_client()`: Get the shared MongoDB client
- `get_pool_stats()`: Get connection pool statistics
- `close()`: Close all connections

**Default Configuration:**
- `maxPoolSize`: 100
- `minPoolSize`: 10
- `maxIdleTimeMS`: 30000 (30 seconds)
- `waitQueueTimeoutMS`: 5000 (5 seconds)
- `retryWrites`: True
- `retryReads`: True

### Helper Functions

#### create_mongodb_session_manager
```python
create_mongodb_session_manager(
    session_id: str,
    connection_string: Optional[str] = None,
    database_name: str = "database_name",
    collection_name: str = "collection_name",
    client: Optional[MongoClient] = None,
    **kwargs
) -> MongoDBSessionManager
```
Convenience function to create a session manager with default settings.

## 🔗 Integration Examples

### Available Examples
- `examples/example_calculator_tool.py`: Complete agent with tools demonstration
- `examples/example_fastapi.py`: FastAPI integration with connection pooling
- `examples/example_performance.py`: Performance benchmarks and comparisons
- `examples/example_stream_async.py`: Async streaming responses with real-time metrics
- `examples/example_fastapi_streaming.py`: FastAPI with streaming responses and proper factory usage

Each example includes:
- Basic usage demonstration
- Factory function usage
- Production configuration patterns
- Performance optimization techniques

## 🎮 Interactive Chat Playground

### Overview
The project includes an interactive web-based chat interface to test the MongoDB session manager with a real-time streaming FastAPI backend. This playground demonstrates session persistence, real-time token streaming, and metadata tracking.

### Quick Start
The playground uses a Makefile for easy startup:

```bash
# Terminal 1: Start the FastAPI backend (port 8880)
cd playground/chat
make backend-fastapi-streaming

# Terminal 2: Start the frontend web server (port 8881)
cd playground/chat
make frontend
```

Then open your browser to: http://localhost:8881/chat.html

### Architecture
- **Frontend** (port 8881): Static HTML/JS chat interface with real-time streaming support
- **Backend** (port 8880): FastAPI server with MongoDB session management and streaming responses
- **CORS**: Enabled to allow cross-origin requests between frontend and backend

### Features
- **Real-time Streaming**: Watch responses appear token-by-token as they're generated
- **Session Persistence**: Each chat session is uniquely identified and stored in MongoDB
- **Metadata View**: Toggle to see session information, metrics, and statistics
- **Responsive UI**: Modern chat interface with Tailwind CSS styling
- **Automatic Metrics**: Token usage and latency tracked automatically

### How It Works
1. The frontend generates a unique session ID for each browser session
2. Messages are sent to the FastAPI backend with the session ID in headers
3. The backend uses MongoDB session manager to persist conversations
4. Responses are streamed back in real-time using Server-Sent Events
5. All metrics (tokens, latency) are automatically tracked and stored

### Backend Configuration
The example FastAPI server (`examples/example_fastapi_streaming.py`) demonstrates:
- Global factory initialization with connection pooling
- Session manager creation per request (reusing connections)
- Streaming responses with automatic metrics tracking
- Agent with custom tools for state management
- Health and metrics endpoints for monitoring

### Frontend Features
The chat interface (`playground/chat/chat.html`) includes:
- Floating action button (FAB) to open chat
- Slide-out chat panel with message history
- Real-time message streaming with typewriter effect
- Metadata panel showing session details and statistics
- Markdown rendering for formatted responses
- Auto-scrolling to latest messages

### Customization
You can customize the chat behavior by modifying:
- **System Prompt**: Edit `_AGENT_PROMPT` in `example_fastapi_streaming.py`
- **Model**: Change the model in the Agent initialization
- **Tools**: Add or modify tools available to the agent
- **UI**: Modify `chat.html` and `chat-widget.js` for UI changes

## 📄 License

This project is licensed under the same terms as the parent Itzulbira project.

---

**Itzulbira Session Manager** - Production-ready MongoDB session management for conversational AI with comprehensive metrics tracking.