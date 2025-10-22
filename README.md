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
- **Metadata Management**: Partial updates preserve existing fields, field-level deletion
- **Agent Tools**: Built-in metadata tool allows agents to manage session context
- **Metadata Hooks**: Intercept and enhance metadata operations with custom logic
- **Feedback System**: Store user feedback with ratings and comments
- **Feedback Hooks**: Intercept feedback operations for audit, validation, and notifications
- **AWS Integration**: Optional SNS, SQS, and WebSocket hooks for real-time notifications and event propagation

### Performance Optimization
- **Connection Pool Singleton**: Reuse MongoDB connections across requests
- **Factory Pattern**: Efficient session manager creation without connection overhead
- **Stateless-Ready**: Optimized for FastAPI and other stateless frameworks
- **Reduced Connection Overhead**: Significant performance improvement over per-request connections

## 📂 Documentation & Examples

This project provides two complementary resources to help you learn and use MongoDB Session Manager:

### 🚀 Runnable Scripts (`/examples/`)

Execute immediately to see features in action:

```bash
# Basic agent with tools
uv run python examples/example_calculator_tool.py

# Agent configuration persistence
uv run python examples/example_agent_config.py

# FastAPI integration
uv run python examples/example_fastapi_streaming.py

# Metadata management
uv run python examples/example_metadata_tool.py

# Feedback system
uv run python examples/example_feedback_hook.py
```

[View all examples →](examples/)

### 📚 Comprehensive Documentation (`/docs/`)

In-depth guides with explanations, patterns, and best practices:

- **[Getting Started](docs/getting-started/)** - Installation, quickstart, basic concepts
- **[User Guides](docs/user-guide/)** - Session management, pooling, factory, metadata, feedback, AWS, streaming
- **[Examples & Patterns](docs/examples/)** - Practical examples and advanced patterns
- **[API Reference](docs/api-reference/)** - Complete API documentation
- **[Architecture](docs/architecture/)** - Design decisions, data model, performance
- **[Development](docs/development/)** - Contributing, testing, releasing

💡 **Recommended Workflow**: Read the docs to learn → Run the examples to practice → Build your application

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
- **Partial metadata updates**: Update specific fields without overwriting others
- **Metadata field deletion**: Remove specific metadata fields for data cleanup
- **Metadata tool for agents**: Agents can autonomously manage session metadata
- **Metadata hooks**: Intercept and enhance metadata operations with custom logic

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

## 📊 Metadata Management

### Enhanced Metadata Operations
The session manager now supports partial metadata updates that preserve existing fields:

```python
# Initial metadata
session_manager.update_metadata({
    "user_id": "user-123",
    "priority": "high",
    "department": "sales"
})

# Update only specific fields (preserves user_id and department)
session_manager.update_metadata({
    "priority": "medium",
    "assigned_to": "agent-456"
})

# Delete sensitive fields before archival
session_manager.delete_metadata(["user_email", "phone_number"])

# Get current metadata
metadata = session_manager.get_metadata()
```

### Metadata Hooks
Intercept and enhance metadata operations with custom logic:

```python
# Example: Audit hook that logs all metadata operations
def metadata_audit_hook(original_func, action, session_id, **kwargs):
    logger.info(f"[AUDIT] {action} metadata for session {session_id}")
    if action == "update" and "metadata" in kwargs:
        logger.info(f"[AUDIT] Data: {kwargs['metadata']}")
    
    # Execute original function
    if action == "update":
        return original_func(kwargs["metadata"])
    elif action == "delete":
        return original_func(kwargs["keys"])
    else:  # get
        return original_func()

# Create session manager with metadata hook
session_manager = MongoDBSessionManager(
    session_id="audited-session",
    connection_string="mongodb://...",
    database_name="my_db",
    metadataHook=metadata_audit_hook  # Intercepts all metadata operations
)

# All metadata operations will be audited
session_manager.update_metadata({"status": "active"})  # Logged
metadata = session_manager.get_metadata()              # Logged
session_manager.delete_metadata(["temp_field"])        # Logged
```

### Hook Use Cases
- **Audit Trail**: Log all metadata operations for compliance
- **Validation**: Enforce data quality rules before updates
- **Caching**: Implement read caching for performance
- **Synchronization**: Mirror metadata to external systems
- **Access Control**: Enforce permissions on metadata fields

