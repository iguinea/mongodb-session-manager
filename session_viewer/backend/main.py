"""Session Viewer Backend - FastAPI Application.

This FastAPI application provides REST API endpoints for searching and viewing
MongoDB session data, with support for dynamic filtering, pagination, and
unified timeline visualization of multi-agent conversations.
"""

import logging
import sys
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

# Add parent directory to path to access src module
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mongodb_session_manager import (
    MongoDBConnectionPool,
    initialize_global_factory,
    close_global_factory,
    get_global_factory,
)

from config import settings
from models import (
    SessionSearchResponse,
    SessionPreview,
    SessionDetail,
    TimelineMessage,
    TimelineFeedback,
    TimelineItem,
    AgentSummary,
    MetadataFieldsResponse,
    HealthResponse,
    ConnectionPoolStats,
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(levelname)s:     %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================================
# Application Lifespan
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    # Startup
    logger.info("Starting Session Viewer Backend...")

    # Initialize the global MongoDB connection factory
    factory = initialize_global_factory(
        connection_string=settings.mongodb_connection_string,
        database_name=settings.database_name,
        collection_name=settings.collection_name,
        maxPoolSize=settings.max_pool_size,
        minPoolSize=settings.min_pool_size,
        maxIdleTimeMS=settings.max_idle_time_ms,
    )

    # Store factory in app state
    app.state.factory = factory

    # Get direct database access for queries
    app.state.collection = factory._client[settings.database_name][settings.collection_name]

    logger.info(
        f"MongoDB connection initialized - "
        f"Database: {settings.database_name}, "
        f"Collection: {settings.collection_name}"
    )

    yield  # Application runs

    # Shutdown
    logger.info("Shutting down Session Viewer Backend...")
    close_global_factory()
    logger.info("Cleanup complete")


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="Session Viewer API",
    description="REST API for viewing and analyzing MongoDB session data",
    version="0.1.16",
    lifespan=lifespan,
)

# CORS Middleware - DESARROLLO: Permitir todos los orígenes
# Para producción, cambiar allow_origins=["*"] por settings.allowed_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # Debe ser False cuando allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Authentication Middleware
# ============================================================================

@app.middleware("http")
async def password_middleware(request: Request, call_next):
    """Validate password for all requests except /health and /check_password."""
    # Exclude authentication endpoints
    excluded_paths = ["/health", "/api/v1/check_password"]

    if request.url.path in excluded_paths:
        return await call_next(request)

    # Validate X-Password header
    password_hash = request.headers.get("X-Password")

    if not password_hash:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing password header"}
        )

    # Generate expected hash from environment variable
    expected_password = settings.backend_password
    expected_hash = hashlib.sha256(expected_password.encode()).hexdigest()

    if password_hash != expected_hash:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid password"}
        )

    return await call_next(request)


# ============================================================================
# Helper Functions
# ============================================================================

def build_search_query(
    filters: Optional[str],
    session_id: Optional[str],
    created_at_start: Optional[datetime],
    created_at_end: Optional[datetime],
) -> Dict[str, Any]:
    """Build MongoDB query from search parameters.

    Args:
        filters: JSON string with metadata filters
        session_id: Session ID for partial matching
        created_at_start: Start date for date range
        created_at_end: End date for date range

    Returns:
        MongoDB query dictionary
    """
    import json

    query = {}

    # Parse and apply dynamic metadata filters
    if filters:
        try:
            filters_dict = json.loads(filters)
            for key, value in filters_dict.items():
                if key.startswith("metadata."):
                    # Case-insensitive partial matching for metadata fields
                    query[key] = {"$regex": str(value), "$options": "i"}
                else:
                    query[key] = value
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in filters parameter: {filters}")

    # Session ID partial matching
    if session_id:
        query["session_id"] = {"$regex": session_id, "$options": "i"}

    # Date range filtering
    if created_at_start or created_at_end:
        query["created_at"] = {}
        if created_at_start:
            query["created_at"]["$gte"] = created_at_start
        if created_at_end:
            query["created_at"]["$lte"] = created_at_end

    return query


