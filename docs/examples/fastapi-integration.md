# FastAPI Integration Examples

## 🚀 Runnable Examples

This guide includes multiple code examples. For complete, executable scripts, see:

| Script | Description | Run Command |
|--------|-------------|-------------|
| [example_fastapi.py](../../examples/example_fastapi.py) | FastAPI with connection pooling | `uv run python examples/example_fastapi.py` |
| [example_fastapi_streaming.py](../../examples/example_fastapi_streaming.py) | FastAPI with streaming responses | `uv run python examples/example_fastapi_streaming.py` |

📁 **All examples**: [View examples directory](../../examples/)

---

This guide demonstrates how to integrate MongoDB Session Manager with FastAPI for production-grade applications. Learn about connection pooling, lifecycle management, streaming responses, and scalable architectures.

## Table of Contents

- [Why FastAPI Integration?](#why-fastapi-integration)
- [Basic FastAPI Setup](#basic-fastapi-setup)
- [Connection Pooling with Factory Pattern](#connection-pooling-with-factory-pattern)
- [Lifespan Management](#lifespan-management)
- [Streaming Endpoints](#streaming-endpoints)
- [Health Checks and Metrics](#health-checks-and-metrics)
- [Error Handling](#error-handling)
- [CORS Configuration](#cors-configuration)
- [Complete Production Example](#complete-production-example)
- [Interactive Chat Playground](#interactive-chat-playground)

---

## Why FastAPI Integration?

FastAPI is ideal for stateless microservices, but naive implementation can lead to:
- **Connection exhaustion**: Creating new MongoDB connections per request
- **Performance degradation**: Connection overhead (10-50ms per request)
- **Resource leaks**: Unclosed connections

MongoDB Session Manager solves these problems with:
- **Connection pooling**: Shared connections across all requests
- **Factory pattern**: Zero connection overhead per request
- **Lifecycle hooks**: Proper initialization and cleanup

**Performance Comparison:**
```
Without Factory Pattern:
- Connection overhead: 10-50ms per request
- Max throughput: ~20-30 requests/second

With Factory Pattern:
- Connection overhead: <1ms per request
- Max throughput: 500+ requests/second
```

---

## Basic FastAPI Setup

Simple FastAPI endpoint with session management (not recommended for production).

```python
"""
Basic FastAPI integration - Simple but not optimized.
Use factory pattern for production (see next section).
"""

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from strands import Agent
from mongodb_session_manager import create_mongodb_session_manager

app = FastAPI()

class ChatRequest(BaseModel):
    prompt: str

class ChatResponse(BaseModel):
    response: str
    session_id: str

@app.post("/chat", response_model=ChatResponse)
async def chat(
    chat_request: ChatRequest,
    session_id: str = Header(...)
) -> ChatResponse:
    """
    Process a chat message.
    WARNING: This creates a new connection per request!
    """
    # Creates new MongoDB connection (inefficient!)
    session_manager = create_mongodb_session_manager(
        session_id=session_id,
        connection_string="mongodb://localhost:27017/",
        database_name="my_app"
    )

    try:
        # Create agent
        agent = Agent(
            model="claude-3-sonnet-20240229",
            session_manager=session_manager,
            system_prompt="You are a helpful assistant."
        )

        # Process message
        response = agent(chat_request.prompt)

        return ChatResponse(
            response=str(response),
            session_id=session_id
        )

    finally:
        session_manager.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**Problems:**
- Creates new MongoDB connection for each request
- High latency due to connection overhead
- Risk of connection pool exhaustion
- Not suitable for production

---

## Connection Pooling with Factory Pattern

Optimized approach using the factory pattern for connection reuse.

Based on `/workspace/examples/example_fastapi.py`:

```python
"""
Optimized FastAPI integration with connection pooling.
This is the RECOMMENDED approach for production.
"""

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from contextlib import asynccontextmanager
from strands import Agent

from mongodb_session_manager import (
    initialize_global_factory,
    get_global_factory,
    close_global_factory,
    MongoDBConnectionPool,
)

# Request/Response models
class ChatRequest(BaseModel):
    prompt: str
    agent_config: dict = {}

class ChatResponse(BaseModel):
    response: str
    session_id: str
    metrics: dict = {}

# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    # Startup: Initialize global factory with connection pooling
    factory = initialize_global_factory(
        connection_string="mongodb://localhost:27017/",
        database_name="my_app",
        collection_name="sessions",
        # Optimized connection pool settings
        maxPoolSize=100,      # Maximum connections
        minPoolSize=10,       # Minimum connections
        maxIdleTimeMS=30000,  # Close idle connections after 30s
    )

    # Store in app state (optional - can also use get_global_factory())
    app.state.session_factory = factory

    yield  # Application runs

    # Shutdown: Clean up resources
    close_global_factory()

# Create app with lifespan
app = FastAPI(
    title="Virtual Agent API",
    lifespan=lifespan
)

@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    chat_request: ChatRequest,
    session_id: str = Header(...)
) -> ChatResponse:
    """
    Process a chat message with optimized session management.

    This endpoint:
    1. Reuses MongoDB connections via the factory
    2. Zero connection overhead per request
    3. Automatic metrics tracking
    """
    try:
        # Get factory from app state (no new connection!)
        factory = request.app.state.session_factory
        # OR use global: factory = get_global_factory()

        # Create session manager (reuses existing connection)
        session_manager = factory.create_session_manager(session_id)

        # Create agent
        agent = Agent(
            model="claude-3-sonnet-20240229",
            session_manager=session_manager,
            system_prompt="You are a helpful assistant.",
            **chat_request.agent_config
        )

        # Process message
        response = agent(chat_request.prompt)

        # Get metrics (if available)
        try:
            metrics_summary = session_manager.get_metrics_summary(agent.agent_id)
            metrics = {
                "total_tokens": metrics_summary.get("total_tokens", 0),
                "average_latency_ms": metrics_summary.get("average_latency_ms", 0),
                "total_messages": metrics_summary.get("total_messages", 0),
            }
        except:
            metrics = {}

        return ChatResponse(
            response=str(response),
            session_id=session_id,
            metrics=metrics
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        workers=1,        # Single worker for shared pool
        loop="uvloop",    # Faster event loop
        log_level="info"
    )
```

**Benefits:**
- Single MongoDB connection pool shared across all requests
- Near-zero connection overhead (<1ms)
- Handles 500+ concurrent requests efficiently
- Proper resource cleanup on shutdown

---

## Lifespan Management

Understanding FastAPI's lifespan for proper initialization and cleanup.

```python
"""
Comprehensive lifespan management example.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from mongodb_session_manager import (
    initialize_global_factory,
    close_global_factory,
    MongoDBConnectionPool,
)

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages application lifecycle.

    Startup:
    - Initialize connection pool
    - Set up monitoring
    - Validate configuration

    Shutdown:
    - Close connections gracefully
    - Flush pending operations
    - Clean up resources
    """
    # === STARTUP ===
    logger.info("Starting application...")

    try:
        # Initialize connection pool
        factory = initialize_global_factory(
            connection_string="mongodb://localhost:27017/",
            database_name="my_app",
            # Pool configuration
            maxPoolSize=100,
            minPoolSize=10,
            maxIdleTimeMS=30000,
            # Timeouts
            connectTimeoutMS=5000,
            serverSelectionTimeoutMS=5000,
        )

        # Validate connection
        stats = factory.get_connection_stats()
        logger.info(f"Connection pool initialized: {stats}")

        # Store in app state
        app.state.session_factory = factory
        app.state.startup_time = "2024-01-26T10:00:00"

        logger.info("Application started successfully")

    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        raise

    yield  # Application is running

    # === SHUTDOWN ===
    logger.info("Shutting down application...")

    try:
        # Get final statistics
        stats = MongoDBConnectionPool.get_pool_stats()
        logger.info(f"Final pool stats: {stats}")

        # Close the factory and connection pool
        close_global_factory()

        logger.info("Application shutdown complete")

    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root(request: Request):
    """Root endpoint with app state access."""
    return {
        "status": "running",
        "startup_time": request.app.state.startup_time,
        "pool_stats": MongoDBConnectionPool.get_pool_stats()
    }
```

**Key Points:**
- Use `@asynccontextmanager` for lifespan
- Initialize resources before `yield`
- Clean up resources after `yield`
- Handle errors gracefully
- Log important events

---

## Streaming Endpoints

Real-time streaming responses with session persistence.

Based on `/workspace/examples/example_fastapi_streaming.py`:

```python
"""
Streaming chat endpoint with MongoDB session persistence.
"""

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from strands import Agent

from mongodb_session_manager import get_global_factory

app = FastAPI()

class ChatRequest(BaseModel):
    prompt: str

@app.post("/chat/stream")
async def chat_stream(
    chat_request: ChatRequest,
    session_id: str = Header(...)
):
    """
    Stream chat responses in real-time while persisting to MongoDB.

    Flow:
    1. User sends message
    2. Response streams to client
    3. Full response is saved to MongoDB
    4. Metrics are captured
    """
    try:
        # Get factory and create session manager
        factory = get_global_factory()
        session_manager = factory.create_session_manager(session_id)

        # Create agent
        agent = Agent(
            agent_id="virtual-agent",
            model="claude-3-sonnet-20240229",
            session_manager=session_manager,
            system_prompt="You are a helpful assistant."
        )

        # Track response chunks for later storage
        response_chunks = []

        async def generate():
            """Stream generator that yields chunks."""
            try:
                # Stream from agent
                async for event in agent.stream_async(chat_request.prompt):
                    if "data" in event:
                        chunk = event["data"]
                        response_chunks.append(chunk)
                        yield chunk

                # After streaming completes, save to MongoDB
                full_response = "".join(response_chunks)

                # The agent already appended user message
                # Now append the complete assistant response
                session_manager.append_message(
                    {
                        "role": "assistant",
                        "content": full_response
                    },
                    agent
                )

                # Sync agent state and metrics
                session_manager.sync_agent(agent)

            except Exception as e:
                logger.error(f"Streaming error: {e}")
                yield f"\n\nError: {str(e)}"

        # Return streaming response
        return StreamingResponse(
            generate(),
            media_type="text/plain"
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

**Client-Side Usage:**

```javascript
// JavaScript client for streaming endpoint
async function streamChat(prompt, sessionId) {
    const response = await fetch('http://localhost:8000/chat/stream', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'session-id': sessionId
        },
        body: JSON.stringify({ prompt })
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        // Display chunk in UI
        appendToChat(chunk);
    }
}
```

---

## Health Checks and Metrics

Production-ready health checks and monitoring endpoints.

```python
"""
Health check and metrics endpoints.
"""

from fastapi import FastAPI, Request
from mongodb_session_manager import (
    get_global_factory,
    MongoDBConnectionPool
)

app = FastAPI()

@app.get("/health")
async def health_check():
    """
    Health check endpoint with connection pool status.

    Returns:
    - 200 OK if healthy
    - 503 Service Unavailable if unhealthy
    """
    try:
        # Get pool statistics
        pool_stats = MongoDBConnectionPool.get_pool_stats()

        # Check if pool is healthy
        is_healthy = (
            pool_stats.get("active_connections", 0) >= 0 and
            pool_stats.get("total_connections", 0) > 0
        )

        if is_healthy:
            return {
                "status": "healthy",
                "connection_pool": pool_stats,
                "timestamp": "2024-01-26T10:00:00"
            }
        else:
            return {
                "status": "unhealthy",
                "reason": "Connection pool not available",
                "connection_pool": pool_stats
            }

    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }

@app.get("/metrics")
async def get_metrics(request: Request):
    """
    Detailed metrics endpoint.

    Returns:
    - Connection pool statistics
    - Factory information
    - System metrics
    """
    try:
        factory = request.app.state.session_factory

        # Connection pool stats
        pool_stats = factory.get_connection_stats()

        # Additional metrics
        metrics = {
            "connection_pool": pool_stats,
            "factory": {
                "database": factory.database_name,
                "collection": factory.collection_name,
            },
            "timestamp": "2024-01-26T10:00:00"
        }

        return metrics

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics/session/{session_id}")
async def get_session_metrics(session_id: str, request: Request):
    """
    Get metrics for a specific session.
    """
    try:
        factory = request.app.state.session_factory
        session_manager = factory.create_session_manager(session_id)

        # Get session data
        session_data = session_manager.get_session()

        if not session_data:
            raise HTTPException(status_code=404, detail="Session not found")

        # Compile metrics
        metrics = {
            "session_id": session_id,
            "agents": {},
            "total_messages": 0
        }

        for agent_id, agent_data in session_data.agents.items():
            agent_metrics = {
                "name": agent_data.name,
                "message_count": len(agent_data.messages),
                "state": agent_data.state
            }
            metrics["agents"][agent_id] = agent_metrics
            metrics["total_messages"] += len(agent_data.messages)

        return metrics

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

**Monitoring Integration:**

```python
# Prometheus metrics (example)
from prometheus_client import Counter, Histogram, Gauge

# Define metrics
chat_requests = Counter('chat_requests_total', 'Total chat requests')
chat_duration = Histogram('chat_duration_seconds', 'Chat request duration')
active_sessions = Gauge('active_sessions', 'Number of active sessions')

@app.post("/chat")
async def chat(...):
    chat_requests.inc()
    with chat_duration.time():
        # Process chat
        ...
```

---

## Error Handling

Comprehensive error handling for production applications.

```python
"""
Production-grade error handling.
"""

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import logging

logger = logging.getLogger(__name__)

app = FastAPI()

# Custom exception classes
class SessionNotFoundError(Exception):
    """Raised when session is not found."""
    pass

class AgentError(Exception):
    """Raised when agent encounters an error."""
    pass

# Exception handlers
@app.exception_handler(SessionNotFoundError)
async def session_not_found_handler(request: Request, exc: SessionNotFoundError):
    """Handle session not found errors."""
    logger.warning(f"Session not found: {exc}")
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": "session_not_found",
            "message": str(exc),
            "session_id": getattr(exc, 'session_id', None)
        }
    )

@app.exception_handler(AgentError)
async def agent_error_handler(request: Request, exc: AgentError):
    """Handle agent errors."""
    logger.error(f"Agent error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "agent_error",
            "message": "An error occurred processing your request",
            "details": str(exc)
        }
    )

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors."""
    logger.warning(f"Validation error: {exc}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "validation_error",
            "message": "Invalid request data",
            "details": exc.errors()
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Catch-all exception handler."""
    logger.error(f"Unexpected error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred"
        }
    )

# Using exceptions in endpoints
@app.post("/chat")
async def chat(chat_request: ChatRequest, session_id: str = Header(...)):
    try:
        factory = get_global_factory()
        session_manager = factory.create_session_manager(session_id)

        # Check if session exists
        if not session_manager.check_session_exists():
            raise SessionNotFoundError(f"Session {session_id} not found")

        # Process chat
        agent = Agent(...)
        response = agent(chat_request.prompt)

        return ChatResponse(response=str(response), session_id=session_id)

    except SessionNotFoundError:
        raise  # Let exception handler deal with it
    except Exception as e:
        raise AgentError(f"Failed to process chat: {e}")
```

---

## CORS Configuration

Proper CORS setup for cross-origin requests.

```python
"""
CORS configuration for production.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Development: Allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Production: Restrict to specific origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://myapp.com",
        "https://www.myapp.com",
        "https://admin.myapp.com"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "session-id"],
)

# Multiple environments
import os

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

if ENVIRONMENT == "production":
    allowed_origins = os.getenv("ALLOWED_ORIGINS", "").split(",")
else:
    allowed_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## Complete Production Example

Full production-ready FastAPI application combining all best practices.

```python
"""
Complete production FastAPI application.
Reference: /workspace/examples/example_fastapi.py
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from strands import Agent

from mongodb_session_manager import (
    initialize_global_factory,
    get_global_factory,
    close_global_factory,
    MongoDBConnectionPool,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
MONGO_CONNECTION = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
DATABASE_NAME = os.getenv("DATABASE_NAME", "production_app")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Models
class ChatRequest(BaseModel):
    prompt: str
    agent_config: Dict[str, Any] = {}

class ChatResponse(BaseModel):
    response: str
    session_id: str
    metrics: Dict[str, Any] = {}

# Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    logger.info(f"Starting application in {ENVIRONMENT} mode...")

    # Initialize connection pool
    factory = initialize_global_factory(
        connection_string=MONGO_CONNECTION,
        database_name=DATABASE_NAME,
        collection_name="sessions",
        maxPoolSize=100,
        minPoolSize=10,
        maxIdleTimeMS=30000,
    )

    app.state.session_factory = factory
    logger.info("MongoDB session factory initialized")

    yield

    logger.info("Shutting down application...")
    close_global_factory()
    logger.info("Cleanup complete")

# Create app
app = FastAPI(
    title="Virtual Agent API",
    description="Production MongoDB Session Manager API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
if ENVIRONMENT == "production":
    allowed_origins = os.getenv("ALLOWED_ORIGINS", "").split(",")
else:
    allowed_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Endpoints
@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    chat_request: ChatRequest,
    session_id: str = Header(...)
) -> ChatResponse:
    """Process a chat message."""
    try:
        factory = request.app.state.session_factory
        session_manager = factory.create_session_manager(session_id)

        agent = Agent(
            model="claude-3-sonnet-20240229",
            session_manager=session_manager,
            system_prompt="You are a helpful assistant.",
            **chat_request.agent_config
        )

        response = agent(chat_request.prompt)

        # Get metrics
        try:
            metrics = session_manager.get_metrics_summary(agent.agent_id)
        except:
            metrics = {}

        return ChatResponse(
            response=str(response),
            session_id=session_id,
            metrics=metrics
        )

    except Exception as e:
        logger.error(f"Error processing chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        pool_stats = MongoDBConnectionPool.get_pool_stats()
        return {
            "status": "healthy",
            "connection_pool": pool_stats,
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

@app.get("/metrics")
async def get_metrics(request: Request):
    """Get system metrics."""
    try:
        factory = request.app.state.session_factory
        pool_stats = factory.get_connection_stats()
        return {"connection_pool": pool_stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        workers=1,
        loop="uvloop",
        log_level="info",
    )
```

---

## Interactive Chat Playground

The project includes a complete web-based chat interface for testing.

**Location:** `/workspace/playground/chat/`

**Starting the Playground:**

```bash
# Terminal 1: Start backend API (port 8880)
cd /workspace/playground/chat
make backend-fastapi-streaming

# Terminal 2: Start frontend (port 8881)
cd /workspace/playground/chat
make frontend

# Open browser
open http://localhost:8881/chat.html
```

**Features:**
- Real-time streaming responses
- Session persistence across page reloads
- Automatic metrics tracking
- Metadata view with session statistics
- Connection status indicators

**Architecture:**

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────┐
│  Chat Frontend  │────────▶│  FastAPI Backend │────────▶│  MongoDB    │
│  (Port 8881)    │  HTTP   │  (Port 8880)     │  Async  │             │
│  chat.html      │◀────────│  Streaming API   │◀────────│  Sessions   │
└─────────────────┘  SSE    └──────────────────┘         └─────────────┘
```

**Makefile Reference:**

```makefile
# From /workspace/playground/chat/Makefile

frontend:
    python3 -m http.server 8881

backend-fastapi-streaming:
    uv run /workspace/examples/example_fastapi_streaming.py
```

---

## Deployment Considerations

### Docker Deployment

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync

# Copy application
COPY . .

# Run with uvicorn
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Environment Variables

```bash
# .env file
MONGODB_URI=mongodb://user:pass@localhost:27017/
DATABASE_NAME=production
ENVIRONMENT=production
ALLOWED_ORIGINS=https://myapp.com,https://www.myapp.com
MAX_POOL_SIZE=100
MIN_POOL_SIZE=10
```

### Load Balancing

```yaml
# docker-compose.yml
version: '3.8'

services:
  api:
    build: .
    deploy:
      replicas: 3  # Multiple instances
    environment:
      - MONGODB_URI=mongodb://mongo:27017/
    depends_on:
      - mongo

  nginx:
    image: nginx:latest
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf

  mongo:
    image: mongo:7
    volumes:
      - mongo_data:/data/db

volumes:
  mongo_data:
```

---

## Troubleshooting

### Connection Pool Exhaustion

```python
# Problem: Too many concurrent requests
# Solution: Increase maxPoolSize

factory = initialize_global_factory(
    connection_string=MONGO_CONNECTION,
    maxPoolSize=200,  # Increased from 100
    minPoolSize=20
)
```

### Memory Leaks

```python
# Problem: Session managers not being garbage collected
# Solution: Ensure proper cleanup (factory pattern handles this automatically)

# Don't do this:
session_manager = create_mongodb_session_manager(...)  # Creates new connection

# Do this instead:
session_manager = factory.create_session_manager(...)  # Reuses connection
```

### Slow Response Times

```python
# Check connection pool stats
@app.get("/debug/pool")
async def debug_pool():
    stats = MongoDBConnectionPool.get_pool_stats()
    return stats

# If active_connections ≈ maxPoolSize, increase pool size
```

---

## Next Steps

- Explore [Metadata Patterns](metadata-patterns.md) for session tracking
- Learn [Feedback Patterns](feedback-patterns.md) for user feedback
- See [AWS Patterns](aws-patterns.md) for cloud integrations

## Reference Files

- `/workspace/examples/example_fastapi.py` - Basic FastAPI integration
- `/workspace/examples/example_fastapi_streaming.py` - Streaming implementation
- `/workspace/playground/chat/` - Interactive playground
- `/workspace/src/mongodb_session_manager/mongodb_session_factory.py` - Factory implementation