### Metadata Tool for Agents
Agents can now dynamically manage session metadata using the built-in metadata tool:

```python
# Get the metadata tool from session manager
metadata_tool = session_manager.get_metadata_tool()

# Create agent with metadata tool
agent = Agent(
    model="claude-3-sonnet",
    agent_id="assistant",
    session_manager=session_manager,
    tools=[metadata_tool],  # Agent can now manage metadata
    system_prompt="You are a helpful assistant with metadata access."
)

# Agent can use the tool autonomously
response = agent("Please store my name as John and my preference for dark theme")
# Agent will use manage_metadata("set", {"user_name": "John", "theme": "dark"})
```

### Metadata Tool Operations
The `manage_metadata` tool supports three actions:

```python
# Direct tool usage examples
metadata_tool = session_manager.get_metadata_tool()

# Get all metadata
result = metadata_tool(action="get")

# Get specific fields
result = metadata_tool(action="get", keys=["user_name", "preferences"])

# Set/update metadata (preserves existing fields)
result = metadata_tool(action="set", metadata={"status": "active", "level": 5})

# Delete specific fields
result = metadata_tool(action="delete", keys=["temp_data", "old_field"])
```

### Use Cases
- **Progressive Information Gathering**: Build metadata throughout conversation
- **Dynamic Context Management**: Agents can store and retrieve context as needed
- **User Preferences**: Store and update user preferences during chat
- **Status Updates**: Update session status without losing other metadata
- **Data Privacy**: Remove sensitive fields before long-term storage
- **Audit Trail**: Add timestamps and interaction counts incrementally

See examples:
- `examples/example_metadata_update.py`: Basic metadata operations
- `examples/example_metadata_production.py`: Production customer support scenario
- `examples/example_metadata_tool.py`: Agent using metadata tool autonomously
- `examples/example_metadata_tool_direct.py`: Direct tool usage patterns
- `examples/example_metadata_hook.py`: Comprehensive metadata hook examples

## 💬 Feedback Management

### User Feedback System
The session manager supports storing user feedback with ratings and comments:

```python
# Add feedback to a session
session_manager.add_feedback({
    "rating": "up",  # or "down" or None
    "comment": "The response was very helpful!"
})

# Get all feedback for a session
feedbacks = session_manager.get_feedbacks()
# Returns: [{"rating": "up", "comment": "...", "created_at": datetime}, ...]
```

### Feedback Hooks
Intercept and enhance feedback operations with custom logic:

```python
# Audit hook - log all feedback
def feedback_audit_hook(original_func, action, session_id, **kwargs):
    logger.info(f"[FEEDBACK] New feedback for session {session_id}: {kwargs['feedback']}")
    return original_func(kwargs["feedback"])

# Validation hook - ensure quality feedback
def feedback_validation_hook(original_func, action, session_id, **kwargs):
    feedback = kwargs["feedback"]
    if feedback.get("rating") == "down" and not feedback.get("comment"):
        raise ValueError("Please provide a comment with negative feedback")
    return original_func(feedback)

# Create session manager with feedback hooks
session_manager = MongoDBSessionManager(
    session_id="user-session",
    connection_string="mongodb://...",
    feedbackHook=feedback_audit_hook
)
```

### FastAPI Integration Example
```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class FeedbackRequest(BaseModel):
    rating: Optional[str] = None  # "up", "down", or None
    comment: str = ""

@app.post("/api/sessions/{session_id}/feedback")
async def add_feedback(session_id: str, feedback_data: FeedbackRequest):
    try:
        session_manager = factory.create_session_manager(
            session_id=session_id,
            feedbackHook=feedback_validation_hook
        )
        
        session_manager.add_feedback({
            "rating": feedback_data.rating,
            "comment": feedback_data.comment
        })
        
        return {"status": "success", "message": "Feedback recorded"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

### Use Cases
- **Quality Monitoring**: Track user satisfaction with agent responses
- **Improvement Insights**: Analyze negative feedback to improve prompts
- **Audit Trail**: Log all feedback for compliance and analysis
- **Real-time Alerts**: Notify support team on negative feedback
- **Analytics**: Collect metrics on feedback patterns

See `examples/example_feedback_hook.py` for comprehensive examples including:
- Audit hooks for logging
- Validation hooks for data quality
- Notification hooks for alerts
- Analytics hooks for metrics collection
- Combined hooks for multiple behaviors

## 🚀 AWS Integration Hooks

### Optional AWS Service Integrations
The library includes optional hooks for integrating with AWS services. These require the `custom_aws` package (python-helpers) to be installed.

### SNS Feedback Notifications
Send real-time notifications to different topics based on feedback rating:

```python
from mongodb_session_manager import (
    create_feedback_sns_hook,
    is_feedback_sns_hook_available
)

