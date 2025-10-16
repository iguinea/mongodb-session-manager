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
    FieldInfo,
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
    version="0.1.19",
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
    # Allow OPTIONS requests (CORS preflight) to pass through
    if request.method == "OPTIONS":
        return await call_next(request)

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


def get_indexed_fields(collection: Any) -> List[str]:
    """Extract field names from MongoDB collection indexes.

    This function queries all indexes on the collection and extracts
    the field names, excluding system indexes (_id, _fts, etc.).

    Args:
        collection: MongoDB collection object

    Returns:
        List of unique indexed field names

    Example:
        >>> get_indexed_fields(my_collection)
        ['session_id', 'created_at', 'metadata.status', 'metadata.priority']
    """
    indexed_fields = []

    try:
        indexes = collection.list_indexes()

        for index in indexes:
            index_name = index.get("name", "")

            # Skip system indexes
            if index_name.startswith("_"):
                continue

            # Extract field names from index keys
            # index["key"] is like: {"metadata.status": 1, "created_at": -1}
            for field_name, _ in index.get("key", {}).items():
                # Skip internal fields
                if field_name not in ["_id", "_fts", "_ftsx"]:
                    indexed_fields.append(field_name)

        # Remove duplicates and return
        unique_fields = list(set(indexed_fields))
        logger.info(f"Found {len(unique_fields)} unique indexed fields")
        return unique_fields

    except Exception as e:
        logger.error(f"Error listing indexes: {e}")
        return []


def detect_field_type(collection: Any, field_name: str) -> str:
    """Detect field data type by sampling documents.

    Analyzes up to 100 random documents to determine the most common
    data type for the field. Uses heuristics for type detection:
    - Convention-based: fields with "date" or "at" suffix → date
    - Sample-based: analyze actual values in documents

    Args:
        collection: MongoDB collection
        field_name: Full field name (e.g., "metadata.status")

    Returns:
        Type string: "string", "date", "number", "boolean"
        Priority order: boolean > number > date > string

    Example:
        >>> detect_field_type(collection, "metadata.priority")
        "string"
        >>> detect_field_type(collection, "created_at")
        "date"
    """
    # Convention-based detection for dates
    if "date" in field_name.lower() or field_name.endswith("_at"):
        return "date"

    # Sample documents to analyze actual values
    try:
        pipeline = [
            {"$match": {field_name: {"$exists": True, "$ne": None}}},
            {"$sample": {"size": 100}},
            {"$project": {field_name: 1}}
        ]

        samples = list(collection.aggregate(pipeline))

        if not samples:
            return "string"  # Default if no samples

        # Analyze types found in samples
        types_found = set()

        for doc in samples:
            # Navigate nested fields (e.g., "metadata.status")
            value = doc
            for part in field_name.split("."):
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break

            if value is None:
                continue

            # Determine Python type
            if isinstance(value, bool):
                types_found.add("boolean")
            elif isinstance(value, (int, float)):
                types_found.add("number")
            elif isinstance(value, datetime):
                types_found.add("date")
            else:
                types_found.add("string")

        # Return most specific type (priority order)
        if "boolean" in types_found:
            return "boolean"
        elif "number" in types_found:
            return "number"
        elif "date" in types_found:
            return "date"
        else:
            return "string"

    except Exception as e:
        logger.warning(f"Error detecting type for {field_name}: {e}")
        return "string"  # Safe default


