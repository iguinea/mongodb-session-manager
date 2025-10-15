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
uv run python examples/example_metadata_tool.py
uv run python examples/example_metadata_tool_direct.py
uv run python examples/example_metadata_hook.py
uv run python examples/example_feedback_hook.py

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

# Run the Session Viewer web application
cd session_viewer/backend
make dev                   # Start backend API on port 8882

cd session_viewer/frontend
make run                   # Start frontend on port 8883
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
│       └── hooks/                         # AWS integration hooks
│           ├── __init__.py                # Hooks package initialization
│           ├── feedback_sns_hook.py       # SNS notifications for feedback
│           └── metadata_sqs_hook.py       # SQS propagation for metadata
├── examples/                              # Example scripts
│   ├── example_calculator_tool.py         # Complete agent example with tools
│   ├── example_fastapi.py                 # FastAPI integration example
│   ├── example_performance.py             # Performance benchmarks
│   ├── example_stream_async.py            # Async streaming with real-time metrics
│   ├── example_fastapi_streaming.py       # FastAPI with streaming and factory pattern
│   ├── example_metadata_tool.py           # Agent using metadata tool autonomously
│   ├── example_metadata_hook.py           # Metadata hooks (audit, validation, caching)
│   ├── example_feedback_hook.py           # Feedback hooks (audit, validation, notifications)
│   └── example_agent_config.py            # Agent configuration persistence demo
├── playground/                            # Interactive demos
│   └── chat/                              # Web-based chat interface
│       ├── chat.html                      # Chat UI with real-time streaming
│       ├── chat-widget.js                 # JavaScript for chat functionality
│       └── Makefile                       # Commands to run frontend/backend
├── session_viewer/                        # Session Viewer web application (v0.1.16)
│   ├── backend/                           # FastAPI REST API
│   │   ├── main.py                        # API endpoints and business logic
│   │   ├── models.py                      # Pydantic request/response models
│   │   ├── config.py                      # Settings with pydantic-settings
│   │   ├── .env.example                   # Configuration template
│   │   ├── Makefile                       # Development commands
│   │   └── README.md                      # Backend API documentation
│   └── frontend/                          # Vanilla JS + Tailwind CSS UI
│       ├── index.html                     # 3-panel layout (filters, results, detail)
│       ├── viewer.js                      # ES6 classes (OOP architecture)
│       ├── components.js                  # Reusable UI components
│       ├── Makefile                       # Frontend server commands
│       └── README.md                      # Frontend documentation
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
   - **Agent Configuration Persistence**: Automatically captures and stores model and system_prompt
   - **Metadata Management**: Direct methods for update, get, delete operations
   - **Metadata Tool**: Provides get_metadata_tool() for agent integration
   - **Metadata Hooks**: Supports intercepting metadata operations with custom logic
   - **Feedback System**: Stores user feedback (rating + comment) with automatic timestamps
   - **Feedback Hooks**: Supports intercepting feedback operations for audit, validation, etc.
   - **Agent Config Methods**: get_agent_config(), update_agent_config(), list_agents()
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

5. **AWS Integration Hooks** (`hooks/` directory): Optional AWS service integrations
   - **FeedbackSNSHook** (`feedback_sns_hook.py`): Send feedback notifications to AWS SNS
     - Real-time alerts for negative feedback
     - Non-blocking async notifications
     - Graceful degradation if SNS fails
   - **MetadataSQSHook** (`metadata_sqs_hook.py`): Propagate metadata changes to AWS SQS
     - Real-time metadata synchronization via SSE
     - Selective field propagation
     - Queue-based event distribution

6. **Helper Functions** (in `__init__.py` and `mongodb_session_factory.py`):
   - `create_mongodb_session_manager()`: Convenience function to create session manager
   - `initialize_global_factory()`: Set up global factory for FastAPI
   - `get_global_factory()`: Access the global factory instance
   - `close_global_factory()`: Clean up global resources
   - `is_feedback_sns_hook_available()`: Check if SNS hook can be used
   - `is_metadata_sqs_hook_available()`: Check if SQS hook can be used

### MongoDB Schema

