# AWS Integration Patterns

## 🚀 Runnable Examples

This guide includes code examples for AWS integrations. The actual implementation is in the hooks directory:

| Component | Description | Location |
|-----------|-------------|----------|
| FeedbackSNSHook | SNS notifications for feedback | [hooks/feedback_sns_hook.py](../../src/mongodb_session_manager/hooks/feedback_sns_hook.py) |
| MetadataSQSHook | SQS propagation for metadata | [hooks/metadata_sqs_hook.py](../../src/mongodb_session_manager/hooks/metadata_sqs_hook.py) |

📁 **All examples**: [View examples directory](../../examples/)

---

This guide demonstrates AWS service integrations with MongoDB Session Manager. Learn how to set up SNS feedback notifications, SQS metadata propagation, and build event-driven architectures with real-world patterns.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [SNS Feedback Notifications](#sns-feedback-notifications)
- [Topic Routing Based on Rating](#topic-routing-based-on-rating)
- [SQS Metadata Propagation](#sqs-metadata-propagation)
- [Combined SNS + SQS Usage](#combined-sns--sqs-usage)
- [Environment Configuration](#environment-configuration)
- [Error Handling and Graceful Degradation](#error-handling-and-graceful-degradation)
- [Testing AWS Integrations](#testing-aws-integrations)
- [Production Patterns](#production-patterns)

---

## Overview

MongoDB Session Manager provides seamless integration with AWS services for:

**SNS (Simple Notification Service):**
- Real-time feedback alerts
- Rating-based topic routing
- Non-blocking notifications
- Support team integration

**SQS (Simple Queue Service):**
- Metadata change propagation
- Server-Sent Events (SSE) back-propagation
- Selective field synchronization
- Event-driven architectures

**Key Features:**
- Optional dependencies (graceful degradation)
- Async/non-blocking operations
- Thread-safe execution
- Automatic error handling
- Production-ready patterns

---

## Prerequisites

### Install AWS Dependencies

```bash
# Install the python-helpers package for AWS integration
pip install python-helpers

# Or with UV
uv add python-helpers
```

### Check Availability

```python
"""
Check if AWS integrations are available.
"""

from mongodb_session_manager import (
    is_feedback_sns_hook_available,
    is_metadata_sqs_hook_available
)

# Check SNS hook availability
if is_feedback_sns_hook_available():
    print("✓ SNS feedback hook available")
    from mongodb_session_manager import create_feedback_sns_hook
else:
    print("✗ SNS hook not available - install python-helpers package")

# Check SQS hook availability
if is_metadata_sqs_hook_available():
    print("✓ SQS metadata hook available")
    from mongodb_session_manager import create_metadata_sqs_hook
else:
    print("✗ SQS hook not available - install python-helpers package")
```

### AWS Credentials

Set up AWS credentials:

```bash
# Option 1: Environment variables
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=eu-west-1

# Option 2: AWS credentials file (~/.aws/credentials)
[default]
aws_access_key_id = your_access_key
aws_secret_access_key = your_secret_key
region = eu-west-1

# Option 3: IAM role (for EC2/ECS/Lambda)
# No configuration needed - automatic
```

### Create AWS Resources

```bash
# Create SNS topics for feedback
aws sns create-topic --name feedback-good --region eu-west-1
aws sns create-topic --name feedback-bad --region eu-west-1
aws sns create-topic --name feedback-neutral --region eu-west-1

# Create SQS queue for metadata
aws sqs create-queue --queue-name metadata-updates --region eu-west-1

# Note the ARNs and URLs for use in your application
```

---

## SNS Feedback Notifications

Send real-time notifications when users submit feedback.

Reference: `/workspace/src/mongodb_session_manager/hooks/feedback_sns_hook.py`

### Basic SNS Setup

```python
"""
Basic SNS feedback notifications.
Based on /workspace/src/mongodb_session_manager/hooks/feedback_sns_hook.py
"""

from mongodb_session_manager import (
    MongoDBSessionManager,
    create_feedback_sns_hook,
    is_feedback_sns_hook_available
)

# Check availability
if not is_feedback_sns_hook_available():
    print("SNS hook not available - install python-helpers package")
    exit(1)

# Create SNS hook with three separate topics
feedback_hook = create_feedback_sns_hook(
    topic_arn_good="arn:aws:sns:eu-west-1:123456789:feedback-good",
    topic_arn_bad="arn:aws:sns:eu-west-1:123456789:feedback-bad",
    topic_arn_neutral="arn:aws:sns:eu-west-1:123456789:feedback-neutral"
)

# Create session manager with SNS hook
session_manager = MongoDBSessionManager(
    session_id="sns-demo-session",
    connection_string="mongodb://localhost:27017/",
    database_name="aws_examples",
    feedbackHook=feedback_hook
)

# Add feedback - automatically sends to appropriate SNS topic
print("=== Sending Positive Feedback ===")
session_manager.add_feedback({
    "rating": "up",
    "comment": "Great response! Very helpful."
})
print("✓ Feedback stored and SNS notification sent to topic_arn_good\n")

print("=== Sending Negative Feedback ===")
session_manager.add_feedback({
    "rating": "down",
    "comment": "The response was incomplete and unclear."
})
print("✓ Feedback stored and SNS notification sent to topic_arn_bad\n")

print("=== Sending Neutral Feedback ===")
session_manager.add_feedback({
    "rating": None,
    "comment": "Just saving this for reference."
})
print("✓ Feedback stored and SNS notification sent to topic_arn_neutral\n")

session_manager.close()
```

### SNS Message Format

When feedback is added, SNS receives:

```json
{
  "Subject": "Virtual Agents Feedback negative on session sns-demo-session",
  "Message": "Session: sns-demo-session\n\nThe response was incomplete and unclear.",
  "MessageAttributes": {
    "session_id": {
      "DataType": "String",
      "StringValue": "sns-demo-session"
    },
    "rating": {
      "DataType": "String",
      "StringValue": "negative"
    }
  }
}
```

---

## Topic Routing Based on Rating

Route feedback to different SNS topics based on rating.

```python
"""
Rating-based topic routing.
Demonstrates selective topic usage.
"""

from mongodb_session_manager import (
    MongoDBSessionManager,
    create_feedback_sns_hook
)

# Configuration 1: All feedback types
hook_all = create_feedback_sns_hook(
    topic_arn_good="arn:aws:sns:eu-west-1:123456789:feedback-good",
    topic_arn_bad="arn:aws:sns:eu-west-1:123456789:feedback-bad",
    topic_arn_neutral="arn:aws:sns:eu-west-1:123456789:feedback-neutral"
)

# Configuration 2: Only negative feedback (alerts)
hook_alerts_only = create_feedback_sns_hook(
    topic_arn_good="none",  # Disable positive notifications
    topic_arn_bad="arn:aws:sns:eu-west-1:123456789:feedback-alerts",
    topic_arn_neutral="none"  # Disable neutral notifications
)

# Configuration 3: Only positive feedback (celebration)
hook_positive_only = create_feedback_sns_hook(
    topic_arn_good="arn:aws:sns:eu-west-1:123456789:feedback-celebration",
    topic_arn_bad="none",
    topic_arn_neutral="none"
)

# Use case: Alert support team only on negative feedback
session_manager = MongoDBSessionManager(
    session_id="alerts-session",
    connection_string="mongodb://localhost:27017/",
    database_name="aws_examples",
    feedbackHook=hook_alerts_only
)

# Positive feedback - no SNS notification
session_manager.add_feedback({
    "rating": "up",
    "comment": "Perfect!"
})
print("✓ Positive feedback stored (no SNS notification)")

# Negative feedback - SNS alert sent
session_manager.add_feedback({
    "rating": "down",
    "comment": "Critical issue with the response"
})
print("🚨 Negative feedback stored and alert sent to support team")

session_manager.close()
```

### Routing Patterns

```python
"""
Advanced routing patterns.
"""

# Pattern 1: Different teams for different ratings
create_feedback_sns_hook(
    topic_arn_good="arn:aws:sns:eu-west-1:123:team-success",      # To success metrics team
    topic_arn_bad="arn:aws:sns:eu-west-1:123:team-support",       # To support team
    topic_arn_neutral="arn:aws:sns:eu-west-1:123:team-analytics"  # To analytics team
)

# Pattern 2: Escalation for negative feedback
create_feedback_sns_hook(
    topic_arn_good="none",
    topic_arn_bad="arn:aws:sns:eu-west-1:123:critical-alerts",  # PagerDuty integration
    topic_arn_neutral="none"
)

# Pattern 3: All feedback to analytics, alerts to support
# Use combined hooks (see Combined SNS + SQS section)
```

---

## SQS Metadata Propagation

Propagate metadata changes to SQS for real-time synchronization.

Reference: `/workspace/src/mongodb_session_manager/hooks/metadata_sqs_hook.py`

### Basic SQS Setup

```python
"""
Basic SQS metadata propagation.
Based on /workspace/src/mongodb_session_manager/hooks/metadata_sqs_hook.py
"""

from mongodb_session_manager import (
    MongoDBSessionManager,
    create_metadata_sqs_hook,
    is_metadata_sqs_hook_available
)

# Check availability
if not is_metadata_sqs_hook_available():
    print("SQS hook not available - install python-helpers package")
    exit(1)

# Create SQS hook with selective field propagation
metadata_hook = create_metadata_sqs_hook(
    queue_url="https://sqs.eu-west-1.amazonaws.com/123456789/metadata-updates",
    metadata_fields=["status", "agent_state", "priority"]  # Only these fields
)

# Create session manager with SQS hook
session_manager = MongoDBSessionManager(
    session_id="sqs-demo-session",
    connection_string="mongodb://localhost:27017/",
    database_name="aws_examples",
    metadataHook=metadata_hook
)

# Update metadata - propagated fields sent to SQS
print("=== Updating Metadata ===")
session_manager.update_metadata({
    "status": "processing",           # Sent to SQS
    "agent_state": "thinking",        # Sent to SQS
    "priority": "high",               # Sent to SQS
    "internal_field": "not_sent",     # NOT sent to SQS (not in metadata_fields)
    "user_id": "user-123"             # NOT sent to SQS (not in metadata_fields)
})
print("✓ Metadata updated - selective fields sent to SQS\n")

# Delete metadata - deletion sent to SQS
print("=== Deleting Metadata ===")
session_manager.delete_metadata(["priority"])
print("✓ Metadata deleted - deletion event sent to SQS\n")

session_manager.close()
```

### SQS Message Format

When metadata is updated, SQS receives:

```json
{
  "session_id": "sqs-demo-session",
  "event": "metadata_update",
  "operation": "update",
  "metadata": {
    "status": "processing",
    "agent_state": "thinking",
    "priority": "high"
  },
  "timestamp": "2024-01-26T10:00:00.123456"
}
```

When metadata is deleted:

```json
{
  "session_id": "sqs-demo-session",
  "event": "metadata_update",
  "operation": "delete",
  "metadata": {
    "priority": null
  },
  "timestamp": "2024-01-26T10:00:15.789012"
}
```

---

## Combined SNS + SQS Usage

Use both SNS and SQS together for comprehensive event handling.

```python
"""
Combined SNS and SQS integration.
Demonstrates using both hooks simultaneously.
"""

from mongodb_session_manager import (
    MongoDBSessionManager,
    create_feedback_sns_hook,
    create_metadata_sqs_hook
)

# Create both hooks
feedback_hook = create_feedback_sns_hook(
    topic_arn_good="arn:aws:sns:eu-west-1:123:feedback-good",
    topic_arn_bad="arn:aws:sns:eu-west-1:123:feedback-bad",
    topic_arn_neutral="arn:aws:sns:eu-west-1:123:feedback-neutral"
)

metadata_hook = create_metadata_sqs_hook(
    queue_url="https://sqs.eu-west-1.amazonaws.com/123/metadata-updates",
    metadata_fields=["status", "agent_state", "user_satisfaction"]
)

# Create session manager with both hooks
session_manager = MongoDBSessionManager(
    session_id="combined-demo-session",
    connection_string="mongodb://localhost:27017/",
    database_name="aws_examples",
    feedbackHook=feedback_hook,
    metadataHook=metadata_hook
)

# Scenario: User interaction with full tracking
print("=== User Interaction Flow ===\n")

# 1. Update session status
print("1. Setting session status...")
session_manager.update_metadata({
    "status": "active",
    "agent_state": "ready"
})
print("   ✓ Metadata update sent to SQS\n")

# 2. User provides feedback
print("2. User provides positive feedback...")
session_manager.add_feedback({
    "rating": "up",
    "comment": "Great assistance!"
})
print("   ✓ Feedback notification sent to SNS (good topic)\n")

# 3. Update satisfaction score in metadata
print("3. Updating satisfaction score...")
session_manager.update_metadata({
    "user_satisfaction": "high",
    "agent_state": "completed"
})
print("   ✓ Satisfaction update sent to SQS\n")

# 4. Another feedback (negative)
print("4. User provides negative feedback...")
session_manager.add_feedback({
    "rating": "down",
    "comment": "Follow-up was unclear"
})
print("   ✓ Feedback alert sent to SNS (bad topic)\n")

# 5. Update status based on negative feedback
print("5. Updating status based on feedback...")
session_manager.update_metadata({
    "status": "needs_review",
    "user_satisfaction": "low"
})
print("   ✓ Status update sent to SQS\n")

print("=== Complete Flow ===")
print("Events sent:")
print("  - 3 SQS messages (metadata updates)")
print("  - 2 SNS notifications (feedback alerts)")
print("\nData synchronized across:")
print("  - MongoDB (persistent storage)")
print("  - SQS (real-time metadata sync)")
print("  - SNS (feedback notifications)")

session_manager.close()
```

### Use Case: Real-time Dashboard

```python
"""
Real-time dashboard with AWS integration.
"""

# Consumer side (separate process/service)
import boto3
import json

sqs = boto3.client('sqs', region_name='eu-west-1')
queue_url = "https://sqs.eu-west-1.amazonaws.com/123/metadata-updates"

def process_metadata_updates():
    """
    Process metadata updates from SQS for real-time dashboard.
    """
    while True:
        # Receive messages
        response = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=20  # Long polling
        )

        if 'Messages' not in response:
            continue

        for message in response['Messages']:
            # Parse message
            body = json.loads(message['Body'])

            session_id = body['session_id']
            operation = body['operation']
            metadata = body['metadata']

            # Update dashboard via SSE
            if operation == "update":
                send_sse_update(session_id, metadata)
            elif operation == "delete":
                send_sse_delete(session_id, metadata)

            # Delete message from queue
            sqs.delete_message(
                QueueUrl=queue_url,
                ReceiptHandle=message['ReceiptHandle']
            )

def send_sse_update(session_id: str, metadata: dict):
    """Send SSE update to connected clients."""
    # Implementation depends on your SSE server
    print(f"SSE Update: {session_id} -> {metadata}")

def send_sse_delete(session_id: str, deleted_fields: dict):
    """Send SSE delete event to connected clients."""
    print(f"SSE Delete: {session_id} -> {list(deleted_fields.keys())}")
```

---

## Environment Configuration

Manage AWS configuration across environments.

```python
"""
Environment-based AWS configuration.
"""

import os
from mongodb_session_manager import (
    MongoDBSessionManager,
    create_feedback_sns_hook,
    create_metadata_sqs_hook
)

# Environment-specific configuration
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# SNS Topics
SNS_TOPICS = {
    "development": {
        "good": "arn:aws:sns:eu-west-1:123:dev-feedback-good",
        "bad": "arn:aws:sns:eu-west-1:123:dev-feedback-bad",
        "neutral": "arn:aws:sns:eu-west-1:123:dev-feedback-neutral"
    },
    "staging": {
        "good": "arn:aws:sns:eu-west-1:123:staging-feedback-good",
        "bad": "arn:aws:sns:eu-west-1:123:staging-feedback-bad",
        "neutral": "arn:aws:sns:eu-west-1:123:staging-feedback-neutral"
    },
    "production": {
        "good": "arn:aws:sns:eu-west-1:123:prod-feedback-good",
        "bad": "arn:aws:sns:eu-west-1:123:prod-feedback-bad",
        "neutral": "arn:aws:sns:eu-west-1:123:prod-feedback-neutral"
    }
}

# SQS Queues
SQS_QUEUES = {
    "development": "https://sqs.eu-west-1.amazonaws.com/123/dev-metadata",
    "staging": "https://sqs.eu-west-1.amazonaws.com/123/staging-metadata",
    "production": "https://sqs.eu-west-1.amazonaws.com/123/prod-metadata"
}

def create_session_manager_with_aws(session_id: str):
    """Create session manager with environment-appropriate AWS hooks."""

    # Get environment config
    sns_config = SNS_TOPICS[ENVIRONMENT]
    sqs_queue = SQS_QUEUES[ENVIRONMENT]

    # Create hooks
    feedback_hook = create_feedback_sns_hook(
        topic_arn_good=sns_config["good"],
        topic_arn_bad=sns_config["bad"],
        topic_arn_neutral=sns_config["neutral"]
    )

    metadata_hook = create_metadata_sqs_hook(
        queue_url=sqs_queue,
        metadata_fields=["status", "priority", "agent_state"]
    )

    # Create session manager
    return MongoDBSessionManager(
        session_id=session_id,
        connection_string=os.getenv("MONGODB_URI"),
        database_name=f"{ENVIRONMENT}_db",
        feedbackHook=feedback_hook,
        metadataHook=metadata_hook
    )

# Usage
session_manager = create_session_manager_with_aws("user-session-123")

# Works across all environments with appropriate AWS resources
session_manager.add_feedback({"rating": "up", "comment": "Great!"})
session_manager.update_metadata({"status": "processing"})

session_manager.close()
```

### Configuration File Pattern

```python
"""
Configuration file pattern for AWS resources.
"""

# config/aws_config.py
from dataclasses import dataclass
from typing import Optional

@dataclass
class AWSConfig:
    """AWS configuration for MongoDB Session Manager."""
    sns_topic_good: str
    sns_topic_bad: str
    sns_topic_neutral: str
    sqs_queue_url: str
    region: str = "eu-west-1"

    @classmethod
    def from_env(cls, environment: str) -> Optional['AWSConfig']:
        """Load configuration from environment."""
        configs = {
            "development": cls(
                sns_topic_good="arn:aws:sns:eu-west-1:123:dev-feedback-good",
                sns_topic_bad="arn:aws:sns:eu-west-1:123:dev-feedback-bad",
                sns_topic_neutral="arn:aws:sns:eu-west-1:123:dev-feedback-neutral",
                sqs_queue_url="https://sqs.eu-west-1.amazonaws.com/123/dev-metadata"
            ),
            "production": cls(
                sns_topic_good="arn:aws:sns:eu-west-1:123:prod-feedback-good",
                sns_topic_bad="arn:aws:sns:eu-west-1:123:prod-feedback-bad",
                sns_topic_neutral="arn:aws:sns:eu-west-1:123:prod-feedback-neutral",
                sqs_queue_url="https://sqs.eu-west-1.amazonaws.com/123/prod-metadata"
            )
        }
        return configs.get(environment)

# Usage
config = AWSConfig.from_env("production")
feedback_hook = create_feedback_sns_hook(
    topic_arn_good=config.sns_topic_good,
    topic_arn_bad=config.sns_topic_bad,
    topic_arn_neutral=config.sns_topic_neutral
)
```

---

## Error Handling and Graceful Degradation

Handle AWS errors gracefully to ensure core functionality continues.

```python
"""
Graceful degradation and error handling.
"""

import logging
from mongodb_session_manager import (
    MongoDBSessionManager,
    create_feedback_sns_hook,
    is_feedback_sns_hook_available
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_session_manager_safe(session_id: str):
    """
    Create session manager with optional AWS integration.
    Falls back gracefully if AWS is unavailable.
    """
    feedback_hook = None

    # Try to create SNS hook
    if is_feedback_sns_hook_available():
        try:
            feedback_hook = create_feedback_sns_hook(
                topic_arn_good="arn:aws:sns:eu-west-1:123:feedback-good",
                topic_arn_bad="arn:aws:sns:eu-west-1:123:feedback-bad",
                topic_arn_neutral="arn:aws:sns:eu-west-1:123:feedback-neutral"
            )
            logger.info("✓ AWS SNS integration enabled")
        except Exception as e:
            logger.warning(f"⚠ AWS SNS integration failed: {e}")
            logger.warning("Continuing without SNS notifications")
            feedback_hook = None
    else:
        logger.info("ℹ AWS SNS integration not available (missing python-helpers)")

    # Create session manager (works with or without hook)
    return MongoDBSessionManager(
        session_id=session_id,
        connection_string="mongodb://localhost:27017/",
        database_name="examples",
        feedbackHook=feedback_hook
    )

# Usage - works regardless of AWS availability
session_manager = create_session_manager_safe("resilient-session")

# Feedback is always stored in MongoDB
# SNS notification is sent if available
session_manager.add_feedback({
    "rating": "up",
    "comment": "Works great!"
})

print("✓ Feedback stored successfully")
print("  - MongoDB: Stored")
print("  - SNS: Sent (if available)")

session_manager.close()
```

### Error Scenarios

```python
"""
Handling various error scenarios.
"""

# Scenario 1: Invalid topic ARN
try:
    hook = create_feedback_sns_hook(
        topic_arn_good="invalid-arn",
        topic_arn_bad="arn:aws:sns:eu-west-1:123:feedback-bad",
        topic_arn_neutral="none"
    )
except Exception as e:
    logger.error(f"Invalid SNS configuration: {e}")
    # Fall back to no hook

# Scenario 2: Network issues
# The hook automatically handles network errors
# Feedback is stored in MongoDB regardless

# Scenario 3: Permission denied
# Hook logs error but doesn't fail the operation

# Scenario 4: Missing dependencies
if not is_feedback_sns_hook_available():
    logger.warning("python-helpers not installed")
    logger.info("To enable SNS: pip install python-helpers")
    # Proceed without SNS integration
```

---

## Testing AWS Integrations

Test AWS integrations locally and in CI/CD.

### Local Testing with LocalStack

```python
"""
Local testing with LocalStack.
"""

import os
import boto3
from mongodb_session_manager import (
    MongoDBSessionManager,
    create_feedback_sns_hook
)

# Configure LocalStack endpoints
os.environ['AWS_ACCESS_KEY_ID'] = 'test'
os.environ['AWS_SECRET_ACCESS_KEY'] = 'test'
os.environ['AWS_DEFAULT_REGION'] = 'eu-west-1'

# Create LocalStack client
sns = boto3.client(
    'sns',
    endpoint_url='http://localhost:4566',  # LocalStack
    region_name='eu-west-1'
)

# Create local topics
response = sns.create_topic(Name='test-feedback-good')
topic_arn = response['TopicArn']

# Create hook with local topic
feedback_hook = create_feedback_sns_hook(
    topic_arn_good=topic_arn,
    topic_arn_bad=topic_arn,
    topic_arn_neutral=topic_arn
)

# Test
session_manager = MongoDBSessionManager(
    session_id="test-session",
    connection_string="mongodb://localhost:27017/",
    database_name="test",
    feedbackHook=feedback_hook
)

session_manager.add_feedback({"rating": "up", "comment": "Test"})
print("✓ Local test successful")

session_manager.close()
```

### Mock Testing

```python
"""
Unit testing with mocks.
"""

from unittest.mock import Mock, patch
from mongodb_session_manager import MongoDBSessionManager

def test_feedback_with_sns():
    """Test feedback with mocked SNS."""

    # Mock the SNS hook
    mock_hook = Mock()

    session_manager = MongoDBSessionManager(
        session_id="test-session",
        connection_string="mongodb://localhost:27017/",
        database_name="test",
        feedbackHook=mock_hook
    )

    # Add feedback
    session_manager.add_feedback({
        "rating": "up",
        "comment": "Test feedback"
    })

    # Verify hook was called
    assert mock_hook.called
    call_args = mock_hook.call_args
    assert call_args[1]["action"] == "add"
    assert call_args[1]["feedback"]["rating"] == "up"

    session_manager.close()
```

---

## Production Patterns

Real-world production patterns and architectures.

### Pattern 1: Multi-Channel Notifications

```python
"""
Send feedback to multiple channels simultaneously.
"""

from mongodb_session_manager import create_feedback_sns_hook

# Create hook with different topics for different channels
feedback_hook = create_feedback_sns_hook(
    # Good feedback -> Celebration channel
    topic_arn_good="arn:aws:sns:eu-west-1:123:team-celebrations",

    # Bad feedback -> Multiple subscriptions:
    # - Email to support team
    # - Slack notification
    # - PagerDuty alert (for critical)
    topic_arn_bad="arn:aws:sns:eu-west-1:123:critical-alerts",

    # Neutral -> Analytics only
    topic_arn_neutral="arn:aws:sns:eu-west-1:123:analytics-feed"
)
```

### Pattern 2: Event-Driven Workflow

```python
"""
Trigger workflows based on metadata changes.
"""

# SQS consumer triggers Step Functions workflow
import boto3
import json

sqs = boto3.client('sqs')
stepfunctions = boto3.client('stepfunctions')

def process_metadata_event(event):
    """Process metadata event and trigger workflow."""
    session_id = event['session_id']
    metadata = event['metadata']

    # Check for workflow triggers
    if metadata.get('status') == 'needs_review':
        # Start review workflow
        stepfunctions.start_execution(
            stateMachineArn='arn:aws:states:eu-west-1:123:stateMachine:ReviewWorkflow',
            input=json.dumps({
                'session_id': session_id,
                'metadata': metadata
            })
        )

    elif metadata.get('priority') == 'high':
        # Escalate to senior support
        sns.publish(
            TopicArn='arn:aws:sns:eu-west-1:123:senior-support',
            Message=f'High priority session: {session_id}'
        )
```

### Pattern 3: Analytics Pipeline

```python
"""
Build analytics pipeline with SQS and Kinesis.
"""

# SQS -> Lambda -> Kinesis -> Analytics
import boto3

kinesis = boto3.client('kinesis')

def metadata_to_analytics(event):
    """Forward metadata events to analytics stream."""
    session_id = event['session_id']
    metadata = event['metadata']

    # Enrich with additional data
    record = {
        'session_id': session_id,
        'metadata': metadata,
        'timestamp': event['timestamp'],
        'event': event['event']
    }

    # Send to Kinesis for real-time analytics
    kinesis.put_record(
        StreamName='session-analytics',
        Data=json.dumps(record),
        PartitionKey=session_id
    )
```

### Pattern 4: Disaster Recovery

```python
"""
Implement disaster recovery with SQS DLQ.
"""

# Configure SQS with Dead Letter Queue
import boto3

sqs = boto3.client('sqs')

# Create DLQ
dlq_response = sqs.create_queue(
    QueueName='metadata-updates-dlq',
    Attributes={
        'MessageRetentionPeriod': '1209600'  # 14 days
    }
)

# Create main queue with DLQ
queue_response = sqs.create_queue(
    QueueName='metadata-updates',
    Attributes={
        'RedrivePolicy': json.dumps({
            'deadLetterTargetArn': dlq_response['QueueUrl'],
            'maxReceiveCount': '3'
        })
    }
)

# Monitor DLQ for failed processing
def monitor_dlq():
    """Monitor DLQ and alert on failures."""
    response = sqs.receive_message(
        QueueUrl=dlq_response['QueueUrl'],
        MaxNumberOfMessages=1
    )

    if 'Messages' in response:
        # Alert on failed messages
        sns.publish(
            TopicArn='arn:aws:sns:eu-west-1:123:ops-alerts',
            Subject='SQS DLQ Alert',
            Message=f'Messages in DLQ: investigate failed processing'
        )
```

---

## Try It Yourself

1. **Set up LocalStack** for local AWS development
2. **Create an SNS->Slack integration** for feedback alerts
3. **Build a real-time dashboard** consuming SQS metadata events
4. **Implement sentiment analysis** on feedback before SNS notification
5. **Create a CloudWatch dashboard** tracking feedback metrics

## Troubleshooting

### SNS Permissions Error

```bash
# Problem: AccessDenied when publishing to SNS
# Solution: Add IAM policy

{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "sns:Publish",
    "Resource": "arn:aws:sns:eu-west-1:123:feedback-*"
  }]
}
```

### SQS Message Not Received

```python
# Problem: Messages not appearing in SQS
# Solution: Check queue policy and VPC settings

import boto3
sqs = boto3.client('sqs')

# Check queue attributes
response = sqs.get_queue_attributes(
    QueueUrl='your-queue-url',
    AttributeNames=['All']
)
print(response['Attributes'])

# Verify message visibility
response = sqs.receive_message(
    QueueUrl='your-queue-url',
    VisibilityTimeout=0,  # Make visible immediately
    WaitTimeSeconds=10
)
```

### Hook Not Executing

```python
# Problem: AWS hook doesn't seem to run
# Solution: Check logs and verify hook installation

import logging
logging.basicConfig(level=logging.DEBUG)

# This will show hook execution
session_manager.add_feedback({"rating": "up", "comment": "test"})
```

## Next Steps

- Review [Feedback Patterns](feedback-patterns.md) for feedback best practices
- Explore [Metadata Patterns](metadata-patterns.md) for metadata management
- Check [FastAPI Integration](fastapi-integration.md) for production APIs

## Reference Files

- `/workspace/src/mongodb_session_manager/hooks/feedback_sns_hook.py` - SNS implementation
- `/workspace/src/mongodb_session_manager/hooks/metadata_sqs_hook.py` - SQS implementation
- `/workspace/src/mongodb_session_manager/__init__.py` - Hook exports and helpers
