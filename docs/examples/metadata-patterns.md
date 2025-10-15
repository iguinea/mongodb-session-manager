# Metadata Management Patterns

## 🚀 Runnable Examples

This guide includes multiple code examples. For complete, executable scripts, see:

| Script | Description | Run Command |
|--------|-------------|-------------|
| [example_metadata_tool.py](../../examples/example_metadata_tool.py) | Agent autonomously managing metadata | `uv run python examples/example_metadata_tool.py` |
| [example_metadata_tool_direct.py](../../examples/example_metadata_tool_direct.py) | Direct metadata tool usage | `uv run python examples/example_metadata_tool_direct.py` |
| [example_metadata_hook.py](../../examples/example_metadata_hook.py) | Metadata hooks (audit, validation, caching) | `uv run python examples/example_metadata_hook.py` |
| [example_metadata_update.py](../../examples/example_metadata_update.py) | Metadata update with field preservation | `uv run python examples/example_metadata_update.py` |
| [example_metadata_production.py](../../examples/example_metadata_production.py) | Production customer support example | `uv run python examples/example_metadata_production.py` |

📁 **All examples**: [View examples directory](../../examples/)

---

This guide demonstrates advanced metadata management patterns with MongoDB Session Manager. Learn how to track session context, implement progressive information gathering, and build intelligent systems with metadata hooks.

## Table of Contents