# Check if SNS integration is available
if is_feedback_sns_hook_available():
    # Create SNS hook with three separate topics for routing
    feedback_hook = create_feedback_sns_hook(
        topic_arn_good="arn:aws:sns:eu-west-1:123456789:feedback-good",
        topic_arn_bad="arn:aws:sns:eu-west-1:123456789:feedback-bad",
        topic_arn_neutral="arn:aws:sns:eu-west-1:123456789:feedback-neutral"
    )

    # Create session manager with SNS notifications
    session_manager = MongoDBSessionManager(
        session_id="user-session",
        connection_string="mongodb://...",
        feedbackHook=feedback_hook
    )

    # Routes to topic_arn_bad
    session_manager.add_feedback({
        "rating": "down",
        "comment": "The answer was incorrect"
    })

    # Routes to topic_arn_good
    session_manager.add_feedback({
        "rating": "up",
        "comment": "Great response!"
    })
```

Features:
- Automatic topic routing based on feedback rating
- Real-time alerts with session context
- Non-blocking async notifications
- Rich message attributes for filtering
- Graceful degradation if SNS fails

### SQS Metadata Propagation
Propagate metadata changes for Server-Sent Events (SSE) or real-time sync:

```python
from mongodb_session_manager import (
    create_metadata_sqs_hook,
    is_metadata_sqs_hook_available
)

# Check if SQS integration is available
if is_metadata_sqs_hook_available():
    # Create SQS hook for metadata propagation
    metadata_hook = create_metadata_sqs_hook(
        queue_url="https://sqs.eu-west-1.amazonaws.com/123456789/metadata-sync",
        metadata_fields=["status", "priority", "agent_state"]  # Only sync these fields
    )
    
    # Create session manager with SQS propagation
    session_manager = MongoDBSessionManager(
        session_id="user-session",
        connection_string="mongodb://...",
        metadataHook=metadata_hook
    )
    
    # These changes will be sent to SQS
    session_manager.update_metadata({
        "status": "processing",
        "priority": "high",
        "internal_data": "not synced"  # Won't be sent to SQS
    })
```

Features:
- Selective field propagation
- Real-time metadata synchronization
- Queue-based event distribution
- Support for SSE back-propagation

### WebSocket Real-time Updates
Push metadata changes directly to connected WebSocket clients with ultra-low latency:

```python
from mongodb_session_manager import (
    create_metadata_websocket_hook,
    is_metadata_websocket_hook_available
)

# Check if WebSocket integration is available
if is_metadata_websocket_hook_available():
    # Create WebSocket hook for direct push to clients
    websocket_hook = create_metadata_websocket_hook(
        api_gateway_endpoint="https://abc123.execute-api.us-east-1.amazonaws.com/prod",
        metadata_fields=["status", "progress", "agent_state"],  # Only push these fields
        region="us-east-1"
    )

    # Create session manager with WebSocket push
    session_manager = MongoDBSessionManager(
        session_id="user-session",
        connection_string="mongodb://...",
        metadataHook=websocket_hook
    )

    # IMPORTANT: Connection ID must be stored in metadata
    # This comes from API Gateway $connect event
    session_manager.update_metadata({
        "connection_id": "abc123def456",  # Required!
        "status": "processing",
        "progress": 50,
        "agent_state": "thinking"
    })
