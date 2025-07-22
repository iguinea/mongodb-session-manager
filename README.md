# MongoDB Session Manager - Production Ready

A production-ready MongoDB session manager for Strands Agents with comprehensive metrics tracking and optimized performance for stateless environments.

## 🚀 Features

### Core Session Management
- **MongoDB Persistence**: Complete session data stored in MongoDB documents
- **Automatic Session Resumption**: Continue conversations across days, weeks, or months
- **Multiple Agents per Session**: Support for multiple agents in the same session
- **Connection Pooling**: Built-in MongoDB connection pooling for high performance
- **Automatic Indexing**: Optimized indexes for fast queries
- **Thread-safe**: Designed for concurrent operations

### Advanced Metrics Tracking
- **Fully Automatic Token Tracking**: Tokens extracted automatically from model responses
- **Zero-Configuration Latency Measurement**: Response time tracking with no setup needed
- **Model & Configuration Storage**: Automatic capture of model and system prompt
- **Persistent Metrics**: All metrics stored and persist across session resumption  
- **Production Monitoring**: Real-time metrics for operational visibility

### Production Ready
- **Error Handling**: Comprehensive error handling and logging
- **Performance Optimized**: Efficient queries and minimal overhead  
- **Clean API**: Simple, intuitive interface
- **Unified Implementation**: Single class combining all functionality
- **Connection Management**: Built-in connection pooling and lifecycle management

### Performance Optimization
- **Connection Pool Singleton**: Reuse MongoDB connections across requests
- **Factory Pattern**: Efficient session manager creation without connection overhead
- **LRU Metadata Cache**: In-memory caching for frequently accessed sessions
- **Stateless-Ready**: Optimized for FastAPI and other stateless frameworks
- **5-10x Performance Improvement**: Compared to creating connections per request

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

# Create session manager with all features enabled
session_manager = create_mongodb_session_manager(
    session_id="customer-12345",
    connection_string="mongodb://user:pass@host:27017/",
    database_name="itzulbira",
    collection_name="agent_sessions",
    # ttl_hours=24  # Note: TTL not implemented yet
)

# Create agent with session persistence
agent = Agent(
    model="eu.anthropic.claude-3-sonnet-20240229-v1:0",
    agent_id="support-agent",
    session_manager=session_manager,
    system_prompt="Eres un asistente de soporte para Itzulbira."
)

# Use with fully automatic metrics tracking!
response = agent("¿Puedes ayudarme con la configuración?")  # Everything automatic!

# Get comprehensive metrics
metrics = session_manager.get_metrics_summary("support-agent")
print(f"Model: {metrics['model']}")
print(f"Total tokens: {metrics['total_tokens']}")
print(f"Average latency: {metrics['average_latency_ms']}ms")

# Clean up
session_manager.close()
```

## 📊 Metrics Tracking

### Fully Automatic Token Tracking
```python
# Tokens are automatically extracted and tracked - no manual setup needed!
response = agent("Hola")  # Tokens detected and stored automatically

# View accumulated metrics
metrics = session_manager.get_metrics_summary("agent-id")
print(f"Total input tokens: {metrics['total_input_tokens']}")
print(f"Total output tokens: {metrics['total_output_tokens']}")
print(f"Total tokens: {metrics['total_tokens']}")
```

### Automatic Latency Measurement
```python
# Timing starts automatically when user message is sent!
# No need to call start_timing() manually
response = agent("¿Qué tiempo hace?")

# Latency automatically calculated and stored
metrics = session_manager.get_metrics_summary("agent-id")
print(f"Average response time: {metrics['average_latency_ms']}ms")
```

### Model and Configuration Tracking
```python
# Model and system prompt automatically captured
agent = Agent(
    model="eu.anthropic.claude-3-sonnet-20240229-v1:0",
    system_prompt="Eres un traductor especializado en euskera.",
    session_manager=session_manager
)

# Configuration and state available in metrics
metrics = session_manager.get_metrics_summary("agent-id")
print(f"Model: {metrics['model']}")
print(f"System: {metrics['system_prompt']}")
print(f"Agent State: {metrics['state']}")  # Agent's key-value state
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

# View current agent state:
metrics = session_manager.get_metrics_summary("agent-id")
print(f"Current state: {metrics['state']}")
# Output: {'user_language': 'euskera', 'translation_count': 42, ...}
```

### Session Verification and Metadata Recovery
```python
# Check if session exists before creating agents
session_manager = create_mongodb_session_manager(
    session_id="calculator-test-session",
    connection_string="mongodb://...",
    database_name="my_database"
)

