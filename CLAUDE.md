# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the MongoDB Session Manager - a MongoDB session manager library for Strands Agents that provides persistent storage for agent conversations and state, with connection pooling optimized for stateless environments. The project uses UV as its package manager and Python 3.11+.

## Development Environment

This project uses UV (Python package and project manager) for dependency management. All Python commands should be run through UV.

## Common Development Commands

```bash
# Install dependencies
uv sync

# Run example scripts
uv run python examples/example_calculator_tool.py
uv run python examples/example_fastapi.py
uv run python examples/example_performance.py
uv run python examples/example_stream_async.py

# Run tests (when test suite is created)
uv run pytest tests/

# Add a new dependency
uv add <package-name>

# Add a development dependency
uv add --dev <package-name>

# Build the package
uv build

# Run linting/formatting
uv run ruff check .
uv run ruff format .

# Run the interactive chat playground
cd playground/chat
make frontend              # Start frontend server on port 8881
make backend-fastapi-streaming  # Start backend API on port 8880
```

## Project Structure

```
mongodb-session-manager/
├── src/
│   └── mongodb_session_manager/           # Package directory
│       ├── __init__.py                    # Package root with exports
│       ├── mongodb_session_manager.py     # Main session manager implementation
│       ├── mongodb_session_repository.py  # MongoDB repository implementation
│       ├── mongodb_connection_pool.py     # Singleton connection pool
│       ├── mongodb_session_factory.py     # Factory pattern implementation
├── examples/                              # Example scripts
│   ├── example_calculator_tool.py         # Complete agent example with tools
│   ├── example_fastapi.py                 # FastAPI integration example
│   ├── example_performance.py             # Performance benchmarks
│   ├── example_stream_async.py            # Async streaming with real-time metrics
│   └── example_fastapi_streaming.py       # FastAPI with streaming and factory pattern
├── playground/                            # Interactive demos
│   └── chat/                              # Web-based chat interface
│       ├── chat.html                      # Chat UI with real-time streaming
│       ├── chat-widget.js                 # JavaScript for chat functionality
│       └── Makefile                       # Commands to run frontend/backend
├── tests/                                 # Test directory (to be created)
├── pyproject.toml                         # Project configuration
├── uv.lock                                # UV lock file
└── README.md                              # User documentation
```

## Architecture Notes

### Core Components

1. **MongoDBSessionRepository** (`mongodb_session_repository.py`): Implements the `SessionRepository` interface from Strands SDK
   - Handles all MongoDB operations (CRUD for sessions, agents, messages)
   - Now accepts optional MongoDB client to enable connection reuse
   - Serializes/deserializes datetime objects for MongoDB storage
   - Smart connection lifecycle management (owns vs borrowed client)

2. **MongoDBSessionManager** (`mongodb_session_manager.py`): Extends `RepositorySessionManager` from Strands SDK
   - Provides high-level session management interface
   - Integrates with Strands Agent lifecycle hooks
   - **Event Loop Metrics**: Captures metrics from agent's event_loop_metrics during sync_agent()
   - **Simplified Implementation**: Many automatic features have been commented out or removed
   - **Note**: Methods like check_session_exists() and get_metrics_summary() are not implemented in base class

3. **MongoDBConnectionPool** (`mongodb_connection_pool.py`): Singleton pattern for MongoDB client management
   - Thread-safe connection pool shared across all session managers
   - Configurable pool sizes and timeouts
   - Built-in connection statistics and monitoring
   - Prevents connection exhaustion in high-traffic scenarios

4. **MongoDBSessionManagerFactory** (`mongodb_session_factory.py`): Factory pattern for optimized session manager creation
   - Manages shared MongoDB connection pool
   - Creates session managers without connection overhead
   - Perfect for stateless environments like FastAPI


6. **Helper Functions** (in `__init__.py` and `mongodb_session_factory.py`):
   - `create_mongodb_session_manager()`: Convenience function to create session manager
   - `initialize_global_factory()`: Set up global factory for FastAPI
   - `get_global_factory()`: Access the global factory instance
   - `close_global_factory()`: Clean up global resources

### MongoDB Schema

Sessions are stored as single documents with embedded agents and messages:
- Collection: Configurable (defaults to `collection_name` parameter)
- Document structure: 
  - Root: session document with `_id`, `session_id`, `session_type`, timestamps
  - Agents: Nested under `agents` object, keyed by agent_id
  - Messages: Array within each agent, with auto-incrementing message_id
  - Metrics: Stored in `event_loop_metrics` field of assistant messages
- Indexes: Automatically created on `created_at` and `updated_at` fields

### Key Design Decisions

- **Document-based storage**: All session data in one document for atomic operations
- **Connection pooling**: Singleton pattern prevents connection exhaustion
- **Factory pattern**: Efficient session manager creation for stateless environments
- **Smart connection management**: Supports both owned and borrowed MongoDB clients
- **Simplified Implementation**: Core session persistence with event loop metrics
- **Automatic Metrics**: Captures tokens and latency from agent's event_loop_metrics
- **Timestamp preservation**: Original creation times maintained during updates
- **Error Handling**: Comprehensive error handling and logging
- **Metadata Management**: Enhanced metadata operations with field-level updates

### Performance Optimizations for Stateless Environments

The library includes several optimizations specifically for stateless environments like FastAPI:

1. **Connection Pool Singleton**: Prevents creating new MongoDB connections per request
2. **Factory Pattern**: Reuses the shared connection pool across all session managers
3. **Smart Index Creation**: Indexes created only once per collection
4. **Connection Lifecycle Management**: Proper handling of owned vs borrowed clients

## Package Exports