```

Features:
- Ultra-low latency direct push to WebSocket clients
- Perfect for real-time UIs (Session Viewer, dashboards)
- Automatic handling of disconnected clients
- Selective field propagation minimizes bandwidth
- Non-blocking async operation

**WebSocket vs SQS:**
- **WebSocket**: Ultra-low latency, single-client push, ideal for real-time UIs
- **SQS**: Multi-consumer, guaranteed delivery, ideal for backend processing
- **Best Practice**: Use both together for comprehensive real-time architecture

### AWS Hook Requirements

**For SNS and SQS hooks:**
- Install `python-helpers` package: `pip install python-helpers`
- Configure AWS credentials with appropriate permissions:
  - SNS: `sns:Publish` permission on the topic
  - SQS: `sqs:SendMessage` permission on the queue
- Create SNS topic and/or SQS queue in your AWS account

**For WebSocket hook:**
- Install `boto3` (already a core dependency): `pip install boto3`
- Configure AWS credentials with appropriate permissions:
  - API Gateway: `execute-api:ManageConnections` permission
- Create API Gateway WebSocket API in your AWS account

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
                "model": "eu.anthropic.claude-sonnet-4-20250514-v1:0",
                "system_prompt": "You are a helpful assistant",
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
    },
    "metadata": {
        "priority": "high",
        "category": "support"
    },
    "feedbacks": [
        {
            "rating": "up",
            "comment": "Very helpful response!",
            "created_at": ISODate("2024-01-22T15:00:00Z")
        },
        {
            "rating": "down",
            "comment": "The answer was incomplete",
            "created_at": ISODate("2024-01-22T16:30:00Z")
        }
    ]
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
- `update_metadata(session_id, metadata)`: Update session metadata (preserves existing fields)
- `get_metadata(session_id)`: Retrieve session metadata
- `delete_metadata(session_id, metadata_keys)`: Delete specific metadata fields
- `close()`: Close the MongoDB connection (if owned)

**Key Features:**
- Smart connection management (owns vs borrows client)
- Automatic index creation on timestamps
- Filters out `event_loop_metrics` when returning messages
- Preserves original timestamps during updates

#### MongoDBSessionManager
Main session management class extending RepositorySessionManager from Strands SDK.

**Implemented Methods:**
- `__init__(metadataHook=None, feedbackHook=None, **kwargs)`: Initialize with MongoDB connection options and optional hooks
- `append_message(message, agent)`: Store message in session
- `redact_latest_message(redact_message, agent)`: Redact the latest message
- `sync_agent(agent)`: Sync agent data, capture event loop metrics, and persist agent configuration (model, system_prompt)
- `initialize(agent)`: Initialize an agent with the session
- `update_metadata(metadata)`: Update session metadata (preserves existing fields)
- `get_metadata()`: Retrieve session metadata
- `delete_metadata(metadata_keys)`: Delete specific metadata fields
- `get_metadata_tool()`: Get a Strands tool for agent metadata management
- `add_feedback(feedback)`: Store user feedback with rating and comment
- `get_feedbacks()`: Retrieve all feedback for the session
- `get_agent_config(agent_id)`: Get agent configuration (model, system_prompt) **NEW v0.1.14**
- `update_agent_config(agent_id, model, system_prompt)`: Update agent configuration **NEW v0.1.14**
- `list_agents()`: List all agents in session with their configurations **NEW v0.1.14**
- `close()`: Close database connections

**Automatic Features:**
- Captures metrics from `agent.event_loop_metrics` during `sync_agent()`
- **Captures and persists agent configuration** (model, system_prompt) during `sync_agent()` **NEW v0.1.14**
- Updates last message with token counts and latency
- Handles MongoDB connection lifecycle intelligently
- Applies metadata and feedback hooks to intercept operations

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
- `examples/example_metadata_update.py`: Demonstrates partial metadata updates and deletion
- `examples/example_metadata_production.py`: Production use case for customer support with metadata
- `examples/example_metadata_tool.py`: Agent autonomously managing metadata with built-in tool
- `examples/example_metadata_tool_direct.py`: Direct usage of the metadata tool
- `examples/example_metadata_hook.py`: Metadata hooks for audit, validation, and caching
- `examples/example_feedback_hook.py`: Feedback hooks for audit, validation, notifications, and analytics
- `examples/example_agent_config.py`: **NEW v0.1.14** - Agent configuration persistence and retrieval

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

## 🔍 Session Viewer (v0.1.16)

### Overview
Session Viewer is a complete web application for visualizing and analyzing MongoDB sessions. It provides a modern interface to search, filter, and view conversation timelines with real-time interaction.

### Quick Start

```bash
# Terminal 1: Start the backend API (port 8882)
cd session_viewer/backend
make dev