- [Understanding Metadata](#understanding-metadata)
- [Basic Metadata Operations](#basic-metadata-operations)
- [Progressive Information Gathering](#progressive-information-gathering)
- [User Context Tracking](#user-context-tracking)
- [Session Status Updates](#session-status-updates)
- [Metadata Tool for Agents](#metadata-tool-for-agents)
- [Metadata Validation Patterns](#metadata-validation-patterns)
- [Caching with Metadata Hooks](#caching-with-metadata-hooks)
- [External System Synchronization](#external-system-synchronization)
- [Combined Hook Patterns](#combined-hook-patterns)

---

## Understanding Metadata

Metadata in MongoDB Session Manager is a flexible key-value store attached to each session. It's perfect for:

- **User Context**: Preferences, profile information, settings
- **Session State**: Current step, workflow status, flags
- **Analytics**: Tracking user behavior, interaction patterns
- **Integration**: Syncing data with external systems
- **Feature Flags**: Controlling behavior per session

**Key Features:**
- **Partial Updates**: Update specific fields without affecting others
- **Field Deletion**: Remove sensitive or outdated data
- **Hooks**: Intercept and customize metadata operations
- **Agent Integration**: Agents can manage metadata autonomously
- **Persistence**: Metadata survives across session resumption

---

## Basic Metadata Operations

Fundamental metadata operations: update, get, and delete.

```python
"""
Basic metadata operations.
"""

from mongodb_session_manager import create_mongodb_session_manager

# Create session manager
session_manager = create_mongodb_session_manager(
    session_id="metadata-basics",
    connection_string="mongodb://localhost:27017/",
    database_name="examples"
)

# === UPDATE METADATA ===
# Set initial metadata
session_manager.update_metadata({
    "user_id": "user-123",
    "user_name": "Alice",
    "language": "en",
    "theme": "dark"
})

print("Initial metadata set")

# Partial update - only changes specified fields
session_manager.update_metadata({
    "language": "es",  # Changed
    "tier": "premium"  # Added
    # user_id, user_name, theme remain unchanged
})

print("Metadata partially updated")

# === GET METADATA ===
# Get all metadata
result = session_manager.get_metadata()
metadata = result.get("metadata", {})

print("\nAll metadata:")
for key, value in metadata.items():
    print(f"  {key}: {value}")

# Expected:
# user_id: user-123
# user_name: Alice
# language: es (updated)
# theme: dark
# tier: premium (added)

# === DELETE METADATA ===
# Remove specific fields
session_manager.delete_metadata(["theme", "tier"])

print("\nAfter deletion:")
metadata = session_manager.get_metadata().get("metadata", {})
for key, value in metadata.items():
    print(f"  {key}: {value}")

# Expected:
# user_id: user-123
# user_name: Alice
# language: es

# Clean up
session_manager.close()
```

**Output:**
```
Initial metadata set
Metadata partially updated

All metadata:
  user_id: user-123
  user_name: Alice
  language: es
  theme: dark
  tier: premium

After deletion:
  user_id: user-123
  user_name: Alice
  language: es
```

---

## Progressive Information Gathering

Collect user information progressively throughout the conversation.

```python
"""
Progressive information gathering pattern.
Use metadata to build up user profile over time.
"""

import asyncio
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent

async def main():
    session_manager = create_mongodb_session_manager(
        session_id="onboarding-session",
        connection_string="mongodb://localhost:27017/",
        database_name="examples"
    )

    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="onboarding-agent",
        session_manager=session_manager,
        system_prompt="""You are an onboarding assistant.

Your goal is to collect user information progressively:
1. Start with name
2. Then email
3. Then preferences
4. Finally, goals

Be friendly and conversational. Don't ask for everything at once.
After collecting each piece of info, acknowledge it and move to the next."""
    )

    # Simulate onboarding flow
    conversations = [
        "Hello! I'd like to get started.",
        "My name is Alice Johnson.",
        "My email is alice@example.com",
        "I prefer dark mode and email notifications.",
        "I want to learn about AI and automation."
    ]

    for user_message in conversations:
        print(f"\n{'='*60}")
        print(f"User: {user_message}")

        # Agent responds
        response = await agent.invoke_async(user_message)
        print(f"Agent: {response}")

        # Extract information and update metadata
        metadata_updates = {}

        # Simple pattern matching (in production, use NER or structured extraction)
        if "name is" in user_message.lower():
            name = user_message.split("name is")[-1].strip().rstrip(".")
            metadata_updates["user_name"] = name
            metadata_updates["onboarding_step"] = "email"

        elif "@" in user_message:
            email = user_message.split()[-1].rstrip(".")
            metadata_updates["email"] = email
            metadata_updates["onboarding_step"] = "preferences"

        elif "prefer" in user_message.lower():
            if "dark" in user_message.lower():
                metadata_updates["theme"] = "dark"
            if "email" in user_message.lower():
                metadata_updates["notifications"] = "email"
            metadata_updates["onboarding_step"] = "goals"

        elif "want to" in user_message.lower() or "learn" in user_message.lower():
            metadata_updates["goals"] = user_message
            metadata_updates["onboarding_step"] = "complete"
            metadata_updates["onboarding_completed"] = True

        # Update metadata if we extracted anything
        if metadata_updates:
            session_manager.update_metadata(metadata_updates)
            print(f"\n[Metadata updated: {list(metadata_updates.keys())}]")

        # Show current metadata
        current_metadata = session_manager.get_metadata().get("metadata", {})
        print(f"[Current profile: {dict(current_metadata)}]")

    # Final profile
    print(f"\n{'='*60}")
    print("ONBOARDING COMPLETE")
    print(f"{'='*60}")

    final_metadata = session_manager.get_metadata().get("metadata", {})
    print("\nUser Profile:")
    for key, value in final_metadata.items():
        print(f"  {key}: {value}")

    session_manager.close()

if __name__ == "__main__":
    asyncio.run(main())
```

**Expected Flow:**
```
============================================================
User: Hello! I'd like to get started.
Agent: Welcome! I'd love to help you get started. What's your name?
[Current profile: {}]

============================================================
User: My name is Alice Johnson.
Agent: Nice to meet you, Alice! What's your email address?
[Metadata updated: ['user_name', 'onboarding_step']]
[Current profile: {'user_name': 'Alice Johnson', 'onboarding_step': 'email'}]

============================================================
User: My email is alice@example.com
Agent: Great! Do you have any preferences for theme or notifications?
[Metadata updated: ['email', 'onboarding_step']]
[Current profile: {'user_name': 'Alice Johnson', 'onboarding_step': 'preferences', 'email': 'alice@example.com'}]

...

============================================================
ONBOARDING COMPLETE
============================================================

User Profile:
  user_name: Alice Johnson
  onboarding_step: complete
  email: alice@example.com
  theme: dark
  notifications: email
  goals: I want to learn about AI and automation.
  onboarding_completed: True
```

---

## User Context Tracking

Track user context across sessions for personalization.

```python
"""
User context tracking for personalized experiences.
"""

import asyncio
from datetime import datetime
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent

async def main():
    # Create or resume session
    session_manager = create_mongodb_session_manager(
        session_id="user-alice-context",
        connection_string="mongodb://localhost:27017/",
        database_name="examples"
    )

    # Get existing metadata or initialize
    existing_metadata = session_manager.get_metadata().get("metadata", {})

    if not existing_metadata:
        # First time user
        print("New user detected - initializing profile")
        session_manager.update_metadata({
            "first_seen": datetime.now().isoformat(),
            "visit_count": 1,
            "last_topic": None,
            "preferences": {
                "language": "en",
                "expertise_level": "beginner"
            }
        })
    else:
        # Returning user
        print(f"Welcome back! Last visit: {existing_metadata.get('last_seen')}")
        visit_count = existing_metadata.get("visit_count", 0) + 1
        session_manager.update_metadata({
            "visit_count": visit_count,
            "last_seen": datetime.now().isoformat()
        })

    # Create agent that uses context
    metadata = session_manager.get_metadata().get("metadata", {})
    expertise = metadata.get("preferences", {}).get("expertise_level", "beginner")

    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="context-aware-agent",
        session_manager=session_manager,
        system_prompt=f"""You are a helpful assistant.

User context:
- Expertise level: {expertise}
- Visits: {metadata.get('visit_count', 1)}
- Last topic: {metadata.get('last_topic', 'None')}

Adjust your explanations based on expertise level:
- beginner: Detailed, simple explanations
- intermediate: Balanced technical depth
- expert: Concise, technical explanations
"""
    )

    # Conversation
    response = await agent.invoke_async("Explain machine learning to me")
    print(f"\nUser: Explain machine learning to me")
    print(f"Agent: {response}")

    # Update context
    session_manager.update_metadata({
        "last_topic": "machine_learning",
        "topics_discussed": metadata.get("topics_discussed", []) + ["machine_learning"]
    })

    # User progresses
    print("\n[User completes beginner course]")
    session_manager.update_metadata({
        "preferences": {
            "language": "en",
            "expertise_level": "intermediate"  # Upgraded!
        },
        "courses_completed": ["ml_basics"]
    })

    # Next session - agent adapts
    print("\n--- Next Session ---\n")

    # Recreate agent with updated context
    metadata = session_manager.get_metadata().get("metadata", {})
    expertise = metadata.get("preferences", {}).get("expertise_level", "beginner")

    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="context-aware-agent",
        session_manager=session_manager,
        system_prompt=f"""You are a helpful assistant.

User context:
- Expertise level: {expertise}
- Visits: {metadata.get('visit_count', 1)}
- Topics discussed: {metadata.get('topics_discussed', [])}
- Courses completed: {metadata.get('courses_completed', [])}

Adjust explanations based on expertise level."""
    )

    response = await agent.invoke_async("Now explain neural networks")
    print(f"User: Now explain neural networks")
    print(f"Agent: {response}")

    session_manager.close()

if __name__ == "__main__":
    asyncio.run(main())
```

**Key Benefits:**
- Personalized experiences based on user history
- Progressive expertise adaptation
- Topic continuity across sessions
- User journey tracking

---

## Session Status Updates

Track workflow status and session lifecycle.

```python
"""
Session status tracking for workflows.
"""

from mongodb_session_manager import create_mongodb_session_manager
from datetime import datetime
from enum import Enum

class SessionStatus(Enum):
    INITIATED = "initiated"
    IN_PROGRESS = "in_progress"
    WAITING_INPUT = "waiting_input"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"

def update_status(session_manager, status: SessionStatus, details: str = None):
    """Update session status with timestamp."""
    update = {
        "status": status.value,
        "status_updated_at": datetime.now().isoformat()
    }
    if details:
        update["status_details"] = details

    session_manager.update_metadata(update)
    print(f"[Status: {status.value}] {details or ''}")

# Create session
session_manager = create_mongodb_session_manager(
    session_id="workflow-session",
    connection_string="mongodb://localhost:27017/",
    database_name="examples"
)

# Workflow simulation
update_status(session_manager, SessionStatus.INITIATED, "User started order process")

# Collecting information
update_status(session_manager, SessionStatus.WAITING_INPUT, "Waiting for shipping address")

# User provides input
session_manager.update_metadata({
    "shipping_address": "123 Main St, City, 12345",
    "shipping_method": "express"
})

update_status(session_manager, SessionStatus.PROCESSING, "Processing order")

# Processing steps
steps = ["Validate address", "Calculate shipping", "Process payment", "Create order"]
for i, step in enumerate(steps, 1):
    session_manager.update_metadata({
        f"step_{i}_completed": True,
        f"step_{i}_timestamp": datetime.now().isoformat()
    })
    print(f"  ✓ {step}")

update_status(session_manager, SessionStatus.COMPLETED, "Order #12345 created successfully")

# Check final metadata
metadata = session_manager.get_metadata().get("metadata", {})
print("\nFinal Session Metadata:")
print(f"  Status: {metadata.get('status')}")
print(f"  Shipping: {metadata.get('shipping_method')}")
print(f"  Steps completed: {sum(1 for k in metadata.keys() if 'step_' in k and 'completed' in k)}")

session_manager.close()
```

---

## Metadata Tool for Agents

Enable agents to autonomously manage session metadata.

Reference: `/workspace/examples/example_metadata_tool.py`

```python
"""
Metadata tool integration - agents manage their own context.
Based on /workspace/examples/example_metadata_tool.py
"""

import asyncio
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent

async def main():
    # Create session manager
    session_manager = create_mongodb_session_manager(
        session_id="agent-metadata-demo",
        connection_string="mongodb://localhost:27017/",
        database_name="examples"
    )

    # Get the metadata tool
    metadata_tool = session_manager.get_metadata_tool()

    # Create agent with metadata tool
    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="metadata-agent",
        session_manager=session_manager,
        tools=[metadata_tool],
        system_prompt="""You are a helpful assistant with metadata management.

You can use the manage_metadata tool to:
- Get metadata: manage_metadata("get")
- Get specific keys: manage_metadata("get", keys=["key1", "key2"])
- Set/update metadata: manage_metadata("set", {"key": "value"})
- Delete keys: manage_metadata("delete", keys=["key1"])

Use metadata to track:
- User preferences
- Conversation context
- Session state
- Important information

Always confirm when you update metadata."""
    )

    # Agent sets up metadata
    print("=== Agent Setting Up Context ===\n")
    response = await agent.invoke_async(
        "Please set up initial metadata for our conversation. "
        "Set my name as 'Alice', language preference as 'English', "
        "and note that we're discussing MongoDB."
    )
    print(f"Agent: {response}\n")

    # Agent retrieves metadata
    print("=== Agent Checking Metadata ===\n")
    response = await agent.invoke_async(
        "What metadata do we have stored?"
    )
    print(f"Agent: {response}\n")

    # Agent updates metadata
    print("=== Agent Updating Context ===\n")
    response = await agent.invoke_async(
        "Change my language preference to Spanish and "
        "add a timezone field set to 'UTC-5'."
    )
    print(f"Agent: {response}\n")

    # Agent uses metadata context
    print("=== Agent Using Context ===\n")
    response = await agent.invoke_async(
        "Based on what you know about me, greet me appropriately."
    )
    print(f"Agent: {response}\n")

    # Agent cleans up metadata
    print("=== Agent Cleaning Up ===\n")
    response = await agent.invoke_async(
        "Remove the timezone field but keep my name and language preference."
    )
    print(f"Agent: {response}\n")

    # Verify final state
    metadata = session_manager.get_metadata().get("metadata", {})
    print("=== Final Metadata ===")
    for key, value in metadata.items():
        print(f"  {key}: {value}")

    session_manager.close()

if __name__ == "__main__":
    asyncio.run(main())
```

**Expected Output:**
```
=== Agent Setting Up Context ===

Agent: I've set up the initial metadata for our conversation. I've stored:
- Your name as "Alice"
- Language preference as "English"
- Current topic as "MongoDB"

=== Agent Checking Metadata ===

Agent: We currently have the following metadata stored:
- name: Alice
- language: English
- topic: MongoDB

=== Agent Updating Context ===

Agent: I've updated the metadata:
- Changed language preference to Spanish
- Added timezone: UTC-5

=== Agent Using Context ===

Agent: ¡Hola Alice! Based on your preference for Spanish and your interest
in MongoDB, I'm here to help you in your preferred language.

=== Agent Cleaning Up ===

Agent: I've removed the timezone field. The remaining metadata is:
- name: Alice
- language: Spanish

=== Final Metadata ===
  name: Alice
  language: Spanish
```

---

## Metadata Validation Patterns

Validate and enrich metadata before storage using hooks.

Reference: `/workspace/examples/example_metadata_hook.py`

```python
"""
Metadata validation with hooks.
Based on /workspace/examples/example_metadata_hook.py
"""

import logging
from datetime import datetime
from mongodb_session_manager import MongoDBSessionManager

logger = logging.getLogger(__name__)

def metadata_validation_hook(original_func, action: str, session_id: str, **kwargs):
    """
    Hook that validates metadata before operations.
    """
    # Define validation rules
    PROTECTED_FIELDS = ["_id", "session_id", "created_at", "system_internal"]
    REQUIRED_FIELDS = ["last_updated", "updated_by"]
    MAX_VALUE_LENGTH = 1000

    if action == "update" and "metadata" in kwargs:
        metadata = kwargs["metadata"]

        # Check for protected fields
        for field in PROTECTED_FIELDS:
            if field in metadata:
                raise ValueError(f"Cannot update protected field: {field}")

        # Auto-add required fields
        for field in REQUIRED_FIELDS:
            if field not in metadata:
                metadata[field] = (
                    "system" if field == "updated_by"
                    else datetime.now().isoformat()
                )

        # Validate value lengths
        for key, value in metadata.items():
            if isinstance(value, str) and len(value) > MAX_VALUE_LENGTH:
                raise ValueError(
                    f"Value for '{key}' exceeds maximum length of {MAX_VALUE_LENGTH}"
                )

        # Add validation timestamp
        metadata["_validated_at"] = datetime.now().isoformat()

        logger.info(f"[VALIDATION] Metadata validated for session {session_id}")
        return original_func(metadata)

    elif action == "delete" and "keys" in kwargs:
        # Prevent deletion of protected fields
        protected_deletions = [
            key for key in kwargs["keys"]
            if key in PROTECTED_FIELDS
        ]
        if protected_deletions:
            raise ValueError(f"Cannot delete protected fields: {protected_deletions}")

        return original_func(kwargs["keys"])

    else:  # get
        return original_func()


# Usage
session_manager = MongoDBSessionManager(
    session_id="validated-session",
    connection_string="mongodb://localhost:27017/",
    database_name="examples",
    metadataHook=metadata_validation_hook
)

# This will auto-add required fields
session_manager.update_metadata({
    "user_name": "Alice",
    "department": "Engineering"
})

# Check what was stored
metadata = session_manager.get_metadata().get("metadata", {})
print("Metadata with auto-added fields:")
for key, value in metadata.items():
    print(f"  {key}: {value}")

# Expected:
# user_name: Alice
# department: Engineering
# last_updated: 2024-01-26T10:00:00.123456
# updated_by: system
# _validated_at: 2024-01-26T10:00:00.123456

# This will fail - protected field
try:
    session_manager.update_metadata({
        "_id": "cannot-change-this"
    })
except ValueError as e:
    print(f"\n✓ Validation caught error: {e}")

session_manager.close()
```

---

## Caching with Metadata Hooks

Implement caching layer for metadata reads using hooks.

Reference: `/workspace/examples/example_metadata_hook.py`

```python
"""
Metadata caching with hooks.
Based on /workspace/examples/example_metadata_hook.py
"""

import logging
import time
from typing import Callable, Dict, Any
from mongodb_session_manager import MongoDBSessionManager

logger = logging.getLogger(__name__)

class MetadataCacheHook:
    """Hook that implements caching for metadata operations."""

    def __init__(self, ttl_seconds: int = 60):
        self.cache = {}
        self.ttl_seconds = ttl_seconds

    def __call__(self, original_func: Callable, action: str, session_id: str, **kwargs):
        if action == "get":
            # Check cache
            cache_key = f"{session_id}:metadata"
            if cache_key in self.cache:
                cached_data, timestamp = self.cache[cache_key]
                if time.time() - timestamp < self.ttl_seconds:
                    logger.info(f"[CACHE] Hit for session {session_id}")
                    return cached_data

            # Cache miss - fetch and cache
            logger.info(f"[CACHE] Miss for session {session_id}")
            result = original_func()
            self.cache[cache_key] = (result, time.time())
            return result

        elif action in ["update", "delete"]:
            # Invalidate cache on write operations
            cache_key = f"{session_id}:metadata"
            if cache_key in self.cache:
                del self.cache[cache_key]
                logger.info(f"[CACHE] Invalidated for session {session_id}")

            # Execute operation
            if action == "update":
                return original_func(kwargs["metadata"])
            else:  # delete
                return original_func(kwargs["keys"])


# Usage
cache_hook = MetadataCacheHook(ttl_seconds=5)

session_manager = MongoDBSessionManager(
    session_id="cached-session",
    connection_string="mongodb://localhost:27017/",
    database_name="examples",
    metadataHook=cache_hook
)

# First call - cache miss
session_manager.update_metadata({"data": "initial"})
metadata1 = session_manager.get_metadata()  # Cache miss
print("[CACHE] Miss - fetched from MongoDB")

# Second call - cache hit (within TTL)
metadata2 = session_manager.get_metadata()  # Cache hit
print("[CACHE] Hit - returned from cache")

# Update invalidates cache
session_manager.update_metadata({"data": "updated"})
print("[CACHE] Invalidated")

# Next call - cache miss again
metadata3 = session_manager.get_metadata()  # Cache miss
print("[CACHE] Miss - fetched from MongoDB after invalidation")

session_manager.close()
```

**Performance Impact:**
```
Without caching:
- Every get_metadata() queries MongoDB (~5-10ms)

With caching (60s TTL):
- First call: MongoDB query (~5-10ms)
- Subsequent calls: Cache hit (<1ms)
- 50-100x improvement for read-heavy workloads
```

---

## External System Synchronization

Sync metadata changes to external systems using hooks.

```python
"""
External system synchronization with metadata hooks.
"""

import logging
import asyncio
from typing import Dict, Any, Callable
from mongodb_session_manager import MongoDBSessionManager

logger = logging.getLogger(__name__)

class ExternalSyncHook:
    """Hook to sync metadata to external systems."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def sync_to_external(self, session_id: str, metadata: Dict[str, Any], operation: str):
        """Sync metadata to external system (simulated)."""
        # In production, this would make HTTP request to webhook
        logger.info(f"[SYNC] Sending {operation} to {self.webhook_url}")
        logger.info(f"[SYNC] Session: {session_id}, Data: {metadata}")

        # Simulate API call
        await asyncio.sleep(0.1)
        logger.info(f"[SYNC] Successfully synced to external system")

    def __call__(self, original_func: Callable, action: str, session_id: str, **kwargs):
        # Execute original operation first
        if action == "update":
            result = original_func(kwargs["metadata"])

            # Sync to external system asynchronously
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self.sync_to_external(session_id, kwargs["metadata"], action)
                )
            except RuntimeError:
                # No running loop - create thread
                import threading
                def run():
                    asyncio.run(
                        self.sync_to_external(session_id, kwargs["metadata"], action)
                    )
                threading.Thread(target=run, daemon=True).start()

        elif action == "delete":
            result = original_func(kwargs["keys"])

            # Notify external system of deletion
            deleted_metadata = {key: None for key in kwargs["keys"]}
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self.sync_to_external(session_id, deleted_metadata, action)
                )
            except RuntimeError:
                import threading
                def run():
                    asyncio.run(
                        self.sync_to_external(session_id, deleted_metadata, action)
                    )
                threading.Thread(target=run, daemon=True).start()

        else:  # get
            result = original_func()

        return result


# Usage
sync_hook = ExternalSyncHook(webhook_url="https://api.example.com/webhooks/metadata")

session_manager = MongoDBSessionManager(
    session_id="synced-session",
    connection_string="mongodb://localhost:27017/",
    database_name="examples",
    metadataHook=sync_hook
)

# All updates are synced
session_manager.update_metadata({
    "status": "processing",
    "priority": "high"
})

# Deletions are synced too
session_manager.delete_metadata(["priority"])

session_manager.close()
```

---

## Combined Hook Patterns

Chain multiple hooks together for complex behavior.

Reference: `/workspace/examples/example_metadata_hook.py`

```python
"""
Combined hooks - validation + audit + caching.
Based on /workspace/examples/example_metadata_hook.py
"""

import logging
import json
import time
from datetime import datetime
from mongodb_session_manager import MongoDBSessionManager

logger = logging.getLogger(__name__)

# Hook 1: Audit
def audit_hook(original_func, action: str, session_id: str, **kwargs):
    """Audit all metadata operations."""
    logger.info(f"[AUDIT] {action} on session {session_id}")
    if action == "update" and "metadata" in kwargs:
        logger.info(f"[AUDIT] Data: {json.dumps(kwargs['metadata'], default=str)}")

    start_time = time.time()

    if action == "update":
        result = original_func(kwargs["metadata"])
    elif action == "delete":
        result = original_func(kwargs["keys"])
    else:
        result = original_func()

    elapsed = time.time() - start_time
    logger.info(f"[AUDIT] {action} completed in {elapsed:.3f}s")

    return result

# Hook 2: Validation
def validation_hook(original_func, action: str, session_id: str, **kwargs):
    """Validate metadata before storage."""
    if action == "update" and "metadata" in kwargs:
        metadata = kwargs["metadata"]

        # Add required fields
        if "last_updated" not in metadata:
            metadata["last_updated"] = datetime.now().isoformat()
        if "updated_by" not in metadata:
            metadata["updated_by"] = "system"

        logger.info(f"[VALIDATION] Validated for {session_id}")
        return original_func(metadata)

    elif action == "delete":
        return original_func(kwargs["keys"])
    else:
        return original_func()

# Combine hooks
def create_combined_hook(*hooks):
    """Chain multiple hooks together."""
    def combined_hook(original_func, action: str, session_id: str, **kwargs):
        # Build chain
        current_func = original_func
        for hook in reversed(hooks):
            def make_wrapped(hook, next_func):
                def wrapped(*args, **kw):
                    if args:
                        return next_func(*args, **kw)
                    else:
                        return hook(next_func, action, session_id, **kw)
                return wrapped

            current_func = make_wrapped(hook, current_func)

        # Execute
        if action == "update":
            return current_func(kwargs["metadata"])
        elif action == "delete":
            return current_func(kwargs["keys"])
        else:
            return current_func()

    return combined_hook

# Usage
combined_hook = create_combined_hook(
    audit_hook,
    validation_hook
)

session_manager = MongoDBSessionManager(
    session_id="combined-hooks-session",
    connection_string="mongodb://localhost:27017/",
    database_name="examples",
    metadataHook=combined_hook
)

# Operations go through both hooks
session_manager.update_metadata({
    "user_action": "login",
    "ip_address": "192.168.1.1"
})

# Check result - validation added fields, audit logged everything
metadata = session_manager.get_metadata().get("metadata", {})
print("\nFinal metadata (with auto-added fields):")
for key, value in metadata.items():
    print(f"  {key}: {value}")

session_manager.close()
```

**Expected Output:**
```
[AUDIT] update on session combined-hooks-session
[AUDIT] Data: {"user_action": "login", "ip_address": "192.168.1.1"}
[VALIDATION] Validated for combined-hooks-session
[AUDIT] update completed in 0.015s

Final metadata (with auto-added fields):
  user_action: login
  ip_address: 192.168.1.1
  last_updated: 2024-01-26T10:00:00.123456
  updated_by: system
```

---

## Try It Yourself

1. **Build a user preference system** that tracks theme, language, and notification settings
2. **Create a workflow tracker** that updates status as users progress through steps
3. **Implement a recommendation system** that uses metadata to personalize suggestions
4. **Build a metadata migration tool** that updates old metadata formats to new ones
5. **Create a compliance hook** that ensures GDPR-required fields are present

## Troubleshooting

### Metadata Not Persisting
```python
# Problem: Metadata changes aren't saved
# Solution: Ensure you're not creating a new session manager

# Wrong:
session_manager1.update_metadata({"key": "value"})
session_manager2 = create_mongodb_session_manager(session_id)  # Different instance!

# Right:
session_manager.update_metadata({"key": "value"})
# Use same instance or same session_id
```

### Hook Not Executing
```python
# Problem: Hook doesn't seem to run
# Solution: Check hook signature

# Wrong signature:
def my_hook(func, session_id):  # Missing action and kwargs
    pass

# Correct signature:
def my_hook(original_func, action: str, session_id: str, **kwargs):
    pass
```

## Next Steps

- Learn [Feedback Patterns](feedback-patterns.md) for user feedback collection
- Explore [AWS Patterns](aws-patterns.md) for cloud integrations
- See [FastAPI Integration](fastapi-integration.md) for production deployments

## Reference Files

- `/workspace/examples/example_metadata_tool.py` - Agent metadata tool
- `/workspace/examples/example_metadata_hook.py` - Comprehensive hook examples
- `/workspace/src/mongodb_session_manager/mongodb_session_manager.py` - Implementation
