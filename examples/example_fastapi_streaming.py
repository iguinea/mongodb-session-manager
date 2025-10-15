"""Example FastAPI integration with streaming responses and factory pattern.

📚 **Related Documentation:**
   - User Guide: docs/examples/fastapi-integration.md
   - Async Streaming: docs/user-guide/async-streaming.md

🚀 **How to Run:**
   ```bash
   uv run python examples/example_fastapi_streaming.py
   ```

🔗 **Learn More:** https://github.com/iguinea/mongodb-session-manager/tree/main/docs

This example demonstrates real-time streaming responses with session persistence
and the factory pattern for optimized connection management.
"""

import logging
import asyncio
import signal
import sys

from fastapi import FastAPI, Header, HTTPException, Depends, Request, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.logging import DefaultFormatter
from strands import Agent
from typing import Optional
from contextlib import asynccontextmanager
from builtins import Exception, str, dict, print, max, min, KeyboardInterrupt
from enum import Enum


from session_context import set_session_context_id


# Usar el mismo formatter que Uvicorn para consistencia visual
handler = logging.StreamHandler()
handler.setFormatter(DefaultFormatter(fmt="%(levelprefix)s %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[handler])


### SHUTDOWN HANDLING ###
shutdown_signal = (
    asyncio.Event()
)  # Renamed to avoid conflict with shutdown_event function
force_shutdown_count = 0


def handle_shutdown(signum, frame):
    """Handle shutdown signals gracefully."""
    global force_shutdown_count
    force_shutdown_count += 1

    if force_shutdown_count == 1:
        logging.info("Received shutdown signal. Gracefully shutting down...")
        shutdown_signal.set()
    else:
        logging.warning("Force shutdown requested. Exiting immediately...")
        sys.exit(1)


# Register signal handlers
signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)
### END SHUTDOWN HANDLING ###


from mongodb_session_manager import (
    initialize_global_factory,
    close_global_factory,
    MongoDBConnectionPool,
    get_global_factory,
)


# Lifespan event handler for FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    # Startup
    logging.info("Starting FastAPI application...")

    # Initialize the global factory with connection pooling
    factory = initialize_global_factory(
        connection_string="mongodb://mongodb:mongodb@mongodb_session_manager-mongodb:27017/",
        database_name="examples",
        collection_name="fastapi_streaming",
        # Connection pool settings optimized for high concurrency
        maxPoolSize=100,
        minPoolSize=10,
        maxIdleTimeMS=30000,
    )

    # Store factory in app state for access in endpoints
    app.state.session_factory = factory

    logging.info(
        "MongoDB session factory initialized with connection pooling"
    )

    yield  # Application runs

    # Shutdown
    logging.info("Shutting down FastAPI application...")

    # Close the global factory and connection pool
    close_global_factory()

    logging.info("Cleanup complete")


# Create FastAPI app with lifespan handler
app = FastAPI(
    # title="Virtual Agent API with Optimized Session Management",
    # description="This API demonstrates optimized session management using MongoDB with connection pooling and caching.",
    # version="1.0.0",
    # contact={
    #     "name": "Iñaki Guinea Beristain",
    #     "email": "iguinea@gmail.com"
    # },
    # license_info={"name": "MIT License"},
    lifespan=lifespan
)

# --- Middleware CORS ---
# Esencial en una arquitectura de 2 servidores para permitir la comunicación
# entre el frontend (ej: localhost:8000) y el backend (ej: localhost:8001).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*"
    ],  # En producción, deberías restringirlo a "http://localhost:8000"
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from CaseType import CaseType


_AGENT_PROMPT = f"""
Eres un asistente de IA que responde siempre en formato mark down.

# Herramientas disponibles:

## set_state - Para guardar valores:
- set_state({{"case_type": "New Client", "customer_phone": "123456789"}})
- set_state({{"case_type": "New Case", "customer_phone": "123456789", "customer_name": "ES123..."}})
- set_state({{"case_type": "New Case Type", "customer_phone": "123456789", "customer_name": "ES123...", "customer_address": "123456789"}})
- set_state({{"case_type": "New Case Status", "customer_phone": "123456789", "customer_name": "ES123...", "customer_address": "123456789"}})

## get_state - Para consultar datos:
- get_state()
- get_state("case_type")
- get_state(["case_type", "customer_phone", "customer_name"])

# Funcionamiento

* Lo primero que harás es recuperar toda la información posible sobre un cliente para averiguar el tipo de caso que nos ocupa.:
- El teléfono del cliente (customer_phone)
- El nombre del cliente (customer_name)
- La dirección del cliente (customer_address)

* Una vez tienes la información, usa la herramienta 'set_state' para establecer estos parametros en la metadata de la sesión:
- customer_phone: El teléfono del cliente
- customer_name: El nombre del cliente
- customer_address: La dirección del cliente

* Con esta información ya puedes empezar a recuperar información sobre el cliente de lo sistemas de información.

* Los tipos de casos son:
{chr(10).join(f'- {case_type}' for case_type in CaseType.list_values())}

* Si identificas el tipo de caso, usa la herramienta 'set_state' para establecer el 'case_type' en la metadata de la sesión.

"""
from tools_agent_state import set_state, get_state


