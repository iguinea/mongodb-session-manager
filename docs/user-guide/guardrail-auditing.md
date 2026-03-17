# Guardrail Auditing

## Overview

MongoDB Session Manager automatically records Bedrock Guardrail interventions at both the message level and the session level, providing a complete audit trail of content moderation actions.

When Amazon Bedrock Guardrails intercepts a message (e.g., blocking harmful content, filtering PII, or enforcing topic restrictions), the Strands SDK calls `redact_latest_message()`. MongoDB Session Manager hooks into this to record the event for auditing and compliance.

## How It Works

### Automatic Recording

When a guardrail intervenes, the following happens automatically:

1. The Strands SDK detects the guardrail intervention
2. It calls `redact_latest_message()` with the redacted content
3. MongoDB Session Manager records the event at two levels:
   - **Message level**: A `guardrail_event` field on the affected message
   - **Session level**: An entry in the `guardrail_events[]` array

Both updates happen in a single MongoDB operation for efficiency.

### Data Recorded

#### Message-Level Event

Each redacted message gets a `guardrail_event` field:

```json
{
  "message_id": 3,
  "role": "assistant",
  "content": "[Content blocked by guardrail]",
  "guardrail_event": {
    "action": "BLOCKED",
    "timestamp": "2026-03-17T10:00:00Z"
  }
}
```

#### Session-Level Audit Trail

The session document maintains a centralized `guardrail_events[]` array:

```json
{
  "session_id": "user-123",
  "guardrail_events": [
    {
      "message_id": 3,
      "agent_id": "support-agent",
      "action": "BLOCKED",
      "timestamp": "2026-03-17T10:00:00Z"
    },
    {
      "message_id": 7,
      "agent_id": "support-agent",
      "action": "ANONYMIZED",
      "timestamp": "2026-03-17T10:15:00Z"
    }
  ]
}
```

## Usage

### With Bedrock Guardrails (Automatic)

When using Strands Agents with Bedrock Guardrails configured, recording is fully automatic:

```python
from strands import Agent
from mongodb_session_manager import create_mongodb_session_manager

session_manager = create_mongodb_session_manager(
    session_id="user-123",
    connection_string="mongodb://localhost:27017/",
    database_name="my_db"
)

# Agent with Bedrock Guardrails configured in the model
agent = Agent(
    model="us.anthropic.claude-sonnet-4-20250514-v1:0",
    agent_id="support-agent",
    session_manager=session_manager,
    system_prompt="You are a helpful assistant."
)

# If a guardrail intervenes, the event is recorded automatically
response = agent("Some message that triggers a guardrail")
session_manager.sync_agent(agent)
```

### Manual Redaction

You can also manually redact messages with custom actions:

```python
from strands.types.content import Message
from mongodb_session_manager.mongodb_session_manager import GUARDRAIL_ACTION_BLOCKED

# Redact with default action (BLOCKED)
redacted = Message(
    role="assistant",
    content="[Content removed for privacy]"
)
session_manager.redact_latest_message(redacted, agent)

# Redact with custom action
session_manager.redact_latest_message(redacted, agent, action="ANONYMIZED")

# Using the constant
session_manager.redact_latest_message(redacted, agent, action=GUARDRAIL_ACTION_BLOCKED)
```

### Custom Actions

The `action` parameter accepts any string, allowing you to categorize different types of interventions:

| Action | Use Case |
|--------|----------|
| `"BLOCKED"` | Content completely blocked (default) |
| `"ANONYMIZED"` | PII removed but content preserved |
| `"FILTERED"` | Partial content filtering |
| `"REDACTED"` | Sensitive information removed |

## Querying Guardrail Events

### All Events for a Session

Use the session-level `guardrail_events` array for quick access:

```python
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017/")
db = client["my_db"]
collection = db["agent_sessions"]

# Get all guardrail events for a session
session = collection.find_one(
    {"session_id": "user-123"},
    {"guardrail_events": 1}
)

for event in session.get("guardrail_events", []):
    print(f"Message {event['message_id']} by {event['agent_id']}: "
          f"{event['action']} at {event['timestamp']}")
```

### Sessions with Guardrail Interventions

Find all sessions that had guardrail interventions:

```python
# Sessions with any guardrail events
sessions = collection.find(
    {"guardrail_events": {"$ne": []}},
    {"session_id": 1, "guardrail_events": 1}
)

# Sessions with BLOCKED actions specifically
sessions = collection.find(
    {"guardrail_events.action": "BLOCKED"},
    {"session_id": 1, "guardrail_events": 1}
)
```

### Count Interventions by Action Type

```python
pipeline = [
    {"$unwind": "$guardrail_events"},
    {"$group": {
        "_id": "$guardrail_events.action",
        "count": {"$sum": 1}
    }},
    {"$sort": {"count": -1}}
]

results = collection.aggregate(pipeline)
for r in results:
    print(f"{r['_id']}: {r['count']} events")
```

## Schema Reference

### Session Document Fields

| Field | Type | Description |
|-------|------|-------------|
| `guardrail_events` | `Array` | Session-level audit trail of all guardrail interventions |
| `guardrail_events[].message_id` | `int` | ID of the affected message |
| `guardrail_events[].agent_id` | `str` | ID of the agent whose message was redacted |
| `guardrail_events[].action` | `str` | Action taken (e.g., `"BLOCKED"`, `"ANONYMIZED"`) |
| `guardrail_events[].timestamp` | `datetime` | When the intervention occurred |

### Message-Level Fields

| Field | Type | Description |
|-------|------|-------------|
| `guardrail_event` | `Object` | Present only on redacted messages |
| `guardrail_event.action` | `str` | Action taken |
| `guardrail_event.timestamp` | `datetime` | When the intervention occurred |

## Future Enhancements

See [Issue #32](https://github.com/iguinea/mongodb-session-manager/issues/32) for planned enhancements to capture richer guardrail metrics from the Strands SDK, including:

- Full `GuardrailTrace` with input/output assessments
- Policy details (ContentPolicy, TopicPolicy, WordPolicy, SensitiveInformationPolicy, ContextualGroundingPolicy)
- Confidence levels and stop reasons

## See Also

- [Session Management](session-management.md) - General session management guide
- [MongoDBSessionManager API](../api-reference/mongodb-session-manager.md#redact_latest_message) - API reference for `redact_latest_message`
- [Data Model](../architecture/data-model.md) - Complete MongoDB schema documentation
- [Amazon Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html) - AWS documentation
