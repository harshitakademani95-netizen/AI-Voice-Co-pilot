"""Session lifecycle and mock route handlers."""
from typing import Optional
from fastapi import APIRouter, Query, status

from src.models.session import (
    SessionCreateRequest,
    SessionEvent,
    SessionEventCreateRequest,
    SessionListResponse,
    SessionResponse,
    SessionState,
    SessionTransitionRequest,
)
from src.repositories.session_repository import session_repository

router = APIRouter(prefix="/sessions", tags=["Sessions"])


def _to_response(session) -> SessionResponse:
    """Converts a Session model to SessionResponse."""
    return SessionResponse(
        session_id=session.session_id,
        state=session.state,
        created_at=session.created_at,
        updated_at=session.updated_at,
        metadata=session.metadata,
        events_count=len(session.events),
        events=session.events,
    )


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new session",
    description="Initializes a session in the 'created' state with optional metadata.",
)
async def create_session(request: Optional[SessionCreateRequest] = None) -> SessionResponse:
    """Creates a new session in the in-memory repository."""
    req = request or SessionCreateRequest()
    session = session_repository.create(
        session_id=req.session_id,
        metadata=req.metadata,
    )
    return _to_response(session)


@router.get(
    "",
    response_model=SessionListResponse,
    summary="List all sessions",
    description="Retrieves all sessions currently held in the in-memory repository.",
)
async def list_sessions(
    state: Optional[SessionState] = Query(default=None, description="Filter sessions by state"),
) -> SessionListResponse:
    """Lists in-memory sessions with optional state filtering."""
    sessions = session_repository.list_all()
    if state:
        sessions = [s for s in sessions if s.state == state]
    return SessionListResponse(
        total=len(sessions),
        sessions=[_to_response(s) for s in sessions],
    )


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Retrieve session information",
    description="Fetches state, metadata, and event history for a given session ID.",
)
async def get_session(session_id: str) -> SessionResponse:
    """Retrieves session information. Returns 404 with typed error if not found."""
    session = session_repository.get(session_id)
    return _to_response(session)


@router.post(
    "/{session_id}/transition",
    response_model=SessionResponse,
    summary="Transition session state",
    description="Enforces lifecycle state machine transitions (created, active, paused, stopping, completed, failed, expired).",
)
async def transition_session(
    session_id: str,
    request: SessionTransitionRequest,
) -> SessionResponse:
    """Transitions a session's state adhering to enforced transition rules."""
    session = session_repository.transition(
        session_id=session_id,
        to_state=request.to_state,
        reason=request.reason,
    )
    return _to_response(session)


@router.post(
    "/{session_id}/events",
    response_model=SessionEvent,
    status_code=status.HTTP_201_CREATED,
    summary="Record a mock event in session",
    description="Appends a mock event (e.g. voice_transcription, agent_plan) into the session event stream.",
)
async def record_session_event(
    session_id: str,
    request: SessionEventCreateRequest,
) -> SessionEvent:
    """Records an event in the session event log."""
    return session_repository.add_event(
        session_id=session_id,
        event_type=request.event_type,
        payload=request.payload,
    )


@router.post(
    "/mock/quickstart",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Quickstart mock session",
    description="Creates a session, transitions it to 'active', and fires an initial mock voice transcription event.",
)
async def quickstart_mock_session() -> SessionResponse:
    """Demo route to showcase an end-to-end mock session flow in a single call."""
    session = session_repository.create(
        metadata={"mock_flow": "quickstart", "client": "ai-copilot-mock-client"}
    )
    session = session_repository.transition(
        session_id=session.session_id,
        to_state=SessionState.ACTIVE,
        reason="Mock user speech initiated",
    )
    session_repository.add_event(
        session_id=session.session_id,
        event_type="mock_voice_transcript",
        payload={
            "transcript": "Explain this python error in my terminal",
            "confidence": 0.98,
            "language": "en",
        },
    )
    updated_session = session_repository.get(session.session_id)
    return _to_response(updated_session)
