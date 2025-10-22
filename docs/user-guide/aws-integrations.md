# AWS Integrations User Guide

## Overview

The MongoDB Session Manager provides optional AWS service integrations for real-time notifications and event propagation. This guide covers SNS feedback notifications and SQS metadata propagation.

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [FeedbackSNSHook](#feedbacksnshook)
4. [MetadataSQSHook](#metadatasqshook)
5. [Configuration](#configuration)
6. [Message Formats](#message-formats)
7. [Best Practices](#best-practices)

## Prerequisites

### Required Package

AWS integrations require the `python-helpers` package:

```bash
pip install python-helpers
```

### Check Availability

```python
from mongodb_session_manager import (
    is_feedback_sns_hook_available,
    is_metadata_sqs_hook_available
)

# Check if SNS hook is available
if is_feedback_sns_hook_available():
    print("SNS feedback hook available")
else:
    print("Install python-helpers: pip install python-helpers")

# Check if SQS hook is available
if is_metadata_sqs_hook_available():
    print("SQS metadata hook available")
else:
    print("Install python-helpers: pip install python-helpers")
```

### AWS Credentials

Configure AWS credentials via:
- Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)
- AWS credentials file (`~/.aws/credentials`)
- IAM role (for EC2/ECS/Lambda)

### IAM Permissions

**For SNS**:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "sns:Publish",
            "Resource": "arn:aws:sns:region:account:topic-name"
        }
    ]
}
```

**For SQS**:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "sqs:SendMessage",
            "Resource": "arn:aws:sqs:region:account:queue-name"
        }
    ]
}
```

## FeedbackSNSHook

Send real-time SNS notifications when users submit feedback, with routing based on feedback rating.

### Features

- **Topic Routing**: Different SNS topics for positive, negative, and neutral feedback
- **Non-blocking**: Async notifications don't slow down feedback storage
- **Graceful Degradation**: Feedback is stored even if SNS fails
- **Rich Attributes**: Message attributes for filtering and routing
- **Selective Notifications**: Disable notifications for specific feedback types

### Basic Usage

```python
from mongodb_session_manager import (
    MongoDBSessionManager,
    create_feedback_sns_hook,
    is_feedback_sns_hook_available
)

# Check availability
if not is_feedback_sns_hook_available():
    raise ImportError("Install python-helpers: pip install python-helpers")

# Create SNS hook with three topics
feedback_hook = create_feedback_sns_hook(
    topic_arn_good="arn:aws:sns:eu-west-1:123456789:feedback-good",
    topic_arn_bad="arn:aws:sns:eu-west-1:123456789:feedback-bad",
    topic_arn_neutral="arn:aws:sns:eu-west-1:123456789:feedback-neutral"
)

# Create session manager with SNS notifications
session_manager = MongoDBSessionManager(
    session_id="user-session-123",
    connection_string="mongodb://localhost:27017/",
    database_name="my_db",
    feedbackHook=feedback_hook
)

# Negative feedback routes to topic_arn_bad
session_manager.add_feedback({
    "rating": "down",
    "comment": "The response was incomplete"
})

# Positive feedback routes to topic_arn_good
session_manager.add_feedback({
    "rating": "up",
    "comment": "Great response!"
})

# Neutral feedback routes to topic_arn_neutral
session_manager.add_feedback({
    "rating": None,
    "comment": "Just saving for later"
})
```

### Selective Notifications

Disable notifications for specific feedback types using `"none"`:

```python
# Only notify on negative feedback
feedback_hook = create_feedback_sns_hook(
    topic_arn_good="none",      # No notifications for positive
    topic_arn_bad="arn:aws:sns:eu-west-1:123456789:feedback-bad",  # Notify on negative
    topic_arn_neutral="none"    # No notifications for neutral
)

session_manager = MongoDBSessionManager(
    session_id="user-session",
    connection_string="mongodb://localhost:27017/",
    database_name="my_db",
    feedbackHook=feedback_hook
)

# This triggers SNS notification
session_manager.add_feedback({
    "rating": "down",
    "comment": "Issue with the code"
})

# This does NOT trigger notification
session_manager.add_feedback({
    "rating": "up",
    "comment": "Great!"
})
```

### SNS Message Format

**Subject:**
```
Virtual Agents Feedback {positive|negative|neutral} on session {session_id}
```

**Message Body:**
```
Session: user-session-123

The response was incomplete and unclear
```

**Message Attributes:**
```python
{
    "session_id": {
        "DataType": "String",
        "StringValue": "user-session-123"
    },
    "rating": {
        "DataType": "String",
        "StringValue": "negative"  # positive, negative, or neutral
    }
}
```

### Production Example

```python
from mongodb_session_manager import create_feedback_sns_hook, MongoDBSessionManager
import os

# Use environment variables for topic ARNs
feedback_hook = create_feedback_sns_hook(
    topic_arn_good=os.getenv("SNS_TOPIC_FEEDBACK_GOOD"),
    topic_arn_bad=os.getenv("SNS_TOPIC_FEEDBACK_BAD"),
    topic_arn_neutral="none"  # Don't notify on neutral
)

session_manager = MongoDBSessionManager(
    session_id="customer-support-001",
    connection_string=os.getenv("MONGODB_URI"),
    database_name="production_db",
    feedbackHook=feedback_hook
)
```

## MetadataSQSHook

Propagate metadata changes to SQS for Server-Sent Events (SSE) or real-time synchronization.

### Features

- **Real-time Sync**: Metadata changes sent to SQS immediately
- **Selective Fields**: Only propagate specified metadata fields
- **Event Distribution**: Queue-based architecture for multiple consumers
- **Non-blocking**: Async operation doesn't slow down metadata updates
- **SSE Support**: Perfect for real-time UI updates

### Basic Usage

```python
from mongodb_session_manager import (
    MongoDBSessionManager,
    create_metadata_sqs_hook,
    is_metadata_sqs_hook_available
)

# Check availability
if not is_metadata_sqs_hook_available():
    raise ImportError("Install python-helpers: pip install python-helpers")

# Create SQS hook with selective field propagation
metadata_hook = create_metadata_sqs_hook(
    queue_url="https://sqs.eu-west-1.amazonaws.com/123456789/metadata-updates",
    metadata_fields=["status", "agent_state", "priority"]  # Only sync these
)

# Create session manager with SQS propagation
session_manager = MongoDBSessionManager(
    session_id="user-session-123",
    connection_string="mongodb://localhost:27017/",
    database_name="my_db",
    metadataHook=metadata_hook
)

# Metadata changes are automatically sent to SQS
session_manager.update_metadata({
    "status": "processing",     # Sent to SQS
    "agent_state": "thinking",  # Sent to SQS
    "priority": "high",         # Sent to SQS
    "internal_field": "value"   # NOT sent to SQS
})
```

### SQS Message Format

**Message Body (JSON):**
```json
{
    "session_id": "user-session-123",
    "event": "metadata_update",
    "operation": "update",
    "metadata": {
        "status": "processing",
        "agent_state": "thinking",
        "priority": "high"
    },
    "timestamp": "2024-01-26T10:30:45.123456"
}
```

**Message Attributes:**
```python
{
    "session_id": {
        "DataType": "String",
        "StringValue": "user-session-123"
    },
    "event": {
        "DataType": "String",
        "StringValue": "metadata_update"
    }
}
```

### SSE Back-Propagation Pattern

```python
# Backend: Send metadata updates to SQS
from mongodb_session_manager import create_metadata_sqs_hook, MongoDBSessionManager

metadata_hook = create_metadata_sqs_hook(
    queue_url="https://sqs.eu-west-1.amazonaws.com/123/metadata-queue",
    metadata_fields=["status", "progress", "current_step"]
)

session_manager = MongoDBSessionManager(
    session_id="workflow-123",
    connection_string="mongodb://localhost:27017/",
    database_name="my_db",
    metadataHook=metadata_hook
)

# Update triggers SQS message
session_manager.update_metadata({
    "status": "running",
    "progress": 50,
    "current_step": "processing_data"
})

# SSE Consumer: Read from SQS and send to connected clients
import asyncio
import boto3
import json

sqs = boto3.client('sqs')

async def sse_consumer():
    """Read from SQS and send to SSE clients."""
    while True:
        # Poll SQS
        response = sqs.receive_message(
            QueueUrl="https://sqs.eu-west-1.amazonaws.com/123/metadata-queue",
            MaxNumberOfMessages=10,
            WaitTimeSeconds=5
        )

        for message in response.get('Messages', []):
            # Parse message
            data = json.loads(message['Body'])
            session_id = data['session_id']
            metadata = data['metadata']

            # Send to connected SSE clients for this session
            await broadcast_to_sse_clients(session_id, {
                "type": "metadata_update",
                "data": metadata
            })

            # Delete message from queue
            sqs.delete_message(
                QueueUrl="...",
                ReceiptHandle=message['ReceiptHandle']
            )
```

### Production Example

```python
import os
from mongodb_session_manager import create_metadata_sqs_hook, MongoDBSessionManager

# Use environment variables
metadata_hook = create_metadata_sqs_hook(
    queue_url=os.getenv("SQS_METADATA_QUEUE_URL"),
    metadata_fields=["status", "progress", "current_task", "errors"]
)

session_manager = MongoDBSessionManager(
    session_id="workflow-456",
    connection_string=os.getenv("MONGODB_URI"),
    database_name="production_db",
    metadataHook=metadata_hook
)

# Update workflow status - automatically propagated
session_manager.update_metadata({
    "status": "processing",
    "progress": 75,
    "current_task": "generating_report"
})
```

## Configuration

### Environment Variables

```bash
# SNS Configuration
export SNS_TOPIC_FEEDBACK_GOOD="arn:aws:sns:eu-west-1:123456789:feedback-good"
export SNS_TOPIC_FEEDBACK_BAD="arn:aws:sns:eu-west-1:123456789:feedback-bad"
export SNS_TOPIC_FEEDBACK_NEUTRAL="arn:aws:sns:eu-west-1:123456789:feedback-neutral"

# SQS Configuration
export SQS_METADATA_QUEUE_URL="https://sqs.eu-west-1.amazonaws.com/123456789/metadata-updates"

# AWS Credentials
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_DEFAULT_REGION="eu-west-1"
```

### AWS Resources Setup

**Create SNS Topics:**
```bash
# Create topics for feedback routing
aws sns create-topic --name feedback-good
aws sns create-topic --name feedback-bad
aws sns create-topic --name feedback-neutral

# Subscribe email endpoints
aws sns subscribe --topic-arn arn:aws:sns:eu-west-1:123:feedback-bad \
    --protocol email --notification-endpoint support@example.com
```

**Create SQS Queue:**
```bash
# Create queue for metadata updates
aws sqs create-queue --queue-name metadata-updates

# Get queue URL
aws sqs get-queue-url --queue-name metadata-updates
```

### Combined Usage

```python
from mongodb_session_manager import (
    MongoDBSessionManager,
    create_feedback_sns_hook,
    create_metadata_sqs_hook
)

# Create both hooks
feedback_hook = create_feedback_sns_hook(
    topic_arn_good=os.getenv("SNS_TOPIC_FEEDBACK_GOOD"),
    topic_arn_bad=os.getenv("SNS_TOPIC_FEEDBACK_BAD"),
    topic_arn_neutral=os.getenv("SNS_TOPIC_FEEDBACK_NEUTRAL")
)

metadata_hook = create_metadata_sqs_hook(
    queue_url=os.getenv("SQS_METADATA_QUEUE_URL"),
    metadata_fields=["status", "priority", "assigned_to"]
)

# Use both hooks
session_manager = MongoDBSessionManager(
    session_id="customer-support-001",
    connection_string=os.getenv("MONGODB_URI"),
    database_name="production_db",
    feedbackHook=feedback_hook,  # SNS for feedback
    metadataHook=metadata_hook    # SQS for metadata
)

# Feedback triggers SNS
session_manager.add_feedback({
    "rating": "down",
    "comment": "Issue with billing"
})

# Metadata triggers SQS
session_manager.update_metadata({
    "status": "escalated",
    "priority": "high",
    "assigned_to": "supervisor-jane"
})
```

## Best Practices

### 1. Use Environment Variables

```python
# Good - configurable
feedback_hook = create_feedback_sns_hook(
    topic_arn_good=os.getenv("SNS_TOPIC_FEEDBACK_GOOD"),
    topic_arn_bad=os.getenv("SNS_TOPIC_FEEDBACK_BAD"),
    topic_arn_neutral=os.getenv("SNS_TOPIC_FEEDBACK_NEUTRAL")
)

# Bad - hardcoded
feedback_hook = create_feedback_sns_hook(
    topic_arn_good="arn:aws:sns:eu-west-1:123:feedback-good",
    # ...
)
```

### 2. Handle Missing Dependencies

```python
# Good - graceful degradation
from mongodb_session_manager import is_feedback_sns_hook_available

if is_feedback_sns_hook_available():
    feedback_hook = create_feedback_sns_hook(...)
else:
    logger.warning("SNS hook not available - feedback notifications disabled")
    feedback_hook = None

session_manager = MongoDBSessionManager(
    feedbackHook=feedback_hook  # None is fine
)

# Bad - unhandled error
feedback_hook = create_feedback_sns_hook(...)  # May raise ImportError
```

### 3. Limit Propagated Fields

```python
# Good - only necessary fields
metadata_hook = create_metadata_sqs_hook(
    queue_url="...",
    metadata_fields=["status", "priority"]  # Minimal data
)

# Bad - all fields
metadata_hook = create_metadata_sqs_hook(
    queue_url="...",
    metadata_fields=None  # Sends everything!
)
```

### 4. Monitor Queue Depth

```python
import boto3

sqs = boto3.client('sqs')

def check_queue_health():
    """Monitor SQS queue depth."""
    attrs = sqs.get_queue_attributes(
        QueueUrl="...",
        AttributeNames=['ApproximateNumberOfMessages']
    )

    depth = int(attrs['Attributes']['ApproximateNumberOfMessages'])

    if depth > 1000:
        logger.warning(f"SQS queue backlog: {depth} messages")
```

### 5. Use Dead Letter Queues

```bash
# Create DLQ for failed messages
aws sqs create-queue --queue-name metadata-updates-dlq

# Configure main queue to use DLQ
aws sqs set-queue-attributes \
    --queue-url https://sqs.eu-west-1.amazonaws.com/123/metadata-updates \
    --attributes file://redrive-policy.json
```

**redrive-policy.json:**
```json
{
    "RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:eu-west-1:123:metadata-updates-dlq\",\"maxReceiveCount\":\"3\"}"
}
```

### 6. Log AWS Errors

```python
import logging

logger = logging.getLogger(__name__)

# AWS hooks log errors automatically
# Enable DEBUG logging to see AWS operations
logging.getLogger("mongodb_session_manager").setLevel(logging.DEBUG)
```

### 7. Test Without AWS

```python
# Development mode - disable AWS hooks
if os.getenv("ENV") == "development":
    feedback_hook = None
    metadata_hook = None
else:
    feedback_hook = create_feedback_sns_hook(...)
    metadata_hook = create_metadata_sqs_hook(...)
```

## Next Steps

- **[Feedback System](feedback-system.md)**: Learn about feedback management
- **[Metadata Management](metadata-management.md)**: Understand metadata operations
- **[Production Deployment](../deployment/aws.md)**: Deploy to AWS

## Additional Resources

- [AWS SNS Documentation](https://docs.aws.amazon.com/sns/)
- [AWS SQS Documentation](https://docs.aws.amazon.com/sqs/)
- [boto3 Documentation](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html)