# Terminal 2: Start the frontend (port 8883)
cd session_viewer/frontend
make run
```

Then open your browser to: http://localhost:8883

### Key Features

**Backend (FastAPI REST API):**
- **Dynamic Filtering**: Search by session ID, date range, and any metadata field
- **Multiple Filters**: Apply multiple metadata filters simultaneously with AND logic
- **Pagination**: Server-side pagination with configurable page sizes (default: 20)
- **Unified Timeline**: Chronologically merged messages from all agents + feedbacks
- **Connection Pooling**: Uses MongoDBConnectionPool for optimal performance
- **Configurable**: MongoDB connection settings via .env file

**Frontend (Vanilla JavaScript + Tailwind CSS):**
- **3-Panel Layout**: Filters, results list, and session detail side-by-side
- **Dynamic Filters**: Add/remove metadata filters at runtime
- **Real-time Search**: Instant results with loading states
- **Timeline View**: Messages and feedbacks in chronological order
- **Responsive Design**: Works on desktop, tablet, and mobile
- **Health Monitoring**: Real-time backend connectivity indicator

### API Endpoints

```bash
# Health check
GET /health

# Get available metadata fields
GET /api/v1/metadata-fields

# Search sessions
GET /api/v1/sessions/search?session_id=abc&limit=20&offset=0&filters={"priority":"high"}

# Get session detail
GET /api/v1/sessions/{session_id}
```

### Architecture

**Backend Stack:**
- FastAPI with async/await
- Pydantic models for validation
- MongoDB aggregation for metadata discovery
- Dynamic query building with regex
- Timeline unification algorithm

**Frontend Stack:**
- Vanilla JavaScript with ES6 classes (OOP)
- Tailwind CSS (utility-first styling)
- axios (HTTP client)
- marked.js (markdown rendering)
- dayjs (date formatting)

**Key Classes:**
- `APIClient`: HTTP communication
- `FilterPanel`: Dynamic filter management
- `ResultsList`: Search results with pagination
- `SessionDetail`: Session visualization with timeline
- `SessionViewer`: Main orchestrator

### Configuration

Backend configuration via `session_viewer/backend/.env`:

```env
# MongoDB
MONGODB_CONNECTION_STRING=mongodb://localhost:27017/
MONGODB_DATABASE=chats
MONGODB_COLLECTION=virtual_agents

# API
API_HOST=0.0.0.0
API_PORT=8882

# CORS
ALLOWED_ORIGINS=http://localhost:8883,http://127.0.0.1:8883

# Pagination
DEFAULT_PAGE_SIZE=20
MAX_PAGE_SIZE=100
```

Frontend connects to backend at `http://localhost:8882/api/v1` (configurable in viewer.js).

### Use Cases

- **Session Analysis**: Review conversation history and agent interactions
- **Quality Assurance**: Examine agent responses and user feedback
- **Debugging**: Trace issues by viewing complete session timelines
- **Metrics Review**: Analyze token usage, latency, and agent performance
- **Customer Support**: Quick lookup of customer conversations by metadata
- **Data Exploration**: Discover patterns in session metadata fields

### Documentation

- **Backend**: Complete API documentation in `session_viewer/backend/README.md`
- **Frontend**: UI architecture guide in `session_viewer/frontend/README.md`
- **Feature Plan**: Implementation details in `features/2_session_viewer/plan.md`

### Example: Search Sessions

```bash
# Search by session ID (partial match)
curl "http://localhost:8882/api/v1/sessions/search?session_id=user-123"

# Search with metadata filters
curl "http://localhost:8882/api/v1/sessions/search?filters={\"priority\":\"high\",\"status\":\"active\"}"

# Search with date range
curl "http://localhost:8882/api/v1/sessions/search?created_at_start=2024-01-01T00:00:00Z&created_at_end=2024-12-31T23:59:59Z"

# Combine all filters with pagination
curl "http://localhost:8882/api/v1/sessions/search?session_id=support&filters={\"category\":\"billing\"}&limit=10&offset=0"
```

### Benefits

- **Visibility**: Gain insights into agent behavior and user interactions
- **Efficiency**: Quickly find and review sessions with flexible filtering
- **Collaboration**: Share session URLs with team members for review
- **Monitoring**: Track feedback patterns and identify improvement areas
- **Self-Service**: Non-technical users can explore session data independently

## 📄 License

This project is licensed under the same terms as the parent Itzulbira project.

---

**Itzulbira Session Manager** - Production-ready MongoDB session management for conversational AI with comprehensive metrics tracking.