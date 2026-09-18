# Hooks API Reference

## Overview

The MongoDB Session Manager provides a powerful hook system that allows you to intercept and customize metadata and feedback operations. Hooks enable use cases like audit logging, validation, caching, notifications, and integration with external services.

This document covers:
- **Metadata Hooks**: Intercept metadata operations (update, get, delete)
- **Feedback Hooks**: Intercept feedback operations (add)
- **AWS SNS Integration**: Real-time feedback notifications via Amazon SNS
- **AWS SQS Integration**: Metadata propagation for Server-Sent Events (SSE)

---

## Table of Contents

1. [Metadata Hooks](#metadata-hooks)
2. [Feedback Hooks](#feedback-hooks)
3. [FeedbackSNSHook Class](#feedbacksnshook-class)
4. [MetadataSQSHook Class](#metadatasqshook-class)
5. [Hook Patterns and Best Practices](#hook-patterns-and-best-practices)
6. [Complete Examples](#complete-examples)

---

## Metadata Hooks

Metadata hooks intercept all metadata operations, allowing you to add custom logic before or after metadata changes.

### Hook Signature

```python
def metadata_hook(
    original_func: Callable,
    action: str,
    session_id: str,
    **kwargs
) -> Any
```

#### Parameters

- **original_func** (`Callable`): The original method being intercepted. Call this to execute the standard operation.

- **action** (`str`): The metadata operation being performed:
  - `"update"`: Metadata is being updated
  - `"get"`: Metadata is being retrieved
  - `"delete"`: Metadata fields are being deleted

- **session_id** (`str`): The unique identifier of the session being operated on.

- **kwargs** (`Dict[str, Any]`): Additional arguments specific to the action:
  - For `"update"`: `metadata` (Dict[str, Any]) - the metadata being set
  - For `"delete"`: `keys` (List[str]) - the fields being deleted
  - For `"get"`: (no additional arguments)

#### Return Value

- For `"update"` and `"delete"`: Should return `None` (or the result of `original_func`)
- For `"get"`: Should return `Dict[str, Any]` with the metadata

### Usage

```python
from mongodb_session_manager import MongoDBSessionManager


def my_metadata_hook(original_func, action, session_id, **kwargs):
    # Add your custom logic here
    if action == "update":
        # kwargs contains 'metadata'
        return original_func(kwargs["metadata"])
    elif action == "delete":
        # kwargs contains 'keys'
        return original_func(kwargs["keys"])
    else:  # action == "get"
        return original_func()


# Create session manager with hook
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    metadata_hook=my_metadata_hook,
)
```

### Common Metadata Hook Patterns

#### 1. Audit Logging Hook

Track all metadata operations for compliance and debugging:

```python
import logging

logger = logging.getLogger(__name__)


def audit_metadata_hook(original_func, action, session_id, **kwargs):
    """Log all metadata operations for audit trail"""
    if action == "update":
        metadata = kwargs["metadata"]
        logger.info(
            f"[AUDIT] Metadata UPDATE on session {session_id} - "
            f"Fields: {list(metadata.keys())}"
        )
        result = original_func(metadata)
        logger.info(f"[AUDIT] Update completed for session {session_id}")
        return result

    elif action == "delete":
        keys = kwargs["keys"]
        logger.info(f"[AUDIT] Metadata DELETE on session {session_id} - Keys: {keys}")
        result = original_func(keys)
        logger.info(f"[AUDIT] Delete completed for session {session_id}")
        return result

    else:  # get
        logger.info(f"[AUDIT] Metadata GET on session {session_id}")
        result = original_func()
        field_count = len(result.get("metadata", {}))
        logger.info(
            f"[AUDIT] Retrieved {field_count} metadata fields for session {session_id}"
        )
        return result


# Usage
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    metadata_hook=audit_metadata_hook,
)
```

#### 2. Validation Hook

Enforce data quality rules on metadata:

```python
def validation_metadata_hook(original_func, action, session_id, **kwargs):
    """Validate metadata before storing"""
    if action == "update":
        metadata = kwargs["metadata"]

        # Validate priority field
        if "priority" in metadata:
            allowed_priorities = ["low", "medium", "high", "critical"]
            if metadata["priority"] not in allowed_priorities:
                raise ValueError(
                    f"Invalid priority '{metadata['priority']}'. "
                    f"Must be one of: {allowed_priorities}"
                )

        # Validate email format
        if "email" in metadata:
            if "@" not in metadata["email"]:
                raise ValueError("Invalid email format")

        # Validate numeric fields
        if "score" in metadata:
            try:
                score = float(metadata["score"])
                if not 0 <= score <= 100:
                    raise ValueError("Score must be between 0 and 100")
            except (ValueError, TypeError):
                raise ValueError("Score must be a number")

        return original_func(metadata)

    elif action == "delete":
        keys = kwargs["keys"]
        # Prevent deletion of critical fields
        protected_fields = ["user_id", "created_at"]
        for key in keys:
            if key in protected_fields:
                raise ValueError(f"Cannot delete protected field: {key}")
        return original_func(keys)

    else:  # get
        return original_func()


# Usage
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    metadata_hook=validation_metadata_hook,
)

# This will raise ValueError
# manager.update_metadata({"priority": "super-urgent"})

# This works
manager.update_metadata({"priority": "high"})
```

#### 3. Caching Hook

Cache frequently accessed metadata to reduce database queries:

```python
from typing import Dict, Any
from datetime import datetime, timedelta


class MetadataCache:
    def __init__(self, ttl_seconds: int = 300):
        self.cache: Dict[str, tuple] = {}  # session_id -> (metadata, timestamp)
        self.ttl = timedelta(seconds=ttl_seconds)

    def get(self, session_id: str) -> Dict[str, Any]:
        if session_id in self.cache:
            metadata, timestamp = self.cache[session_id]
            if datetime.now() - timestamp < self.ttl:
                return metadata
        return None

    def set(self, session_id: str, metadata: Dict[str, Any]) -> None:
        self.cache[session_id] = (metadata, datetime.now())

    def invalidate(self, session_id: str) -> None:
        if session_id in self.cache:
            del self.cache[session_id]


# Create cache instance
cache = MetadataCache(ttl_seconds=300)


def caching_metadata_hook(original_func, action, session_id, **kwargs):
    """Cache metadata to reduce database queries"""
    if action == "get":
        # Try cache first
        cached = cache.get(session_id)
        if cached is not None:
            logger.debug(f"Cache HIT for session {session_id}")
            return cached

        # Cache miss - get from database
        logger.debug(f"Cache MISS for session {session_id}")
        result = original_func()
        if result:
            cache.set(session_id, result)
        return result

    elif action == "update":
        # Invalidate cache and update
        cache.invalidate(session_id)
        result = original_func(kwargs["metadata"])
        return result

    else:  # delete
        # Invalidate cache and delete
        cache.invalidate(session_id)
        result = original_func(kwargs["keys"])
        return result


# Usage
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    metadata_hook=caching_metadata_hook,
)

# First call - database query
metadata1 = manager.get_metadata()  # Cache MISS

# Second call within TTL - from cache
metadata2 = manager.get_metadata()  # Cache HIT
```

#### 4. Transformation Hook

Transform metadata before storage:

```python
from datetime import datetime


def transformation_metadata_hook(original_func, action, session_id, **kwargs):
    """Transform metadata before storage"""
    if action == "update":
        metadata = kwargs["metadata"]

        # Add timestamp
        metadata["last_updated"] = datetime.now().isoformat()

        # Normalize email to lowercase
        if "email" in metadata:
            metadata["email"] = metadata["email"].lower()

        # Sanitize string fields
        for key, value in metadata.items():
            if isinstance(value, str):
                metadata[key] = value.strip()

        return original_func(metadata)

    elif action == "delete":
        return original_func(kwargs["keys"])
    else:
        return original_func()


# Usage
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    metadata_hook=transformation_metadata_hook,
)

# Email will be normalized to lowercase
manager.update_metadata({"email": "Alice@Example.COM"})
# Stored as: {"email": "alice@example.com", "last_updated": "2024-01-26T..."}
```

---

## Feedback Hooks

Feedback hooks intercept feedback operations, allowing you to add custom logic when users submit feedback.

### Hook Signature

```python
def feedback_hook(
    original_func: Callable,
    action: str,
    session_id: str,
    **kwargs
) -> None
```

#### Parameters

- **original_func** (`Callable`): The original method being intercepted. Call this to execute the standard operation.

- **action** (`str`): The feedback operation being performed. Currently only `"add"` is supported.

- **session_id** (`str`): The unique identifier of the session.

- **kwargs** (`Dict[str, Any]`): Additional arguments:
  - For `"add"`: `feedback` (Dict[str, Any]) - the feedback being added

#### Return Value

Should return `None` (or the result of `original_func`)

### Usage

```python
from mongodb_session_manager import MongoDBSessionManager


def my_feedback_hook(original_func, action, session_id, **kwargs):
    # Add your custom logic here
    if action == "add":
        feedback = kwargs["feedback"]
        # ... custom logic ...
        return original_func(feedback)


# Create session manager with hook
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    feedback_hook=my_feedback_hook,
)
```

### Common Feedback Hook Patterns

#### 1. Audit Logging Hook

Track all feedback submissions:

```python
import logging

logger = logging.getLogger(__name__)


def audit_feedback_hook(original_func, action, session_id, **kwargs):
    """Log all feedback submissions for audit trail"""
    if action == "add":
        feedback = kwargs["feedback"]
        rating = feedback.get("rating")
        has_comment = bool(feedback.get("comment"))

        logger.info(
            f"[AUDIT] Feedback received for session {session_id} - "
            f"Rating: {rating}, Has comment: {has_comment}"
        )

        result = original_func(feedback)

        logger.info(f"[AUDIT] Feedback stored for session {session_id}")
        return result


# Usage
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    feedback_hook=audit_feedback_hook,
)
```

#### 2. Validation Hook

Validate feedback data:

```python
def validation_feedback_hook(original_func, action, session_id, **kwargs):
    """Validate feedback before storing"""
    if action == "add":
        feedback = kwargs["feedback"]

        # Validate rating
        rating = feedback.get("rating")
        if rating not in ["up", "down", None]:
            raise ValueError(
                f"Invalid rating '{rating}'. Must be 'up', 'down', or None"
            )

        # Validate comment length
        comment = feedback.get("comment", "")
        if len(comment) > 1000:
            raise ValueError("Comment too long (max 1000 characters)")

        # Check for inappropriate content (simple example)
        banned_words = ["spam", "inappropriate"]
        if any(word in comment.lower() for word in banned_words):
            raise ValueError("Comment contains inappropriate content")

        return original_func(feedback)


# Usage
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    feedback_hook=validation_feedback_hook,
)
```

#### 3. Notification Hook

Send notifications for specific feedback:

```python
import requests


def notification_feedback_hook(original_func, action, session_id, **kwargs):
    """Send notifications for negative feedback"""
    if action == "add":
        feedback = kwargs["feedback"]

        # Store feedback first
        result = original_func(feedback)

        # Send notification for negative feedback
        if feedback.get("rating") == "down":
            try:
                # Send to Slack, email, etc.
                message = (
                    f"Negative feedback received!\n"
                    f"Session: {session_id}\n"
                    f"Comment: {feedback.get('comment', 'No comment')}"
                )

                # Example: Slack webhook
                requests.post(
                    "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
                    json={"text": message},
                    timeout=5,
                )
            except Exception as e:
                logger.error(f"Failed to send notification: {e}")

        return result


# Usage
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    feedback_hook=notification_feedback_hook,
)
```

#### 4. Analytics Hook

Track feedback metrics:

```python
from collections import defaultdict
from datetime import datetime


class FeedbackAnalytics:
    def __init__(self):
        self.stats = defaultdict(int)
        self.ratings_by_hour = defaultdict(lambda: {"up": 0, "down": 0, "neutral": 0})

    def track(self, session_id: str, feedback: dict) -> None:
        rating = feedback.get("rating")
        hour = datetime.now().strftime("%Y-%m-%d %H:00")

        # Track overall counts
        self.stats["total"] += 1
        if rating == "up":
            self.stats["positive"] += 1
            self.ratings_by_hour[hour]["up"] += 1
        elif rating == "down":
            self.stats["negative"] += 1
            self.ratings_by_hour[hour]["down"] += 1
        else:
            self.stats["neutral"] += 1
            self.ratings_by_hour[hour]["neutral"] += 1

        if feedback.get("comment"):
            self.stats["with_comment"] += 1

    def get_stats(self) -> dict:
        return dict(self.stats)


# Create analytics instance
analytics = FeedbackAnalytics()


def analytics_feedback_hook(original_func, action, session_id, **kwargs):
    """Track feedback analytics"""
    if action == "add":
        feedback = kwargs["feedback"]

        # Store feedback
        result = original_func(feedback)

        # Track analytics
        analytics.track(session_id, feedback)

        # Log stats periodically
        if analytics.stats["total"] % 100 == 0:
            logger.info(f"Feedback stats: {analytics.get_stats()}")

        return result


# Usage
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    feedback_hook=analytics_feedback_hook,
)

# Later, get analytics
print(analytics.get_stats())
# Output: {'total': 150, 'positive': 120, 'negative': 20, 'neutral': 10, 'with_comment': 45}
```

---

## FeedbackSNSHook Class

AWS SNS integration for real-time feedback notifications.

### Class Definition

```python
class FeedbackSNSHook:
    """Hook to send feedback notifications to SNS with separate topics per rating"""
```

**Module**: `mongodb_session_manager.hooks.feedback_sns_hook`

**Requirements**: `boto3` (installed with the library), AWS credentials and `sns:Publish` on the topics

### Constructor

```python
def __init__(
    self,
    topic_arn_good: str,
    topic_arn_bad: str,
    topic_arn_neutral: str
) -> None
```

#### Parameters

- **topic_arn_good** (`str`): SNS topic ARN for positive feedback (rating="up"). Use `"none"` to disable notifications for positive feedback.

- **topic_arn_bad** (`str`): SNS topic ARN for negative feedback (rating="down"). Use `"none"` to disable notifications for negative feedback.

- **topic_arn_neutral** (`str`): SNS topic ARN for neutral feedback (rating=None). Use `"none"` to disable notifications for neutral feedback.

#### Raises

- `ImportError`: If `boto3` cannot be imported.

### SNS Message Format

**Subject**:
```
Virtual Agents Feedback {positive|negative|neutral} on session {session_id}
```

**Message Body**:
```
Session: {session_id}

{comment}
```

**Message Attributes**:
- `session_id` (String): The session identifier
- `rating` (String): "positive", "negative", or "neutral"

### Methods

#### `on_feedback_add`

```python
async def on_feedback_add(
    self,
    session_id: str,
    feedback: Dict[str, Any]
) -> None
```

Async method called when feedback is added. Sends notification to appropriate SNS topic based on rating.

### Helper Function: `create_feedback_sns_hook`

```python
def create_feedback_sns_hook(
    topic_arn_good: str,
    topic_arn_bad: str,
    topic_arn_neutral: str,
    loop: asyncio.AbstractEventLoop | None = None
)
```

Create a feedback hook function for mongodb-session-manager.

#### Parameters

Same as `FeedbackSNSHook.__init__()`, plus:

- **loop** (`asyncio.AbstractEventLoop`, optional): Event loop the
  notifications run on. Defaults to the loop running when the hook is created.
  See [Async Operations in Hooks](#async-operations-in-hooks).

#### Returns

Hook function compatible with `MongoDBSessionManager(feedback_hook=...)`

#### Example

```python
from mongodb_session_manager import (
    MongoDBSessionManager,
    create_feedback_sns_hook,
    is_feedback_sns_hook_available,
)

# Check availability
if not is_feedback_sns_hook_available():
    print("SNS hook not available: boto3 could not be imported.")
    exit(1)

# Create SNS hook with separate topics
sns_hook = create_feedback_sns_hook(
    topic_arn_good="arn:aws:sns:eu-west-1:123456789:feedback-good",
    topic_arn_bad="arn:aws:sns:eu-west-1:123456789:feedback-bad",
    topic_arn_neutral="arn:aws:sns:eu-west-1:123456789:feedback-neutral",
)

# Create session manager with SNS notifications
manager = MongoDBSessionManager(
    session_id="user-session-123",
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    feedback_hook=sns_hook,
)

# Feedback is automatically sent to SNS
manager.add_feedback(
    {
        "rating": "down",  # Routes to topic_arn_bad
        "comment": "Response was incomplete",
    }
)

manager.add_feedback(
    {
        "rating": "up",  # Routes to topic_arn_good
        "comment": "Great response!",
    }
)

manager.add_feedback(
    {
        "rating": None,  # Routes to topic_arn_neutral
        "comment": "Just testing",
    }
)
```

### Selective Notifications

You can disable notifications for specific rating types by using `"none"`:

```python
# Only send notifications for negative feedback
sns_hook = create_feedback_sns_hook(
    topic_arn_good="none",  # No notifications for positive
    topic_arn_bad="arn:aws:sns:eu-west-1:123456789:feedback-bad",
    topic_arn_neutral="none",  # No notifications for neutral
)
```

### AWS Configuration

Ensure your AWS credentials are configured with permissions to publish to SNS:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "sns:Publish",
            "Resource": [
                "arn:aws:sns:eu-west-1:123456789:feedback-good",
                "arn:aws:sns:eu-west-1:123456789:feedback-bad",
                "arn:aws:sns:eu-west-1:123456789:feedback-neutral"
            ]
        }
    ]
}
```

### Error Handling

- Feedback is always stored in MongoDB first
- Notifications are sent asynchronously to avoid blocking
- An SNS failure raises out of the notification, where the background work
  counts it as `failed` and logs it once with its context and its traceback.
  It cannot reach the caller: by then the feedback is written and the call has
  returned. The notification is dispatched as `Delivery.GUARANTEED`, and a
  guarantee whose counter cannot tell a lost notification from a sent one is
  not verifiable

---

## MetadataSQSHook Class

AWS SQS integration for metadata propagation to enable Server-Sent Events (SSE).

### Class Definition

```python
class MetadataSQSHook:
    """Hook to send metadata changes to SQS for SSE back-propagation"""
```

**Module**: `mongodb_session_manager.hooks.metadata_sqs_hook`

**Requirements**: `boto3` (installed with the library), AWS credentials and `sqs:SendMessage` on the queue

### Constructor

```python
def __init__(
    self,
    queue_url: str,
    metadata_fields: List[str]
) -> None
```

#### Parameters

- **queue_url** (`str`): Full SQS queue URL (e.g., `https://sqs.eu-west-1.amazonaws.com/123456789/metadata-updates`)

- **metadata_fields** (`List[str]`): List of metadata field names to propagate. Only these fields will be sent to SQS. If empty, all fields are sent.

#### Raises

- `ImportError`: If `boto3` cannot be imported.

### SQS Message Format

**Message Body** (JSON):
```json
{
    "session_id": "user-session-123",
    "event": "metadata_update",
    "operation": "update",
    "metadata": {
        "status": "processing",
        "agent_state": "thinking"
    },
    "timestamp": "2024-01-26T10:30:45.123456"
}
```

**Message Attributes**:
- `session_id` (String): The session identifier
- `event` (String): Always "metadata_update"

### Methods

#### `on_metadata_change`

```python
async def on_metadata_change(
    self,
    session_id: str,
    metadata: Dict[str, Any],
    operation: str
) -> None
```

Async method called when metadata changes. Sends change notification to SQS queue.

### Helper Function: `create_metadata_sqs_hook`

```python
def create_metadata_sqs_hook(
    queue_url: str,
    metadata_fields: List[str] = None,
    loop: asyncio.AbstractEventLoop | None = None
)
```

Create a metadata hook function for mongodb-session-manager.

#### Parameters

- **queue_url** (`str`): Full SQS queue URL

- **metadata_fields** (`List[str]`, optional): List of fields to propagate. If `None`, all fields are sent.

- **loop** (`asyncio.AbstractEventLoop`, optional): Event loop the
  notifications run on. Defaults to the loop running when the hook is created.
  See [Async Operations in Hooks](#async-operations-in-hooks).

#### Returns

Hook function compatible with `MongoDBSessionManager(metadata_hook=...)`

#### Example

```python
from mongodb_session_manager import (
    MongoDBSessionManager,
    create_metadata_sqs_hook,
    is_metadata_sqs_hook_available,
)

# Check availability
if not is_metadata_sqs_hook_available():
    print("SQS hook not available: boto3 could not be imported.")
    exit(1)

# Create SQS hook with selective field propagation
sqs_hook = create_metadata_sqs_hook(
    queue_url="https://sqs.eu-west-1.amazonaws.com/123456789/metadata-updates",
    metadata_fields=["status", "agent_state", "priority"],
)

# Create session manager with SQS propagation
manager = MongoDBSessionManager(
    session_id="user-session-123",
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    metadata_hook=sqs_hook,
)

# Metadata changes are automatically sent to SQS
manager.update_metadata(
    {
        "status": "processing",  # Sent to SQS
        "agent_state": "thinking",  # Sent to SQS
        "internal_field": "value",  # NOT sent to SQS (not in metadata_fields)
    }
)

# Delete operations also propagated
manager.delete_metadata(["old_field"])
# SQS receives: {"old_field": null}
```

### Use Cases

1. **Real-time Dashboards**: Update monitoring dashboards when session state changes
2. **Multi-client Synchronization**: Keep multiple connected clients in sync via SSE
3. **Workflow Orchestration**: Trigger workflows based on metadata changes
4. **Audit Logging**: Stream metadata changes to audit systems
5. **Event-driven Architecture**: Enable reactive systems based on session state

### AWS Configuration

Ensure your AWS credentials are configured with SQS send permissions:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "sqs:SendMessage",
            "Resource": "arn:aws:sqs:eu-west-1:123456789:metadata-updates"
        }
    ]
}
```

### Error Handling

- Metadata operations always complete in MongoDB first
- Messages are sent asynchronously to avoid blocking
- An SQS failure raises out of the notification, where the background work
  counts it as `failed` and logs it once with its context and its traceback.
  It cannot reach the caller: by then the metadata is written and the call has
  returned

The WebSocket hook is the same, with one exception: a `GoneException` from API
Gateway means the client disconnected, which is how a WebSocket session ends.
It is logged at `INFO` and counted as a normal outcome, not a failure.

---

## Hook Patterns and Best Practices

### Combining Multiple Hooks

You can combine multiple hook behaviors using composition:

```python
def create_combined_metadata_hook():
    """Combine audit logging, validation, and caching"""
    cache = MetadataCache()

    def combined_hook(original_func, action, session_id, **kwargs):
        # 1. Audit logging
        logger.info(f"[AUDIT] {action} on {session_id}")

        # 2. Validation (for update)
        if action == "update":
            metadata = kwargs["metadata"]
            if "priority" in metadata:
                if metadata["priority"] not in ["low", "medium", "high"]:
                    raise ValueError("Invalid priority")

        # 3. Cache invalidation
        if action in ["update", "delete"]:
            cache.invalidate(session_id)

        # 4. Execute operation
        if action == "update":
            result = original_func(kwargs["metadata"])
        elif action == "delete":
            result = original_func(kwargs["keys"])
        else:  # get
            # Check cache first
            cached = cache.get(session_id)
            if cached:
                return cached
            result = original_func()
            cache.set(session_id, result)

        return result

    return combined_hook


# Usage
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    metadata_hook=create_combined_metadata_hook(),
)
```

### Async Operations in Hooks

For operations that shouldn't block (like sending notifications), use
`dispatch_async()`. It hands the coroutine to an event loop and returns
immediately, so the metadata or feedback write is never delayed by the
notification:

```python
import asyncio

from mongodb_session_manager.hooks.utils_async import capture_loop, dispatch_async


def create_notification_hook(loop: asyncio.AbstractEventLoop | None = None):
    """Send notifications without blocking the write."""
    # Remember the loop running now, if any: the hook may later be called from
    # a worker thread, and then there is no loop to find.
    dispatch_loop = loop if loop is not None else capture_loop()

    def notification_hook(original_func, action, session_id, **kwargs):
        if action != "add" or "feedback" not in kwargs:
            return original_func()

        feedback = kwargs["feedback"]
        result = original_func(feedback)  # store first

        if feedback.get("rating") == "down":
            dispatch_async(
                send_slack_message(session_id, feedback),
                "sending feedback notification to Slack",
                loop=dispatch_loop,
            )

        return result

    return notification_hook
```

#### Which thread the notification runs on

`dispatch_async(coro, error_context, loop=None)` resolves the target in this
order:

| `loop` | Where the coroutine runs |
|--------|--------------------------|
| Given (and reachable) | On that loop, via `asyncio.run_coroutine_threadsafe()`. Returns a `concurrent.futures.Future` |
| Not given, a loop runs in the calling thread | A task on that loop. Returns the `Task` |
| Not given, no loop anywhere | The library's **reserve loop**: one event loop, shared by the whole process, in a daemon thread started on first use. Returns a `Future` |

Passing the loop is what makes the dispatch independent of the calling thread.
Without it, the same hook behaves differently depending on where the write
happens — though never, since v0.18.0, by starting a thread per event.

That is not an exotic case. Two ordinary paths land there:

- **The agent's own metadata writes.** `get_metadata_tool()` returns a
  *synchronous* tool, and Strands runs synchronous tools with
  `asyncio.to_thread` (`strands/tools/decorator.py`). Every `update_metadata`
  the agent performs therefore reaches the hook from a worker thread, even in
  an entirely `async def` server.
- **The synchronous turn moved off the loop** with `run_in_threadpool`, the
  pattern in [FastAPI Integration](../examples/fastapi-integration.md).

Writes your own `async def` code makes directly still run on the loop and take
the task path.

The three bundled hooks — `create_feedback_sns_hook`,
`create_metadata_sqs_hook` and `create_metadata_websocket_hook` — take the same
`loop` argument and default to the loop running when they are created. Build
them inside your async lifespan and they keep notifying on the server loop:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inside a running loop: the hook captures it.
    app.state.metadata_hook = create_metadata_websocket_hook(
        api_gateway_endpoint="https://abc123.execute-api.eu-west-1.amazonaws.com/prod",
        metadata_fields=["status", "progress"],
    )
    yield
```

Built at import time instead, there is no loop to capture and each call decides
on its own; pass `loop=asyncio.get_running_loop()` from the lifespan, or hold
off building the hook until then.

#### Failures are logged, not swallowed

The dispatch keeps a strong reference to the work — an event loop only holds
weak ones, so an unreferenced task can be garbage collected mid-flight — and
logs how it ends. A coroutine that raises is reported as
`Error <error_context>: <exception>` with its traceback, and a cancelled one as
`Cancelled while <error_context>`. Give `error_context` a phrase that reads in
that sentence, and put the session in it ("sending feedback notification to
Slack for session abc-123"): it is the only log line the failure gets, so
whatever is not in it is not anywhere.

That is also why the three bundled hooks raise their AWS error instead of
catching it. Catching it produced two lines — an `ERROR` from the hook and a
`DEBUG` `Finished:` from the dispatch — and a counter that called the lost
notification a delivered one.

The returned handle is there for callers that want the result — the
`Future` of a dispatch to a known loop resolves with the coroutine's return
value — but ignoring it does not lose the failure.

#### How much may run at once, and in what order

The notifications of every hook in the process share one bounded pool of
background work (`hooks/background_work.py`). Three rules apply to it, and the
bundled hooks each opt into the ones their domain needs:

**A limit on work in flight.** 64 notifications at once, by default. Past it,
best-effort work is refused rather than queued without end: the coroutine is
closed, a `WARNING` names what was dropped, and the `dropped` counter records
it. Nothing is ever queued silently.

**Order per key.** Work dispatched with `order_key` never runs concurrently
with other work for that same key, and never overtakes it. The metadata hooks
pass the `session_id`, so two updates of the same session cannot arrive
swapped — which matters when the receiving client just applies whatever
arrives last. Per key there is at most one notification in flight; the rest
**queue in the order they were submitted** (8 deep by default), because a
metadata notification carries the dict the caller passed — a partial update,
not the whole state. Dropping `{"progress": 50}` because `{"status": "done"}`
came after it would lose `progress` for good. Only when the queue is full does
the oldest give way, with a `WARNING`. Different keys still run in parallel.

**Delivery.** `Delivery.GUARANTEED` opts out of the limit: the work is accepted
over it, with a `WARNING`, instead of being dropped. The feedback hook uses it,
because a feedback notification carries something nothing produces again.

```python
from mongodb_session_manager.hooks import Delivery, dispatch_async

dispatch_async(
    send_progress(session_id, metadata),
    "sending progress to Slack",
    loop=dispatch_loop,
    order_key=session_id,  # never overtaken by a later update
)

dispatch_async(
    escalate(session_id, feedback),
    "escalating the feedback",
    loop=dispatch_loop,
    delivery=Delivery.GUARANTEED,  # never dropped to respect the limit
)
```

#### Closing the process without losing notifications

Close the background work where your process shuts down. It waits for the
notifications in flight, cancels whatever does not make it in time, stops the
reserve loop, and returns the counters. Work dispatched afterwards is refused,
loudly.

There are two calls, and which one you want depends on where you are. From
inside an event loop — a FastAPI lifespan, an async signal handler — use
**`shutdown_hooks_async()`**: the notifications are riding that very loop, and
blocking it is what would stop them from finishing.

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from mongodb_session_manager import close_global_factory, shutdown_hooks_async


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    stats = await shutdown_hooks_async(timeout=5.0)
    logger.info("hook notifications drained", extra=stats.as_dict())
    close_global_factory()
```

From a thread with no loop of its own — a plain `main()`, a synchronous signal
handler — `shutdown_hooks()` is the same close, blocking. It warns if you call
it from inside the loop it is draining, rather than silently spending the whole
budget and cancelling work it could have delivered.

A process that never makes that call still drains on the way out: the library
registers the close with `threading._register_atexit()`, which runs *before*
Python shuts its thread pools down — `atexit` runs after, too late for hooks
that make their AWS call on one of those pools. Measured, with 20 notifications
in flight: 20 delivered either way, against 0 before v0.18.0.

What no hook can survive is a signal. `SIGTERM` without a handler runs no
Python at all — not `atexit`, not the thread shutdown — so a service whose
orchestrator stops it that way (ECS does) still needs the call in a handler:

```python
import signal

from mongodb_session_manager import shutdown_hooks


def _drain(signum, frame):
    shutdown_hooks(timeout=5.0)
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _drain)
```

#### Watching the background work

`hooks_background_stats()` returns the counters as a frozen dataclass, with an
`as_dict()` for logs and metrics:

```python
from mongodb_session_manager import hooks_background_stats

stats = hooks_background_stats()
# BackgroundWorkStats(dispatched=412, completed=409, failed=1, cancelled=0,
#                     dropped=2, in_flight=0, queued=0)
```

`dropped` growing means the limit is being reached — either a burst or
notifications slower than the events producing them. `in_flight` staying high
means the same thing before it starts costing anything.

`completed` counts coroutines that returned and `failed` those that raised. For
the three bundled hooks the two say what they look like they say: since v0.20.0
they let their boto3 error out, so a notification SNS, SQS or API Gateway
refused is a `failed` and an `ERROR` in the log, not a `completed`. The one
exception is the WebSocket `GoneException` — a client that disconnected is a
normal outcome, and it counts as completed.

What `completed` still cannot promise is a hook **of your own**: a notification
that catches its own error and returns anyway is indistinguishable, from here,
from one that worked. If you want its failures in this counter, let them raise
— nobody is waiting on that coroutine, and the dispatch will log it with its
context. `dispatched`, `dropped`, `cancelled`, `in_flight` and `queued` are the
background work's own bookkeeping and mean exactly what they say.

#### Forking after the first notification

A child of `os.fork()` inherits this whole machinery but only the thread that
forked, so the reserve loop it inherits is an object with no thread behind it.
The library resets itself in the child (`os.register_at_fork`): new loop, new
locks, counters from zero, and the parent's work in flight left to the parent.
Nothing to do from a prefork server (gunicorn `--preload`) beyond closing in
each worker.

#### How long a notification may talk to AWS

The three bundled hooks build their boto3 clients with a bounded config: 3 s to
connect, 5 s to read, 2 attempts in the `standard` retry mode. botocore's
defaults (60 s, 60 s, legacy mode) suit a request somebody is waiting for; a
notification nobody waits for would hold a thread for minutes, and the thread is
what the limit above protects. The worst case stays under the 30 s an
orchestrator like ECS gives a task to shut down.

### Error Handling in Hooks

A hook has two halves, and they want opposite things.

The **wrapper** runs in the caller's path, around the write itself: an error it
lets through fails `update_metadata()` or `add_feedback()`. Handle it there, and
re-raise only what should stop the write.

The **notification**, if you dispatch one with `dispatch_async()`, runs after
the write has returned. Nobody is waiting on it, so catching its error buys
nothing and costs the counter: `BackgroundWork` can only see that the coroutine
returned, and records a lost notification as `completed`. Let it raise — the
dispatch logs it with its context and its traceback, and counts it as `failed`.
That is what the three bundled hooks do.

Handling errors in the wrapper, then, so as not to break the main operation:

```python
def safe_hook(original_func, action, session_id, **kwargs):
    """Hook with comprehensive error handling"""
    try:
        # Pre-operation logic
        if action == "update":
            logger.debug(f"Pre-update: {session_id}")

        # Execute operation
        if action == "update":
            result = original_func(kwargs["metadata"])
        elif action == "delete":
            result = original_func(kwargs["keys"])
        else:
            result = original_func()

        # Post-operation logic
        try:
            send_external_notification()
        except Exception as e:
            # Log but don't fail the main operation
            logger.error(f"Notification failed: {e}")

        return result

    except Exception as e:
        # Log error
        logger.error(f"Hook error in {action} for {session_id}: {e}")
        # Re-raise to prevent data corruption
        raise
```

### Hook Testing

```python
import pytest
from unittest.mock import Mock


def test_validation_hook():
    """Test metadata validation hook"""
    # Create mock original function
    original_func = Mock()

    # Test valid priority
    validation_metadata_hook(
        original_func, "update", "session-123", metadata={"priority": "high"}
    )
    original_func.assert_called_once()

    # Test invalid priority
    with pytest.raises(ValueError):
        validation_metadata_hook(
            original_func, "update", "session-123", metadata={"priority": "invalid"}
        )
```

---

## Complete Examples

### Example 1: Production-Ready Metadata Hook

```python
import logging
from typing import Dict, Any, Callable
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class ProductionMetadataHook:
    """Production-ready metadata hook with caching, validation, and audit"""

    def __init__(self, cache_ttl: int = 300):
        self.cache = {}
        self.cache_ttl = timedelta(seconds=cache_ttl)
        self.allowed_priorities = ["low", "medium", "high", "critical"]

    def validate(self, metadata: Dict[str, Any]) -> None:
        """Validate metadata fields"""
        if "priority" in metadata:
            if metadata["priority"] not in self.allowed_priorities:
                raise ValueError(
                    f"Invalid priority. Allowed: {self.allowed_priorities}"
                )

        if "email" in metadata:
            if "@" not in metadata["email"]:
                raise ValueError("Invalid email format")

    def get_cached(self, session_id: str) -> Dict[str, Any]:
        """Get metadata from cache if valid"""
        if session_id in self.cache:
            metadata, timestamp = self.cache[session_id]
            if datetime.now() - timestamp < self.cache_ttl:
                return metadata
        return None

    def set_cache(self, session_id: str, metadata: Dict[str, Any]) -> None:
        """Store metadata in cache"""
        self.cache[session_id] = (metadata, datetime.now())

    def invalidate_cache(self, session_id: str) -> None:
        """Remove metadata from cache"""
        if session_id in self.cache:
            del self.cache[session_id]

    def __call__(self, original_func: Callable, action: str, session_id: str, **kwargs):
        """Hook implementation"""
        try:
            # Audit log
            logger.info(f"[METADATA] {action.upper()} session={session_id}")

            if action == "update":
                metadata = kwargs["metadata"]

                # Validate
                self.validate(metadata)

                # Add timestamp
                metadata["last_updated"] = datetime.now().isoformat()

                # Invalidate cache
                self.invalidate_cache(session_id)

                # Execute
                result = original_func(metadata)

                logger.info(f"[METADATA] Updated fields: {list(metadata.keys())}")
                return result

            elif action == "delete":
                keys = kwargs["keys"]

                # Invalidate cache
                self.invalidate_cache(session_id)

                # Execute
                result = original_func(keys)

                logger.info(f"[METADATA] Deleted fields: {keys}")
                return result

            else:  # get
                # Check cache
                cached = self.get_cached(session_id)
                if cached:
                    logger.debug(f"[METADATA] Cache HIT for {session_id}")
                    return cached

                # Execute
                result = original_func()

                # Cache result
                if result:
                    self.set_cache(session_id, result)
                    logger.debug(f"[METADATA] Cache MISS for {session_id}")

                return result

        except Exception as e:
            logger.error(
                f"[METADATA] Error in {action} for {session_id}: {e}", exc_info=True
            )
            raise


# Usage
metadata_hook = ProductionMetadataHook(cache_ttl=300)

manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    metadata_hook=metadata_hook,
)
```

### Example 2: Multi-Channel Feedback Notifications

```python
import asyncio
from typing import Dict, Any
import requests


