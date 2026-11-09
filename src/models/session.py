"""Session domain models, state enums, and request/response schemas."""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


class SessionState(str, Enum):
    """Permitted session lifecycle states."""
    CREATED = "created"
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class SessionEvent(BaseModel):
    """An event recorded within a session lifecycle."""
    event_id: str = Field(
        default_factory=lambda: f"evt-{uuid.uuid4().hex[:10]}",
        description="Unique event ID",
    )
    event_type: str = Field(..., description="Type of event, e.g. session_created, state_change")
    session_id: Optional[str] = Field(default=None, description="Session ID associated with event")
    correlation_id: Optional[str] = Field(default=None, description="Correlation ID for traceability")
    sequence_number: int = Field(default=1, description="Strict incremental sequence number within session")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Event data")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp of event occurrence",
    )


class Session(BaseModel):
    """Internal entity representing an active or historic session."""
    session_id: str = Field(..., description="Unique identifier for the session")
    state: SessionState = Field(default=SessionState.CREATED, description="Current lifecycle state")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Session creation timestamp",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Session last update timestamp",
    )
    expires_at: Optional[str] = Field(
        default=None,
        description="Session calculated expiration timestamp based on TTL",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom contextual metadata")
    events: List[SessionEvent] = Field(default_factory=list, description="Ordered audit/mock event stream")


class SessionCreateRequest(BaseModel):
    """Request schema to initialize a new session."""
    session_id: Optional[str] = Field(
        default=None,
        description="Optional custom session ID; auto-generated if omitted",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Initial session metadata (e.g. application, user)",
    )


class SessionTransitionRequest(BaseModel):
    """Request schema to change a session's state."""
    to_state: SessionState = Field(..., description="Target lifecycle state to transition to")
    reason: Optional[str] = Field(
        default=None,
        description="Optional explanation for state transition",
    )


class SessionPauseRequest(BaseModel):
    """Request schema to pause an active session."""
    reason: Optional[str] = Field(
        default="User paused session",
        description="Reason for pausing the session",
    )


class SessionResumeRequest(BaseModel):
    """Request schema to resume a paused session."""
    reason: Optional[str] = Field(
        default="User resumed session",
        description="Reason for resuming the session",
    )


class SessionStopRequest(BaseModel):
    """Request schema to gracefully stop a session."""
    reason: Optional[str] = Field(
        default="User stopped session",
        description="Reason for stopping the session",
    )


class SessionEventCreateRequest(BaseModel):
    """Request schema to push a mock event into a session."""
    event_type: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Type of mock event (e.g., voice_input, agent_plan)",
    )
    payload: Dict[str, Any] = Field(default_factory=dict, description="Payload data for the event")


class SessionResponse(BaseModel):
    """API response schema for a session object."""
    session_id: str
    state: SessionState
    created_at: str
    updated_at: str
    expires_at: Optional[str] = None
    metadata: Dict[str, Any]
    events_count: int
    events: List[SessionEvent]


class SessionListResponse(BaseModel):
    """API response schema for session listings."""
    total: int
    sessions: List[SessionResponse]


class SessionEventsResponse(BaseModel):
    """API response schema for session event retrieval."""
    session_id: str
    events_count: int
    events: List[SessionEvent]
