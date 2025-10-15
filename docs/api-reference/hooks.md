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
    metadataHook=my_metadata_hook
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
        logger.info(
            f"[AUDIT] Metadata DELETE on session {session_id} - "
            f"Keys: {keys}"
        )
        result = original_func(keys)
        logger.info(f"[AUDIT] Delete completed for session {session_id}")
        return result

    else:  # get
        logger.info(f"[AUDIT] Metadata GET on session {session_id}")
        result = original_func()
        field_count = len(result.get("metadata", {}))
        logger.info(
            f"[AUDIT] Retrieved {field_count} metadata fields "
            f"for session {session_id}"
        )
        return result

# Usage
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    metadataHook=audit_metadata_hook
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
    metadataHook=validation_metadata_hook
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
    metadataHook=caching_metadata_hook
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
    metadataHook=transformation_metadata_hook
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
    feedbackHook=my_feedback_hook
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
    feedbackHook=audit_feedback_hook
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
    feedbackHook=validation_feedback_hook
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
                    timeout=5
                )
            except Exception as e:
                logger.error(f"Failed to send notification: {e}")

        return result

# Usage
manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://...",
    feedbackHook=notification_feedback_hook
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
    feedbackHook=analytics_feedback_hook
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

**Requirements**: `custom_aws.sns` module (from python-helpers package)

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

- `ImportError`: If `custom_aws.sns` module is not available.

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
    topic_arn_neutral: str
)
```

Create a feedback hook function for mongodb-session-manager.

#### Parameters

Same as `FeedbackSNSHook.__init__()`.

#### Returns

Hook function compatible with `MongoDBSessionManager(feedbackHook=...)`

#### Example

```python
from mongodb_session_manager import (
    MongoDBSessionManager,
    create_feedback_sns_hook,
    is_feedback_sns_hook_available
)

# Check availability
if not is_feedback_sns_hook_available():
    print("SNS hook not available. Install python-helpers package.")
    exit(1)

# Create SNS hook with separate topics
sns_hook = create_feedback_sns_hook(
    topic_arn_good="arn:aws:sns:eu-west-1:123456789:feedback-good",
    topic_arn_bad="arn:aws:sns:eu-west-1:123456789:feedback-bad",
    topic_arn_neutral="arn:aws:sns:eu-west-1:123456789:feedback-neutral"
)

# Create session manager with SNS notifications
manager = MongoDBSessionManager(
    session_id="user-session-123",
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    feedbackHook=sns_hook
)

# Feedback is automatically sent to SNS
manager.add_feedback({
    "rating": "down",  # Routes to topic_arn_bad
    "comment": "Response was incomplete"
})

manager.add_feedback({
    "rating": "up",  # Routes to topic_arn_good
    "comment": "Great response!"
})

