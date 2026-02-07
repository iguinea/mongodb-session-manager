"""Session Viewer Backend - FastAPI Application.

This FastAPI application provides REST API endpoints for searching and viewing
MongoDB session data, with support for dynamic filtering, pagination, and
unified timeline visualization of multi-agent conversations.
"""

import logging
import sys
import hashlib
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Add parent directory to path to access src module
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mongodb_session_manager import (
    MongoDBConnectionPool,
    initialize_global_factory,
    close_global_factory,
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


# ============================================================================
# Structured Logging Configuration
# ============================================================================

def configure_logging():
    """Configure logging based on settings.

    Supports two formats:
    - "json": Structured JSON logging for CloudWatch Insights (production)
    - "text": Human-readable format for development
    """
    log_level = getattr(logging, settings.log_level.upper())

    if settings.log_format.lower() == "json":
        from pythonjsonlogger import jsonlogger

        class CustomJsonFormatter(jsonlogger.JsonFormatter):
            """Custom JSON formatter with service context."""

            def add_fields(self, log_record, record, message_dict):
                super().add_fields(log_record, record, message_dict)
                log_record['timestamp'] = datetime.now(timezone.utc).isoformat()
                log_record['service'] = settings.log_service_name
                log_record['environment'] = settings.log_environment
                log_record['level'] = record.levelname
                log_record.pop('levelname', None)

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(CustomJsonFormatter(
            '%(timestamp)s %(level)s %(name)s %(message)s'
        ))

        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.addHandler(handler)
        root_logger.setLevel(log_level)

        for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
            uvicorn_logger = logging.getLogger(logger_name)
            uvicorn_logger.handlers.clear()
            uvicorn_logger.addHandler(handler)

    else:
        logging.basicConfig(
            level=log_level,
            format="%(levelname)s:     %(message)s",
            force=True
        )


# Initialize logging
configure_logging()
logger = logging.getLogger(__name__)


# ============================================================================
# Security Helpers (CWE-209, CWE-532)
# ============================================================================

def sanitize_query_for_logging(query: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize MongoDB query for safe logging.

    Prevents sensitive data exposure in logs (CWE-532).
    """
    import copy

    if not query:
        return {}

    safe_query = copy.deepcopy(query)

    for key, value in safe_query.items():
        if isinstance(value, dict):
            if "$regex" in value:
                pattern = value["$regex"]
                if len(pattern) > 20:
                    value["$regex"] = pattern[:20] + "..."
        elif isinstance(value, str):
            if len(value) > 20:
                safe_query[key] = value[:20] + "..."

    return safe_query


def truncate_session_id(session_id: str) -> str:
    """Truncate session ID for safe logging (CWE-532)."""
    if not session_id:
        return "<empty>"
    if len(session_id) <= 8:
        return session_id
    return session_id[:8] + "..."


def generate_error_response(
    status_code: int,
    error: Exception,
    context: str = "operation"
) -> tuple[str, str]:
    """Generate safe error response with request ID for correlation (CWE-209)."""
    request_id = str(uuid.uuid4())[:8]

    logger.error(
        f"[{request_id}] Error in {context}: {type(error).__name__}: {error}",
        exc_info=True
    )

    messages = {
        400: "Invalid request parameters",
        401: "Authentication required",
        403: "Access denied",
        404: "Resource not found",
        500: "An internal error occurred. Please try again later.",
    }

    generic_message = messages.get(status_code, "An error occurred")

    return request_id, generic_message


# ============================================================================
# Application Lifespan
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    logger.info("Starting Session Viewer Backend...")

    factory = initialize_global_factory(
        connection_string=settings.mongodb_connection_string,
        database_name=settings.database_name,
        collection_name=settings.collection_name,
        maxPoolSize=settings.max_pool_size,
        minPoolSize=settings.min_pool_size,
        maxIdleTimeMS=settings.max_idle_time_ms,
        retryWrites=False,
    )

    app.state.factory = factory
    app.state.collection = factory._client[settings.database_name][settings.collection_name]

    logger.info(
        f"MongoDB connection initialized - "
        f"Database: {settings.database_name}, "
        f"Collection: {settings.collection_name}"
    )

    yield

    logger.info("Shutting down Session Viewer Backend...")
    close_global_factory()
    logger.info("Cleanup complete")


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="Session Viewer API",
    description="REST API for viewing and analyzing MongoDB session data",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
    max_age=3600,
)

# ============================================================================
# Security Headers Middleware (CWE-693 Prevention)
# ============================================================================

if settings.security_headers_enabled:
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        """Add security headers to all HTTP responses."""
        response = await call_next(request)

        response.headers["X-Frame-Options"] = settings.x_frame_options
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = settings.content_security_policy
        response.headers["Referrer-Policy"] = settings.referrer_policy
        response.headers["Permissions-Policy"] = settings.permissions_policy

        if "server" in response.headers:
            del response.headers["server"]

        return response

    logger.info("Security headers middleware enabled")
else:
    logger.warning("Security headers middleware DISABLED - not recommended for production")


# ============================================================================
# Rate Limiting (CWE-307 Prevention)
# ============================================================================

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

logger.info(
    f"Rate limiting configured - Auth: {settings.rate_limit_auth}, "
    f"Search: {settings.rate_limit_search}, Read: {settings.rate_limit_read}, "
    f"Metadata: {settings.rate_limit_metadata}"
)


# ============================================================================
# Frontend Static Files (Served via Endpoints)
# ============================================================================

frontend_path = Path(__file__).parent.parent / "frontend"


def get_frontend_file_path(filename: str) -> Optional[Path]:
    """Get safe path to frontend file, validating it exists within frontend directory."""
    file_path = (frontend_path / filename).resolve()
    if not str(file_path).startswith(str(frontend_path.resolve())):
        return None
    return file_path if file_path.exists() else None


@app.get("/")
async def serve_index():
    """Serve index.html at root path."""
    try:
        file_path = get_frontend_file_path("index.html")
        if not file_path:
            raise HTTPException(status_code=404, detail="index.html not found")
        return FileResponse(str(file_path), media_type="text/html")
    except Exception as e:
        logger.error(f"Error serving index.html: {e}")
        raise HTTPException(status_code=500, detail="Failed to serve index.html")


@app.get("/components.js")
async def serve_components_js():
    """Serve components.js JavaScript file."""
    try:
        file_path = get_frontend_file_path("components.js")
        if not file_path:
            raise HTTPException(status_code=404, detail="components.js not found")
        return FileResponse(str(file_path), media_type="application/javascript")
    except Exception as e:
        logger.error(f"Error serving components.js: {e}")
        raise HTTPException(status_code=500, detail="Failed to serve components.js")


@app.get("/viewer.js")
async def serve_viewer_js():
    """Serve viewer.js JavaScript file."""
    try:
        file_path = get_frontend_file_path("viewer.js")
        if not file_path:
            raise HTTPException(status_code=404, detail="viewer.js not found")
        return FileResponse(str(file_path), media_type="application/javascript")
    except Exception as e:
        logger.error(f"Error serving viewer.js: {e}")
        raise HTTPException(status_code=500, detail="Failed to serve viewer.js")


if frontend_path.exists():
    logger.info(f"Frontend files will be served via endpoints from {frontend_path}")
else:
    logger.warning(f"Frontend directory not found at {frontend_path}")


# ============================================================================
# Authentication Middleware
# ============================================================================

@app.middleware("http")
async def password_middleware(request: Request, call_next):
    """Validate password for all requests except /health, /check_password, and frontend routes.

    Supports dual authentication:
    1. X-Session-Password: Session-specific password for direct access
    2. X-Password: Global password for authenticated access
    """
    if request.method == "OPTIONS":
        return await call_next(request)

    excluded_paths = ["/health", "/api/session_viewer/v1/check_password", "/", "/components.js", "/viewer.js"]

    if request.url.path in excluded_paths or request.url.path.endswith("/check_password"):
        return await call_next(request)

    session_password_hash = request.headers.get("X-Session-Password")
    if session_password_hash:
        path_parts = request.url.path.split("/")

        if len(path_parts) >= 6 and path_parts[1] == "api" and path_parts[2] == "session_viewer" and path_parts[3] == "v1" and path_parts[4] == "sessions":
            session_id = path_parts[5]

            is_valid, used_global = validate_session_password(session_id, session_password_hash)
            if is_valid:
                logger.debug(f"Session password authentication successful for {session_id}")
                return await call_next(request)
            else:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid session password"}
                )
        else:
            return JSONResponse(
                status_code=403,
                content={"detail": "Session password only grants access to specific session"}
            )

    password_hash = request.headers.get("X-Password")

    if not password_hash:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing password header"}
        )

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

def validate_session_password(session_id: str, password_hash: str) -> tuple[bool, bool]:
    """Validate session-specific password with fallback to global password."""
    try:
        collection = app.state.collection

        session_doc = collection.find_one({"_id": session_id}, {"session_viewer_password": 1})

        if session_doc and "session_viewer_password" in session_doc:
            expected_hash = hashlib.sha256(session_doc["session_viewer_password"].encode()).hexdigest()
            if password_hash == expected_hash:
                logger.debug(f"Session password validated for {session_id}")
                return (True, False)

        expected_password = settings.backend_password
        expected_hash = hashlib.sha256(expected_password.encode()).hexdigest()

        if password_hash == expected_hash:
            logger.debug(f"Global password used for session {session_id}")
            return (True, True)

        return (False, False)

    except Exception as e:
        logger.error(f"Error validating session password for {truncate_session_id(session_id)}: {e}")
        return (False, False)


def build_search_query(
    filters: Optional[str],
    session_id: Optional[str],
    created_at_start: Optional[datetime],
    created_at_end: Optional[datetime],
) -> Dict[str, Any]:
    """Build MongoDB query from search parameters.

    All regex values are sanitized with re.escape() to prevent NoSQL injection.
    """
    import json
    import re

    query = {}

    if filters:
        try:
            filters_dict = json.loads(filters)
            for key, value in filters_dict.items():
                if key.startswith("metadata."):
                    safe_value = re.escape(str(value))
                    query[key] = {"$regex": safe_value, "$options": "i"}
                else:
                    query[key] = str(value)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in filters parameter: {filters}")

    if session_id:
        safe_session_id = re.escape(session_id)
        query["session_id"] = {"$regex": safe_session_id, "$options": "i"}

    if created_at_start or created_at_end:
        query["created_at"] = {}
        if created_at_start:
            query["created_at"]["$gte"] = created_at_start
        if created_at_end:
            query["created_at"]["$lte"] = created_at_end

    return query


def build_unified_timeline(session_doc: Dict[str, Any]) -> List[TimelineItem]:
    """Build unified chronological timeline from session document."""
    timeline = []

    agents = session_doc.get("agents", {})
    for agent_id, agent_data in agents.items():
        messages = agent_data.get("messages", [])
        for msg in messages:
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

    feedbacks = session_doc.get("feedbacks", [])
    for feedback in feedbacks:
        timeline_feedback = TimelineFeedback(
            timestamp=feedback.get("created_at"),
            rating=feedback.get("rating"),
            comment=feedback.get("comment")
        )
        timeline.append(timeline_feedback)

    timeline.sort(key=lambda x: x.timestamp)

    return timeline


def get_indexed_fields(collection: Any) -> List[str]:
    """Extract field names from MongoDB collection indexes."""
    indexed_fields = []

    try:
        indexes = collection.list_indexes()

        for index in indexes:
            index_name = index.get("name", "")

            if index_name.startswith("_"):
                continue

            for field_name, _ in index.get("key", {}).items():
                if field_name not in ["_id", "_fts", "_ftsx"]:
                    indexed_fields.append(field_name)

        unique_fields = list(set(indexed_fields))
        logger.info(f"Found {len(unique_fields)} unique indexed fields")
        return unique_fields

    except Exception as e:
        logger.error(f"Error listing indexes: {e}")
        return []


def detect_field_type(collection: Any, field_name: str) -> str:
    """Detect field data type by sampling documents."""
    if "date" in field_name.lower() or field_name.endswith("_at"):
        return "date"

    try:
        pipeline = [
            {"$match": {field_name: {"$exists": True, "$ne": None}}},
            {"$sample": {"size": 100}},
            {"$project": {field_name: 1}}
        ]

        samples = list(collection.aggregate(pipeline))

        if not samples:
            return "string"

        types_found = set()

        for doc in samples:
            value = doc
            for part in field_name.split("."):
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break

            if value is None:
                continue

            if isinstance(value, bool):
                types_found.add("boolean")
            elif isinstance(value, (int, float)):
                types_found.add("number")
            elif isinstance(value, datetime):
                types_found.add("date")
            else:
                types_found.add("string")

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
        return "string"


def get_enum_values(
    collection: Any,
    field_name: str,
    max_values: int
) -> Optional[List[Any]]:
    """Get distinct values for a field to use as enum options."""
    try:
        distinct_values = collection.distinct(field_name)

        if len(distinct_values) > max_values:
            logger.info(
                f"Field {field_name} has {len(distinct_values)} values "
                f"(exceeds limit of {max_values}), treating as regular field"
            )
            return None

        sorted_values = sorted(distinct_values, key=lambda x: str(x))

        logger.debug(f"Field {field_name} enum values: {sorted_values}")
        return sorted_values

    except Exception as e:
        logger.warning(f"Error getting enum values for {field_name}: {e}")
        return None


def get_metadata_fields(collection: Any) -> MetadataFieldsResponse:
    """Get indexed fields with type information and enum values."""
    try:
        indexed_fields = get_indexed_fields(collection)

        logger.info(f"Found {len(indexed_fields)} indexed fields")

        field_infos = []

        for field_name in indexed_fields:
            field_type = detect_field_type(collection, field_name)

            values = None
            if field_name in settings.enum_fields:
                logger.info(f"Checking enum values for configured field: {field_name}")
                values = get_enum_values(
                    collection,
                    field_name,
                    settings.enum_max_values
                )

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

            field_info = FieldInfo(
                field=field_name,
                type=field_type,
                values=values
            )
            field_infos.append(field_info)

        field_infos.sort(key=lambda f: f.field.lower())

        logger.info(f"Returning {len(field_infos)} fields with type information")

        return MetadataFieldsResponse(fields=field_infos)

    except Exception as e:
        request_id, message = generate_error_response(500, e, "get_metadata_fields")
        raise HTTPException(
            status_code=500,
            detail=f"{message} [ref: {request_id}]"
        )


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/api/session_viewer/v1/sessions/search", response_model=SessionSearchResponse)
@limiter.limit(settings.rate_limit_search)
async def search_sessions(
    request: Request,
    filters: Optional[str] = Query(None, description="JSON string with metadata filters"),
    session_id: Optional[str] = Query(None, description="Session ID for partial matching"),
    created_at_start: Optional[datetime] = Query(None, description="Start date for filtering"),
    created_at_end: Optional[datetime] = Query(None, description="End date for filtering"),
    limit: int = Query(settings.default_page_size, ge=1, le=settings.max_page_size),
    offset: int = Query(0, ge=0),
):
    """Search sessions with dynamic filters and pagination."""
    try:
        collection = app.state.collection

        query = build_search_query(filters, session_id, created_at_start, created_at_end)

        logger.info(f"Searching sessions with query: {sanitize_query_for_logging(query)}")

        total = collection.count_documents(query)

        cursor = collection.find(query).skip(offset).limit(limit).sort("created_at", -1)
        documents = list(cursor)

        sessions = []
        for doc in documents:
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
        request_id, message = generate_error_response(500, e, "search_sessions")
        raise HTTPException(status_code=500, detail=f"{message} [ref: {request_id}]")


@app.get("/api/session_viewer/v1/sessions/{session_id}", response_model=SessionDetail)
@limiter.limit(settings.rate_limit_read)
async def get_session_detail(request: Request, session_id: str):
    """Get complete session detail with unified timeline."""
    try:
        collection = app.state.collection

        session_doc = collection.find_one({"_id": session_id})

        if not session_doc:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        timeline = build_unified_timeline(session_doc)

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
        request_id, message = generate_error_response(500, e, "get_session_detail")
        raise HTTPException(status_code=500, detail=f"{message} [ref: {request_id}]")


@app.get("/api/session_viewer/v1/metadata-fields", response_model=MetadataFieldsResponse)
@limiter.limit(settings.rate_limit_metadata)
async def list_metadata_fields(request: Request):
    """Get indexed fields with type information."""
    try:
        collection = app.state.collection
        return get_metadata_fields(collection)

    except HTTPException:
        raise
    except Exception as e:
        request_id, message = generate_error_response(500, e, "list_metadata_fields")
        raise HTTPException(status_code=500, detail=f"{message} [ref: {request_id}]")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    try:
        collection = app.state.collection
        collection.find_one({}, {"_id": 1})

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


@app.post("/api/session_viewer/v1/sessions/{session_id}/check_password")
@limiter.limit(settings.rate_limit_auth)
async def check_session_password(request: Request, session_id: str, body: Dict[str, Any]):
    """Validate session-specific password for direct session access."""
    try:
        password_hash = body.get("password_hash")

        if not password_hash:
            logger.warning(f"No password_hash in request for session {truncate_session_id(session_id)}")
            return {"valid": False, "used_global": False}

        is_valid, used_global = validate_session_password(session_id, password_hash)

        return {
            "valid": is_valid,
            "used_global": used_global
        }

    except Exception as e:
        logger.error(f"Error checking session password for {truncate_session_id(session_id)}: {e}")
        return {"valid": False, "used_global": False}


@app.post("/api/session_viewer/v1/check_password")
@limiter.limit(settings.rate_limit_auth)
async def check_password(request: Request, body: Dict[str, Any]):
    """Validate password hash."""
    try:
        password_hash = body.get("password_hash")

        if not password_hash:
            logger.warning("No password_hash in request")
            return {"valid": False}

        expected_password = settings.backend_password
        expected_hash = hashlib.sha256(expected_password.encode()).hexdigest()

        is_valid = password_hash == expected_hash

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