class MultiChannelFeedbackHook:
    """Send feedback to multiple notification channels"""

    def __init__(
        self, slack_webhook: str = None, email_api: str = None, sms_api: str = None
    ):
        self.slack_webhook = slack_webhook
        self.email_api = email_api
        self.sms_api = sms_api

    async def send_slack(self, session_id: str, feedback: Dict[str, Any]):
        """Send notification to Slack"""
        if not self.slack_webhook:
            return

        message = {
            "text": (
                f"Feedback received!\n"
                f"Session: {session_id}\n"
                f"Rating: {feedback.get('rating')}\n"
                f"Comment: {feedback.get('comment', 'No comment')}"
            )
        }

        try:
            await asyncio.to_thread(
                requests.post, self.slack_webhook, json=message, timeout=5
            )
        except Exception as e:
            logger.error(f"Slack notification failed: {e}")

    async def send_email(self, session_id: str, feedback: Dict[str, Any]):
        """Send email notification"""
        if not self.email_api:
            return

        # Implement email sending
        pass

    def __call__(self, original_func, action: str, session_id: str, **kwargs):
        """Hook implementation"""
        if action == "add":
            feedback = kwargs["feedback"]

            # Store feedback first
            result = original_func(feedback)

            # Send notifications asynchronously for negative feedback
            if feedback.get("rating") == "down":

                async def send_notifications():
                    await asyncio.gather(
                        self.send_slack(session_id, feedback),
                        self.send_email(session_id, feedback),
                        return_exceptions=True,
                    )

                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(send_notifications())
                except RuntimeError:
                    # No running loop
                    import threading

                    def run():
                        asyncio.run(send_notifications())

                    thread = threading.Thread(target=run, daemon=True)
                    thread.start()

            return result


