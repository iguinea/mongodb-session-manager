# MongoDB Session Manager

[![Version](https://img.shields.io/badge/version-0.5.0-blue.svg)](https://github.com/iguinea/mongodb-session-manager)
[![Python](https://img.shields.io/badge/python-3.13+-green.svg)](https://python.org)

A MongoDB session manager for [Strands Agents](https://github.com/strands-agents/strands-agents-python) that provides persistent storage for agent conversations and state, with connection pooling optimized for stateless environments.

## Features

- **Session Persistence**: Complete conversation history stored in MongoDB
- **Multiple Agents per Session**: Support for specialized agents sharing context
- **Connection Pooling**: Built-in MongoDB connection pool for high performance
- **Event Loop Metrics**: Automatic capture of tokens, latency, TTFB from Strands SDK
- **Agent State Persistence**: Store and restore agent state across sessions
- **Metadata Management**: Partial updates, field deletion, and built-in agent tool
- **Feedback System**: Store user ratings and comments with hooks
- **AWS Integration**: Optional SNS, SQS, and WebSocket hooks for notifications
- **Factory Pattern**: Optimized for FastAPI and stateless frameworks

## Installation

Install directly from GitHub:

```bash
# With uv (recommended)
uv add git+https://github.com/iguinea/mongodb-session-manager.git

# With pip
pip install git+https://github.com/iguinea/mongodb-session-manager.git
```

For local development:

```bash
git clone https://github.com/iguinea/mongodb-session-manager.git
cd mongodb-session-manager
uv sync
```

## Quick Start

```python
from strands import Agent
from mongodb_session_manager import create_mongodb_session_manager

# Create session manager
session_manager = create_mongodb_session_manager(
    session_id="customer-12345",
    connection_string="mongodb://user:pass@host:27017/",
    database_name="my_database",
    application_name="customer-support-bot"  # Optional: categorize sessions by app
)

# Create agent with session persistence
agent = Agent(
    model="us.anthropic.claude-sonnet-4-20250514-v1:0",
    agent_id="support-agent",
    session_manager=session_manager,
    system_prompt="You are a helpful assistant."
)

# Use the agent - conversation is automatically persisted
response = agent("Hello, can you help me?")

# Sync agent to persist state and metrics
session_manager.sync_agent(agent)

# Read application name (immutable, set at creation)
app_name = session_manager.get_application_name()

# Clean up
session_manager.close()
```

## Factory Pattern (Recommended for Production)

For FastAPI and other stateless frameworks, use the factory pattern for optimal connection reuse:

```python
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
from mongodb_session_manager import (
    initialize_global_factory,
    get_global_factory,
    close_global_factory
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize global factory once
    initialize_global_factory(
        connection_string="mongodb://localhost:27017/",
        database_name="my_database",
        application_name="my-fastapi-app",  # Default for all sessions
        maxPoolSize=100,
        minPoolSize=10
    )
    yield
    # Shutdown: Clean up connections
    close_global_factory()

app = FastAPI(lifespan=lifespan)

@app.post("/chat")
async def chat(request: Request, session_id: str, message: str):
    # Create session manager (reuses pooled connection)
    manager = get_global_factory().create_session_manager(session_id)

    agent = Agent(
        model="us.anthropic.claude-sonnet-4-20250514-v1:0",
        agent_id="assistant",
        session_manager=manager
    )

    response = agent(message)
    manager.sync_agent(agent)

    return {"response": str(response)}
```

## API Reference

### Core Classes

#### `create_mongodb_session_manager()`

Convenience function to create a session manager:

```python
manager = create_mongodb_session_manager(
    session_id="unique-session-id",
    connection_string="mongodb://...",
    database_name="my_db",
    collection_name="agent_sessions",  # optional, default: "agent_sessions"
    metadataHook=my_hook,              # optional
    feedbackHook=my_hook               # optional
)
```

#### `MongoDBSessionManager`

Main class extending `RepositorySessionManager` from Strands SDK.

**Key Methods:**

| Method | Description |
|--------|-------------|
| `sync_agent(agent)` | Persist agent state, config, and event loop metrics |
| `update_metadata(metadata)` | Update session metadata (preserves existing fields) |
| `get_metadata()` | Retrieve session metadata |
| `delete_metadata(keys)` | Delete specific metadata fields |
| `get_metadata_tool()` | Get Strands tool for agent metadata management |
| `add_feedback(feedback)` | Store user feedback with rating and comment |
| `get_feedbacks()` | Retrieve all feedback for the session |
| `get_application_name()` | Get session's application name (read-only, immutable) |
| `close()` | Close database connections |

#### `MongoDBSessionManagerFactory`

Factory for creating session managers with connection pooling.

**Global Factory Functions:**

```python
from mongodb_session_manager import (
    initialize_global_factory,
    get_global_factory,
    close_global_factory
)

# Initialize once at app startup
factory = initialize_global_factory(
    connection_string="mongodb://...",
    database_name="my_db",
    maxPoolSize=100
)

# Get factory anywhere in the app
factory = get_global_factory()

# Create managers per request
manager = factory.create_session_manager(session_id)

# Clean up at shutdown
close_global_factory()
```

### Metadata Tool for Agents

Allow agents to autonomously manage session metadata:

```python
metadata_tool = session_manager.get_metadata_tool()

agent = Agent(
    model="us.anthropic.claude-sonnet-4-20250514-v1:0",
    tools=[metadata_tool],
    session_manager=session_manager
)

# Agent can now use manage_metadata tool
response = agent("Store my name as John and preference for dark theme")
```

### Hooks

Intercept metadata and feedback operations:

```python
def my_metadata_hook(original_func, action, session_id, **kwargs):
    # action: "get", "update", or "delete"
    logger.info(f"Metadata {action} for session {session_id}")

    if action == "update":
        return original_func(kwargs["metadata"])
    elif action == "delete":
        return original_func(kwargs["keys"])
    else:
        return original_func()

session_manager = MongoDBSessionManager(
    session_id="...",
    connection_string="...",
    metadataHook=my_metadata_hook,
    feedbackHook=my_feedback_hook
)
```

## AWS Integration (Optional)

### SNS Feedback Notifications

```python
from mongodb_session_manager import (
    create_feedback_sns_hook,
    is_feedback_sns_hook_available
)

if is_feedback_sns_hook_available():
    hook = create_feedback_sns_hook(
        topic_arn_good="arn:aws:sns:...:feedback-good",
        topic_arn_bad="arn:aws:sns:...:feedback-bad",
        topic_arn_neutral="arn:aws:sns:...:feedback-neutral",
        subject_prefix_bad="[URGENT] "
    )

    session_manager = MongoDBSessionManager(
        session_id="...",
        feedbackHook=hook
    )
```

### SQS Metadata Propagation

```python
from mongodb_session_manager import (
    create_metadata_sqs_hook,
    is_metadata_sqs_hook_available
)

if is_metadata_sqs_hook_available():
    hook = create_metadata_sqs_hook(
        queue_url="https://sqs...",
        metadata_fields=["status", "priority"]
    )
```

### WebSocket Real-time Updates

```python
from mongodb_session_manager import (
    create_metadata_websocket_hook,
    is_metadata_websocket_hook_available
)

if is_metadata_websocket_hook_available():
    hook = create_metadata_websocket_hook(
        api_gateway_endpoint="https://abc123.execute-api...",
        metadata_fields=["status", "progress"]
    )
```

**Requirements:** AWS hooks require `boto3` and appropriate IAM permissions.

## MongoDB Schema

Sessions are stored as nested documents:

```json
{
    "_id": "session-id",
    "session_id": "session-id",
    "application_name": "my-app",
    "created_at": "2024-01-15T09:00:00Z",
    "updated_at": "2024-01-22T14:30:00Z",
    "agents": {
        "agent-id": {
            "agent_data": {
                "model": "claude-sonnet-4",
                "system_prompt": "You are helpful",
                "state": {"key": "value"}
            },
            "messages": [
                {
                    "role": "user",
                    "content": "Hello",
                    "created_at": "2024-01-15T09:00:00Z"
                },
                {
                    "role": "assistant",
                    "content": "Hi there!",
                    "event_loop_metrics": {
                        "accumulated_usage": {
                            "inputTokens": 10,
                            "outputTokens": 20
                        },
                        "accumulated_metrics": {
                            "latencyMs": 250
                        }
                    }
                }
            ]
        }
    },
    "metadata": {"priority": "high"},
    "feedbacks": [
        {"rating": "up", "comment": "Helpful!", "created_at": "..."}
    ]
}
```

## Documentation

For comprehensive documentation, see the `/docs/` directory:

- **[Getting Started](docs/getting-started/)** - Installation, quickstart, concepts
- **[User Guides](docs/user-guide/)** - Session management, pooling, factory, metadata, feedback, AWS, streaming
- **[Examples](docs/examples/)** - Practical examples and patterns
- **[API Reference](docs/api-reference/)** - Complete API documentation
- **[Architecture](docs/architecture/)** - Design decisions, data model, performance

## Examples

Run examples with:

```bash
uv run python examples/example_calculator_tool.py
uv run python examples/example_fastapi_streaming.py
uv run python examples/example_metadata_tool.py
uv run python examples/example_feedback_hook.py
```

## License

MIT License - see LICENSE file for details.