Sessions are stored as single documents with embedded agents and messages:
- Collection: Configurable (defaults to `collection_name` parameter)
- Document structure:
  - Root: session document with `_id`, `session_id`, `session_type`, timestamps
  - Agents: Nested under `agents` object, keyed by agent_id
    - **agent_data**: Contains agent_id, state, conversation_manager_state, **model**, **system_prompt**, timestamps
  - Messages: Array within each agent, with auto-incrementing message_id
  - Metrics: Stored in `event_loop_metrics` field of assistant messages
  - Feedbacks: Array of feedback objects with rating, comment, and created_at timestamp
- Indexes: Automatically created on `created_at` and `updated_at` fields

**New in v0.1.14**: `model` and `system_prompt` fields in agent_data for configuration persistence

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
- **Metadata Hooks**: Intercept and customize metadata operations

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
  - `FeedbackSNSHook`: AWS SNS hook for feedback (if custom_aws available)
  - `MetadataSQSHook`: AWS SQS hook for metadata (if custom_aws available)
- **Functions**:
  - `create_mongodb_session_manager`: Convenience function
  - `initialize_global_factory`: Set up global factory
  - `get_global_factory`: Access global factory
  - `close_global_factory`: Clean up global factory
  - `create_feedback_sns_hook`: Create SNS feedback hook (if custom_aws available)
  - `create_metadata_sqs_hook`: Create SQS metadata hook (if custom_aws available)
  - `is_feedback_sns_hook_available()`: Check SNS hook availability
  - `is_metadata_sqs_hook_available()`: Check SQS hook availability
- **Version**: `__version__ = "0.1.15"`

## Dependencies

Core dependencies:
- `pymongo>=4.13.2`: MongoDB Python driver
- `strands-agents>=1.12.0`: Core Strands Agents SDK
- `strands-agents-tools>=0.2.11`: Strands tools
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
session_manager.update_metadata({
    "priority": "high",
    "assigned_to": "agent-123"
})  # Other metadata fields remain unchanged

# Delete specific metadata fields
session_manager.delete_metadata(["sensitive_field1", "sensitive_field2"])

# Get all metadata
metadata = session_manager.get_metadata()
```

### Metadata Tool Pattern
```python
# Get metadata tool for agent integration
metadata_tool = session_manager.get_metadata_tool()

# Create agent with metadata capabilities
agent = Agent(
    model="claude-3-sonnet",
    tools=[metadata_tool],
    session_manager=session_manager
)

# Agent can manage metadata autonomously
response = agent("Store my preference for notifications as enabled")

# Direct tool usage
result = metadata_tool(action="get")  # Get all metadata
result = metadata_tool(action="set", metadata={"key": "value"})  # Update
result = metadata_tool(action="delete", keys=["key1", "key2"])  # Delete
```

### Metadata Hook Pattern
```python
# Create a hook to intercept metadata operations
def metadata_audit_hook(original_func, action, session_id, **kwargs):
    logger.info(f"[AUDIT] {action} on session {session_id}")
    # Call original function with appropriate arguments
    if action == "update":
        return original_func(kwargs["metadata"])
    elif action == "delete":
        return original_func(kwargs["keys"])
    else:  # get
        return original_func()

# Create session manager with hook
session_manager = MongoDBSessionManager(
    session_id="audited-session",
    connection_string="mongodb://...",
    metadataHook=metadata_audit_hook  # All metadata ops will be audited
)

# Hook examples: audit, validation, caching, combined hooks
# See examples/example_metadata_hook.py for comprehensive examples
```

### Feedback Management Pattern
```python
# Add feedback to session
session_manager.add_feedback({
    "rating": "up",  # or "down" or None
    "comment": "Great response!"
})

# Get all feedbacks
feedbacks = session_manager.get_feedbacks()

# Create session manager with feedback hook
def feedback_audit_hook(original_func, action, session_id, **kwargs):
    logger.info(f"[FEEDBACK] {action} on session {session_id}: {kwargs['feedback']}")
    return original_func(kwargs["feedback"])

session_manager = MongoDBSessionManager(
    session_id="user-session",
    connection_string="mongodb://...",
    feedbackHook=feedback_audit_hook
)

