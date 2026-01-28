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
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from strands import Agent

import sys
from pathlib import Path

# Add parent directory to path to access src module
sys.path.insert(0, str(Path(__file__).parent.parent))

from mongodb_session_manager import (
    initialize_global_factory,
    close_global_factory,
    MongoDBConnectionPool,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Request/Response models
class ChatRequest(BaseModel):
    prompt: str
    agent_config: Dict[str, Any] = {}


class ChatResponse(BaseModel):
    response: str
    session_id: str
    metrics: Dict[str, Any] = {}


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
        maxIdleTimeMS=30000,
    )

    # Store factory in app state for access in endpoints
    # Note: You can access the factory in two ways:
    # 1. From app state: request.app.state.session_factory (used in this example)
    # 2. From global: get_global_factory() (simpler but less flexible)
    app.state.session_factory = factory

    logger.info(
        "MongoDB session factory initialized with connection pooling"
    )

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
    2. Proper metrics tracking
    """
    try:
        # Get factory from app state (no new connection created)
        factory = request.app.state.session_factory

        # Create session manager (reuses existing MongoDB connection)
        session_manager = factory.create_session_manager(session_id)

        # Create a mock agent for demonstration
        # In real usage, you would configure your actual agent here
        agent = Agent(
            name="VirtualAgent",
            model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
            system_prompt="You are a helpful assistant.",
            **chat_request.agent_config,
        )

        # Configure agent with session manager
        agent.session_manager = session_manager

        # Process the message
        # The session manager automatically tracks timing and metrics
        # Agent uses __call__ method, which is synchronous
        response = agent(chat_request.prompt)

        # Get metrics summary
        metrics = session_manager.get_metrics_summary(agent.agent_id)

        return ChatResponse(
            response=response,
            session_id=session_id,
            metrics={
                "total_tokens": metrics.get("total_tokens", 0),
                "average_latency_ms": metrics.get("average_latency_ms", 0),
                "total_messages": metrics.get("total_messages", 0),
            },
        )

    except Exception as e:
        logger.error(f"Error processing chat request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))



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