The package exports the following from `src/mongodb_session_manager/__init__.py`:
- **Classes**:
  - `MongoDBSessionManager`: Main session manager class
  - `MongoDBSessionRepository`: Repository implementation
  - `MongoDBConnectionPool`: Connection pool singleton
  - `MongoDBSessionManagerFactory`: Factory for session managers
- **Functions**:
  - `create_mongodb_session_manager`: Convenience function
  - `initialize_global_factory`: Set up global factory
  - `get_global_factory`: Access global factory
  - `close_global_factory`: Clean up global factory
- **Version**: `__version__ = "0.1.2"`

## Dependencies

Core dependencies:
- `pymongo>=4.13.2`: MongoDB Python driver
- `strands-agents>=1.0.1`: Core Strands Agents SDK
- `strands-agents-tools>=0.2.1`: Strands tools
- `fastapi>=0.116.1`: For FastAPI integration examples
- `uvloop>=0.21.0`: High-performance event loop

Development dependencies:
- `pytest>=7.4.0`: Testing framework
- `pytest-cov>=4.1.0`: Coverage reporting
- `pytest-mock>=3.11.0`: Mocking utilities
- `pytest-asyncio>=0.21.0`: Async test support

## Testing Considerations

When writing tests:
- Mock MongoDB connections for unit tests
- Use actual MongoDB instance for integration tests
- Test connection pooling behavior
- Verify index creation only happens once
- Test error handling for network failures
- **Test Event Loop Metrics**: Verify metrics are captured from agent's event_loop_metrics
- **Test Session Resumption**: Ensure conversations persist across manager restarts
- **Test Multiple Agents**: Verify separate message storage for different agents
- **Test Connection Pool**: Verify singleton behavior and connection reuse
- **Test Factory Pattern**: Ensure proper session manager creation without overhead
- **Test Concurrent Access**: Thread safety of connection pool
- **Test Resource Cleanup**: Proper closure of connections and factories
- **Test Async Streaming**: Verify streaming responses work correctly

## Example Usage Patterns

### Basic Pattern
```python
from mongodb_session_manager import create_mongodb_session_manager

# Creates session manager with new connection
manager = create_mongodb_session_manager(
    session_id="test",
    connection_string="mongodb://...",
    database_name="my_db"
)
```

### Optimized Pattern (Recommended for Stateless)
```python
from mongodb_session_manager import initialize_global_factory, get_global_factory

# Initialize once at startup
factory = initialize_global_factory(
    connection_string="mongodb://...",
    maxPoolSize=100
)

# In each request
manager = get_global_factory().create_session_manager(session_id)
# Reuses connection!
```

### Performance Expectations
- **Connection Overhead**: Reduced from 10-50ms to ~0ms
- **Concurrent Requests**: Significant throughput improvement
- **Resource Usage**: Controlled and predictable

### Async Streaming Pattern
```python
# Stream responses with session persistence
async def handle_streaming(session_manager, agent, prompt):
    session_manager.append_message({"role": "user", "content": prompt}, agent)
    
    response_chunks = []
    async for event in agent.stream_async(prompt):
        if "data" in event:
            response_chunks.append(event["data"])
            yield event["data"]
    
    full_response = "".join(response_chunks)
    session_manager.append_message({"role": "assistant", "content": full_response}, agent)
    session_manager.sync_agent(agent)  # Captures event loop metrics
```

### Metadata Management Pattern
```python
# Partial metadata updates preserve existing fields
session_manager.repository.update_metadata(session_id, {
    "priority": "high",
    "assigned_to": "agent-123"
})  # Other metadata fields remain unchanged

# Delete specific metadata fields
session_manager.repository.delete_metadata(session_id, ["sensitive_field1", "sensitive_field2"])

# Get all metadata
metadata = session_manager.repository.get_metadata(session_id)
```

### Interactive Chat Playground
The project includes a web-based chat interface for testing:

```bash
# Terminal 1: Start backend API (port 8880)
cd playground/chat && make backend-fastapi-streaming

# Terminal 2: Start frontend (port 8881) 
cd playground/chat && make frontend

# Open browser to: http://localhost:8881/chat.html
```

The playground demonstrates:
- Real-time streaming responses
- Session persistence across page reloads
- Automatic metrics tracking
- Metadata view with session statistics

## Current Implementation Status

### Working Features
- ✅ Full MongoDB session persistence (messages, agents, state)
- ✅ Connection pooling via singleton pattern
- ✅ Factory pattern for efficient session manager creation
- ✅ Event loop metrics capture from agents (via sync_agent)
- ✅ Multiple agents per session with separate conversation history
- ✅ Thread-safe operations
- ✅ Async streaming support
- ✅ Partial metadata updates preserving existing fields
- ✅ Metadata field deletion for data cleanup

### Implementation Notes
- The codebase implements core session persistence with automatic metrics capture
- Metrics are automatically extracted from agent's event_loop_metrics during sync_agent()
- Some methods referenced in examples (like get_metrics_summary) are not implemented
- The repository filters out event_loop_metrics when returning SessionMessage objects
- Connection management is smart - can use external clients or create its own

## Recent Updates

- Simplified implementation by removing automatic metrics features
- Updated documentation to reflect current functionality
- Maintained core session persistence and connection pooling features
- Simplified implementation focusing on core functionality
- Removed caching layer implementation
- Updated documentation to reflect actual implementation
- Maintained automatic metrics capture from agent's event loop
- **NEW**: Enhanced metadata update to preserve existing fields when updating
- **NEW**: Added metadata deletion capability for specific fields
- **NEW**: Fixed syntax error in delete_metadata method