# Hook examples: audit, validation, notification, analytics
# See examples/example_feedback_hook.py for comprehensive examples
```

### AWS Integration Patterns

#### SNS Feedback Notifications
```python
from mongodb_session_manager import (
    MongoDBSessionManager,
    create_feedback_sns_hook,
    is_feedback_sns_hook_available
)

# Check if SNS hook is available
if is_feedback_sns_hook_available():
    # Create SNS hook with separate topics for different feedback types
    feedback_hook = create_feedback_sns_hook(
        topic_arn_good="arn:aws:sns:eu-west-1:123456789:feedback-good",
        topic_arn_bad="arn:aws:sns:eu-west-1:123456789:feedback-bad",
        topic_arn_neutral="arn:aws:sns:eu-west-1:123456789:feedback-neutral"
    )

    session_manager = MongoDBSessionManager(
        session_id="user-session",
        connection_string="mongodb://...",
        feedbackHook=feedback_hook
    )

    # Routes to topic_arn_bad
    session_manager.add_feedback({
        "rating": "down",
        "comment": "Response was incomplete"
    })

    # Routes to topic_arn_good
    session_manager.add_feedback({
        "rating": "up",
        "comment": "Great response!"
    })
else:
    print("SNS hook not available - install python-helpers package")
```

#### SQS Metadata Propagation
```python
from mongodb_session_manager import (
    MongoDBSessionManager,
    create_metadata_sqs_hook,
    is_metadata_sqs_hook_available
)

# Check if SQS hook is available
if is_metadata_sqs_hook_available():
    # Create SQS hook for SSE back-propagation
    metadata_hook = create_metadata_sqs_hook(
        queue_url="https://sqs.eu-west-1.amazonaws.com/123456789/metadata-updates",
        metadata_fields=["status", "agent_state", "priority"]  # Only propagate these fields
    )
    
    session_manager = MongoDBSessionManager(
        session_id="user-session",
        connection_string="mongodb://...",
        metadataHook=metadata_hook
    )
    
    # Metadata changes are sent to SQS for real-time sync
    session_manager.update_metadata({
        "status": "processing",
        "agent_state": "thinking",
        "internal_field": "not propagated"  # Won't be sent to SQS
    })
else:
    print("SQS hook not available - install python-helpers package")
```

### Agent Configuration Persistence Pattern
```python
# Configuration is automatically captured during sync_agent()
agent = Agent(
    agent_id="support-agent",
    model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
    system_prompt="You are a friendly customer support agent.",
    session_manager=session_manager
)

# Use the agent
response = agent("Hello!")  # sync_agent() is called automatically, capturing config

# Retrieve agent configuration
config = session_manager.get_agent_config("support-agent")
print(f"Model: {config['model']}")
print(f"System Prompt: {config['system_prompt']}")

# Update agent configuration (useful for experimentation)
session_manager.update_agent_config(
    "support-agent",
    model="eu.anthropic.claude-haiku-4-20250514-v1:0",  # Switch to faster model
    system_prompt="You are a friendly and efficient customer support agent."
)

# List all agents in session with their configurations
agents = session_manager.list_agents()
for agent_info in agents:
    print(f"Agent: {agent_info['agent_id']}")
    print(f"  Model: {agent_info.get('model', 'Not captured')}")
    print(f"  Prompt: {agent_info.get('system_prompt', 'Not captured')[:50]}...")

# Use cases:
# 1. Auditing: Track which models were used for compliance
# 2. Debugging: Reproduce agent behavior with exact configuration
# 3. Analytics: Analyze model usage patterns and costs
# 4. A/B Testing: Compare different prompts/models for same conversations
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

### Session Viewer Web Application (v0.1.16)
The project includes a complete web application for visualizing and analyzing MongoDB sessions stored by the session manager.

```bash
# Terminal 1: Start backend API (port 8882)
cd session_viewer/backend && make dev

# Terminal 2: Start frontend (port 8883)
cd session_viewer/frontend && make run

# Open browser to: http://localhost:8883
```

