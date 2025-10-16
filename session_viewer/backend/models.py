"""Pydantic models for Session Viewer API requests and responses."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ============================================================================
# Search Models
# ============================================================================

class SessionPreview(BaseModel):
    """Preview of a session in search results."""

    session_id: str = Field(..., description="Unique session identifier")
    created_at: datetime = Field(..., description="Session creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Session metadata")
    agents_count: int = Field(..., description="Number of agents in session")
    messages_count: int = Field(..., description="Total number of messages")
    feedbacks_count: int = Field(..., description="Number of feedbacks")


class SessionSearchResponse(BaseModel):
    """Response for session search with pagination."""

    sessions: List[SessionPreview] = Field(..., description="List of matching sessions")
    total: int = Field(..., description="Total number of matching sessions")
    limit: int = Field(..., description="Results per page limit")
    offset: int = Field(..., description="Current offset")
    has_more: bool = Field(..., description="Whether there are more results")


# ============================================================================
# Session Detail Models
# ============================================================================

class MessageContent(BaseModel):
    """Content of a message."""

    text: Optional[str] = None
    toolUse: Optional[Dict[str, Any]] = None
    toolResult: Optional[Dict[str, Any]] = None


class TimelineMessage(BaseModel):
    """Message in the timeline."""

    type: Literal["message"] = "message"
    timestamp: datetime = Field(..., description="Message timestamp")
    agent_id: str = Field(..., description="Agent identifier")
    role: Literal["user", "assistant"] = Field(..., description="Message role")
    content: List[Dict[str, Any]] = Field(..., description="Message content")
    message_id: int = Field(..., description="Message ID within agent conversation")
    metrics: Optional[Dict[str, Any]] = Field(None, description="Event loop metrics if available")


class TimelineFeedback(BaseModel):
    """Feedback in the timeline."""

    type: Literal["feedback"] = "feedback"
    timestamp: datetime = Field(..., description="Feedback timestamp")
    rating: Optional[Literal["up", "down"]] = Field(None, description="Feedback rating")
    comment: Optional[str] = Field(None, description="Feedback comment")


# Union type for timeline items
TimelineItem = TimelineMessage | TimelineFeedback


class AgentSummary(BaseModel):
    """Summary information about an agent."""

    messages_count: int = Field(..., description="Number of messages from this agent")
    model: Optional[str] = Field(None, description="Model used by agent")
    system_prompt: Optional[str] = Field(None, description="System prompt")
    created_at: Optional[datetime] = Field(None, description="Agent creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Agent last update timestamp")


class SessionDetail(BaseModel):
    """Complete session detail with unified timeline."""

    session_id: str = Field(..., description="Unique session identifier")
    created_at: datetime = Field(..., description="Session creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Session metadata")
    timeline: List[TimelineItem] = Field(..., description="Unified chronological timeline")
    agents_summary: Dict[str, AgentSummary] = Field(..., description="Summary of all agents")


# ============================================================================
# Metadata Fields Models
# ============================================================================

class FieldInfo(BaseModel):
    """Information about an indexed field.

    Attributes:
        field: Full field name (e.g., "metadata.status", "created_at")
        type: Detected field type (string, date, number, boolean, enum)
        values: Possible values for enum fields (None for other types)

    Example:
        {
          "field": "metadata.status",
          "type": "enum",
          "values": ["active", "completed", "failed"]
        }
    """
    field: str = Field(..., description="Field name")
    type: Literal["string", "date", "number", "boolean", "enum"] = Field(
        ...,
        description="Detected field type"
    )
    values: Optional[List[Any]] = Field(
        None,
        description="Possible values for enum fields"
    )


class MetadataFieldsResponse(BaseModel):
    """Available indexed fields with type information.

    This model replaces the old structure that returned plain field names
    and sample values. Now returns structured FieldInfo objects with
    type information for better frontend rendering.
    """

    fields: List[FieldInfo] = Field(..., description="List of indexed fields with type info")


# ============================================================================
# Health Check Models
# ============================================================================

class ConnectionPoolStats(BaseModel):
    """MongoDB connection pool statistics."""

    active_connections: Optional[int] = None
    available_connections: Optional[int] = None
    total_connections: Optional[int] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: Literal["healthy", "unhealthy"] = Field(..., description="Service status")
    mongodb: Literal["connected", "disconnected"] = Field(..., description="MongoDB connection status")
    connection_pool: Optional[ConnectionPoolStats] = Field(None, description="Connection pool stats")
    error: Optional[str] = Field(None, description="Error message if unhealthy")