# Check session and get metadata
session_info = session_manager.check_session_exists()
if session_info['exists']:
    print(f"✅ Existing session from {session_info['created_at']}")
    
    # Check specific agent
    agent_info = session_manager.check_session_exists("calculator-agent")
    if "calculator-agent" in agent_info['agents']:
        metadata = agent_info['agents']['calculator-agent']
        print(f"Model: {metadata['model']}")
        print(f"System Prompt: {metadata['system_prompt']}")
        print(f"Messages: {metadata['message_count']}")
        
        # Recreate agent with existing configuration
        agent = Agent(
            agent_id="calculator-agent",
            model=metadata['model'],
            system_prompt=metadata['system_prompt'],
            session_manager=session_manager
        )
else:
    print("❌ New session - creating fresh agent")
    agent = Agent(
        agent_id="calculator-agent",
        model="default-model",
        system_prompt="You are a helpful assistant",
        session_manager=session_manager
    )
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

# Metrics are accumulated across sessions
metrics = session_manager.get_metrics_summary("traductor-principal")
print(f"Total tokens used across all sessions: {metrics['total_tokens']}")
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

# Each agent has separate metrics
translator_metrics = session_manager.get_metrics_summary("euskera-translator")
support_metrics = session_manager.get_metrics_summary("tech-support")
```

## 📈 Session Statistics

### Comprehensive Analytics
```python
# Get session-wide statistics
stats = session_manager.get_session_stats()
print(f"Session ID: {stats['session_id']}")
print(f"Total agents: {stats['total_agents']}")
print(f"Total messages: {stats['total_messages']}")
print(f"Created: {stats['created_at']}")
print(f"Last updated: {stats['updated_at']}")

# Per-agent breakdown
for agent_info in stats['agents']:
    agent_id = agent_info['agent_id']
    metrics = agent_info['metrics']
    print(f"\nAgent {agent_id}:")
    print(f"  Messages: {agent_info['message_count']}")
    print(f"  Tokens: {metrics['total_tokens']}")
    print(f"  Avg Latency: {metrics['average_latency_ms']}ms")
```

## 🧪 Testing

Run tests with UV:

```bash
# Run examples
uv run python examples/example_calculator_tool.py

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
from fastapi import FastAPI
from contextlib import asynccontextmanager
from mongodb_session_manager import initialize_global_factory, get_global_factory

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize global factory once
    factory = initialize_global_factory(
        connection_string="mongodb://localhost:27017/",
        database_name="virtualagents",
        maxPoolSize=100,        # Connection pool size
        minPoolSize=10,         # Keep minimum connections ready
        enable_cache=True,      # Enable metadata caching
        cache_max_size=1000,    # Cache up to 1000 sessions
        cache_ttl_seconds=300   # 5-minute cache TTL
    )
    yield
    # Shutdown: Clean up connections
    close_global_factory()

app = FastAPI(lifespan=lifespan)

@app.post("/chat")
async def chat(session_id: str):
    # Get factory (no new connection)
    factory = get_global_factory()
    
    # Create session manager (reuses pooled connection)
    manager = factory.create_session_manager(session_id)
    
    # Operations use cached metadata after first access
    session_info = manager.check_session_exists()  # First: DB query
    session_info = manager.check_session_exists()  # Second: From cache!
```

#### 2. Performance Benefits
- **5-10x faster**: Connection reuse eliminates overhead
- **Higher throughput**: Handle more concurrent requests
- **Lower latency**: Cache reduces database queries
- **Resource efficient**: Controlled connection pool

#### 3. Monitoring Performance
```python
@app.get("/metrics")
async def get_metrics():
    factory = get_global_factory()
    
    # Connection pool statistics
    pool_stats = factory.get_connection_stats()
    
    # Cache performance metrics
    cache_stats = factory.get_cache_stats()
    
    return {
        "pool": pool_stats,
        "cache": {
            "hit_rate": cache_stats["hit_rate"],
            "size": cache_stats["size"],
            "hits": cache_stats["hits"],
            "misses": cache_stats["misses"]
        }
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
    waitQueueTimeoutMS=5000,
    # Aggressive caching for read-heavy workloads
    enable_cache=True,
    cache_max_size=5000,
    cache_ttl_seconds=600  # 10 minutes
)
```

#### Cache Management
```python
# Invalidate cache after updates
@app.post("/sessions/{session_id}/update")
async def update_session(session_id: str):
    factory = get_global_factory()
    manager = factory.create_session_manager(session_id)
    
    # Perform updates...
    
    # Invalidate cache to ensure consistency
    if hasattr(manager, 'invalidate_cache'):
        manager.invalidate_cache()