# Usage
feedback_hook = MultiChannelFeedbackHook(
    slack_webhook="https://hooks.slack.com/services/YOUR/WEBHOOK",
    email_api="https://api.example.com/send-email",
)

manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    feedback_hook=feedback_hook,
)
```

---

## Availability Check Functions

### `is_feedback_sns_hook_available`

```python
def is_feedback_sns_hook_available() -> bool
```

Check if the feedback SNS hook is available. It needs only `boto3`, a runtime dependency, so it is `True` wherever the library is installed.

#### Returns

`bool`: `True` if SNS hook is available, `False` otherwise.

#### Example

```python
from mongodb_session_manager import is_feedback_sns_hook_available

if is_feedback_sns_hook_available():
    from mongodb_session_manager import create_feedback_sns_hook
    # Use SNS hook
else:
    print("SNS hook not available: boto3 could not be imported.")
```

### `is_metadata_sqs_hook_available`

```python
def is_metadata_sqs_hook_available() -> bool
```

Check if the metadata SQS hook is available. It needs only `boto3`, a runtime dependency, so it is `True` wherever the library is installed.

#### Returns

`bool`: `True` if SQS hook is available, `False` otherwise.

#### Example

```python
from mongodb_session_manager import is_metadata_sqs_hook_available

if is_metadata_sqs_hook_available():
    from mongodb_session_manager import create_metadata_sqs_hook
    # Use SQS hook
else:
    print("SQS hook not available: boto3 could not be imported.")
```

---

## See Also

- [MongoDBSessionManager](./mongodb-session-manager.md) - Main session manager class
- [User Guide - Metadata Management](../user-guide/metadata-management.md)
- [User Guide - Feedback System](../user-guide/feedback-system.md)
- [User Guide - AWS Integrations](../user-guide/aws-integrations.md)