def build_unified_timeline(session_doc: Dict[str, Any]) -> List[TimelineItem]:
    """Build unified chronological timeline from session document.

    Merges messages from all agents and feedbacks into a single
    chronologically ordered timeline.

    Args:
        session_doc: MongoDB session document

    Returns:
        List of timeline items (messages and feedbacks) sorted by timestamp
    """
    timeline = []

    # Extract messages from all agents
    agents = session_doc.get("agents", {})
    for agent_id, agent_data in agents.items():
        messages = agent_data.get("messages", [])
        for msg in messages:
            # Extract message data
            message_data = msg.get("message", {})
            role = message_data.get("role")
            content = message_data.get("content", [])

            timeline_msg = TimelineMessage(
                timestamp=msg.get("created_at"),
                agent_id=agent_id,
                role=role,
                content=content,
                message_id=msg.get("message_id", 0),
                metrics=msg.get("event_loop_metrics")
            )
            timeline.append(timeline_msg)

    # Extract feedbacks
    feedbacks = session_doc.get("feedbacks", [])
    for feedback in feedbacks:
        timeline_feedback = TimelineFeedback(
            timestamp=feedback.get("created_at"),
            rating=feedback.get("rating"),
            comment=feedback.get("comment")
        )
        timeline.append(timeline_feedback)

    # Sort chronologically by timestamp
    timeline.sort(key=lambda x: x.timestamp)

    return timeline


def get_metadata_fields(collection: Any) -> MetadataFieldsResponse:
    """Get available metadata fields from all sessions.

    Uses MongoDB aggregation pipeline to extract unique metadata field names
    and sample values across all documents.

    Args:
        collection: MongoDB collection

    Returns:
        MetadataFieldsResponse with fields and sample values
    """
    try:
        # Aggregation pipeline to extract metadata fields
        pipeline = [
            {"$project": {"metadata": {"$objectToArray": "$metadata"}}},
            {"$unwind": "$metadata"},
            {"$group": {
                "_id": "$metadata.k",
                "sample_values": {"$addToSet": "$metadata.v"}
            }},
            {"$project": {
                "field": "$_id",
                "sample_values": {"$slice": ["$sample_values", 10]}
            }}
        ]

        results = list(collection.aggregate(pipeline))

        fields = [r["field"] for r in results]
        sample_values = {r["field"]: r["sample_values"] for r in results}

        return MetadataFieldsResponse(
            fields=fields,
            sample_values=sample_values
        )

    except PyMongoError as e:
        logger.error(f"Error getting metadata fields: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve metadata fields")


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/api/v1/sessions/search", response_model=SessionSearchResponse)
async def search_sessions(
    filters: Optional[str] = Query(None, description="JSON string with metadata filters"),
    session_id: Optional[str] = Query(None, description="Session ID for partial matching"),
    created_at_start: Optional[datetime] = Query(None, description="Start date for filtering"),
    created_at_end: Optional[datetime] = Query(None, description="End date for filtering"),
    limit: int = Query(settings.default_page_size, ge=1, le=settings.max_page_size),
    offset: int = Query(0, ge=0),
):
    """Search sessions with dynamic filters and pagination.

    Supports:
    - Dynamic metadata field filtering with partial matching
    - Session ID partial matching
    - Date range filtering
    - Pagination with configurable page size

    Example filters JSON:
    ```json
    {
        "metadata.case_type": "IP_REAPERTURA",
        "metadata.customer_phone": "604"
    }
    ```
    """
    try:
        collection = app.state.collection

        # Build MongoDB query
        query = build_search_query(filters, session_id, created_at_start, created_at_end)

        logger.info(f"Searching sessions with query: {query}")

        # Get total count
        total = collection.count_documents(query)

        # Execute query with pagination
        cursor = collection.find(query).skip(offset).limit(limit).sort("created_at", -1)
        documents = list(cursor)

        # Build session previews
        sessions = []
        for doc in documents:
            # Count agents, messages, and feedbacks
            agents = doc.get("agents", {})
            agents_count = len(agents)

            messages_count = sum(
                len(agent_data.get("messages", []))
                for agent_data in agents.values()
            )

            feedbacks_count = len(doc.get("feedbacks", []))

            session_preview = SessionPreview(
                session_id=doc["session_id"],
                created_at=doc["created_at"],
                updated_at=doc["updated_at"],
                metadata=doc.get("metadata", {}),
                agents_count=agents_count,
                messages_count=messages_count,
                feedbacks_count=feedbacks_count,
            )
            sessions.append(session_preview)

        has_more = (offset + limit) < total

        logger.info(f"Found {total} sessions, returning {len(sessions)}")

        return SessionSearchResponse(
            sessions=sessions,
            total=total,
            limit=limit,
            offset=offset,
            has_more=has_more,
        )

    except Exception as e:
        logger.error(f"Error searching sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/sessions/{session_id}", response_model=SessionDetail)