manager.add_feedback({
    "rating": None,  # Routes to topic_arn_neutral
    "comment": "Just testing"
})
```

### Selective Notifications

You can disable notifications for specific rating types by using `"none"`:

```python
# Only send notifications for negative feedback
sns_hook = create_feedback_sns_hook(
    topic_arn_good="none",  # No notifications for positive
    topic_arn_bad="arn:aws:sns:eu-west-1:123456789:feedback-bad",
    topic_arn_neutral="none"  # No notifications for neutral
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
- SNS notification failures are logged but don't raise exceptions
- Notifications are sent asynchronously to avoid blocking

---

## MetadataSQSHook Class

AWS SQS integration for metadata propagation to enable Server-Sent Events (SSE).

### Class Definition

```python
class MetadataSQSHook:
    """Hook to send metadata changes to SQS for SSE back-propagation"""
```

**Module**: `mongodb_session_manager.hooks.metadata_sqs_hook`

**Requirements**: `custom_aws.sqs` module (from python-helpers package)

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

- `ImportError`: If `custom_aws.sqs` module is not available.

### SQS Message Format

**Message Body** (JSON):
```json
{
    "session_id": "user-session-123",
    "event_type": "metadata_update",
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
- `event_type` (String): Always "metadata_update"

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
    metadata_fields: List[str] = None
)
```

Create a metadata hook function for mongodb-session-manager.

#### Parameters

- **queue_url** (`str`): Full SQS queue URL

- **metadata_fields** (`List[str]`, optional): List of fields to propagate. If `None`, all fields are sent.

#### Returns

Hook function compatible with `MongoDBSessionManager(metadataHook=...)`

#### Example

```python
from mongodb_session_manager import (
    MongoDBSessionManager,
    create_metadata_sqs_hook,
    is_metadata_sqs_hook_available
)

# Check availability
if not is_metadata_sqs_hook_available():
    print("SQS hook not available. Install python-helpers package.")
    exit(1)

# Create SQS hook with selective field propagation
sqs_hook = create_metadata_sqs_hook(
    queue_url="https://sqs.eu-west-1.amazonaws.com/123456789/metadata-updates",
    metadata_fields=["status", "agent_state", "priority"]
)

# Create session manager with SQS propagation
manager = MongoDBSessionManager(
    session_id="user-session-123",
    connection_string="mongodb://localhost:27017/",
    database_name="chat_db",
    metadataHook=sqs_hook
)

# Metadata changes are automatically sent to SQS
manager.update_metadata({
    "status": "processing",  # Sent to SQS
    "agent_state": "thinking",  # Sent to SQS
    "internal_field": "value"  # NOT sent to SQS (not in metadata_fields)
})

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
- SQS send failures are logged but don't raise exceptions
- Messages are sent asynchronously to avoid blocking

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
    metadataHook=create_combined_metadata_hook()
)
```

### Async Operations in Hooks

For operations that shouldn't block (like sending notifications), use async:

```python
import asyncio
import threading

def async_notification_hook(original_func, action, session_id, **kwargs):
    """Send notifications asynchronously"""
    if action == "add":
        feedback = kwargs["feedback"]

        # Store feedback first
        result = original_func(feedback)

        # Send notification asynchronously
        if feedback.get("rating") == "down":
            async def send_notification():
                await send_slack_message(session_id, feedback)

            # Run in background
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(send_notification())
            except RuntimeError:
                # No running loop, use thread
                def run_async():
                    asyncio.run(send_notification())
                thread = threading.Thread(target=run_async, daemon=True)
                thread.start()

        return result

    return original_func()
```

### Error Handling in Hooks

Always handle errors gracefully to avoid breaking the main operation:

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
        original_func,
        "update",
        "session-123",
        metadata={"priority": "high"}
    )
    original_func.assert_called_once()

    # Test invalid priority
    with pytest.raises(ValueError):
        validation_metadata_hook(
            original_func,
            "update",
            "session-123",
            metadata={"priority": "invalid"}
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

    def __call__(
        self,
        original_func: Callable,
        action: str,
        session_id: str,
        **kwargs
    ):
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

                logger.info(
                    f"[METADATA] Updated fields: {list(metadata.keys())}"
                )
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
                f"[METADATA] Error in {action} for {session_id}: {e}",
                exc_info=True
            )
            raise

# Usage
metadata_hook = ProductionMetadataHook(cache_ttl=300)

manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    metadataHook=metadata_hook
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
        self,
        slack_webhook: str = None,
        email_api: str = None,
        sms_api: str = None
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
                requests.post,
                self.slack_webhook,
                json=message,
                timeout=5
            )
        except Exception as e:
            logger.error(f"Slack notification failed: {e}")

    async def send_email(self, session_id: str, feedback: Dict[str, Any]):
        """Send email notification"""
        if not self.email_api:
            return

        # Implement email sending
        pass

    def __call__(
        self,
        original_func,
        action: str,
        session_id: str,
        **kwargs
    ):
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
                        return_exceptions=True
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
    email_api="https://api.example.com/send-email"
)

manager = MongoDBSessionManager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    feedbackHook=feedback_hook
)
```

---

## Availability Check Functions

### `is_feedback_sns_hook_available`

```python
def is_feedback_sns_hook_available() -> bool
```

Check if the feedback SNS hook is available (requires `custom_aws.sns` module).

#### Returns

`bool`: `True` if SNS hook is available, `False` otherwise.

#### Example

```python
from mongodb_session_manager import is_feedback_sns_hook_available

if is_feedback_sns_hook_available():
    from mongodb_session_manager import create_feedback_sns_hook
    # Use SNS hook
else:
    print("SNS hook not available. Install python-helpers package.")
```

### `is_metadata_sqs_hook_available`

```python
def is_metadata_sqs_hook_available() -> bool
```

Check if the metadata SQS hook is available (requires `custom_aws.sqs` module).

#### Returns

`bool`: `True` if SQS hook is available, `False` otherwise.

#### Example

```python
from mongodb_session_manager import is_metadata_sqs_hook_available

if is_metadata_sqs_hook_available():
    from mongodb_session_manager import create_metadata_sqs_hook
    # Use SQS hook
else:
    print("SQS hook not available. Install python-helpers package.")
```

---

## See Also

- [MongoDBSessionManager](./mongodb-session-manager.md) - Main session manager class
- [User Guide - Metadata Management](../user-guide/metadata-management.md)
- [User Guide - Feedback System](../user-guide/feedback-system.md)
- [User Guide - AWS Integration](../user-guide/aws-integration.md)