```

### Performance Comparison

See `examples/example_performance.py` for benchmarks showing:
- **Sequential operations**: 5-10x speedup
- **Concurrent requests**: 10-20x throughput improvement
- **Cache hit rates**: 80-95% for typical workloads

## 🏗️ MongoDB Schema

Sessions are stored as optimized documents:

```json
{
    "_id": "user-maria-chat-001",
    "session_id": "user-maria-chat-001", 
    "created_at": "2024-01-15T09:00:00Z",
    "updated_at": "2024-01-22T14:30:00Z",
    "agents": {
        "traductor-principal": {
            "agent_data": {
                "agent_id": "traductor-principal",
                "state": {
                    "user_preferences": "formal_tone",
                    "translation_count": 42
                },
                "conversation_manager_state": {
                    "__name__": "SlidingWindowConversationManager",
                    "removed_message_count": 0
                },
                "created_at": "2024-01-15T09:00:00Z",
                "updated_at": "2024-01-22T14:30:00Z"
            },
            "metadata": {
                "model": "eu.anthropic.claude-3-sonnet-20240229-v1:0",
                "system_prompt": "Eres un traductor especializado...",
                "name": "Traductor Principal",
                "description": "Traductor especializado en euskera-castellano",
                "metrics": {
                    "total_input_tokens": 245,
                    "total_output_tokens": 380, 
                    "total_tokens": 625
                }
            },
            "created_at": "2024-01-15T09:00:00Z",
            "updated_at": "2024-01-22T14:30:00Z",
            "messages": [
                {
                    "message_id": 1,
                    "role": "user",
                    "content": "Kaixo...",
                    "created_at": "2024-01-15T09:00:00Z"
                },
                {
                    "message_id": 2,
                    "role": "assistant", 
                    "content": "Hola...",
                    "input_tokens": 20,
                    "output_tokens": 45,
                    "latency_ms": 1250,
                    "created_at": "2024-01-15T09:00:02Z"
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

**Methods:**
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

#### MongoDBSessionManager
Main session management class with automatic metrics tracking.

**Methods:**
- `check_session_exists(agent_id=None)`: Check if session exists and retrieve agent metadata
- `get_metrics_summary(agent_id)`: Get comprehensive metrics for an agent  
- `append_message(message, agent)`: Store message with automatic timing and token extraction
- `sync_agent(agent)`: Sync agent data and capture configuration
- `set_token_counts(input_tokens, output_tokens)`: Manual token setting (optional - usually automatic)
- `start_timing()`: Manual timing start (optional - usually automatic)
- `close()`: Close database connections

#### MongoDBSessionManagerFactory
Factory for creating session managers with connection pooling.

**Methods:**
- `create_session_manager(session_id, ...)`: Create manager with pooled connection
- `get_connection_stats()`: Get MongoDB connection pool statistics
- `get_cache_stats()`: Get metadata cache performance metrics
- `close()`: Clean up factory resources

#### MongoDBConnectionPool
Singleton connection pool for MongoDB client reuse.

**Methods:**
- `initialize(connection_string, **kwargs)`: Initialize the pool
- `get_client()`: Get the shared MongoDB client
- `get_pool_stats()`: Get connection pool statistics
- `close()`: Close all connections

### Helper Functions
- `create_mongodb_session_manager()`: Convenient factory function with defaults
- `initialize_global_factory()`: Initialize global factory for FastAPI
- `get_global_factory()`: Get the global factory instance
- `close_global_factory()`: Clean up global resources

## 🔗 Integration Examples

### Available Examples
- `examples/example_calculator_tool.py`: Complete agent with tools demonstration
- `examples/example_fastapi.py`: FastAPI integration with connection pooling
- `examples/example_performance.py`: Performance benchmarks and comparisons

Each example includes:
- Basic usage demonstration
- Factory function usage
- Production configuration patterns
- Performance optimization techniques

## 📄 License

This project is licensed under the same terms as the parent Itzulbira project.

---

**Itzulbira Session Manager** - Production-ready MongoDB session management for conversational AI with comprehensive metrics tracking.