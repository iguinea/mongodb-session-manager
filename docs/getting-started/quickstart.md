# Quickstart Guide

Get started with MongoDB Session Manager in just 5 minutes! This guide will walk you through creating your first persistent agent conversation.

## Prerequisites

Before you begin, make sure you have:

1. Python 3.11 or higher installed
2. MongoDB running locally or access to MongoDB Atlas
3. The library installed (see [Installation Guide](installation.md))

## Quick Setup

### 1. Install the Library

```bash
# Using UV (recommended)
uv sync

# Using pip
pip install -e .
```

### 2. Start MongoDB (if running locally)

```bash
# macOS (Homebrew)
brew services start mongodb-community

# Linux
sudo systemctl start mongod

# Docker
docker run -d -p 27017:27017 --name mongodb mongo:7.0
```

## Your First Session

### Creating a Session Manager

Create a file called `my_first_session.py`:

```python
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent

# Step 1: Create session manager
session_manager = create_mongodb_session_manager(
    session_id="quickstart-session-001",
    connection_string="mongodb://localhost:27017/",
    database_name="quickstart_db",
    collection_name="agent_sessions"
)

# Step 2: Create an agent with session persistence
agent = Agent(
    model="claude-3-sonnet",
    agent_id="assistant",
    session_manager=session_manager,
    system_prompt="You are a helpful assistant that remembers our conversation."
)

# Step 3: Have a conversation
response1 = agent("Hi! My name is Alice.")
print(f"Agent: {response1}\n")

# Step 4: Sync to save the conversation and metrics
session_manager.sync_agent(agent)

# Step 5: Ask a follow-up question
response2 = agent("What's my name?")
print(f"Agent: {response2}\n")

# Step 6: Sync again
session_manager.sync_agent(agent)

# Step 7: Clean up
session_manager.close()

print("✓ Conversation saved to MongoDB!")
```

Run it:

```bash
uv run python my_first_session.py
```

### Understanding What Happened

1. **Session Created**: A new MongoDB document was created with ID `quickstart-session-001`
2. **Agent Registered**: The agent was added to the session
3. **Messages Stored**: Both user messages and agent responses were persisted
4. **Metrics Captured**: Token counts and latency were automatically recorded
5. **State Saved**: The entire conversation state is now in MongoDB

## Resuming a Session

The real power comes from resuming conversations! Create `resume_session.py`:

```python
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent

# Use the SAME session_id to continue the conversation
session_manager = create_mongodb_session_manager(
    session_id="quickstart-session-001",  # Same as before!
    connection_string="mongodb://localhost:27017/",
    database_name="quickstart_db",
    collection_name="agent_sessions"
)

# Create agent with the SAME agent_id
agent = Agent(
    model="claude-3-sonnet",
    agent_id="assistant",  # Same as before!
    session_manager=session_manager,
    system_prompt="You are a helpful assistant that remembers our conversation."
)

# The agent remembers the previous conversation!
response = agent("Can you remind me what we talked about earlier?")
print(f"Agent: {response}\n")

# Sync and close
session_manager.sync_agent(agent)
session_manager.close()
```

Run it:

```bash
uv run python resume_session.py
```

The agent will remember that your name is Alice from the previous session!

## Adding Metadata

Sessions can store additional metadata about the conversation:

```python
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent

session_manager = create_mongodb_session_manager(
    session_id="metadata-example",
    connection_string="mongodb://localhost:27017/",
    database_name="quickstart_db"
)

# Add metadata to track conversation context
session_manager.update_metadata({
    "user_id": "user-123",
    "language": "en",
    "topic": "general",
    "priority": "normal"
})

# Create and use agent
agent = Agent(
    model="claude-3-sonnet",
    agent_id="assistant",
    session_manager=session_manager
)

response = agent("Hello!")
session_manager.sync_agent(agent)

# Update metadata during conversation
session_manager.update_metadata({
    "topic": "technical-support",
    "priority": "high"
})

# Retrieve metadata
metadata = session_manager.get_metadata()
print(f"Session metadata: {metadata}")

session_manager.close()
```

## Collecting Feedback

Track user satisfaction with the feedback system:

```python
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent

session_manager = create_mongodb_session_manager(
    session_id="feedback-example",
    connection_string="mongodb://localhost:27017/",
    database_name="quickstart_db"
)

agent = Agent(
    model="claude-3-sonnet",
    agent_id="assistant",
    session_manager=session_manager
)

# Have a conversation
response = agent("Explain what MongoDB is in one sentence.")
print(f"Agent: {response}\n")
session_manager.sync_agent(agent)

# User provides feedback
session_manager.add_feedback({
    "rating": "up",  # or "down" or None
    "comment": "Clear and concise explanation!"
})

# Later, retrieve all feedback
feedbacks = session_manager.get_feedbacks()
print(f"Feedback count: {len(feedbacks)}")

session_manager.close()
```

