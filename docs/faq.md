# Frequently Asked Questions (FAQ)

This document answers common questions about the MongoDB Session Manager.

## Table of Contents

- [General Questions](#general-questions)
- [Installation Questions](#installation-questions)
- [Usage Questions](#usage-questions)
- [Performance Questions](#performance-questions)
- [Integration Questions](#integration-questions)
- [Troubleshooting](#troubleshooting)
- [Advanced Topics](#advanced-topics)
- [Contributing and Support](#contributing-and-support)

## General Questions

### What is MongoDB Session Manager?

MongoDB Session Manager is a session persistence library for Strands Agents that stores conversation history, agent state, and metadata in MongoDB. It provides:

- **Session Persistence**: Store and resume conversations across restarts
- **Connection Pooling**: Optimized for stateless environments like FastAPI
- **Automatic Metrics**: Capture token usage and latency from agents
- **Metadata Management**: Store session context and user preferences
- **Multi-Agent Support**: Handle multiple agents per session
- **AWS Integration**: Optional SNS and SQS hooks for real-time notifications

### Why MongoDB instead of other databases?

MongoDB offers several advantages for session management:

1. **Document Model**: Natural fit for nested conversation structures
2. **Flexible Schema**: Easy to extend with new fields
3. **Atomic Operations**: Update sessions atomically with `$set` and `$unset`
4. **Indexing**: Fast queries on timestamps and session IDs
5. **Scalability**: Handles large-scale production deployments
6. **Rich Queries**: Complex filtering and aggregation capabilities

However, the architecture allows for other databases through the `SessionRepository` interface.

### What are the system requirements?

**Minimum Requirements:**
- Python 3.13 or higher
- MongoDB 4.4 or higher
- 512 MB RAM (for development)
- 10 GB disk space

**Recommended for Production:**
- Python 3.13+
- MongoDB 6.0 or higher
- 2 GB+ RAM
- SSD storage
- MongoDB replica set for high availability

### Is this production-ready?

Yes! The library is currently in active development (v0.1.14) and is used in production environments. Features include:

- Comprehensive error handling
- Connection pooling for high concurrency
- Thread-safe operations
- Automatic retry logic for transient failures
- Extensive logging for debugging

However, as with any software, thoroughly test it in your environment before deploying to production.

### What license is this under?

The project follows the same license terms as the parent Itzulbira project. Check the LICENSE file in the repository for details.

## Installation Questions

### How do I install MongoDB Session Manager?

**Using UV (Recommended):**
```bash
# Clone the repository
git clone https://github.com/iguinea/mongodb-session-manager.git
cd mongodb-session-manager

# Install dependencies
uv sync
```

**Using pip:**
```bash
pip install pymongo strands-agents strands-agents-tools fastapi uvloop
```

Currently, the package is not published to PyPI. Install from source.

### Do I need to install MongoDB?

Yes, you need access to a MongoDB instance. Options include:

1. **Docker** (easiest for development):
   ```bash
   docker run -d -p 27017:27017 --name mongodb mongo:7.0
   ```

2. **Local Installation**: Download from [mongodb.com/download](https://www.mongodb.com/try/download/community)

3. **MongoDB Atlas**: Free cloud-hosted MongoDB at [mongodb.com/cloud/atlas](https://www.mongodb.com/cloud/atlas)

### What about AWS dependencies?

AWS integrations (SNS and SQS hooks) are **optional**. They require the `python-helpers` package:

```toml
# pyproject.toml
[tool.uv.sources]
python-helpers = { git = "https://github.com/iguinea/python-helpers", rev = "latest" }
```

If you don't need AWS features, the library works fine without them. Check availability with:

```python
from mongodb_session_manager import (
    is_feedback_sns_hook_available,
    is_metadata_sqs_hook_available
)

print(f"SNS available: {is_feedback_sns_hook_available()}")
print(f"SQS available: {is_metadata_sqs_hook_available()}")
```

### How do I update to the latest version?

**From Git:**
```bash
cd mongodb-session-manager
git pull origin main
uv sync
```

**Check current version:**
```python
from mongodb_session_manager import __version__
print(__version__)  # e.g., "0.1.14"
```

## Usage Questions

### How do I resume a conversation?

Use the same `session_id` and `agent_id`:

```python
# Day 1: Start conversation
manager1 = create_mongodb_session_manager(
    session_id="user-123-chat",
    connection_string="mongodb://localhost:27017/",
    database_name="myapp"
)

agent1 = Agent(
    agent_id="assistant",
    model="claude-3-sonnet",
    session_manager=manager1
)

response1 = agent1("My name is Alice")
manager1.sync_agent(agent1)
manager1.close()

# Day 7: Resume conversation
manager2 = create_mongodb_session_manager(
    session_id="user-123-chat",  # Same session_id
    connection_string="mongodb://localhost:27017/",
    database_name="myapp"
)

agent2 = Agent(
    agent_id="assistant",  # Same agent_id
    model="claude-3-sonnet",
    session_manager=manager2
)

response2 = agent2("What's my name?")  # Agent remembers "Alice"
```

### Can I use multiple agents in one session?

Yes! Each agent maintains its own conversation history within the session:

```python
session_manager = create_mongodb_session_manager(
    session_id="customer-support-session",
    connection_string="mongodb://localhost:27017/",
    database_name="myapp"
)

# Agent 1: Customer support
support_agent = Agent(
    agent_id="support",
    model="claude-3-sonnet",
    session_manager=session_manager,
    system_prompt="You are a customer support agent"
)

# Agent 2: Sales
sales_agent = Agent(
    agent_id="sales",
    model="claude-3-haiku",
    session_manager=session_manager,
    system_prompt="You are a sales agent"
)

# Each agent has separate conversation history
support_response = support_agent("I need help with my order")
sales_response = sales_agent("Tell me about pricing")
```

### How are metrics captured?

Metrics are **automatically** captured from the agent's event loop when you call `sync_agent()`:

```python
# Use the agent
response = agent("Hello, how are you?")

# Sync agent - automatically captures:
# - latencyMs: Response time
# - inputTokens: Tokens in the prompt
# - outputTokens: Tokens in the response
# - totalTokens: Sum of input and output
session_manager.sync_agent(agent)

# Metrics are stored in MongoDB with the assistant message
```

Metrics are stored in the `event_loop_metrics` field of assistant messages in MongoDB.

### What's the difference between metadata and messages?

**Messages** are the conversation history:
- User messages: "Hello"
- Assistant messages: "Hi there!"
- Immutable once created (except for redaction)
- Stored in `agents.{agent_id}.messages` array

**Metadata** is session context:
- User preferences: `{"language": "en", "theme": "dark"}`
- Session info: `{"priority": "high", "status": "active"}`
- Custom fields: Any JSON-serializable data
- Mutable - can be updated or deleted
- Stored in root `metadata` object

```python
# Add messages (conversation)
manager.append_message({"role": "user", "content": "Hello"}, agent)
manager.append_message({"role": "assistant", "content": "Hi!"}, agent)

# Update metadata (context)
manager.update_metadata({
    "user_language": "en",
    "session_priority": "high"
})
```

### How do I delete a session?

Currently, you need to delete directly from MongoDB:

```python
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017/")
db = client["myapp"]
collection = db["agent_sessions"]

# Delete specific session
collection.delete_one({"_id": "session-id-to-delete"})

# Or delete sessions older than 30 days
from datetime import datetime, timedelta
cutoff = datetime.utcnow() - timedelta(days=30)
collection.delete_many({"created_at": {"$lt": cutoff}})
```

**Note**: A `delete_session()` method may be added in a future release.

### Can agents manage their own metadata?

Yes! Use the metadata tool:

```python
# Get metadata tool
metadata_tool = session_manager.get_metadata_tool()

# Create agent with metadata capability
agent = Agent(
    model="claude-3-sonnet",
    agent_id="assistant",
    session_manager=session_manager,
    tools=[metadata_tool],  # Agent can now manage metadata
    system_prompt="You can store user preferences using the metadata tool."
)

# Agent can autonomously manage metadata
response = agent("Remember that I prefer dark mode and English language")
# Agent will use the tool to store: {"theme": "dark", "language": "en"}

# Later, agent can retrieve it
response = agent("What are my preferences?")
# Agent will use the tool to get metadata
```

## Performance Questions

### What's the benefit of connection pooling?

Without connection pooling, each request creates a new MongoDB connection:

```
Request 1: Create connection (10ms) → Query (5ms) → Close connection (5ms) = 20ms
Request 2: Create connection (10ms) → Query (5ms) → Close connection (5ms) = 20ms
Request 3: Create connection (10ms) → Query (5ms) → Close connection (5ms) = 20ms
Total: 60ms
```

With connection pooling:

```
Startup: Create pool (50ms, one-time cost)
Request 1: Get from pool (0ms) → Query (5ms) = 5ms
Request 2: Get from pool (0ms) → Query (5ms) = 5ms
Request 3: Get from pool (0ms) → Query (5ms) = 5ms
Total: 15ms (73% faster)
```

### How do I use the factory pattern?

For stateless environments like FastAPI, use the factory pattern:

```python
from fastapi import FastAPI
from contextlib import asynccontextmanager
from mongodb_session_manager import (
    initialize_global_factory,
    get_global_factory,
    close_global_factory
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize once
    factory = initialize_global_factory(
        connection_string="mongodb://localhost:27017/",
        database_name="myapp",
        maxPoolSize=100  # Pool size for concurrency
    )
    yield
    # Shutdown: Clean up
    close_global_factory()

app = FastAPI(lifespan=lifespan)

@app.post("/chat")
async def chat(session_id: str, message: str):
    # Get factory and create manager (reuses connection!)
    factory = get_global_factory()
    manager = factory.create_session_manager(session_id)

    # Use manager...
    # No need to close - factory manages the connection

    return {"response": "..."}
```

### How many concurrent connections can it handle?

The default pool size is 100 connections, suitable for most applications. Configure based on your needs:

```python
factory = initialize_global_factory(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=200,      # Max connections
    minPoolSize=20,       # Keep 20 connections ready
    maxIdleTimeMS=30000   # Close idle connections after 30s
)
```

**Rule of thumb**: Set `maxPoolSize` to 2-3x your expected concurrent requests.

### Are there any benchmarks?

Yes! Run the performance example:

```bash
uv run python examples/example_performance.py
```

Typical results:
- **Without pooling**: 15-25ms per operation
- **With pooling**: 2-5ms per operation
- **Improvement**: 5-10x faster

For streaming responses, see:
```bash
uv run python examples/example_stream_async.py
```

## Integration Questions

### How do I integrate with FastAPI?

See the comprehensive examples:

```bash
# Basic FastAPI integration
uv run python examples/example_fastapi.py

# FastAPI with streaming
uv run python examples/example_fastapi_streaming.py
```

Key pattern:

```python
from fastapi import FastAPI
from mongodb_session_manager import initialize_global_factory

app = FastAPI()

@app.on_event("startup")
async def startup():
    initialize_global_factory(
        connection_string="mongodb://localhost:27017/",
        database_name="myapp"
    )

@app.post("/chat")
async def chat(session_id: str):
    factory = get_global_factory()
    manager = factory.create_session_manager(session_id)
    # ... use manager
```

### Can I use it with other web frameworks?

Yes! The library works with any Python web framework. The key is:

1. **Initialize factory once** at application startup
2. **Create session managers per request** (reusing connections)
3. **Close factory** at application shutdown

**Flask Example:**
```python
from flask import Flask
from mongodb_session_manager import initialize_global_factory

app = Flask(__name__)

@app.before_first_request
def setup():
    initialize_global_factory(
        connection_string="mongodb://localhost:27017/"
    )

@app.route('/chat', methods=['POST'])
def chat():
    factory = get_global_factory()
    manager = factory.create_session_manager(request.json['session_id'])
    # ... use manager
```

**Django Example:**
```python
# In apps.py
from django.apps import AppConfig
from mongodb_session_manager import initialize_global_factory

class MyAppConfig(AppConfig):
    def ready(self):
        initialize_global_factory(
            connection_string="mongodb://localhost:27017/"
        )
```

### Does it support async operations?

Yes! The library supports async streaming:

```python
async def stream_chat(session_manager, agent, prompt):
    session_manager.append_message({"role": "user", "content": prompt}, agent)

    response_chunks = []
    async for event in agent.stream_async(prompt):
        if "data" in event:
            response_chunks.append(event["data"])
            yield event["data"]  # Stream to client

    full_response = "".join(response_chunks)
    session_manager.append_message(
        {"role": "assistant", "content": full_response},
        agent
    )
    session_manager.sync_agent(agent)
```

See `examples/example_stream_async.py` for complete examples.

## Troubleshooting

### MongoDB connection errors

**Problem**: `ServerSelectionTimeoutError: localhost:27017: [Errno 61] Connection refused`

**Solutions**:

1. **Check if MongoDB is running**:
   ```bash
   # Docker
   docker ps | grep mongo

   # Local (macOS)
   brew services list

   # Local (Linux)
   sudo systemctl status mongod
   ```

2. **Check connection string format**:
   ```python
   # Correct formats:
   "mongodb://localhost:27017/"  # No auth
   "mongodb://user:pass@localhost:27017/"  # With auth
   "mongodb+srv://user:pass@cluster.mongodb.net/"  # Atlas
   ```

3. **Test connection directly**:
   ```bash
   mongosh "mongodb://localhost:27017/"
   ```

### Session not found

**Problem**: Agent doesn't remember previous conversation

**Solutions**:

1. **Check session_id matches**:
   ```python
   # Both must use the same session_id
   manager1 = create_mongodb_session_manager(session_id="user-123")
   manager2 = create_mongodb_session_manager(session_id="user-123")
   ```

2. **Check agent_id matches**:
   ```python
   # Both agents must have the same agent_id
   agent1 = Agent(agent_id="assistant", ...)
   agent2 = Agent(agent_id="assistant", ...)
   ```

3. **Verify data in MongoDB**:
   ```bash
   mongosh
   use myapp
   db.agent_sessions.findOne({"_id": "user-123"})
   ```

### Agent doesn't remember context

**Problem**: Agent forgets conversation after a few messages

**Solutions**:

1. **Ensure sync_agent() is called**:
   ```python
   response = agent("Hello")
   session_manager.sync_agent(agent)  # MUST call this!
   ```

2. **Check message limit**:
   ```python
   # List messages to verify they're stored
   messages = session_manager.list_messages(agent_id="assistant")
   print(f"Stored messages: {len(messages)}")
   ```

3. **Verify agent is initialized**:
   ```python
   # Initialize agent with session
   session_manager.initialize(agent)
   ```

### Connection pool exhausted

**Problem**: `WaitQueueTimeoutError: Timed out while checking out a connection from connection pool`

**Solutions**:

1. **Increase pool size**:
   ```python
   factory = initialize_global_factory(
       connection_string="mongodb://localhost:27017/",
       maxPoolSize=200  # Increase from default 100
   )
   ```

2. **Ensure connections are released**:
   ```python
   # If not using factory, always close:
   manager = create_mongodb_session_manager(...)
   try:
       # Use manager
   finally:
       manager.close()  # Important!
   ```

3. **Check for connection leaks**:
   ```python
   factory = get_global_factory()
   stats = factory.get_connection_stats()
   print(stats)  # Check active connections
   ```

### Import errors

**Problem**: `ModuleNotFoundError: No module named 'mongodb_session_manager'`

**Solutions**:

1. **Use UV to run Python**:
   ```bash
   uv run python your_script.py
   ```

2. **Activate virtual environment**:
   ```bash
   source .venv/bin/activate  # Unix
   .venv\Scripts\activate     # Windows
   python your_script.py
   ```

3. **Reinstall dependencies**:
   ```bash
   uv sync --reinstall
   ```

### AWS hooks not available

**Problem**: `is_feedback_sns_hook_available()` returns `False`

**Solution**: The AWS hooks require `python-helpers` package:

```bash
# Check if python-helpers is installed
uv pip list | grep python-helpers

# If not installed, check pyproject.toml has:
# [tool.uv.sources]
# python-helpers = { git = "https://github.com/iguinea/python-helpers", rev = "latest" }

# Then reinstall
uv sync --reinstall-package python-helpers
```

## Advanced Topics

### How do I implement custom hooks?

Hooks intercept and enhance metadata or feedback operations:

```python
def custom_metadata_hook(original_func, action, session_id, **kwargs):
    """Custom hook for metadata operations."""
    print(f"[HOOK] {action} on session {session_id}")

    # Pre-processing
    if action == "update":
        metadata = kwargs["metadata"]
        # Add timestamp
        metadata["last_updated"] = datetime.utcnow().isoformat()

    # Call original function
    if action == "update":
        result = original_func(kwargs["metadata"])
    elif action == "delete":
        result = original_func(kwargs["keys"])
    else:  # get
        result = original_func()

    # Post-processing
    print(f"[HOOK] {action} completed")

    return result

# Use hook
manager = MongoDBSessionManager(
    session_id="test",
    connection_string="mongodb://localhost:27017/",
    metadataHook=custom_metadata_hook
)
```

See `examples/example_metadata_hook.py` for comprehensive examples.

### How do I use AWS integrations?

**SNS for Feedback Notifications:**

```python
from mongodb_session_manager import (
    create_feedback_sns_hook,
    is_feedback_sns_hook_available
)

if is_feedback_sns_hook_available():
    feedback_hook = create_feedback_sns_hook(
        topic_arn_good="arn:aws:sns:region:account:good",
        topic_arn_bad="arn:aws:sns:region:account:bad",
        topic_arn_neutral="arn:aws:sns:region:account:neutral"
    )

    manager = MongoDBSessionManager(
        session_id="user-session",
        connection_string="mongodb://localhost:27017/",
        feedbackHook=feedback_hook
    )

    # Feedback is sent to appropriate SNS topic
    manager.add_feedback({"rating": "down", "comment": "Incorrect answer"})
```

**SQS for Metadata Propagation:**

```python
from mongodb_session_manager import (
    create_metadata_sqs_hook,
    is_metadata_sqs_hook_available
)

if is_metadata_sqs_hook_available():
    metadata_hook = create_metadata_sqs_hook(
        queue_url="https://sqs.region.amazonaws.com/account/queue",
        metadata_fields=["status", "priority"]  # Only sync these
    )

    manager = MongoDBSessionManager(
        session_id="user-session",
        connection_string="mongodb://localhost:27017/",
        metadataHook=metadata_hook
    )

    # Metadata changes are sent to SQS
    manager.update_metadata({"status": "active", "priority": "high"})
```

### Can I use this in a multi-tenant application?

Yes! Use separate session_id patterns for each tenant:

```python
# Pattern 1: Include tenant_id in session_id
session_id = f"tenant-{tenant_id}-session-{user_id}"

# Pattern 2: Use separate databases per tenant
manager = create_mongodb_session_manager(
    session_id=session_id,
    connection_string="mongodb://localhost:27017/",
    database_name=f"tenant_{tenant_id}"
)

# Pattern 3: Use separate collections per tenant
manager = create_mongodb_session_manager(
    session_id=session_id,
    connection_string="mongodb://localhost:27017/",
    database_name="myapp",
    collection_name=f"sessions_{tenant_id}"
)
```

**Security**: Always validate tenant_id to prevent cross-tenant data access!

### How do I handle sensitive data?

1. **Use metadata hooks for encryption**:
   ```python
   def encryption_hook(original_func, action, session_id, **kwargs):
       if action == "update":
           metadata = kwargs["metadata"]
           # Encrypt sensitive fields
           if "credit_card" in metadata:
               metadata["credit_card"] = encrypt(metadata["credit_card"])
       return original_func(kwargs.get("metadata"), kwargs.get("keys"))
   ```

2. **Delete sensitive fields after use**:
   ```python
   # Delete sensitive fields
   manager.delete_metadata(["credit_card", "ssn", "password"])
   ```

3. **Use MongoDB encryption at rest**:
   Configure MongoDB with encryption:
   ```yaml
   security:
     enableEncryption: true
     encryptionKeyFile: /path/to/keyfile
   ```

4. **Network encryption**:
   Use TLS/SSL for MongoDB connections:
   ```python
   connection_string = "mongodb://host:27017/?tls=true&tlsCAFile=/path/to/ca.pem"
   ```

### How do I monitor performance?

1. **Connection pool statistics**:
   ```python
   factory = get_global_factory()
   stats = factory.get_connection_stats()
   print(f"Active connections: {stats}")
   ```

2. **MongoDB slow query log**:
   ```javascript
   // In MongoDB
   db.setProfilingLevel(1, { slowms: 100 })  // Log queries > 100ms
   ```

3. **Application logging**:
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   # MongoDB Session Manager logs to 'mongodb_session_manager' logger
   ```

4. **Metrics collection**:
   ```python
   # Collect metrics from messages
   messages = manager.list_messages(agent_id="assistant")
   total_tokens = sum(
       msg.get("event_loop_metrics", {})
          .get("accumulated_usage", {})
          .get("totalTokens", 0)
       for msg in messages
   )
   print(f"Total tokens used: {total_tokens}")
   ```

## Contributing and Support

### How do I report a bug?

1. **Search existing issues**: Check if it's already reported
2. **Create detailed issue**: Include:
   - Python version
   - MongoDB version
   - Library version
   - Minimal code to reproduce
   - Error messages and stack traces
3. **Submit**: https://github.com/iguinea/mongodb-session-manager/issues

### How do I request a feature?

1. **Check roadmap**: See if it's already planned
2. **Open discussion**: Describe the use case
3. **Provide examples**: Show how you'd use the feature
4. **Submit**: https://github.com/iguinea/mongodb-session-manager/issues with `enhancement` label

### How do I contribute code?

See the [Contributing Guide](docs/development/contributing.md) for detailed instructions:

1. Fork the repository
2. Create feature branch
3. Make changes with tests
4. Submit pull request

### Where can I get help?

- **Documentation**: Check [docs/](docs/) directory
- **Examples**: See [examples/](examples/) directory
- **Issues**: Search [GitHub Issues](https://github.com/iguinea/mongodb-session-manager/issues)
- **Discussions**: Ask in [GitHub Discussions](https://github.com/iguinea/mongodb-session-manager/discussions)
- **Email**: Contact maintainer at iguinea@gmail.com

### Are there any tutorials or guides?

Yes! Check the documentation:

- [Getting Started](docs/getting-started/quickstart.md): Quick introduction
- [User Guide](docs/user-guide/): Comprehensive usage guide
- [Examples](examples/): Practical code examples
- [API Reference](docs/api-reference/): Detailed API documentation

### What's the project roadmap?

Check the GitHub repository for:
- Milestones: Planned releases
- Projects: Feature tracking
- Issues labeled `roadmap`: Future plans

Current focus areas:
- Improved test coverage
- Performance optimizations
- Additional AWS integrations
- Better documentation

### How stable is the API?

The library is in active development (v0.1.x). The API is relatively stable, but breaking changes may occur before v1.0.0. We follow semantic versioning:

- **MAJOR** (1.0.0): Breaking changes
- **MINOR** (0.X.0): New features, backwards compatible
- **PATCH** (0.0.X): Bug fixes

### Can I use this commercially?

Check the LICENSE file in the repository. The project follows the same license terms as the parent Itzulbira project.

---

## Still Have Questions?

If your question isn't answered here:

1. Check the [documentation](docs/)
2. Search [GitHub Issues](https://github.com/iguinea/mongodb-session-manager/issues)
3. Ask in [GitHub Discussions](https://github.com/iguinea/mongodb-session-manager/discussions)
4. Contact the maintainers

We're here to help!