async def get_session_detail(session_id: str):
    """Get complete session detail with unified timeline.

    Returns:
    - Session metadata
    - Unified chronological timeline of all messages and feedbacks
    - Summary of all agents with their configurations
    """
    try:
        collection = app.state.collection

        # Find session document
        session_doc = collection.find_one({"_id": session_id})

        if not session_doc:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        # Build unified timeline
        timeline = build_unified_timeline(session_doc)

        # Build agents summary
        agents_summary = {}
        agents = session_doc.get("agents", {})
        for agent_id, agent_data in agents.items():
            agent_info = agent_data.get("agent_data", {})
            messages_count = len(agent_data.get("messages", []))

            agents_summary[agent_id] = AgentSummary(
                messages_count=messages_count,
                model=agent_info.get("model"),
                system_prompt=agent_info.get("system_prompt"),
                created_at=agent_data.get("created_at"),
                updated_at=agent_data.get("updated_at"),
            )

        return SessionDetail(
            session_id=session_doc["session_id"],
            created_at=session_doc["created_at"],
            updated_at=session_doc["updated_at"],
            metadata=session_doc.get("metadata", {}),
            timeline=timeline,
            agents_summary=agents_summary,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/metadata-fields", response_model=MetadataFieldsResponse)
async def list_metadata_fields():
    """Get available metadata fields across all sessions.

    Returns all unique metadata field names and sample values
    to help users build dynamic filters.
    """
    try:
        collection = app.state.collection
        return get_metadata_fields(collection)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing metadata fields: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint.

    Verifies:
    - MongoDB connection status
    - Connection pool statistics
    """
    try:
        # Test MongoDB connection
        collection = app.state.collection
        collection.find_one({}, {"_id": 1})

        # Get connection pool stats
        pool_stats = MongoDBConnectionPool.get_pool_stats()

        return HealthResponse(
            status="healthy",
            mongodb="connected",
            connection_pool=ConnectionPoolStats(
                active_connections=pool_stats.get("active_connections"),
                available_connections=pool_stats.get("available_connections"),
                total_connections=pool_stats.get("total_connections"),
            )
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthResponse(
            status="unhealthy",
            mongodb="disconnected",
            error=str(e)
        )


@app.post("/api/v1/check_password")
async def check_password(request: Dict[str, Any]):
    """Validate password hash.

    Accepts a SHA-256 hash of the password and validates it against
    the configured PASSWORD environment variable.

    Args:
        request: Dictionary with "password_hash" key containing SHA-256 hash

    Returns:
        {"valid": True} if password is correct, {"valid": False} otherwise
    """
    try:
        password_hash = request.get("password_hash")

        if not password_hash:
            logger.warning("No password_hash in request")
            return {"valid": False}

        # Generate expected hash from environment variable
        expected_password = settings.backend_password
        expected_hash = hashlib.sha256(expected_password.encode()).hexdigest()

        # Debug logging
        #logger.info(f"Received hash: {password_hash}")
        #logger.info(f"Expected hash: {expected_hash}")
        #logger.info(f"Expected password from env: {expected_password}")

        is_valid = password_hash == expected_hash

        logger.info(f"Password validation: {'success' if is_valid else 'failed'}")

        return {"valid": is_valid}

    except Exception as e:
        logger.error(f"Error checking password: {e}")
        return {"valid": False}


# ============================================================================
# Run Application
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=settings.backend_host,
        port=settings.backend_port,
        log_level=settings.log_level.lower(),
    )