**Architecture:**
- **Backend**: FastAPI REST API with 4 endpoints (health, metadata-fields, search, detail)
- **Frontend**: Vanilla JavaScript (ES6 classes) with Tailwind CSS
- **Connection**: Uses MongoDBConnectionPool for efficient database access

**Key Features:**
- Dynamic filtering by session_id, date range, and any metadata field
- Multiple simultaneous filters with AND logic
- Server-side pagination (configurable page size)
- Unified timeline merging messages from all agents + feedbacks chronologically
- Real-time health monitoring
- Responsive 3-panel layout (filters, results, detail)

**File Structure:**
```
session_viewer/
├── backend/
│   ├── main.py          # FastAPI app with endpoints
│   ├── models.py        # Pydantic request/response models
│   ├── config.py        # Settings with pydantic-settings
│   ├── .env.example     # Configuration template
│   ├── Makefile         # Commands (run, dev, format)
│   └── README.md        # API documentation
└── frontend/
    ├── index.html       # 3-panel UI layout
    ├── viewer.js        # ES6 classes (APIClient, FilterPanel, ResultsList, SessionDetail, SessionViewer)
    ├── components.js    # Pure rendering functions
    ├── Makefile         # Commands (run, open, clean)
    └── README.md        # Frontend documentation
```

**API Endpoints:**
- `GET /health`: Health check
- `GET /api/v1/metadata-fields`: Get available metadata fields (aggregation pipeline)
- `GET /api/v1/sessions/search`: Search with filters, pagination
- `GET /api/v1/sessions/{session_id}`: Get complete session with unified timeline

**Frontend Classes:**
- `APIClient`: HTTP communication with axios
- `FilterPanel`: Dynamic filter management (add/remove filters at runtime)
- `ResultsList`: Search results with pagination controls
- `SessionDetail`: Session visualization with timeline
- `SessionViewer`: Main orchestrator coordinating all components

**Timeline Unification Algorithm:**
The backend merges messages from all agents and feedbacks into a single chronological timeline:
```python
def build_unified_timeline(session_data):
    timeline = []

    # Collect messages from all agents
    for agent_id, agent_data in session_data.get("agents", {}).items():
        for msg in agent_data.get("messages", []):
            timeline.append({
                "type": "message",
                "agent_id": agent_id,
                # ... message data
            })

    # Add feedbacks
    for feedback in session_data.get("feedbacks", []):
        timeline.append({
            "type": "feedback",
            # ... feedback data
        })

    # Sort by timestamp
    timeline.sort(key=lambda x: x["timestamp"])
    return timeline
```

**Configuration:**
Backend uses `.env` file with MongoDB connection, CORS origins, and pagination settings. Frontend connects to backend at `http://localhost:8882/api/v1` (configurable in viewer.js).

**Use Cases:**
- **Session Analysis**: Review conversation history and agent interactions
- **Quality Assurance**: Examine agent responses and user feedback
- **Debugging**: Trace issues by viewing complete session timelines
- **Metrics Review**: Analyze token usage, latency, and agent performance
- **Customer Support**: Quick lookup of customer conversations by metadata
- **Data Exploration**: Discover patterns in session metadata fields

**Implementation Notes:**
- Backend searches by `session_id` field in MongoDB documents
- Dynamic query building with regex for partial matching
- Aggregation pipeline used to discover unique metadata fields
- Component-based frontend architecture for maintainability
- Health indicator shows real-time backend connectivity status

## Current Implementation Status

### Working Features
- ✅ Full MongoDB session persistence (messages, agents, state)
- ✅ Connection pooling via singleton pattern
- ✅ Factory pattern for efficient session manager creation
- ✅ Event loop metrics capture from agents (via sync_agent)
- ✅ **Agent configuration persistence** (model and system_prompt auto-capture)
- ✅ **Agent config retrieval and update** (get_agent_config, update_agent_config, list_agents)
- ✅ Multiple agents per session with separate conversation history
- ✅ Thread-safe operations
- ✅ Async streaming support
- ✅ Partial metadata updates preserving existing fields
- ✅ Metadata field deletion for data cleanup
- ✅ Metadata tool for agent integration (get_metadata_tool)
- ✅ Agents can autonomously manage session metadata
- ✅ Metadata hooks for intercepting and enhancing operations
- ✅ Feedback system for storing user ratings and comments
- ✅ Feedback hooks for audit, validation, and notifications
- ✅ AWS SNS integration for real-time feedback alerts
- ✅ AWS SQS integration for metadata SSE propagation
- ✅ Optional AWS dependencies with graceful degradation
- ✅ **Session Viewer web application** (v0.1.16) - Complete UI for visualizing and analyzing sessions

