"""Example FastAPI integration with optimized MongoDB Session Manager.

📚 **Related Documentation:**
   - User Guide: docs/examples/fastapi-integration.md
   - Factory Pattern: docs/user-guide/factory-pattern.md

🚀 **How to Run:**
   ```bash
   uv run python examples/example_fastapi.py
   ```

🔗 **Learn More:** https://github.com/iguinea/mongodb-session-manager/tree/main/docs

This example demonstrates how to use the connection pooling
for high-performance stateless API endpoints.
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from strands import Agent

# Add parent directory to path to access src module
sys.path.insert(0, str(Path(__file__).parent.parent))

from mongodb_session_manager import (
    MongoDBConnectionPool,
    close_global_factory,
    initialize_global_factory,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Request/Response models
class ChatRequest(BaseModel):
    prompt: str
    agent_config: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    response: str
    session_id: str
    metrics: dict[str, Any] = Field(default_factory=dict)


def _agent_metrics(agent: Agent) -> dict[str, Any]:
    """Return the in-memory metrics captured by Strands for this invocation."""
    summary = agent.event_loop_metrics.get_summary()
    usage = summary.get("accumulated_usage", {})
    accumulated = summary.get("accumulated_metrics", {})
    cycles = summary.get("total_cycles", 0)
    latency_ms = accumulated.get("latencyMs", 0)
    return {
        "total_tokens": usage.get("totalTokens", 0),
        "average_latency_ms": latency_ms / cycles if cycles else 0,
        "total_messages": len(agent.messages),
    }


def _run_agent(
    factory: Any, chat_request: ChatRequest, session_id: str
) -> ChatResponse:
    """Run the complete synchronous request path on a worker thread.

    Agent construction restores the session and can therefore perform as much
    blocking database I/O as the invocation itself. Keeping both in this helper
    prevents either phase from stalling FastAPI's event loop.
    """
    session_manager = factory.create_session_manager(session_id)
    try:
        agent = Agent(
            name="VirtualAgent",
            model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
            system_prompt="You are a helpful assistant.",
            session_manager=session_manager,
            **chat_request.agent_config,
        )
        response = agent(chat_request.prompt)
        return ChatResponse(
            response=str(response),
            session_id=session_id,
            metrics=_agent_metrics(agent),
        )
    finally:
        session_manager.close()


# Lifespan context manager for FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    # Startup
    logger.info("Starting FastAPI application...")

    # Initialize the global factory with connection pooling
    factory = initialize_global_factory(
        connection_string="mongodb://mongodb:mongodb@mongodb_session_manager-mongodb:27017/",
        database_name="example_fastapi",
        collection_name="example_fastapi",
        # Connection pool settings optimized for high concurrency
        maxPoolSize=100,
        minPoolSize=10,
        maxIdleTimeMS=300000,
    )

    # Store factory in app state for access in endpoints
    # Note: You can access the factory in two ways:
    # 1. From app state: request.app.state.session_factory (used in this example)
    # 2. From global: get_global_factory() (simpler but less flexible)
    app.state.session_factory = factory

    logger.info("MongoDB session factory initialized with connection pooling")

    yield  # Application runs

    # Shutdown
    logger.info("Shutting down FastAPI application...")

    # Close the global factory and connection pool
    close_global_factory()

    logger.info("Cleanup complete")


# Create FastAPI app with lifespan handler
app = FastAPI(
    title="Virtual Agent API with Optimized Session Management", lifespan=lifespan
)


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    chat_request: ChatRequest,
    session_id: str = Header(description="Session identifier"),
) -> ChatResponse:
    """Process a chat message with optimized session management.

    This endpoint demonstrates:
    1. Reusing MongoDB connections via the factory
    2. Keeping synchronous Strands and PyMongo work off the event loop
    3. Proper metrics tracking
    """
    try:
        # Get factory from app state (no new connection created)
        factory = request.app.state.session_factory

        # Agent construction restores the session, and Agent.__call__ plus the
        # session callbacks are synchronous. Offload that complete path to
        # Starlette's shared worker pool so health checks and other requests can
        # keep running while MongoDB or the model is slow.
        return await run_in_threadpool(_run_agent, factory, chat_request, session_id)

    except Exception as e:
        logger.error(f"Error processing chat request: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/health")
async def health_check(request: Request):
    """Health check endpoint with connection pool status."""
    try:
        # Get connection pool statistics
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

        # Get connection pool statistics
        pool_stats = factory.get_connection_stats()

        return {"connection_pool": pool_stats}
    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# Example of how to run the application
if __name__ == "__main__":
    import uvicorn
    from fastapi.middleware.cors import CORSMiddleware

    # CORS middleware for cross-origin requests
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, restrict to specific origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Run with optimized settings for production
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        workers=1,  # Single worker for shared connection pool
        loop="uvloop",  # Faster event loop
        log_level="info",
    )
