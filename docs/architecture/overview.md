# Architecture Overview

## Table of Contents
- [Introduction](#introduction)
- [System Architecture](#system-architecture)
- [Component Overview](#component-overview)
- [Data Flow](#data-flow)
- [Integration Points](#integration-points)
- [Deployment Architecture](#deployment-architecture)
- [Scalability Considerations](#scalability-considerations)

## Introduction

The MongoDB Session Manager is a production-ready library designed to provide persistent storage for Strands Agent conversations with a focus on performance, scalability, and reliability. The architecture follows a layered approach with clear separation of concerns, utilizing established design patterns (Singleton, Factory, Repository) to optimize connection management and resource utilization in stateless environments.

### Key Architectural Goals

1. **Performance**: Minimize connection overhead through pooling and reuse
2. **Scalability**: Support high-concurrency stateless environments (FastAPI, Lambda)
3. **Reliability**: Thread-safe operations with comprehensive error handling
4. **Flexibility**: Support both owned and borrowed MongoDB clients
5. **Extensibility**: Hook system for custom behavior injection
6. **Persistence**: Complete session data in single MongoDB documents

## System Architecture

### High-Level Architecture Diagram

```mermaid
graph TB
    subgraph "Application Layer"
        APP[FastAPI/Application]
        AGENT[Strands Agent]
    end

    subgraph "Session Management Layer"
        FACTORY[MongoDBSessionManagerFactory<br/>Singleton Factory Pattern]
        MANAGER[MongoDBSessionManager<br/>Session Orchestration]
        HOOKS[Hook System<br/>Metadata/Feedback Hooks]
    end

    subgraph "Data Access Layer"
        REPO[MongoDBSessionRepository<br/>Data Operations]
        POOL[MongoDBConnectionPool<br/>Singleton Connection Pool]
    end

    subgraph "External Services"
        MONGO[(MongoDB<br/>Document Store)]
        SNS[AWS SNS<br/>Feedback Notifications]
        SQS[AWS SQS<br/>Metadata Events]
    end

    APP --> FACTORY
    FACTORY --> MANAGER
    APP --> AGENT
    AGENT --> MANAGER
    MANAGER --> HOOKS
    MANAGER --> REPO
    HOOKS -.->|Optional| SNS
    HOOKS -.->|Optional| SQS
    REPO --> POOL
    POOL --> MONGO

    style FACTORY fill:#e1f5ff
    style POOL fill:#e1f5ff
    style HOOKS fill:#fff3e0
    style SNS fill:#f3e5f5
    style SQS fill:#f3e5f5
```

### Layer Responsibilities

#### Application Layer
- **FastAPI/Application**: HTTP request handling, API endpoints, application lifecycle
- **Strands Agent**: AI agent orchestration, conversation management, tool execution

#### Session Management Layer
- **Factory**: Creates session managers with shared connection pool
- **Manager**: High-level session operations, metric capture, state synchronization
- **Hooks**: Intercepts operations for custom behavior (audit, validation, notifications)

#### Data Access Layer
- **Repository**: Low-level MongoDB CRUD operations, schema management
- **Connection Pool**: Thread-safe MongoDB client reuse, connection lifecycle

#### External Services
- **MongoDB**: Primary data store for sessions, agents, messages, metadata
- **AWS SNS**: Optional real-time feedback notifications
- **AWS SQS**: Optional metadata change propagation for SSE

## Component Overview

### 1. MongoDBSessionManager

**Location**: `/workspace/src/mongodb_session_manager/mongodb_session_manager.py`

**Purpose**: High-level session management interface that integrates with Strands SDK.

**Key Responsibilities**:
- Session lifecycle management (create, initialize, close)
- Message management (append, redact)
- Agent synchronization with automatic metric capture
- Metadata management (update, get, delete with partial updates)
- Feedback collection and retrieval
- Hook application (metadata and feedback hooks)
- Metadata tool provision for agent integration

**Design Pattern**: Facade + Template Method
- Extends `RepositorySessionManager` from Strands SDK
- Delegates data operations to repository
- Applies Template Method pattern for hook integration

**Key Methods**:
```python
# Session lifecycle
__init__(session_id, connection_string, client, metadata_hook, feedback_hook, **kwargs)
initialize(agent, **kwargs)
close()

# Message operations
append_message(message, agent)
redact_latest_message(redact_message, agent, **kwargs)

# Synchronization (captures metrics from agent.event_loop_metrics)
sync_agent(agent, **kwargs)

# Metadata operations (with hook support)
update_metadata(metadata: Dict[str, Any])
get_metadata() -> Dict[str, Any]
delete_metadata(metadata_keys: List[str])
get_metadata_tool() -> Tool

# Feedback operations (with hook support)
add_feedback(feedback: Dict[str, Any])
get_feedbacks() -> List[Dict[str, Any]]
```

**Connection Management**:
- Accepts either `connection_string` (creates own client) or `client` (uses provided)
- Tracks ownership with `_owns_client` flag for proper cleanup
- Passes MongoDB-specific kwargs to repository

### 2. MongoDBSessionRepository

**Location**: `/workspace/src/mongodb_session_manager/mongodb_session_repository.py`

**Purpose**: Low-level MongoDB operations implementing Strands SDK's SessionRepository interface.

**Key Responsibilities**:
- MongoDB document CRUD operations
- Index creation and management
- Timestamp handling and preservation
- Event loop metrics filtering (excluded from SessionMessage objects)
- Smart connection lifecycle (owned vs borrowed)

**Design Pattern**: Repository Pattern
- Implements `SessionRepository` interface
- Encapsulates all MongoDB-specific logic
- Provides clean abstraction over document storage

**Document Structure**:
```python
{
    "_id": "session-id",                    # Primary key (same as session_id)
    "session_id": "session-id",             # Session identifier
    "session_type": "default",              # Session type
    "created_at": ISODate(),                # Session creation timestamp
    "updated_at": ISODate(),                # Last update timestamp
    "metadata": {},                         # User-defined metadata
    "feedbacks": [],                        # Feedback array
    "agents": {                             # Nested agent documents
        "agent-id": {
            "agent_data": {...},            # Agent state and configuration
            "created_at": ISODate(),        # Agent creation timestamp
            "updated_at": ISODate(),        # Agent update timestamp
            "messages": [...]               # Message array
        }
    }
}
```

**Key Methods**:
```python
# Session operations
create_session(session, **kwargs) -> Session
read_session(session_id, **kwargs) -> Optional[Session]

# Agent operations
create_agent(session_id, session_agent, **kwargs)
read_agent(session_id, agent_id, **kwargs) -> Optional[SessionAgent]
update_agent(session_id, session_agent, **kwargs)

# Message operations
create_message(session_id, agent_id, session_message, **kwargs)
read_message(session_id, agent_id, message_id, **kwargs) -> Optional[SessionMessage]
update_message(session_id, agent_id, session_message, **kwargs)
list_messages(session_id, agent_id, limit, offset, **kwargs) -> List[SessionMessage]

# Metadata operations (custom methods)
update_metadata(session_id, metadata)      # Uses $set with dot notation
get_metadata(session_id) -> Dict[str, Any]
delete_metadata(session_id, metadata_keys) # Uses $unset

# Feedback operations (custom methods)
add_feedback(session_id, feedback)
get_feedbacks(session_id) -> List[Dict[str, Any]]

# Lifecycle
close()
```

**Index Strategy**:
```python
# Automatically created indexes:
- "created_at"              # For session creation time queries
- "updated_at"              # For recent session queries
- "metadata.{field}"        # For each metadata_field specified
```

### 3. MongoDBConnectionPool

**Location**: `/workspace/src/mongodb_session_manager/mongodb_connection_pool.py`

**Purpose**: Singleton connection pool for MongoDB client reuse across the application.

**Key Responsibilities**:
- Singleton pattern implementation (thread-safe)
- MongoDB client creation with optimized defaults
- Connection lifecycle management
- Pool statistics and monitoring
- Connection validation (ping test)

**Design Pattern**: Singleton + Double-Checked Locking
```python
class MongoDBConnectionPool:
    _instance: Optional[MongoDBConnectionPool] = None
    _lock: Lock = Lock()
    _client: Optional[MongoClient] = None

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
```

**Default Configuration**:
```python
{
    "maxPoolSize": 100,              # Maximum connections in pool
    "minPoolSize": 10,               # Minimum connections to maintain
    "maxIdleTimeMS": 30000,          # Close idle connections after 30s
    "waitQueueTimeoutMS": 5000,      # Timeout waiting for connection
    "serverSelectionTimeoutMS": 5000, # Server selection timeout
    "connectTimeoutMS": 10000,       # Initial connection timeout
    "socketTimeoutMS": 30000,        # Socket operation timeout
    "retryWrites": True,             # Automatic retry for writes
    "retryReads": True               # Automatic retry for reads
}
```

**Key Methods**:
```python
# Pool management
initialize(connection_string, **kwargs) -> MongoClient
get_client() -> Optional[MongoClient]
close()

# Monitoring
get_pool_stats() -> Dict[str, Any]
```

**Thread Safety**:
- Uses Python threading.Lock for synchronization
- Double-checked locking pattern prevents race conditions
- MongoClient itself is thread-safe per PyMongo documentation

### 4. MongoDBSessionManagerFactory

**Location**: `/workspace/src/mongodb_session_manager/mongodb_session_factory.py`

**Purpose**: Factory for creating session managers with shared connection pool.

**Key Responsibilities**:
- Initialize shared connection pool at application startup
- Create session managers that reuse connections
- Manage factory lifecycle (startup/shutdown)
- Track global factory instance for FastAPI integration
- Provide connection statistics

**Design Pattern**: Factory + Global Singleton (for FastAPI)
```python
# Global factory instance
_global_factory: Optional[MongoDBSessionManagerFactory] = None

# Helper functions for global access
def initialize_global_factory(...) -> MongoDBSessionManagerFactory
def get_global_factory() -> MongoDBSessionManagerFactory
def close_global_factory() -> None
```

**Key Methods**:
```python
# Factory lifecycle
__init__(connection_string, database_name, collection_name, client, **kwargs)
close()

# Session manager creation
create_session_manager(
    session_id,
    database_name=None,      # Optional override
    collection_name=None,    # Optional override
    metadata_fields=None,    # Optional override
    **kwargs                 # Including hooks
) -> MongoDBSessionManager

# Monitoring
get_connection_stats() -> Dict[str, Any]
```

**Usage Patterns**:
```python
# Pattern 1: Global factory (recommended for FastAPI)
factory = initialize_global_factory(
    connection_string="mongodb://...",
    maxPoolSize=100
)
manager = get_global_factory().create_session_manager("session-123")

# Pattern 2: Local factory
factory = MongoDBSessionManagerFactory(
    connection_string="mongodb://...",
    database_name="mydb"
)
manager = factory.create_session_manager("session-123")
```

### 5. Hook System

**Location**: `/workspace/src/mongodb_session_manager/hooks/`

**Purpose**: Extensibility layer for intercepting and enhancing operations.

**Components**:

#### Metadata Hooks
- Intercept metadata operations (update, get, delete)
- Use cases: audit, validation, caching, synchronization
- Applied via `_apply_metadata_hook()` method decorator pattern

**Hook Signature**:
```python
def metadata_hook(
    original_func: Callable,
    action: str,              # "update", "get", or "delete"
    session_id: str,
    **kwargs                  # metadata for update, keys for delete
):
    # Custom logic before
    if action == "update":
        result = original_func(kwargs["metadata"])
    elif action == "delete":
        result = original_func(kwargs["keys"])
    else:  # get
        result = original_func()
    # Custom logic after
    return result
```

#### Feedback Hooks
- Intercept feedback add operations
- Use cases: audit, validation, notifications, analytics
- Applied via `_apply_feedback_hook()` method decorator pattern

**Hook Signature**:
```python
def feedback_hook(
    original_func: Callable,
    action: str,              # "add"
    session_id: str,
    **kwargs                  # feedback object
):
    # Custom logic before
    result = original_func(kwargs["feedback"])
    # Custom logic after (e.g., send notification)
    return result
```

#### AWS Integration Hooks

**FeedbackSNSHook** (`feedback_sns_hook.py`):
- Sends feedback to different SNS topics based on rating
- Routing: "up" → topic_arn_good, "down" → topic_arn_bad, None → topic_arn_neutral
- Async operation with thread-safe execution
- Graceful degradation if SNS fails

**MetadataSQSHook** (`metadata_sqs_hook.py`):
- Propagates metadata changes to SQS queue
- Selective field propagation to minimize message size
- Supports SSE back-propagation use case
- Async operation with thread-safe execution

## Data Flow

### 1. Request Lifecycle in FastAPI

```mermaid
sequenceDiagram
    participant Client
    participant FastAPI
    participant Factory
    participant Manager
    participant Repository
    participant Pool
    participant MongoDB

    Client->>FastAPI: POST /chat
    FastAPI->>Factory: create_session_manager(session_id)
    Factory->>Pool: get_client()
    Pool-->>Factory: MongoClient (reused)
    Factory->>Manager: new MongoDBSessionManager(client=...)
    Manager->>Repository: new MongoDBSessionRepository(client=...)
    Repository-->>Manager: Repository instance
    Manager-->>Factory: Manager instance
    Factory-->>FastAPI: Manager instance

    FastAPI->>Manager: append_message(user_message, agent)
    Manager->>Repository: create_message(...)
    Repository->>MongoDB: insert message
    MongoDB-->>Repository: success

    FastAPI->>Manager: sync_agent(agent)
    Manager->>Manager: Extract event_loop_metrics
    Manager->>Repository: Update last message with metrics
    Repository->>MongoDB: update with $set
    MongoDB-->>Repository: success

    FastAPI-->>Client: Response
```

### 2. Message Creation and Metric Capture

```mermaid
flowchart TD
    A[User Message Received] --> B[manager.append_message]
    B --> C[repository.create_message]
    C --> D[MongoDB: $push to messages array]

    D --> E[Agent Processes Message]
    E --> F[Agent Populates event_loop_metrics]

    F --> G[manager.sync_agent]
    G --> H{latencyMs > 0?}

    H -->|No| I[Skip Metrics Update]
    H -->|Yes| J[Fetch Last Message]

    J --> K[Extract Metrics from agent.event_loop_metrics]
    K --> L[Build $set Operation]
    L --> M[Update Last Message with Metrics]
    M --> N[MongoDB: $set event_loop_metrics]

    style D fill:#c8e6c9
    style N fill:#c8e6c9
    style F fill:#fff9c4
```

### 3. Metadata Update with Hooks

```mermaid
sequenceDiagram
    participant App
    participant Manager
    participant Hook
    participant Original
    participant Repository
    participant MongoDB

    App->>Manager: update_metadata({"status": "active"})
    Manager->>Hook: Call wrapped update_metadata
    Hook->>Hook: Pre-processing (e.g., audit log)
    Hook->>Original: original_func(metadata)
    Original->>Repository: update_metadata(session_id, metadata)
    Repository->>MongoDB: $set metadata.status
    MongoDB-->>Repository: success
    Repository-->>Original: success
    Original-->>Hook: success
    Hook->>Hook: Post-processing (e.g., send to SQS)
    Hook-->>Manager: success
    Manager-->>App: success
```

### 4. Connection Pool Reuse

```mermaid
flowchart LR
    subgraph "Request 1"
        R1[FastAPI Request] --> F1[Factory]
        F1 --> P1[Pool.get_client]
        P1 --> C1[MongoClient Instance]
        C1 --> M1[Manager 1]
    end

    subgraph "Request 2"
        R2[FastAPI Request] --> F2[Factory]
        F2 --> P2[Pool.get_client]
        P2 --> C2[MongoClient Instance]
        C2 --> M2[Manager 2]
    end

    subgraph "Request 3"
        R3[FastAPI Request] --> F3[Factory]
        F3 --> P3[Pool.get_client]
        P3 --> C3[MongoClient Instance]
        C3 --> M3[Manager 3]
    end

    C1 -.->|Same Client| C2
    C2 -.->|Same Client| C3

    style C1 fill:#ffeb3b
    style C2 fill:#ffeb3b
    style C3 fill:#ffeb3b
```

### 5. Session Persistence and Resumption

```mermaid
flowchart TD
    subgraph "Day 1: Initial Session"
        A1[Create Manager<br/>session-123] --> B1[Create Agent<br/>agent-A]
        B1 --> C1[User: Hello]
        C1 --> D1[Agent: Hi there!]
        D1 --> E1[sync_agent<br/>Metrics Captured]
        E1 --> F1[MongoDB: Session Stored]
    end

    subgraph "Day 7: Resume Session"
        A2[Create Manager<br/>session-123] --> B2[Create Agent<br/>agent-A]
        B2 --> C2[initialize<br/>Load History]
        C2 --> D2[MongoDB: Retrieve Messages]
        D2 --> E2[Agent Has Context]
        E2 --> F2[User: Remember me?]
        F2 --> G2[Agent: Yes, from Day 1!]
    end

    F1 -.->|Same Session ID| A2

    style F1 fill:#c8e6c9
    style D2 fill:#c8e6c9
```

## Integration Points

### 1. Strands SDK Integration

The MongoDB Session Manager implements Strands SDK interfaces:

```python
# Extends base class
class MongoDBSessionManager(RepositorySessionManager):
    pass

# Implements interface
class MongoDBSessionRepository(SessionRepository):
    pass
```

**Integration Methods**:
- `initialize(agent)`: Called by Strands SDK to load session history
- `append_message(message, agent)`: Called after each agent interaction
- `sync_agent(agent)`: Called to persist agent state and metrics
- `redact_latest_message(redact_message, agent)`: For message redaction

**Data Type Compatibility**:
```python
from strands.types.session import Session, SessionAgent, SessionMessage

# Repository methods return/accept these types
def read_session(session_id: str) -> Optional[Session]
def create_agent(session_id: str, session_agent: SessionAgent)
def list_messages(session_id: str, agent_id: str) -> List[SessionMessage]
```

### 2. MongoDB Integration

**Connection Methods**:
```python
# Method 1: Connection string (creates own client)
manager = MongoDBSessionManager(
    session_id="session-123",
    connection_string="mongodb://user:pass@host:27017/",
    database_name="mydb"
)

# Method 2: Shared client (reuses connection)
client = MongoClient("mongodb://...")
manager = MongoDBSessionManager(
    session_id="session-123",
    client=client,
    database_name="mydb"
)
```

**Collection Structure**:
- Single collection per deployment (configurable)
- Document per session (all data embedded)
- Automatic index creation on initialization

**Supported MongoDB Versions**:
- MongoDB 4.2+
- MongoDB Atlas (all tiers)
- DocumentDB (AWS) with MongoDB 4.0+ compatibility

### 3. FastAPI Integration

**Recommended Pattern** (Global Factory):
```python
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
from mongodb_session_manager import (
    initialize_global_factory,
    get_global_factory,
    close_global_factory
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    factory = initialize_global_factory(
        connection_string="mongodb://...",
        database_name="sessions",
        maxPoolSize=100
    )
    app.state.session_factory = factory
    yield
    # Shutdown
    close_global_factory()

app = FastAPI(lifespan=lifespan)

@app.post("/chat")
async def chat(request: Request, session_id: str):
    factory = request.app.state.session_factory
    manager = factory.create_session_manager(session_id)
    # Use manager...
```

**Benefits**:
- Connection pool initialized once at startup
- Connections reused across all requests
- Automatic cleanup on shutdown
- No connection overhead per request

### 4. AWS Integration (Optional)

**SNS Integration** (Feedback Notifications):
```python
from mongodb_session_manager import create_feedback_sns_hook

feedback_hook = create_feedback_sns_hook(
    topic_arn_good="arn:aws:sns:region:account:feedback-good",
    topic_arn_bad="arn:aws:sns:region:account:feedback-bad",
    topic_arn_neutral="arn:aws:sns:region:account:feedback-neutral"
)

manager = MongoDBSessionManager(
    session_id="session-123",
    connection_string="mongodb://...",
    feedback_hook=feedback_hook
)
```

**SQS Integration** (Metadata Propagation):
```python
from mongodb_session_manager import create_metadata_sqs_hook

metadata_hook = create_metadata_sqs_hook(
    queue_url="https://sqs.region.amazonaws.com/account/queue-name",
    metadata_fields=["status", "priority", "agent_state"]
)

manager = MongoDBSessionManager(
    session_id="session-123",
    connection_string="mongodb://...",
    metadata_hook=metadata_hook
)
```

**Requirements**:
- Install `python-helpers` package for `custom_aws` module
- AWS credentials configured (environment variables, IAM role, etc.)
- Appropriate IAM permissions (sns:Publish, sqs:SendMessage)

## Deployment Architecture

### 1. Stateless FastAPI Deployment

```mermaid
graph TB
    subgraph "Load Balancer"
        LB[Application Load Balancer]
    end

    subgraph "Application Tier (Auto-scaling)"
        FAST1[FastAPI Instance 1<br/>Global Factory]
        FAST2[FastAPI Instance 2<br/>Global Factory]
        FAST3[FastAPI Instance N<br/>Global Factory]
    end

    subgraph "Data Tier"
        MONGO[(MongoDB Atlas<br/>Replica Set)]
    end

    subgraph "Optional AWS Services"
        SNS[SNS Topics<br/>Feedback Routing]
        SQS[SQS Queue<br/>Metadata Events]
    end

    LB --> FAST1
    LB --> FAST2
    LB --> FAST3

    FAST1 -->|Connection Pool| MONGO
    FAST2 -->|Connection Pool| MONGO
    FAST3 -->|Connection Pool| MONGO

    FAST1 -.->|Optional| SNS
    FAST2 -.->|Optional| SNS
    FAST3 -.->|Optional| SNS

    FAST1 -.->|Optional| SQS
    FAST2 -.->|Optional| SQS
    FAST3 -.->|Optional| SQS

    style MONGO fill:#4caf50
    style SNS fill:#f3e5f5
    style SQS fill:#f3e5f5
```

**Configuration Example**:
```python
# Each FastAPI instance
factory = initialize_global_factory(
    connection_string=os.getenv("MONGODB_URI"),
    database_name="production",
    maxPoolSize=50,        # 50 connections per instance
    minPoolSize=10
)
```

**Scaling Considerations**:
- Each instance maintains its own connection pool
- Total connections = (instances × maxPoolSize)
- MongoDB Atlas handles connection distribution
- Connection pooling prevents exhaustion under load

### 2. AWS Lambda Deployment

**Challenge**: Lambda cold starts and execution model

**Solution**: Optimize for cold start and reuse

```python
import os
from mongodb_session_manager import MongoDBSessionManagerFactory

# Global variable (reused across warm invocations)
factory = None

def lambda_handler(event, context):
    global factory

    # Initialize factory on first invocation
    if factory is None:
        factory = MongoDBSessionManagerFactory(
            connection_string=os.getenv("MONGODB_URI"),
            database_name="lambda_sessions",
            maxPoolSize=10,      # Lower pool size for Lambda
            minPoolSize=1,
            maxIdleTimeMS=60000  # Keep connections longer
        )

    # Create session manager (reuses connection if warm)
    session_id = event["session_id"]
    manager = factory.create_session_manager(session_id)

    # Process request...
    return {"statusCode": 200}
```

**Lambda Optimization**:
- Lower `maxPoolSize` (5-10) for Lambda's limited memory
- Increase `maxIdleTimeMS` to keep connections during warm periods
- Global factory variable for cross-invocation reuse
- Consider provisioned concurrency for consistent performance

### 3. Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: session-manager-api
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: fastapi
        image: session-manager-api:latest
        env:
        - name: MONGODB_URI
          valueFrom:
            secretKeyRef:
              name: mongodb-secret
              key: connection-string
        - name: POOL_SIZE
          value: "50"
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
---
apiVersion: v1
kind: Service
metadata:
  name: session-manager-api
spec:
  type: LoadBalancer
  ports:
  - port: 80
    targetPort: 8000
  selector:
    app: session-manager-api
```

**Kubernetes Considerations**:
- Use ConfigMaps for non-sensitive configuration
- Use Secrets for MongoDB credentials
- Health checks should verify MongoDB connection
- Graceful shutdown to close connection pools

## Scalability Considerations

### 1. Connection Pool Sizing

**Formula**:
```
Total MongoDB Connections = (Application Instances) × (maxPoolSize)
```

**Recommendations**:
| Deployment Type | Instances | maxPoolSize | Total Connections |
|----------------|-----------|-------------|-------------------|
| Development    | 1         | 20          | 20                |
| Staging        | 2-3       | 50          | 100-150           |
| Production     | 5-10      | 50-100      | 250-1000          |
| High Traffic   | 10-20     | 100         | 1000-2000         |

**MongoDB Atlas Limits**:
- M10: 1,500 connections
- M20: 3,000 connections
- M30: 3,000 connections
- M40+: 12,500+ connections

### 2. Vertical Scaling

**FastAPI Instance Optimization**:
```python
# High-performance configuration
factory = initialize_global_factory(
    connection_string=mongodb_uri,
    maxPoolSize=200,           # More connections per instance
    minPoolSize=50,            # Higher baseline
    maxIdleTimeMS=45000,       # Keep connections alive longer
    waitQueueTimeoutMS=10000,  # Higher timeout for burst traffic
    serverSelectionTimeoutMS=10000
)
```

**Instance Sizing**:
- CPU: 2-4 cores per instance
- Memory: 2-4 GB per instance
- Disk: Minimal (stateless)

### 3. Horizontal Scaling

**Auto-scaling Triggers**:
- CPU utilization > 70%
- Request latency > 500ms (p95)
- MongoDB connection queue depth > 50

**Scaling Strategy**:
```python
# AWS Auto Scaling
{
    "min_instances": 2,
    "max_instances": 20,
    "target_cpu": 70,
    "scale_up_cooldown": 60,
    "scale_down_cooldown": 300
}
```

### 4. Database Scaling

**Read Scaling**:
- MongoDB read preference: `secondaryPreferred`
- Distributes reads across replica set members

```python
factory = MongoDBSessionManagerFactory(
    connection_string="mongodb://host1,host2,host3/?replicaSet=rs0&readPreference=secondaryPreferred",
    # ...
)
```

**Write Scaling**:
- Sharding by session_id for distributed writes
- Write concern: `majority` for durability

**Indexing for Performance**:
```python
# Automatically created indexes
db.sessions.createIndex({"created_at": 1})
db.sessions.createIndex({"updated_at": 1})
db.sessions.createIndex({"metadata.priority": 1})  # If priority in metadata_fields
```

### 5. Monitoring and Observability

**Key Metrics to Track**:

```python
# Application metrics
@app.get("/metrics")
async def metrics():
    factory = get_global_factory()
    stats = factory.get_connection_stats()

    return {
        "pool": stats,
        "instances": {
            "active_sessions": session_counter.value,
            "requests_per_second": request_rate.rate(),
            "avg_latency_ms": latency_histogram.mean()
        }
    }
```

**MongoDB Metrics**:
- Active connections
- Connection wait queue
- Operation latency (p50, p95, p99)
- Document size growth
- Index hit rate

**Application Metrics**:
- Session creation rate
- Message append rate
- Metric capture success rate
- Hook execution time
- Error rate by operation type

### 6. Performance Optimization Checklist

**Application Level**:
- [ ] Use global factory pattern in FastAPI
- [ ] Configure appropriate pool sizes
- [ ] Enable connection pooling
- [ ] Implement proper error handling
- [ ] Monitor connection statistics
- [ ] Use async operations where possible

**MongoDB Level**:
- [ ] Enable indexes on frequently queried fields
- [ ] Use appropriate read preference
- [ ] Set write concern appropriately
- [ ] Monitor slow queries
- [ ] Use projection to limit returned fields
- [ ] Consider sharding for very large deployments

**Infrastructure Level**:
- [ ] Deploy MongoDB in same region as application
- [ ] Use MongoDB Atlas for managed scaling
- [ ] Configure auto-scaling for application tier
- [ ] Set up monitoring and alerting
- [ ] Implement health checks
- [ ] Use load balancer with session affinity (optional)

### 7. Capacity Planning Example

**Scenario**: Chat application with 10,000 concurrent users

**Assumptions**:
- Average session duration: 10 minutes
- Messages per session: 20
- Message rate: 2 messages/minute/user
- Peak concurrent users: 10,000

**Calculations**:
```
Messages per second = (10,000 users × 2 msg/min) / 60 = 333 msg/s
MongoDB operations/s = 333 × 2 (append + sync) = 666 ops/s

Application instances needed:
- Assuming 100 req/s per instance = 666 / 100 = 7 instances

Connection pool:
- 7 instances × 100 maxPoolSize = 700 total connections
- MongoDB Atlas M30 (3,000 connection limit) sufficient

Storage:
- Average message size: 500 bytes
- Messages per day: 333 × 60 × 60 × 24 = 28.8M messages
- Storage per day: 28.8M × 500 bytes ≈ 14.4 GB/day
- 30-day retention: ≈ 432 GB
```

**Recommended Configuration**:
- FastAPI: 7-10 instances (with auto-scaling to 15)
- MongoDB Atlas: M30 or M40 tier
- Connection pool: 50-100 per instance
- Monitoring: Real-time dashboards with alerts

---

## Summary

The MongoDB Session Manager architecture is designed for production use with:

1. **Performance**: Connection pooling eliminates overhead
2. **Scalability**: Horizontal scaling with connection reuse
3. **Reliability**: Thread-safe operations, automatic retries
4. **Flexibility**: Multiple deployment patterns supported
5. **Extensibility**: Hook system for customization
6. **Observability**: Built-in metrics and monitoring support

The layered architecture with clear separation of concerns makes it easy to understand, maintain, and extend while providing excellent performance characteristics for stateless environments like FastAPI, Lambda, and Kubernetes.
