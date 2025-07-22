"""Example FastAPI integration with optimized MongoDB Session Manager.

This example demonstrates how to use the connection pooling and caching features
for high-performance stateless API endpoints.
"""

import asyncio
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

from src import (
    initialize_global_factory,
    get_global_factory,
    close_global_factory,
    MongoDBConnectionPool
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
        connection_string="mongodb://mongodb:mongodb@genai-mrg-mongodb:27017/",
        database_name="example_fastapi",
        collection_name="example_fastapi",
        # Connection pool settings optimized for high concurrency
        maxPoolSize=100,
        minPoolSize=10,
        maxIdleTimeMS=30000,
        # Enable caching for better performance
        enable_cache=True,
        cache_max_size=1000,
        cache_ttl_seconds=300
    )
    
    # Store factory in app state for access in endpoints
    app.state.session_factory = factory
    
    logger.info("MongoDB session factory initialized with connection pooling and caching")
    
    yield  # Application runs
    
    # Shutdown
    logger.info("Shutting down FastAPI application...")
    
    # Close the global factory and connection pool
    close_global_factory()
    
    logger.info("Cleanup complete")


# Create FastAPI app with lifespan handler
app = FastAPI(
    title="Virtual Agent API with Optimized Session Management",
    lifespan=lifespan
)


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    chat_request: ChatRequest,
    session_id: str = Header(description="Session identifier")
) -> ChatResponse:
    """Process a chat message with optimized session management.
    
    This endpoint demonstrates:
    1. Reusing MongoDB connections via the factory
    2. Automatic session caching for metadata lookups
    3. Proper metrics tracking
    """
    try:
        # Get factory from app state (no new connection created)
        factory = get_global_factory()
        
        # Create session manager (reuses existing MongoDB connection)
        # The factory automatically wraps it with caching if enabled
        session_manager = factory.create_session_manager(session_id)
        
        # Check if session exists (uses cache for repeated checks)
        session_info = session_manager.check_session_exists()
        logger.info(f"Session {session_id} exists: {session_info['exists']}")
        
        # Create a mock agent for demonstration
        # In real usage, you would configure your actual agent here
        agent = Agent(
            name="VirtualAgent",
            model="gpt-4",  # Replace with your model
            system_prompt="You are a helpful assistant.",
            **chat_request.agent_config
        )
        
        # Configure agent with session manager
        agent.session_manager = session_manager
        
        # Process the message
        # The session manager automatically tracks timing and metrics
        response = await agent.run_async(chat_request.prompt)
        
        # Get metrics summary
        metrics = session_manager.get_metrics_summary(agent.agent_id)
        
        return ChatResponse(
            response=response,
            session_id=session_id,
            metrics={
                "total_tokens": metrics.get("total_tokens", 0),
                "average_latency_ms": metrics.get("average_latency_ms", 0),
                "total_messages": metrics.get("total_messages", 0)
            }
        )
        
    except Exception as e:
        logger.error(f"Error processing chat request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint with connection pool status."""
    try:
        # Get connection pool statistics
        pool_stats = MongoDBConnectionPool.get_pool_stats()
        
        # Get cache statistics if available
        factory = get_global_factory()
        cache_stats = factory.get_cache_stats()
        
        return {
            "status": "healthy",
            "connection_pool": pool_stats,
            "cache": cache_stats or {"status": "disabled"}
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


@app.get("/metrics")
async def get_metrics():
    """Get system metrics including cache performance."""
    try:
        factory = get_global_factory()
        
        # Get cache statistics
        cache_stats = factory.get_cache_stats()
        
        # Get connection pool statistics
        pool_stats = factory.get_connection_stats()
        
        return {
            "cache_metrics": cache_stats,
            "connection_pool": pool_stats
        }
    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sessions/{session_id}/invalidate-cache")
async def invalidate_session_cache(session_id: str):
    """Manually invalidate cache for a specific session.
    
    Useful after bulk updates or when cache coherency is critical.
    """
    try:
        factory = get_global_factory()
        
        # Create a temporary session manager to invalidate its cache
        session_manager = factory.create_session_manager(session_id)
        
        if hasattr(session_manager, 'invalidate_cache'):
            session_manager.invalidate_cache()
            return {"status": "success", "message": f"Cache invalidated for session {session_id}"}
        else:
            return {"status": "info", "message": "Caching not enabled"}
            
    except Exception as e:
        logger.error(f"Error invalidating cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Example of how to run the application
if __name__ == "__main__":
    import uvicorn
    
    # Run with optimized settings for production
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        workers=1,  # Single worker for shared connection pool
        loop="uvloop",  # Faster event loop
        log_level="info"
    )