# Basic Usage Examples

## 🚀 Runnable Examples

This guide includes multiple code examples. For complete, executable scripts, see:

| Script | Description | Run Command |
|--------|-------------|-------------|
| [example_calculator_tool.py](../../examples/example_calculator_tool.py) | Basic agent with Strands calculator tool | `uv run python examples/example_calculator_tool.py` |
| [example_agent_config.py](../../examples/example_agent_config.py) | Agent configuration persistence and retrieval | `uv run python examples/example_agent_config.py` |

📁 **All examples**: [View examples directory](../../examples/)

---

This guide provides simple, practical examples to get you started with MongoDB Session Manager. These examples demonstrate the fundamental concepts and common patterns for basic session management.

## Table of Contents

- [Hello World Example](#hello-world-example)
- [Basic Conversation](#basic-conversation)
- [Session Resumption](#session-resumption)
- [Multiple Messages](#multiple-messages)
- [Message Redaction](#message-redaction)
- [Agent State Management](#agent-state-management)
- [Clean Shutdown](#clean-shutdown)
- [Complete Example: Calculator Tool](#complete-example-calculator-tool)

---

## Hello World Example

The simplest possible example - create a session manager and have a basic interaction.

```python
import asyncio
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent


async def main():
    # Create session manager
    session_manager = create_mongodb_session_manager(
        session_id="hello-world-session",
        connection_string="mongodb://localhost:27017/",
        database_name="my_app",
        collection_name="sessions",
    )

    # Create agent
    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="assistant",
        session_manager=session_manager,
        system_prompt="You are a helpful assistant.",
    )

    # Simple interaction
    response = agent("Hello! What can you help me with?")
    print(f"Agent: {response}")

    # Clean up
    session_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
```

**Expected Output:**
```
Agent: Hello! I'm here to help you with a wide variety of tasks...
```

**What This Does:**
- Creates a session manager connected to MongoDB
- Initializes an agent with the session manager
- Sends a message and gets a response
- All conversation history is automatically stored in MongoDB

---

## Basic Conversation

Having a multi-turn conversation where context is maintained.

```python
import asyncio
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent


async def main():
    # Create session manager
    session_manager = create_mongodb_session_manager(
        session_id="conversation-session",
        connection_string="mongodb://localhost:27017/",
        database_name="my_app",
    )

    # Create agent
    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="assistant",
        session_manager=session_manager,
        system_prompt="You are a helpful math tutor.",
    )

    # First message
    response = agent("What is 15 + 27?")
    print(f"User: What is 15 + 27?")
    print(f"Agent: {response}\n")

    # Follow-up that relies on context
    response = agent("Can you break down how you calculated that?")
    print(f"User: Can you break down how you calculated that?")
    print(f"Agent: {response}\n")

    # Another follow-up
    response = agent("What if I subtract 10 from that result?")
    print(f"User: What if I subtract 10 from that result?")
    print(f"Agent: {response}\n")

    # Clean up
    session_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
```

**Expected Output:**
```
User: What is 15 + 27?
Agent: 15 + 27 equals 42.

User: Can you break down how you calculated that?
Agent: Sure! To add 15 + 27, we can break it down...

User: What if I subtract 10 from that result?
Agent: If we subtract 10 from 42, we get 32.
```

**Key Points:**
- Each interaction is stored in MongoDB
- Agent remembers previous messages in the conversation
- Context is maintained across multiple turns

---

## Session Resumption

Demonstrating how to resume a conversation after the application restarts.

```python
import asyncio
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent


async def first_conversation():
    """First part of the conversation."""
    print("=== First Session ===\n")

    session_manager = create_mongodb_session_manager(
        session_id="resume-demo-session",
        connection_string="mongodb://localhost:27017/",
        database_name="my_app",
    )

    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="assistant",
        session_manager=session_manager,
        system_prompt="You are a helpful assistant with excellent memory.",
    )

    response = agent("My favorite color is blue. Remember that!")
    print(f"User: My favorite color is blue. Remember that!")
    print(f"Agent: {response}\n")

    response = agent("I live in San Francisco.")
    print(f"User: I live in San Francisco.")
    print(f"Agent: {response}\n")

    session_manager.close()


async def resumed_conversation():
    """Resume the conversation - agent should remember previous context."""
    print("=== Resumed Session (after restart) ===\n")

    # Same session_id to resume the conversation
    session_manager = create_mongodb_session_manager(
        session_id="resume-demo-session",  # Same ID!
        connection_string="mongodb://localhost:27017/",
        database_name="my_app",
    )

    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="assistant",
        session_manager=session_manager,
        system_prompt="You are a helpful assistant with excellent memory.",
    )

    # Agent should remember previous conversation
    response = agent("What's my favorite color?")
    print(f"User: What's my favorite color?")
    print(f"Agent: {response}\n")

    response = agent("Where do I live?")
    print(f"User: Where do I live?")
    print(f"Agent: {response}\n")

    session_manager.close()


async def main():
    # First conversation
    await first_conversation()

    # Simulate application restart
    print("\n--- Application Restart ---\n")

    # Resume conversation
    await resumed_conversation()


if __name__ == "__main__":
    asyncio.run(main())
```

**Expected Output:**
```
=== First Session ===

User: My favorite color is blue. Remember that!
Agent: Got it! I'll remember that your favorite color is blue.

User: I live in San Francisco.
Agent: Noted! You live in San Francisco.

--- Application Restart ---

=== Resumed Session (after restart) ===

User: What's my favorite color?
Agent: Your favorite color is blue!

User: Where do I live?
Agent: You live in San Francisco!
```

**Key Points:**
- Using the same session_id resumes the conversation
- All previous messages are loaded from MongoDB
- Agent maintains full context across restarts

---

## Multiple Messages

Working with multiple agents in the same session.

```python
import asyncio
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent


async def main():
    # Create session manager
    session_manager = create_mongodb_session_manager(
        session_id="multi-agent-session",
        connection_string="mongodb://localhost:27017/",
        database_name="my_app",
    )

    # Create a technical agent
    tech_agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="tech-support",
        session_manager=session_manager,
        system_prompt="You are a technical support agent.",
    )

    # Create a sales agent
    sales_agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="sales-rep",
        session_manager=session_manager,
        system_prompt="You are a friendly sales representative.",
    )

    # Conversation with tech agent
    print("=== Technical Support ===")
    response = tech_agent("My application won't start. What should I do?")
    print(f"User: My application won't start. What should I do?")
    print(f"Tech: {response}\n")

    # Conversation with sales agent
    print("=== Sales ===")
    response = sales_agent("What pricing plans do you offer?")
    print(f"User: What pricing plans do you offer?")
    print(f"Sales: {response}\n")

    # Back to tech agent - maintains separate context
    print("=== Technical Support (Continued) ===")
    response = tech_agent("I tried restarting, but it still doesn't work.")
    print(f"User: I tried restarting, but it still doesn't work.")
    print(f"Tech: {response}\n")

    # Clean up
    session_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
```

**Key Points:**
- Multiple agents can use the same session manager
- Each agent maintains its own conversation history
- Messages are stored separately per agent_id

---

## Message Redaction

How to handle message redaction for privacy or compliance.

Redaction goes through `redact_latest_message()`, and it only ever reaches the **latest** message of an agent: there is no API to redact an arbitrary message after the fact. It happens in two ways:

- **Automatically**, when a Bedrock guardrail intervenes on the input: Strands replaces the user's message and calls `redact_latest_message()` itself.
- **By hand**, calling `redact_latest_message()` yourself. After `agent(...)` returns, the latest message is the answer.

Either way the manager records a `guardrail_event` on the message and an entry in the session's `guardrail_events` array (see [Guardrail Auditing](../user-guide/guardrail-auditing.md)).

```python
import asyncio
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent
from strands.models import BedrockModel


async def main():
    # Create session manager
    session_manager = create_mongodb_session_manager(
        session_id="redaction-demo",
        connection_string="mongodb://localhost:27017/",
        database_name="my_app",
    )

    # A Bedrock model with a guardrail: when it blocks the input, Strands
    # replaces the user's message and redacts it in the session
    model = BedrockModel(
        model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        guardrail_id="your-guardrail-id",
        guardrail_version="1",
        guardrail_redact_input_message="[User input redacted.]",
    )

    agent = Agent(
        model=model,
        agent_id="assistant",
        session_manager=session_manager,
        system_prompt="You are a customer service assistant.",
    )

    # User shares sensitive information
    response = agent("My credit card number is 4532-1234-5678-9010")
    print(f"Agent: {response}\n")

    # Redact by hand: this replaces the latest message, i.e. the answer
    session_manager.redact_latest_message(
        {"role": "assistant", "content": [{"text": "[Removed: payment data]"}]},
        agent,
        action="REDACTED",
    )

    # Verify: read the stored history back. to_message() returns the
    # redacted content when there is one, which is what a restored agent sees.
    repository = session_manager.session_repository
    print("Stored messages:")
    for stored in repository.list_messages(session_manager.session_id, agent.agent_id):
        marker = "[REDACTED] " if stored.redact_message else ""
        text = stored.to_message()["content"][0].get("text", "")
        print(f"  {stored.message['role']}: {marker}{text}")

    # Clean up
    session_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
```

**Expected Output** (when the guardrail blocks the input):
```
Agent: Sorry, the model cannot answer this question.

Stored messages:
  user: [REDACTED] [User input redacted.]
  assistant: [REDACTED] [Removed: payment data]
```

**Key Points:**
- Only the latest message of an agent can be redacted, and a guardrail does it for you
- A restored agent reads the redacted content (`redact_message`), not the original
- With a manual redaction the original stays in the stored `message` field: remove it yourself if it must not be kept
- The `action`, and optionally `stop_reason` and `guardrail_trace`, are stored for audit purposes

---

## Agent State Management

Using agent state to track custom information.

```python
import asyncio
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent


async def main():
    # Create session manager
    session_manager = create_mongodb_session_manager(
        session_id="state-demo",
        connection_string="mongodb://localhost:27017/",
        database_name="my_app",
    )

    # Create agent
    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="assistant",
        session_manager=session_manager,
        system_prompt="You are a shopping assistant.",
    )

    # Initial state
    print("Initial state:", agent.state.get())

    # Add items to cart via state
    agent.state.set("cart", ["laptop", "mouse"])
    agent.state.set("total_items", 2)
    agent.state.set("customer_tier", "gold")

    print("After setting state:", agent.state.get())

    # Sync state to MongoDB. Needed here because the state changed outside
    # an invocation: during agent(...) calls the hooks sync it on their own.
    session_manager.sync_agent(agent)
    print("State synced to MongoDB\n")

    # Simulate restart - create new agent with same ID
    session_manager.close()

    print("--- Simulating Restart ---\n")

    session_manager = create_mongodb_session_manager(
        session_id="state-demo",
        connection_string="mongodb://localhost:27017/",
        database_name="my_app",
    )

    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="assistant",
        session_manager=session_manager,
        system_prompt="You are a shopping assistant.",
    )

    # State is automatically restored
    print("Restored state:", agent.state.get())
    print("Cart:", agent.state.get("cart"))
    print("Customer tier:", agent.state.get("customer_tier"))

    # Clean up
    session_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
```

**Expected Output:**
```
Initial state: {}
After setting state: {'cart': ['laptop', 'mouse'], 'total_items': 2, 'customer_tier': 'gold'}
State synced to MongoDB

--- Simulating Restart ---

Restored state: {'cart': ['laptop', 'mouse'], 'total_items': 2, 'customer_tier': 'gold'}
Cart: ['laptop', 'mouse']
Customer tier: gold
```

**Key Points:**
- Agent state persists across restarts
- Use `agent.state.set()` to store custom data
- State changed during an `agent(...)` call is persisted by the hooks; call `sync_agent()` only for changes made outside one, as here
- State is automatically restored when agent is recreated

---

## Clean Shutdown

Proper cleanup and resource management.

```python
import asyncio
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent


async def main():
    session_manager = None

    try:
        # Create session manager
        session_manager = create_mongodb_session_manager(
            session_id="cleanup-demo",
            connection_string="mongodb://localhost:27017/",
            database_name="my_app",
        )

        # Create agent
        agent = Agent(
            model="claude-3-sonnet-20240229",
            agent_id="assistant",
            session_manager=session_manager,
        )

        # Do some work: the conversation and the state are persisted as the
        # invocation runs, so there is nothing to sync by hand afterwards
        response = agent("Hello!")
        print(f"Agent: {response}")

    except Exception as e:
        print(f"Error: {e}")

    finally:
        # Always close the session manager
        if session_manager:
            session_manager.close()
            print("Session manager closed")


if __name__ == "__main__":
    asyncio.run(main())
```

**Best Practices:**
- Always close the session manager in a `finally` block: `close()` also writes any messages an invocation that never closed left pending
- Handle exceptions gracefully
- Use context managers when available

---

## Complete Example: Calculator Tool

This example is based on `examples/example_calculator_tool.py` and demonstrates a real-world scenario with tools and state management.

```python
#!/usr/bin/env python3
"""
Complete example with calculator tool integration.
Demonstrates tools, state, and metrics tracking.
"""

import asyncio
from strands import Agent, tool
from strands_tools.calculator import calculator
from mongodb_session_manager import create_mongodb_session_manager


@tool
def get_user_info(field: str) -> str:
    """
    Get user information from the session.

    Args:
        field: The field to retrieve (name, email, preferences, etc.)

    Returns:
        The requested user information
    """
    # In a real app, this would query a database
    user_data = {
        "name": "Alice",
        "email": "alice@example.com",
        "preferences": {"theme": "dark", "language": "en"},
    }
    return str(user_data.get(field, "Not found"))


async def main():
    print("MongoDB Session Manager - Calculator Tool Example")
    print("=" * 60)

    # Create session manager
    session_manager = create_mongodb_session_manager(
        session_id="calculator-demo-session",
        connection_string="mongodb://localhost:27017/",
        database_name="examples",
        collection_name="calculator_sessions",
    )
    print(f"Session created: {session_manager.session_id}")

    # Create agent with tools
    agent = Agent(
        agent_id="calculator-agent",
        name="Calculator Assistant",
        description="A helpful calculator assistant.",
        model="claude-3-sonnet-20240229",
        system_prompt="""You are a calculator assistant.

Use the calculator tool for mathematical computations.
Use the get_user_info tool to retrieve user information when needed.

Be friendly and explain your calculations.""",
        tools=[calculator, get_user_info],
        session_manager=session_manager,
    )

    # Track some state
    agent.state.set("session_start", "2024-01-26T10:00:00")
    agent.state.set("calculations_count", 0)

    # First calculation
    print("\n--- Calculation 1 ---")
    response = agent("What is 15 + 27?")
    print(f"User: What is 15 + 27?")
    print(f"Agent: {response}")

    # Update state
    calc_count = agent.state.get("calculations_count", 0)
    agent.state.set("calculations_count", calc_count + 1)

    # Second calculation
    print("\n--- Calculation 2 ---")
    response = agent("Multiply that result by 3")
    print(f"User: Multiply that result by 3")
    print(f"Agent: {response}")

    # Update state
    calc_count = agent.state.get("calculations_count", 0)
    agent.state.set("calculations_count", calc_count + 1)

    # Ask about previous calculation
    print("\n--- Context Test ---")
    response = agent("What was the first calculation I asked about?")
    print(f"User: What was the first calculation I asked about?")
    print(f"Agent: {response}")

    # Use user info tool
    print("\n--- User Info ---")
    response = agent("What's my name?")
    print(f"User: What's my name?")
    print(f"Agent: {response}")

    # Everything above is already in MongoDB: each agent(...) call persisted
    # its messages, the state and the metrics through the session manager.

    # Show final state
    print("\n--- Final State ---")
    print(f"Session ID: {session_manager.session_id}")
    print(f"Agent State: {agent.state.get()}")
    print(f"Total Calculations: {agent.state.get('calculations_count')}")

    # Read back what was stored
    print(f"Total Messages: {session_manager.get_message_count(agent.agent_id)}")
    config = session_manager.get_agent_config(agent.agent_id)
    if config:
        print(f"Model: {config['model']}")

    # Clean up
    session_manager.close()
    print("\nExample completed!")


if __name__ == "__main__":
    asyncio.run(main())
```

**Expected Output:**
```
MongoDB Session Manager - Calculator Tool Example
============================================================
Session created: calculator-demo-session

--- Calculation 1 ---
User: What is 15 + 27?
Agent: Using the calculator: 15 + 27 = 42

--- Calculation 2 ---
User: Multiply that result by 3
Agent: Taking the previous result of 42 and multiplying by 3: 42 × 3 = 126

--- Context Test ---
User: What was the first calculation I asked about?
Agent: The first calculation you asked about was 15 + 27, which equals 42.

--- User Info ---
User: What's my name?
Agent: Your name is Alice!

--- Final State ---
Session ID: calculator-demo-session
Agent State: {'session_start': '2024-01-26T10:00:00', 'calculations_count': 2}
Total Calculations: 2
Total Messages: 14
Model: claude-3-sonnet-20240229

Example completed!
```

**Key Features Demonstrated:**
- Tool integration (calculator and custom tools)
- State management and tracking
- Multi-turn conversation with context
- Session persistence
- Metrics tracking
- Proper cleanup

---

## Try It Yourself

1. **Modify the Hello World example** to use a different model or system prompt
2. **Extend the State Management example** to track more complex data structures
3. **Create your own custom tool** and integrate it like the calculator example
4. **Experiment with session resumption** by running the script multiple times
5. **Try different MongoDB connection strings** for your environment

## Troubleshooting

### Connection Issues
```python
# Problem: Can't connect to MongoDB
# Solution: Check connection string and ensure MongoDB is running

# Test connection
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017/")
client.server_info()  # Will raise exception if can't connect
```

### Session Not Found
```python
# Problem: Session not found when resuming
# Solution: Ensure you're using the same session_id and database

# Check if session exists. Ask the repository: building a session manager
# creates the session when it does not exist, so it cannot tell you.
from mongodb_session_manager import MongoDBSessionRepository

repository = MongoDBSessionRepository(
    connection_string="mongodb://localhost:27017/",
    database_name="my_app",  # and collection_name, if you set one
)
if repository.read_session("resume-demo-session") is None:
    print("Session not found - a new one will be created")
repository.close()
```

### Memory Issues
```python
# Problem: Too many messages in session
# Solution: Implement message pruning or use a new session

# Count what is stored (computed in MongoDB, the history is not transferred)
MAX_MESSAGES = 100
if session_manager.get_message_count(agent.agent_id) > MAX_MESSAGES:
    # Consider starting a new session
    pass

# What the agent keeps in its context is bounded by its conversation manager
# (Strands' default keeps a window of 40 messages), and restoring a session
# skips the messages it has already trimmed
from strands.agent.conversation_manager import SlidingWindowConversationManager

agent = Agent(
    model="claude-3-sonnet-20240229",
    agent_id="assistant",
    session_manager=session_manager,
    conversation_manager=SlidingWindowConversationManager(window_size=20),
)
```

## Next Steps

- Learn about [FastAPI Integration](fastapi-integration.md) for production deployments
- Explore [Metadata Patterns](metadata-patterns.md) for advanced session management
- See [Feedback Patterns](feedback-patterns.md) for user feedback collection
- Check [AWS Patterns](aws-patterns.md) for cloud integrations

## Reference Files

- `examples/example_calculator_tool.py` - Full calculator example
- `src/mongodb_session_manager/mongodb_session_manager.py` - Main implementation
- `src/mongodb_session_manager/mongodb_session_repository.py` - Repository layer