def get_enum_values(
    collection: Any,
    field_name: str,
    max_values: int
) -> Optional[List[Any]]:
    """Get distinct values for a field to use as enum options.

    Retrieves all unique values for the field. If the count exceeds
    max_values, returns None (too many values, not suitable for enum).

    Args:
        collection: MongoDB collection
        field_name: Full field name (e.g., "metadata.status")
        max_values: Maximum number of values allowed for enum

    Returns:
        Sorted list of distinct values if count <= max_values
        None if too many values or error

    Example:
        >>> get_enum_values(collection, "metadata.status", 50)
        ["active", "completed", "failed", "pending"]

        >>> get_enum_values(collection, "metadata.customer_id", 50)
        None  # Too many unique customer IDs
    """
    try:
        # Get distinct values for the field
        distinct_values = collection.distinct(field_name)

        # Check if count is within limit
        if len(distinct_values) > max_values:
            logger.info(
                f"Field {field_name} has {len(distinct_values)} values "
                f"(exceeds limit of {max_values}), treating as regular field"
            )
            return None

        # Sort values for consistent display
        # Convert to string for sorting to handle mixed types
        sorted_values = sorted(distinct_values, key=lambda x: str(x))

        logger.debug(f"Field {field_name} enum values: {sorted_values}")
        return sorted_values

    except Exception as e:
        logger.warning(f"Error getting enum values for {field_name}: {e}")
        return None


def get_metadata_fields(collection: Any) -> MetadataFieldsResponse:
    """Get indexed fields with type information and enum values.

    This function replaces the old aggregation-based approach with
    an index-based approach that:
    1. Lists all indexes on the collection
    2. Extracts field names from indexes
    3. Detects data type for each field
    4. Retrieves enum values for configured enum fields

    Args:
        collection: MongoDB collection

    Returns:
        MetadataFieldsResponse with FieldInfo objects

    Raises:
        HTTPException: If unable to retrieve field information

    Example Response:
        {
          "fields": [
            {"field": "session_id", "type": "string"},
            {"field": "created_at", "type": "date"},
            {
              "field": "metadata.status",
              "type": "enum",
              "values": ["active", "completed"]
            }
          ]
        }
    """
    try:
        # Step 1: Get indexed fields
        indexed_fields = get_indexed_fields(collection)

        logger.info(f"Found {len(indexed_fields)} indexed fields")

        # Step 2: Build FieldInfo for each indexed field
        field_infos = []

        for field_name in indexed_fields:
            # Detect base type
            field_type = detect_field_type(collection, field_name)

            # Check if field should be treated as enum
            values = None
            if field_name in settings.enum_fields:
                logger.info(f"Checking enum values for configured field: {field_name}")
                values = get_enum_values(
                    collection,
                    field_name,
                    settings.enum_max_values
                )

                # Only set type to enum if values were successfully retrieved
                if values:
                    field_type = "enum"
                    logger.info(
                        f"Field {field_name} configured as enum with "
                        f"{len(values)} values"
                    )
                else:
                    logger.warning(
                        f"Field {field_name} configured as enum but has too "
                        f"many values or error, treating as {field_type}"
                    )

            # Create FieldInfo object
            field_info = FieldInfo(
                field=field_name,
                type=field_type,
                values=values
            )
            field_infos.append(field_info)

        # Sort fields alphabetically by field name for better UX
        field_infos.sort(key=lambda f: f.field.lower())

        logger.info(f"Returning {len(field_infos)} fields with type information")

        return MetadataFieldsResponse(fields=field_infos)

    except Exception as e:
        logger.error(f"Error getting metadata fields: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve metadata fields: {str(e)}"
        )


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
    """Get indexed fields with type information.

    Returns all fields that have MongoDB indexes, along with their
    detected data types and enum values (if configured).

    This endpoint now returns structured FieldInfo objects instead of
    plain field names. Frontend uses this to render appropriate input
    controls (text, date, number, enum dropdown).

    Configuration:
    - ENUM_FIELDS_STR: Comma-separated list of fields to treat as enums
    - ENUM_MAX_VALUES: Maximum distinct values for enum detection

    Example Response:
        {
          "fields": [
            {"field": "session_id", "type": "string"},
            {"field": "created_at", "type": "date"},
            {"field": "metadata.status", "type": "enum", "values": ["active", "completed"]}
          ]
        }
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

        # logger.info(f"Password validation: {'success' if is_valid else 'failed'}")

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