### Implementation Notes
- The codebase implements core session persistence with automatic metrics capture
- Metrics are automatically extracted from agent's event_loop_metrics during sync_agent()
- Some methods referenced in examples (like get_metrics_summary) are not implemented
- The repository filters out event_loop_metrics when returning SessionMessage objects
- Connection management is smart - can use external clients or create its own

## Recent Updates

### Version 0.1.16 (2025-10-15) 🆕
- **Session Viewer Web Application**: Complete web app for visualizing and analyzing MongoDB sessions
  - **Backend**: FastAPI REST API with 4 endpoints (health, metadata-fields, search, detail)
  - **Frontend**: Vanilla JavaScript with ES6 classes + Tailwind CSS
  - **Dynamic Filtering**: Search by session ID, date range, and any metadata field
  - **Multiple Filters**: Apply multiple metadata filters simultaneously with AND logic
  - **Pagination**: Server-side pagination with configurable page sizes
  - **Unified Timeline**: Chronologically merged messages from all agents + feedbacks
  - **Real-time Health Monitoring**: Backend connectivity indicator
  - **Responsive Design**: 3-panel layout (filters, results, detail)
  - **Connection Pooling**: Uses MongoDBConnectionPool for optimal performance
  - **Libraries**: axios, marked.js, dayjs, Tailwind CSS
  - **11 Files Created**: Complete backend and frontend implementation
  - See `session_viewer/backend/README.md` and `session_viewer/frontend/README.md` for documentation

### Version 0.1.14 (2025-10-15)
- **Agent Configuration Persistence**: Automatic capture and storage of `model` and `system_prompt`
  - sync_agent() now persists agent configuration automatically
  - New get_agent_config(agent_id) method to retrieve configuration
  - New update_agent_config(agent_id, model, system_prompt) to modify configuration
  - New list_agents() method to list all agents with their configurations
  - Enables auditing, reproducibility, analytics, and compliance
- Created example_agent_config.py demonstrating the new functionality
- MongoDB schema extended with model and system_prompt fields in agent_data
- Fully backward compatible with existing documents

### Previous Updates
- AWS SNS integration hook for real-time feedback notifications
- AWS SQS integration hook for metadata SSE back-propagation
- Added hooks directory with comprehensive AWS service integrations
- Helper functions to check AWS hook availability
- Implemented feedback system with add_feedback() and get_feedbacks() methods
- Added feedbackHook support for intercepting feedback operations
- Implemented get_metadata_tool() for agent metadata management
- Added metadata hooks support for intercepting and customizing metadata operations
- Enhanced metadata update to preserve existing fields when updating
- Added metadata deletion capability for specific fields
- Maintained automatic metrics capture from agent's event loop
- Connection pooling via singleton pattern
- Factory pattern for efficient session manager creation


## Rules
- Trabajas sobre un entorno UV
- Update documentation files (@CLAUDE.md and @README.md) when implementing new features or making significant changes
- Cuando se realicen fixes o se implementen nuevas funcionalidades, y estás se validen por el usuario (por lo que habrá que pedir conformidad con las soluciones implementadas) quiero que actualices la documentacion pertinente, (@docs/README.md para ver que documentacion hay que actualizar) , asi como actualices el fichero @CHANGELOG.md
- Cuando se hable de trabajar en una nueva funcionalidad, cuando el usuario acepte el plan, este se guardará en @features/<n>_<short_description>/plan.md .  Este fichero se usará para ver el progreso de la implementación de la nueva feature.
- En @docs/README.md tienes la referencia a la documentacion del proyecto
- Cuando vayas a generar una nueva release, ten en cuenta que la version tambien está en los ficheros: @src/mongodb_session_manager/__init__.py y @pyproject.toml