@app.post("/chat")
async def chat(request: Request, data: dict, session_id: str = Header(...)):
    """Process a chat message with optimized session management.

    This endpoint demonstrates:
    1. Reusing MongoDB connections via the factory
    2. Proper metrics tracking
    """
    print(f"session_id: {session_id}")
    # Set session ID in context for this request
    set_session_context_id(session_id)

    try:
        # Get factory from app state (no new connection created)
        factory = get_global_factory()

        # Create session manager (reuses existing MongoDB connection)
        session_manager = factory.create_session_manager(session_id)

        prompt = data.get("prompt")
        if not prompt:
            raise HTTPException(status_code=400, detail="Falta prompt")

        agent = Agent(
            agent_id="virtual-agent",
            name="VirtualAgent",
            model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
            system_prompt=_AGENT_PROMPT,
            session_manager=session_manager,
            tools=[set_state, get_state],
            callback_handler=None,
        )

        response_chunks = []

        async def generate():
            async for event in agent.stream_async(prompt):
                if "data" in event:
                    response_chunks.append(event["data"])
                    yield event["data"]

        # Create streaming response
        response = StreamingResponse(generate(), media_type="text/plain")
        return response

    except Exception as e:
        logging.error(f"Error processing chat request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# # --- New endpoints for session management features ---
# @app.get("/sessions/{session_id}")
# async def get_session_details(session_id: str, _: str = Depends(verify_api_key)):
#     """Get session data and metadata."""
#     session_store = get_session_store()
#     if not session_store:
#         raise HTTPException(status_code=503, detail="Session store not initialized")
#     session_data = await session_store.get_session(session_id)
#     if not session_data:
#         raise HTTPException(status_code=404, detail="Session not found")

#     metadata = await session_store.get_session_metadata(session_id)

#     return {
#         "session_id": session_id,
#         "data": session_data,
#         "metadata": metadata
#     }


@app.get("/case-types")
async def get_case_types():
    """Get available case types."""
    return {
        "case_types": [
            {
                "name": case_type.name,
                "value": case_type.value,
                "description": f"Casos de tipo {case_type.value}",
            }
            for case_type in CaseType
        ]
    }


@app.get("/health")
async def health_check():
    """Check the health of the session store services."""
    if shutdown_signal.is_set():
        return {"status": "shutting_down", "reason": "Application is shutting down"}

    try:
        # Get connection pool statistics
        pool_stats = MongoDBConnectionPool.get_pool_stats()

        return {
            "status": "healthy",
            "connection_pool": pool_stats,
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

    # session_store = get_session_store()
    # if not session_store:
    #     return {"status": "unhealthy", "reason": "Session store not initialized"}
    # health = await session_store.get_service_health()
    # return health


@app.get("/metrics")
async def get_metrics():
    """Get system metrics."""
    try:
        factory = get_global_factory()

        # Get connection pool statistics
        pool_stats = factory.get_connection_stats()

        return {"connection_pool": pool_stats}
    except Exception as e:
        logging.error(f"Error getting metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # """Get session store metrics."""
    # session_store = get_session_store()
    # if not session_store:
    #     raise HTTPException(status_code=503, detail="Session store not initialized")
    # metrics = await session_store.get_system_metrics()
    # return metrics


# Add this to handle running with uvicorn programmatically
if __name__ == "__main__":
    import uvicorn

    async def run():
        # Detect if running in Fargate or container with limited CPU
        import multiprocessing
        import os

        cpu_count = multiprocessing.cpu_count()
        # Check if we're in a container environment (Fargate/ECS)
        is_container = os.path.exists("/.dockerenv") or os.getenv(
            "ECS_CONTAINER_METADATA_URI"
        )

        # For Fargate with 1 CPU, use single worker with async concurrency
        if is_container and cpu_count <= 2:
            worker_count = 1  # Single worker for containers with limited CPU
            logging.info(
                f"Container environment detected with {cpu_count} CPU(s), using single worker with async concurrency"
            )
        else:
            # For multi-CPU environments, use multiple workers
            worker_count = max(2, min(4, cpu_count // 2))
            logging.info(
                f"Multi-CPU environment detected ({cpu_count} CPUs), using {worker_count} workers"
            )

        config = uvicorn.Config(
            app=app,
            host="0.0.0.0",
            port=8880,
            workers=worker_count,  # 1 worker for Fargate, multiple for multi-CPU
            loop="uvloop",  # Faster event loop (2-4x performance boost)
            reload=False,  # Disable reload to avoid issues with signal handling
            log_level="info",
            access_log=False,  # Disable access logs for better performance
            limit_concurrency=500,  # Concurrent connections (reduced for 1 CPU)
            timeout_keep_alive=5,  # Keep-alive timeout in seconds
            # Note: limit_max_requests only works with multiple workers
        )
        server = uvicorn.Server(config)

        # Handle shutdown properly
        await server.serve()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logging.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logging.error(f"Server error: {e}")
    finally:
        logging.info("Server stopped")
