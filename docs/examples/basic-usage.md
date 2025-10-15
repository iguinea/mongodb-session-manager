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
        collection_name="sessions"
    )

    # Create agent
    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="assistant",
        session_manager=session_manager,
        system_prompt="You are a helpful assistant."
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
        database_name="my_app"
    )

    # Create agent
    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="assistant",
        session_manager=session_manager,
        system_prompt="You are a helpful math tutor."
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
        database_name="my_app"
    )

    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="assistant",
        session_manager=session_manager,
        system_prompt="You are a helpful assistant with excellent memory."
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
        database_name="my_app"
    )

    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="assistant",
        session_manager=session_manager,
        system_prompt="You are a helpful assistant with excellent memory."
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
        database_name="my_app"
    )

    # Create a technical agent
    tech_agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="tech-support",
        session_manager=session_manager,
        system_prompt="You are a technical support agent."
    )

    # Create a sales agent
    sales_agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="sales-rep",
        session_manager=session_manager,
        system_prompt="You are a friendly sales representative."
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

```python
import asyncio
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent

async def main():
    # Create session manager
    session_manager = create_mongodb_session_manager(
        session_id="redaction-demo",
        connection_string="mongodb://localhost:27017/",
        database_name="my_app"
    )

    # Create agent
    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="assistant",
        session_manager=session_manager,
        system_prompt="You are a customer service assistant."
    )

    # User shares sensitive information
    response = agent("My credit card number is 4532-1234-5678-9010")
    print(f"User: My credit card number is 4532-1234-5678-9010")
    print(f"Agent: {response}\n")

    # Get messages to find the one to redact
    session_data = session_manager.get_session()
    messages = session_data.agents[agent.agent_id].messages

    # Find the message with credit card info
    for msg in messages:
        if "4532-1234-5678-9010" in msg.content:
            print(f"Found sensitive message: {msg.content}")

            # Redact the message
            session_manager.redact_message(
                agent_id=agent.agent_id,
                message_id=msg.message_id,
                redacted_reason="Contains sensitive payment information"
            )
            print("Message redacted!\n")

    # Verify redaction
    session_data = session_manager.get_session()
    messages = session_data.agents[agent.agent_id].messages

    print("Messages after redaction:")
    for msg in messages:
        if msg.redacted:
            print(f"  [REDACTED: {msg.redacted_reason}]")
        else:
            print(f"  {msg.content}")

    # Clean up
    session_manager.close()

if __name__ == "__main__":
    asyncio.run(main())
```

**Expected Output:**
```
User: My credit card number is 4532-1234-5678-9010
Agent: I've received that information...

Found sensitive message: My credit card number is 4532-1234-5678-9010
Message redacted!

Messages after redaction:
  [REDACTED: Contains sensitive payment information]
  I've received that information...
```

**Key Points:**
- Messages can be redacted after the fact
- Original content is replaced with redaction notice
- Redaction reason is stored for audit purposes

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
        database_name="my_app"
    )

    # Create agent
    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="assistant",
        session_manager=session_manager,
        system_prompt="You are a shopping assistant."
    )

    # Initial state
    print("Initial state:", agent.state.get())

    # Add items to cart via state
    agent.state.set("cart", ["laptop", "mouse"])
    agent.state.set("total_items", 2)
    agent.state.set("customer_tier", "gold")

    print("After setting state:", agent.state.get())

    # Sync state to MongoDB
    session_manager.sync_agent(agent)
    print("State synced to MongoDB\n")

    # Simulate restart - create new agent with same ID
    session_manager.close()

    print("--- Simulating Restart ---\n")

    session_manager = create_mongodb_session_manager(
        session_id="state-demo",
        connection_string="mongodb://localhost:27017/",
        database_name="my_app"
    )

    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="assistant",
        session_manager=session_manager,
        system_prompt="You are a shopping assistant."
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
- Call `sync_agent()` to persist state to MongoDB
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
            database_name="my_app"
        )

        # Create agent
        agent = Agent(
            model="claude-3-sonnet-20240229",
            agent_id="assistant",
            session_manager=session_manager
        )

        # Do some work
        response = agent("Hello!")
        print(f"Agent: {response}")

        # Sync final state
        session_manager.sync_agent(agent)
        print("Agent state synced")

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
- Always close the session manager in a `finally` block
- Sync agent state before shutdown
- Handle exceptions gracefully
- Use context managers when available

---

## Complete Example: Calculator Tool

This example is based on `/workspace/examples/example_calculator_tool.py` and demonstrates a real-world scenario with tools and state management.

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
        "preferences": {"theme": "dark", "language": "en"}
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
        collection_name="calculator_sessions"
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
        session_manager=session_manager
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

    # Sync everything to MongoDB
    session_manager.sync_agent(agent)

    # Show final state
    print("\n--- Final State ---")
    print(f"Session ID: {session_manager.session_id}")
    print(f"Agent State: {agent.state.get()}")
    print(f"Total Calculations: {agent.state.get('calculations_count')}")

    # Get metrics if available
    try:
        session_data = session_manager.get_session()
        agent_data = session_data.agents.get(agent.agent_id)
        if agent_data:
            print(f"Total Messages: {len(agent_data.messages)}")
            print(f"Agent Name: {agent_data.name}")
    except Exception as e:
        print(f"Could not retrieve metrics: {e}")

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
Total Messages: 8
Agent Name: Calculator Assistant

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

# Check if session exists
session_data = session_manager.get_session()
if not session_data:
    print("Session not found - creating new session")
```

### Memory Issues
```python
# Problem: Too many messages in session
# Solution: Implement message pruning or use a new session

# Keep only last N messages
MAX_MESSAGES = 100
session_data = session_manager.get_session()
if len(session_data.agents[agent_id].messages) > MAX_MESSAGES:
    # Consider starting a new session or implementing pruning
    pass
```

## Next Steps

- Learn about [FastAPI Integration](fastapi-integration.md) for production deployments
- Explore [Metadata Patterns](metadata-patterns.md) for advanced session management
- See [Feedback Patterns](feedback-patterns.md) for user feedback collection
- Check [AWS Patterns](aws-patterns.md) for cloud integrations

## Reference Files

- `/workspace/examples/example_calculator_tool.py` - Full calculator example
- `/workspace/src/mongodb_session_manager/mongodb_session_manager.py` - Main implementation
- `/workspace/src/mongodb_session_manager/mongodb_session_repository.py` - Repository layer
