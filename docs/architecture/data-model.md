# Data Model

## Table of Contents
- [Introduction](#introduction)
- [MongoDB Document Structure](#mongodb-document-structure)
- [Schema Overview](#schema-overview)
- [Session Document](#session-document)
- [Agent Structure](#agent-structure)
- [Message Array](#message-array)
- [Metadata Object](#metadata-object)
- [Feedbacks Array](#feedbacks-array)
- [Index Strategy](#index-strategy)
- [Field Types and Constraints](#field-types-and-constraints)
- [Schema Evolution](#schema-evolution)
- [Query Patterns](#query-patterns)

## Introduction

The MongoDB Session Manager uses a document-oriented data model optimized for conversational AI workloads. The schema is designed around the principle that sessions are the primary unit of access, with all related data (agents, messages, metadata) embedded within a single document for optimal read performance and atomic operations.

### Design Philosophy

1. **Single Document per Session**: All session data in one MongoDB document
2. **Embedded Relations**: Agents and messages are nested, not referenced
3. **Flexible Schema**: Metadata can be any structure
4. **Optimized for Reads**: Fetching a session requires one query
5. **Atomic Updates**: All session changes can be atomic
6. **Time-Stamped**: Every level has creation and update timestamps

### Collection Structure

```
Database
└── sessions (collection)
    ├── session-001 (document)
    ├── session-002 (document)
    └── session-N (document)
```

Each document represents a complete session with all its agents, messages, and metadata.

## MongoDB Document Structure

### Complete Example

```json
{
    "_id": "user-alice-chat-20240115",
    "session_id": "user-alice-chat-20240115",
    "session_type": "customer_support",
    "created_at": ISODate("2024-01-15T09:00:00.000Z"),
    "updated_at": ISODate("2024-01-22T14:30:45.123Z"),
    "metadata": {
        "user_id": "alice-123",
        "user_name": "Alice Johnson",
        "department": "sales",
        "priority": "high",
        "assigned_to": "agent-456",
        "tags": ["new_customer", "enterprise"],
        "custom_data": {
            "company": "ACME Corp",
            "tier": "premium"
        }
    },
    "feedbacks": [
        {
            "rating": "up",
            "comment": "Very helpful response, solved my issue!",
            "created_at": ISODate("2024-01-22T14:30:00.000Z")
        },
        {
            "rating": "down",
            "comment": "Response was too slow",
            "created_at": ISODate("2024-01-22T16:45:00.000Z")
        },
        {
            "rating": null,
            "comment": "Just testing the feedback system",
            "created_at": ISODate("2024-01-22T17:00:00.000Z")
        }
    ],
    "agents": {
        "support-agent": {
            "agent_data": {
                "agent_id": "support-agent",
                "model": "claude-3-sonnet-20240229",
                "system_prompt": "You are a helpful customer support agent.",
                "temperature": 0.7,
                "max_tokens": 1024,
                "state": {
                    "conversation_count": 5,
                    "last_topic": "billing_inquiry",
                    "user_preferences": {
                        "language": "en",
                        "tone": "professional"
                    }
                },
                "conversation_manager_state": {},
                "created_at": "2024-01-15T09:00:00.000Z",
                "updated_at": "2024-01-22T14:30:00.000Z"
            },
            "created_at": ISODate("2024-01-15T09:00:00.000Z"),
            "updated_at": ISODate("2024-01-22T14:30:45.123Z"),
            "messages": [
                {
                    "message_id": 1,
                    "role": "user",
                    "content": "Hi, I have a question about my billing.",
                    "created_at": ISODate("2024-01-15T09:00:00.000Z"),
                    "updated_at": ISODate("2024-01-15T09:00:00.000Z")
                },
                {
                    "message_id": 2,
                    "role": "assistant",
                    "content": "Hello! I'd be happy to help with your billing question. What would you like to know?",
                    "created_at": ISODate("2024-01-15T09:00:02.456Z"),
                    "updated_at": ISODate("2024-01-15T09:00:02.456Z"),
                    "event_loop_metrics": {
                        "accumulated_metrics": {
                            "latencyMs": 245
                        },
                        "accumulated_usage": {
                            "inputTokens": 28,
                            "outputTokens": 24,
                            "totalTokens": 52
                        }
                    }
                },
                {
                    "message_id": 3,
                    "role": "user",
                    "content": "Why was I charged twice this month?",
                    "created_at": ISODate("2024-01-15T09:01:00.000Z"),
                    "updated_at": ISODate("2024-01-15T09:01:00.000Z")
                },
                {
                    "message_id": 4,
                    "role": "assistant",
                    "content": "I can look into that for you. Let me check your billing history...",
                    "created_at": ISODate("2024-01-15T09:01:03.789Z"),
                    "updated_at": ISODate("2024-01-15T09:01:03.789Z"),
                    "event_loop_metrics": {
                        "accumulated_metrics": {
                            "latencyMs": 312
                        },
                        "accumulated_usage": {
                            "inputTokens": 89,
                            "outputTokens": 18,
                            "totalTokens": 107
                        }
                    }
                }
            ]
        },
        "translator-agent": {
            "agent_data": {
                "agent_id": "translator-agent",
                "model": "claude-3-haiku-20240307",
                "system_prompt": "You are a language translation specialist.",
                "state": {
                    "source_language": "en",
                    "target_language": "es"
                },
                "conversation_manager_state": {},
                "created_at": "2024-01-22T14:00:00.000Z",
                "updated_at": "2024-01-22T14:30:00.000Z"
            },
            "created_at": ISODate("2024-01-22T14:00:00.000Z"),
            "updated_at": ISODate("2024-01-22T14:30:45.123Z"),
            "messages": [
                {
                    "message_id": 1,
                    "role": "user",
                    "content": "Translate: 'Thank you for your patience'",
                    "created_at": ISODate("2024-01-22T14:30:00.000Z"),
                    "updated_at": ISODate("2024-01-22T14:30:00.000Z")
                },
                {
                    "message_id": 2,
                    "role": "assistant",
                    "content": "Gracias por tu paciencia",
                    "created_at": ISODate("2024-01-22T14:30:01.234Z"),
                    "updated_at": ISODate("2024-01-22T14:30:01.234Z"),
                    "event_loop_metrics": {
                        "accumulated_metrics": {
                            "latencyMs": 123
                        },
                        "accumulated_usage": {
                            "inputTokens": 12,
                            "outputTokens": 8,
                            "totalTokens": 20
                        }
                    }
                }
            ]
        }
    }
}
```

## Schema Overview

### Hierarchical Structure

```
Session Document (Root)
├── _id (string)
├── session_id (string)
├── session_type (string)
├── created_at (ISODate)
├── updated_at (ISODate)
├── metadata (object)
│   └── {user-defined fields}
├── feedbacks (array)
│   └── feedback objects
└── agents (object)
    └── {agent_id} (object)
        ├── agent_data (object)
        │   ├── agent_id (string)
        │   ├── model (string)
        │   ├── system_prompt (string)
        │   ├── state (object)
        │   ├── conversation_manager_state (object)
        │   ├── created_at (string, ISO format)
        │   └── updated_at (string, ISO format)
        ├── created_at (ISODate)
        ├── updated_at (ISODate)
        └── messages (array)
            └── message objects
                ├── message_id (int)
                ├── role (string)
                ├── content (string/array)
                ├── created_at (ISODate)
                ├── updated_at (ISODate)
                └── event_loop_metrics (object, optional)
```

### Data Type Map

| Level | Field | Type | Format | Required |
|-------|-------|------|--------|----------|
| Root | _id | string | session_id | Yes |
| Root | session_id | string | user-defined | Yes |
| Root | session_type | string | default: "default" | Yes |
| Root | created_at | ISODate | UTC timestamp | Yes |
| Root | updated_at | ISODate | UTC timestamp | Yes |
| Root | metadata | object | flexible schema | Yes |
| Root | feedbacks | array | feedback objects | Yes |
| Root | agents | object | keyed by agent_id | Yes |
| Agent | agent_data | object | Strands SDK format | Yes |
| Agent | created_at | ISODate | UTC timestamp | Yes |
| Agent | updated_at | ISODate | UTC timestamp | Yes |
| Agent | messages | array | message objects | Yes |
| Message | message_id | int | auto-increment | Yes |
| Message | role | string | user/assistant/system | Yes |
| Message | content | string/array | message content | Yes |
| Message | created_at | ISODate | UTC timestamp | Yes |
| Message | updated_at | ISODate | UTC timestamp | Yes |
| Message | event_loop_metrics | object | metrics data | No |

## Session Document

### Root Fields

#### _id (Primary Key)
```json
{
    "_id": "user-alice-chat-20240115"
}
```

**Type**: String
**Purpose**: MongoDB primary key, used for fast lookups
**Format**: Same as `session_id` (intentional duplication for convenience)
**Indexing**: Automatically indexed by MongoDB
**Uniqueness**: Guaranteed unique across collection

**Why duplicate session_id as _id?**
- Convenient: `db.sessions.find_one({"_id": session_id})`
- Fast: Uses primary key index
- Simple: No need for separate ID generation

#### session_id
```json
{
    "session_id": "user-alice-chat-20240115"
}
```

**Type**: String
**Purpose**: Business identifier for the session
**Format**: User-defined, typically includes:
- User identifier
- Session type
- Timestamp/date
- Unique suffix if needed

**Common Patterns**:
```python
# Customer support
f"customer-{customer_id}-support-{date}"

# Translation
f"user-{user_id}-translation-{thread_id}"

# Monthly sessions
f"user-{user_id}-main-{year}-{month}"
```

#### session_type
```json
{
    "session_type": "customer_support"
}
```

**Type**: String
**Purpose**: Categorize sessions for analytics and filtering
**Default**: "default"
**Examples**: "customer_support", "translation", "chat", "onboarding"

**Use Cases**:
- Analytics: Count sessions by type
- Filtering: Different TTL policies per type
- Reporting: Group metrics by session type

#### Timestamps
```json
{
    "created_at": ISODate("2024-01-15T09:00:00.000Z"),
    "updated_at": ISODate("2024-01-22T14:30:45.123Z")
}
```

**Type**: ISODate (MongoDB BSON type)
**Timezone**: Always UTC
**Precision**: Milliseconds
**Updates**:
- `created_at`: Set once on creation, never changes
- `updated_at`: Updated on every session modification

**Automatic Indexing**: Both fields automatically indexed for time-based queries

### Code Reference
```python
# Session creation in repository
session_doc = {
    "_id": session.session_id,
    "session_id": session.session_id,
    "session_type": session.session_type,
    "created_at": datetime.now(UTC),
    "updated_at": datetime.now(UTC),
    "agents": {},
    "metadata": {},
    "feedbacks": [],
}
```

**Location**: `/workspace/src/mongodb_session_manager/mongodb_session_repository.py` (lines 199-208)

## Agent Structure

### Agent Container Object

Agents are stored in an object (not array) keyed by `agent_id`:

```json
{
    "agents": {
        "support-agent": { /* agent data */ },
        "translator-agent": { /* agent data */ },
        "analytics-agent": { /* agent data */ }
    }
}
```

**Why Object Instead of Array?**
- Direct access: `agents.{agent_id}` faster than array search
- Unique enforcement: Object keys are unique by definition
- Update path: `agents.{agent_id}.field` is simpler than array position
- Query efficiency: `{"agents.support-agent.messages": {...}}` works directly

### Agent Fields

#### agent_data (Strands SDK State)
```json
{
    "agent_data": {
        "agent_id": "support-agent",
        "model": "claude-3-sonnet-20240229",
        "system_prompt": "You are a helpful customer support agent.",
        "temperature": 0.7,
        "max_tokens": 1024,
        "tools": [],
        "state": {
            "conversation_count": 5,
            "last_topic": "billing_inquiry",
            "custom_field": "custom_value"
        },
        "conversation_manager_state": {},
        "created_at": "2024-01-15T09:00:00.000Z",
        "updated_at": "2024-01-22T14:30:00.000Z"
    }
}
```

**Type**: Object (from Strands SDK `SessionAgent.__dict__`)
**Purpose**: Complete agent configuration and state
**Format**: Defined by Strands SDK

**Key Subfields**:
- `agent_id`: Unique identifier for this agent
- `model`: AI model being used
- `system_prompt`: Agent's instructions
- `state`: Key-value store for agent state
- `conversation_manager_state`: Internal SDK state
- `created_at`, `updated_at`: Timestamps in ISO string format (from SDK)

**State Object**:
The `state` object is a flexible key-value store where agents can persist any data:

```python
# Agent can store any data
agent.state.set("user_language", "euskera")
agent.state.set("translation_count", 42)
agent.state.set("preferences", {"tone": "formal"})

# Automatically persisted in MongoDB
{
    "agent_data": {
        "state": {
            "user_language": "euskera",
            "translation_count": 42,
            "preferences": {"tone": "formal"}
        }
    }
}
```

#### Agent-Level Timestamps
```json
{
    "created_at": ISODate("2024-01-15T09:00:00.000Z"),
    "updated_at": ISODate("2024-01-22T14:30:45.123Z")
}
```

**Type**: ISODate
**Purpose**: Track when agent was added to session and last modified
**Different from agent_data timestamps**:
- These are MongoDB ISODate (for queries)
- agent_data timestamps are ISO strings (from Strands SDK)

#### messages (Array)
```json
{
    "messages": [
        { /* message 1 */ },
        { /* message 2 */ },
        { /* message N */ }
    ]
}
```

**Type**: Array of message objects
**Purpose**: Complete conversation history for this agent
**Ordering**: Chronological (oldest to newest)
**Size**: Grows with conversation (monitor document size)

### Agent Creation Code
```python
def create_agent(self, session_id, session_agent, **kwargs):
    agent_data = session_agent.__dict__

    # Convert SDK timestamps to datetime
    agent_data["created_at"] = datetime.fromisoformat(
        session_agent.created_at.replace("Z", "+00:00")
    )
    agent_data["updated_at"] = datetime.fromisoformat(
        session_agent.updated_at.replace("Z", "+00:00")
    )

    agent_doc = {
        "agent_data": agent_data,
        "messages": [],
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }

    self.collection.update_one(
        {"_id": session_id},
        {
            "$set": {
                f"agents.{session_agent.agent_id}": agent_doc,
                "updated_at": datetime.now(UTC),
            }
        },
    )
```

**Location**: `/workspace/src/mongodb_session_manager/mongodb_session_repository.py` (lines 246-288)

## Message Array

### Message Object Structure

```json
{
    "message_id": 2,
    "role": "assistant",
    "content": "Hello! How can I help you today?",
    "created_at": ISODate("2024-01-15T09:00:02.456Z"),
    "updated_at": ISODate("2024-01-15T09:00:02.456Z"),
    "event_loop_metrics": {
        "accumulated_metrics": {
            "latencyMs": 245
        },
        "accumulated_usage": {
            "inputTokens": 28,
            "outputTokens": 24,
            "totalTokens": 52
        }
    }
}
```

### Field Definitions

#### message_id
```json
{
    "message_id": 2
}
```

**Type**: Integer
**Purpose**: Unique identifier within the agent's message array
**Generation**: Auto-incrementing (managed by application, not MongoDB)
**Uniqueness**: Unique per agent (not globally unique)

**Why Not MongoDB ObjectId?**
- Sequential numbering is more user-friendly
- Easier to reference in UI ("message 5")
- Simpler ordering logic

#### role
```json
{
    "role": "assistant"
}
```

**Type**: String
**Values**:
- `"user"`: Message from the user
- `"assistant"`: Message from the AI agent
- `"system"`: System messages (rare)

**Purpose**: Distinguish message author for conversation rendering

#### content
```json
{
    "content": "Hello! How can I help you today?"
}
```

**Type**: String or Array (Strands SDK supports both)
**Purpose**: Actual message text

**String Format** (most common):
```json
{
    "content": "This is a simple text message"
}
```

**Array Format** (for multi-modal content):
```json
{
    "content": [
        {
            "type": "text",
            "text": "Here's an image:"
        },
        {
            "type": "image",
            "source": {
                "type": "base64",
                "data": "iVBORw0KGgoAAAANS..."
            }
        }
    ]
}
```

#### Message Timestamps
```json
{
    "created_at": ISODate("2024-01-15T09:00:02.456Z"),
    "updated_at": ISODate("2024-01-15T09:00:02.456Z")
}
```

**Type**: ISODate
**Purpose**:
- `created_at`: When message was first created (immutable)
- `updated_at`: Last modification (e.g., for redaction)

**Update Behavior**: `created_at` preserved during updates, `updated_at` refreshed

#### event_loop_metrics (Optional)
```json
{
    "event_loop_metrics": {
        "accumulated_metrics": {
            "latencyMs": 245
        },
        "accumulated_usage": {
            "inputTokens": 28,
            "outputTokens": 24,
            "totalTokens": 52
        }
    }
}
```

**Type**: Object (optional)
**Present on**: Assistant messages only (after `sync_agent()`)
**Purpose**: Performance and usage metrics from agent execution

**Subfields**:
- `accumulated_metrics.latencyMs`: Response time in milliseconds
- `accumulated_usage.inputTokens`: Tokens in the prompt
- `accumulated_usage.outputTokens`: Tokens in the response
- `accumulated_usage.totalTokens`: Sum of input and output

**When Added**: During `sync_agent()` call, if `latencyMs > 0`

**Note**: This field is filtered out when returning `SessionMessage` objects (SDK doesn't support it):

```python
# In repository read methods
metrics_fields = ["event_loop_metrics"]
filtered_msg_data = {
    k: v for k, v in msg_data.items() if k not in metrics_fields
}
return SessionMessage(**filtered_msg_data)
```

### Message Operations

#### Create Message
```python
def create_message(self, session_id, agent_id, session_message, **kwargs):
    message_data = session_message.__dict__
    message_data["created_at"] = datetime.now(UTC)
    message_data["updated_at"] = datetime.now(UTC)

    self.collection.update_one(
        {"_id": session_id},
        {
            "$push": {f"agents.{agent_id}.messages": message_data},
            "$set": {
                f"agents.{agent_id}.updated_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            },
        },
    )
```

**Operation**: `$push` appends to array
**Side Effects**: Updates agent and session timestamps
**Atomicity**: Single atomic operation

#### Update Message (Redaction)
```python
def update_message(self, session_id, agent_id, session_message, **kwargs):
    # Find message index in array
    messages = # ... fetch messages ...
    for i, msg in enumerate(messages):
        if msg.get("message_id") == session_message.message_id:
            message_index = i
            # Preserve created_at
            message_data["created_at"] = msg.get("created_at")
            message_data["updated_at"] = datetime.now(UTC)
            break

    # Update specific message
    self.collection.update_one(
        {"_id": session_id},
        {
            "$set": {
                f"agents.{agent_id}.messages.{message_index}": message_data,
                f"agents.{agent_id}.updated_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        },
    )
```

**Operation**: `$set` with array index
**Timestamp Preservation**: `created_at` preserved, `updated_at` refreshed

#### List Messages
```python
def list_messages(self, session_id, agent_id, limit=None, offset=0, **kwargs):
    doc = self.collection.find_one(
        {"_id": session_id},
        {f"agents.{agent_id}.messages": 1}
    )

    messages = doc["agents"][agent_id].get("messages", [])

    # Sort by created_at
    messages.sort(key=lambda x: x.get("created_at", ""), reverse=False)

    # Pagination
    if limit:
        messages = messages[offset:offset + limit]
    else:
        messages = messages[offset:]

    # Convert to SessionMessage (filter metrics)
    result = []
    for msg_data in messages:
        filtered = {k: v for k, v in msg_data.items()
                   if k not in ["event_loop_metrics"]}
        result.append(SessionMessage(**filtered))

    return result
```

**Projection**: Only fetch messages array
**Sorting**: Client-side sort by `created_at`
**Pagination**: Client-side slicing
**Filtering**: Remove `event_loop_metrics` before creating SDK object

## Metadata Object

### Structure

```json
{
    "metadata": {
        "user_id": "alice-123",
        "user_name": "Alice Johnson",
        "department": "sales",
        "priority": "high",
        "assigned_to": "agent-456",
        "tags": ["new_customer", "enterprise"],
        "custom_data": {
            "company": "ACME Corp",
            "tier": "premium",
            "contract_value": 50000
        },
        "timestamps": {
            "first_contact": "2024-01-15T09:00:00Z",
            "last_interaction": "2024-01-22T14:30:00Z"
        }
    }
}
```

**Type**: Object (flexible schema)
**Purpose**: Store user-defined session data
**Default**: Empty object `{}`
**Flexibility**: No enforced schema, can store any JSON-serializable data

### Common Patterns

#### User Information
```json
{
    "user_id": "alice-123",
    "user_name": "Alice Johnson",
    "user_email": "alice@example.com",
    "user_role": "customer"
}
```

#### Session Classification
```json
{
    "priority": "high",
    "department": "sales",
    "category": "billing_inquiry",
    "tags": ["urgent", "enterprise"]
}
```

#### Workflow State
```json
{
    "status": "in_progress",
    "assigned_to": "agent-456",
    "workflow_step": "verification",
    "requires_manager_approval": true
}
```

#### Nested Objects
```json
{
    "customer_data": {
        "company": "ACME Corp",
        "tier": "premium",
        "account_manager": "john@company.com"
    },
    "technical_details": {
        "browser": "Chrome 120",
        "device": "Desktop",
        "ip_address": "192.168.1.1"
    }
}
```

### Update Operations

#### Partial Update (Preserves Existing Fields)
```python
# Current state
{"user_id": "alice", "priority": "low"}

# Update
session_manager.update_metadata({"priority": "high", "status": "active"})

# Result
{"user_id": "alice", "priority": "high", "status": "active"}
```

**MongoDB Operation**:
```javascript
db.sessions.updateOne(
    {"_id": "session-123"},
    {
        "$set": {
            "metadata.priority": "high",
            "metadata.status": "active"
        }
    }
)
```

**Implementation**:
```python
def update_metadata(self, session_id, metadata):
    set_operations = {
        f"metadata.{key}": value
        for key, value in metadata.items()
    }
    self.collection.update_one(
        {"_id": session_id},
        {"$set": set_operations}
    )
```

#### Field Deletion
```python
# Delete sensitive fields
session_manager.delete_metadata(["user_email", "ip_address"])
```

**MongoDB Operation**:
```javascript
db.sessions.updateOne(
    {"_id": "session-123"},
    {
        "$unset": {
            "metadata.user_email": "",
            "metadata.ip_address": ""
        }
    }
)
```

**Implementation**:
```python
def delete_metadata(self, session_id, metadata_keys):
    unset_operations = {
        f"metadata.{key}": ""
        for key in metadata_keys
    }
    self.collection.update_one(
        {"_id": session_id},
        {"$unset": unset_operations}
    )
```

### Indexed Fields

Optionally, specific metadata fields can be indexed:

```python
repository = MongoDBSessionRepository(
    connection_string="mongodb://...",
    metadata_fields=["priority", "department", "status"]
)
```

**Result**: Indexes created on:
- `metadata.priority`
- `metadata.department`
- `metadata.status`

**Use Case**: Fast queries on frequently filtered metadata fields

**Code Reference**: `/workspace/src/mongodb_session_manager/mongodb_session_repository.py` (lines 189-192)

## Feedbacks Array

### Structure

```json
{
    "feedbacks": [
        {
            "rating": "up",
            "comment": "Very helpful response!",
            "created_at": ISODate("2024-01-22T14:30:00.000Z")
        },
        {
            "rating": "down",
            "comment": "Response was incomplete",
            "created_at": ISODate("2024-01-22T16:45:00.000Z")
        },
        {
            "rating": null,
            "comment": "Just testing",
            "created_at": ISODate("2024-01-22T17:00:00.000Z")
        }
    ]
}
```

**Type**: Array of feedback objects
**Purpose**: Store user feedback on session quality
**Default**: Empty array `[]`

### Feedback Object Fields

#### rating
```json
{
    "rating": "up"
}
```

**Type**: String or null
**Values**:
- `"up"`: Positive feedback (thumbs up)
- `"down"`: Negative feedback (thumbs down)
- `null`: Neutral or no rating

**Purpose**: Quick sentiment indicator

#### comment
```json
{
    "comment": "Very helpful response!"
}
```

**Type**: String
**Purpose**: Detailed feedback text
**Optional**: Can be empty string

#### created_at
```json
{
    "created_at": ISODate("2024-01-22T14:30:00.000Z")
}
```

**Type**: ISODate
**Purpose**: When feedback was submitted
**Auto-generated**: Set by repository on creation

### Operations

#### Add Feedback
```python
def add_feedback(self, session_id, feedback):
    feedback_doc = {
        **feedback,
        "created_at": datetime.now(UTC)
    }

    self.collection.update_one(
        {"_id": session_id},
        {
            "$push": {"feedbacks": feedback_doc},
            "$set": {"updated_at": datetime.now(UTC)}
        }
    )
```

**Operation**: `$push` appends to feedbacks array
**Timestamp**: Automatically added
**Side Effect**: Updates session `updated_at`

#### Get Feedbacks
```python
def get_feedbacks(self, session_id):
    doc = self.collection.find_one(
        {"_id": session_id},
        {"feedbacks": 1}
    )
    return doc.get("feedbacks", [])
```

**Projection**: Only fetch feedbacks array
**Return**: List of feedback objects (may be empty)

### Use Cases

#### Quality Monitoring
```python
# Count positive vs negative feedback
feedbacks = session_manager.get_feedbacks()
positive = sum(1 for f in feedbacks if f["rating"] == "up")
negative = sum(1 for f in feedbacks if f["rating"] == "down")
```

#### Alert on Negative Feedback
```python
# In feedback hook
if feedback["rating"] == "down":
    send_alert_to_team(session_id, feedback["comment"])
```

#### Analytics
```javascript
// MongoDB aggregation
db.sessions.aggregate([
    {"$unwind": "$feedbacks"},
    {"$group": {
        "_id": "$feedbacks.rating",
        "count": {"$sum": 1}
    }}
])
```

## Index Strategy

### Automatic Indexes

Created by `_ensure_indexes()` method on repository initialization:

```python
def _ensure_indexes(self):
    # Session timestamps
    self.collection.create_index("created_at")
    self.collection.create_index("updated_at")

    # Metadata fields (if specified)
    if self.metadata_fields:
        for field in self.metadata_fields:
            self.collection.create_index("metadata." + field)
```

**Location**: `/workspace/src/mongodb_session_manager/mongodb_session_repository.py` (lines 181-195)

### Index Types

#### Primary Key Index
```javascript
{
    "_id": 1  // Automatic, unique, clustered
}
```

**Purpose**: Fast session lookup by ID
**Type**: Unique, ascending
**Created**: Automatically by MongoDB
**Performance**: O(log n) lookup

#### Timestamp Indexes
```javascript
{
    "created_at": 1
}
{
    "updated_at": 1
}
```

**Purpose**:
- Time-range queries
- Recent session queries
- TTL implementation (future)

**Type**: Ascending
**Use Cases**:
```javascript
// Find sessions created today
db.sessions.find({
    "created_at": {
        "$gte": ISODate("2024-01-22T00:00:00Z"),
        "$lt": ISODate("2024-01-23T00:00:00Z")
    }
})

// Find recently updated sessions
db.sessions.find({
    "updated_at": {"$gte": ISODate("2024-01-22T00:00:00Z")}
}).sort({"updated_at": -1})
```

#### Metadata Indexes
```javascript
{
    "metadata.priority": 1
}
{
    "metadata.department": 1
}
```

**Purpose**: Fast queries on frequently filtered metadata
**Configuration**: Specified in repository initialization
**Use Cases**:
```javascript
// Find high-priority sessions
db.sessions.find({"metadata.priority": "high"})

// Find sessions by department
db.sessions.find({"metadata.department": "sales"})

// Compound query
db.sessions.find({
    "metadata.priority": "high",
    "metadata.department": "sales"
})
```

### Index Performance

| Query Type | Index Used | Performance |
|-----------|------------|-------------|
| By session_id | _id (primary) | O(1) |
| By created_at range | created_at | O(log n) + scan |
| By updated_at | updated_at | O(log n) + scan |
| By metadata.priority | metadata.priority | O(log n) + scan |
| By agent messages | None (document scan) | O(n) |

### Index Considerations

**When to Add Metadata Indexes**:
- Field is frequently queried
- Field has moderate cardinality (not too unique, not too common)
- Query performance is critical

**When NOT to Index**:
- Field is rarely queried
- Field has very high cardinality (e.g., timestamps)
- Field changes frequently (index maintenance cost)
- Collection is small (< 10,000 documents)

**Future Indexes** (not currently implemented):
```javascript
// Compound index for common queries
{"metadata.department": 1, "metadata.priority": 1, "updated_at": -1}

// Text search on messages
{"agents.$**.messages.content": "text"}

// TTL index for automatic expiration
{"created_at": 1, expireAfterSeconds: 2592000}  // 30 days
```

## Field Types and Constraints

### Type Mapping

| Field | Python Type | BSON Type | MongoDB Type |
|-------|------------|-----------|--------------|
| _id | str | string | string |
| session_id | str | string | string |
| session_type | str | string | string |
| created_at | datetime | date | ISODate |
| updated_at | datetime | date | ISODate |
| metadata | dict | document | object |
| feedbacks | list | array | array |
| agents | dict | document | object |
| message_id | int | int32 | int32 |
| role | str | string | string |
| content | str or list | string or array | string or array |
| event_loop_metrics | dict | document | object |

### Constraints

#### Document Size
**Maximum**: 16 MB (MongoDB limit)
**Typical**: 10-500 KB per session
**Calculation**:
```
Session overhead: ~500 bytes
Agent overhead: ~1 KB per agent
Message: ~500 bytes average
Metrics: ~200 bytes per message
```

**Example**:
```
Session with:
- 2 agents
- 100 messages per agent (200 total)
- Metadata: 1 KB

Estimated size:
= 500 + (2 × 1000) + (200 × 500) + (200 × 200) + 1000
= 500 + 2000 + 100000 + 40000 + 1000
= 143.5 KB
```

**16 MB Limit Reached**:
- ~32,000 messages at 500 bytes each
- Most conversations won't reach this

**Mitigation**:
- Implement message archiving for very long sessions
- Monitor document sizes
- Consider breaking very long sessions into multiple documents

#### Field Length Constraints

| Field | Recommended Max | Reason |
|-------|----------------|---------|
| session_id | 255 characters | Index efficiency |
| session_type | 50 characters | Enum-like field |
| message content | 100 KB | Practical limit for single message |
| metadata (total) | 1 MB | Keep metadata focused |
| feedback comment | 10 KB | Reasonable comment length |

#### Data Validation

Not enforced at database level, but recommended at application level:

```python
# Session ID validation
assert len(session_id) <= 255
assert session_id.isascii()

# Rating validation
assert rating in ["up", "down", None]

# Role validation
assert role in ["user", "assistant", "system"]
```

## Schema Evolution

### Version 1 (Current)

```json
{
    "_id": "session-123",
    "session_id": "session-123",
    "session_type": "default",
    "created_at": ISODate(),
    "updated_at": ISODate(),
    "metadata": {},
    "feedbacks": [],
    "agents": {}
}
```

### Adding New Fields (Backward Compatible)

**Scenario**: Add `language` field to sessions

**Migration**: Not required! Just start using it.

```python
# New sessions
session_doc = {
    # ... existing fields ...
    "language": "en"  # New field
}

# Existing sessions
# Will have language: undefined (fine in MongoDB)
```

**Handling Undefined**:
```python
language = session.get("language", "en")  # Default to "en"
```

### Renaming Fields (Requires Migration)

**Scenario**: Rename `session_type` to `type`

**Migration Script**:
```javascript
db.sessions.updateMany(
    {},
    {
        "$rename": {"session_type": "type"}
    }
)
```

### Changing Field Types (Complex)

**Scenario**: Change `message_id` from int to string

**Approach**:
1. Add new field alongside old
2. Populate new field
3. Update code to use new field
4. Remove old field (later)

```javascript
// Step 1 & 2: Add new field
db.sessions.find().forEach(function(session) {
    for (let agentId in session.agents) {
        let messages = session.agents[agentId].messages;
        for (let i = 0; i < messages.length; i++) {
            messages[i].message_id_str = String(messages[i].message_id);
        }
    }
    db.sessions.save(session);
});

// Step 3: Update code to use message_id_str

// Step 4: Remove old field (later)
// db.sessions.updateMany({}, {"$unset": {"agents.$[].messages.$[].message_id": ""}})
```

### Schema Versioning

**Recommended** approach for production:

```json
{
    "_id": "session-123",
    "schema_version": 1,  // Add version field
    // ... rest of document
}
```

**Migration Logic**:
```python
def migrate_session(session):
    version = session.get("schema_version", 1)

    if version == 1:
        # Migrate v1 to v2
        session = migrate_v1_to_v2(session)
        version = 2

    if version == 2:
        # Migrate v2 to v3
        session = migrate_v2_to_v3(session)
        version = 3

    session["schema_version"] = version
    return session
```

## Query Patterns

### Common Queries

#### 1. Get Session by ID
```javascript
db.sessions.findOne({"_id": "session-123"})
```

**Performance**: O(1) - primary key lookup
**Index**: _id (automatic)

#### 2. Get Recent Sessions
```javascript
db.sessions.find({
    "updated_at": {"$gte": ISODate("2024-01-22T00:00:00Z")}
}).sort({"updated_at": -1}).limit(10)
```

**Performance**: O(log n) + limit
**Index**: updated_at

#### 3. Get Sessions by Metadata
```javascript
db.sessions.find({
    "metadata.priority": "high",
    "metadata.department": "sales"
})
```

**Performance**: O(log n) per indexed field
**Index**: metadata.priority, metadata.department

#### 4. Count Messages in Session
```javascript
db.sessions.aggregate([
    {"$match": {"_id": "session-123"}},
    {"$project": {
        "message_count": {
            "$sum": {
                "$map": {
                    "input": {"$objectToArray": "$agents"},
                    "as": "agent",
                    "in": {"$size": "$$agent.v.messages"}
                }
            }
        }
    }}
])
```

#### 5. Get Sessions with Negative Feedback
```javascript
db.sessions.find({
    "feedbacks": {
        "$elemMatch": {"rating": "down"}
    }
})
```

**Performance**: O(n) - array scan
**Consideration**: No index on array elements currently

#### 6. Get Agent's Last Message
```javascript
db.sessions.findOne(
    {"_id": "session-123"},
    {
        "agents.support-agent.messages": {"$slice": -1}
    }
)
```

**Performance**: O(1) document fetch + O(1) slice
**Note**: Projection with $slice is efficient

#### 7. Time Range with Metadata Filter
```javascript
db.sessions.find({
    "created_at": {
        "$gte": ISODate("2024-01-01T00:00:00Z"),
        "$lt": ISODate("2024-02-01T00:00:00Z")
    },
    "metadata.department": "sales"
})
```

**Indexes Used**: created_at, metadata.department

### Aggregation Patterns

#### 1. Average Messages per Session
```javascript
db.sessions.aggregate([
    {"$project": {
        "message_count": {
            "$sum": {
                "$map": {
                    "input": {"$objectToArray": "$agents"},
                    "in": {"$size": "$$agent.v.messages"}
                }
            }
        }
    }},
    {"$group": {
        "_id": null,
        "avg_messages": {"$avg": "$message_count"}
    }}
])
```

#### 2. Sessions by Department
```javascript
db.sessions.aggregate([
    {"$group": {
        "_id": "$metadata.department",
        "count": {"$sum": 1}
    }},
    {"$sort": {"count": -1}}
])
```

#### 3. Feedback Summary
```javascript
db.sessions.aggregate([
    {"$unwind": "$feedbacks"},
    {"$group": {
        "_id": "$feedbacks.rating",
        "count": {"$sum": 1},
        "sample_comments": {"$push": "$feedbacks.comment"}
    }}
])
```

#### 4. Token Usage per Session
```javascript
db.sessions.aggregate([
    {"$unwind": {"path": "$agents", "preserveNullAndEmptyArrays": false}},
    {"$unwind": "$agents.messages"},
    {"$match": {"agents.messages.event_loop_metrics": {"$exists": true}}},
    {"$group": {
        "_id": "$_id",
        "total_tokens": {
            "$sum": "$agents.messages.event_loop_metrics.accumulated_usage.totalTokens"
        },
        "total_latency": {
            "$sum": "$agents.messages.event_loop_metrics.accumulated_metrics.latencyMs"
        }
    }}
])
```

### Performance Optimization Tips

1. **Use Projection**: Fetch only needed fields
   ```javascript
   db.sessions.findOne({"_id": "session-123"}, {"metadata": 1})
   ```

2. **Limit Results**: Always use `.limit()` for lists
   ```javascript
   db.sessions.find().sort({"updated_at": -1}).limit(100)
   ```

3. **Index Covered Queries**: Query only indexed fields
   ```javascript
   // Covered by index (no document fetch needed)
   db.sessions.find(
       {"metadata.priority": "high"},
       {"metadata.priority": 1, "_id": 1}
   )
   ```

4. **Avoid $where and $regex**: Use indexed fields instead
   ```javascript
   // Bad
   db.sessions.find({"$where": "this.metadata.priority == 'high'"})

   // Good
   db.sessions.find({"metadata.priority": "high"})
   ```

5. **Use Aggregation for Complex Queries**: More efficient than multiple queries

---

## Summary

The MongoDB Session Manager data model is designed for:

1. **Performance**: Single-document reads, indexed queries
2. **Flexibility**: Schema-less metadata, nested structures
3. **Atomicity**: Document-level operations are atomic
4. **Scalability**: Horizontal sharding by session_id
5. **Analytics**: Rich aggregation capabilities

The embedded document approach optimizes for the primary access pattern (fetch entire session) while maintaining flexibility for future schema evolution and complex queries.