## Production Pattern: Factory

For production applications (like FastAPI), use the factory pattern:

```python
from mongodb_session_manager import (
    initialize_global_factory,
    get_global_factory,
    close_global_factory
)

# Startup: Initialize once
factory = initialize_global_factory(
    connection_string="mongodb://localhost:27017/",
    database_name="production_db",
    maxPoolSize=100  # Connection pool size
)

# Per-request: Create session managers (fast!)
def handle_request(session_id: str):
    session_manager = factory.create_session_manager(session_id)

    agent = Agent(
        model="claude-3-sonnet",
        session_manager=session_manager
    )

    response = agent("Hello!")
    session_manager.sync_agent(agent)

    return response

# Use it multiple times
handle_request("user-001")
handle_request("user-002")
handle_request("user-003")

# Shutdown: Clean up once
close_global_factory()
```

**Why factory pattern?**
- Reuses MongoDB connections (10-50ms faster per request)
- Handles hundreds of concurrent sessions efficiently
- Perfect for stateless environments like FastAPI

## Next Steps

Now that you've created your first session, explore more features:

### Learn Core Concepts
- [Basic Concepts](basic-concepts.md) - Understanding sessions, agents, and persistence

### Explore User Guides
- [Session Management](../user-guide/session-management.md) - Deep dive into session lifecycle
- [Connection Pooling](../user-guide/connection-pooling.md) - Optimize for production
- [Factory Pattern](../user-guide/factory-pattern.md) - FastAPI integration guide
- [Metadata Management](../user-guide/metadata-management.md) - Advanced metadata patterns

### Check Out Examples
- [Basic Usage](../examples/basic-usage.md) - More simple examples
- [FastAPI Integration](../examples/fastapi-integration.md) - Production FastAPI setup
- [Metadata Patterns](../examples/metadata-patterns.md) - Advanced metadata use cases

## Common Patterns

### Pattern 1: User-Specific Sessions

```python
def create_user_session(user_id: str):
    """Create a session for a specific user."""
    session_id = f"user-{user_id}-main"

    return create_mongodb_session_manager(
        session_id=session_id,
        connection_string="mongodb://localhost:27017/",
        database_name="app_db"
    )
```

### Pattern 2: Dated Sessions

```python
from datetime import datetime

def create_daily_session(user_id: str):
    """Create a new session each day."""
    date = datetime.now().strftime("%Y-%m-%d")
    session_id = f"user-{user_id}-{date}"

    return create_mongodb_session_manager(
        session_id=session_id,
        connection_string="mongodb://localhost:27017/",
        database_name="app_db"
    )
```

### Pattern 3: Multiple Agents per Session

```python
session_manager = create_mongodb_session_manager(
    session_id="multi-agent-session",
    connection_string="mongodb://localhost:27017/",
    database_name="app_db"
)

# Translator agent
translator = Agent(
    model="claude-3-sonnet",
    agent_id="translator",  # Different agent ID
    session_manager=session_manager
)

# Support agent
support = Agent(
    model="claude-3-haiku",
    agent_id="support",  # Different agent ID
    session_manager=session_manager
)

# Each agent has separate conversation history in the same session
translation = translator("Translate: 'Hello world' to Spanish")
help_response = support("How do I reset my password?")

session_manager.sync_agent(translator)
session_manager.sync_agent(support)
```

## Verification

### Check MongoDB

You can verify your sessions are stored in MongoDB:

```bash
# Connect to MongoDB
mongosh

# Switch to your database
use quickstart_db

# List sessions
db.agent_sessions.find().pretty()

# Find specific session
db.agent_sessions.findOne({"_id": "quickstart-session-001"})
```

### Check Metrics

Your session documents will contain automatic metrics:

```json
{
  "_id": "quickstart-session-001",
  "agents": {
    "assistant": {
      "messages": [
        {
          "message_id": 1,
          "role": "assistant",
          "content": "...",
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

## Troubleshooting

### Error: "Connection refused"

MongoDB is not running. Start it:
```bash
brew services start mongodb-community  # macOS
sudo systemctl start mongod            # Linux
```

### Error: "Session not found"

Make sure you're using the same `session_id` and `agent_id` when resuming.

### Agent doesn't remember previous conversation

Common causes:
1. Different `session_id` used
2. Different `agent_id` used
3. MongoDB connection string changed (pointing to different database)

## Summary

You've learned:

✓ How to create a session manager
✓ How to persist agent conversations
✓ How to resume conversations later
✓ How to add metadata to sessions
✓ How to collect user feedback
✓ How to use the factory pattern for production

Ready for more? Check out:
- [Basic Concepts](basic-concepts.md) for deeper understanding
- [API Reference](../api-reference/mongodb-session-manager.md) for all available methods
- [Examples](../examples/basic-usage.md) for more use cases
