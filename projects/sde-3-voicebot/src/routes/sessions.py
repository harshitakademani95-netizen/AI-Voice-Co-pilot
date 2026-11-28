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


# =============================================================================
# Week 3 Day 21 – Integrated AudioPipeline & Agentic Workflow Routes
# =============================================================================

@router.post(
    "/{session_id}/audio/init",
    response_model=SessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Initialize integrated AudioPipeline and STT Bridge for session",
)
async def init_session_audio(session_id: str) -> SessionResponse:
    """Wires AudioPipeline and STT bridge to the existing session repository (Section 3)."""
    from src.audio.backend_integration import audio_backend_manager
    session = session_repository.get(session_id)
    audio_backend_manager.init_audio_pipeline(
        session_id=session.session_id,
        correlation_id=session.metadata.get("correlation_id"),
    )
    return _to_response(session_repository.get(session_id))


@router.post(
    "/{session_id}/audio/process",
    response_model=SessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Process audio stream through AudioPipeline -> STT Bridge -> Repository",
)
async def process_session_audio(
    session_id: str,
    speech_chunks: int = Query(5, description="Number of speech chunks"),
    silence_chunks: int = Query(4, description="Number of silence debounce chunks"),
) -> SessionResponse:
    """Executes capture -> VAD -> normalized events -> STT accumulation for session."""
    from src.audio.backend_integration import audio_backend_manager
    audio_backend_manager.process_audio_stream(
        session_id=session_id,
        speech_chunks=speech_chunks,
        silence_chunks=silence_chunks,
    )
    return _to_response(session_repository.get(session_id))


@router.post(
    "/{session_id}/audio/reason-and-plan",
    response_model=SessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Feed audio transcript into Reasoning and derive WorkflowPlan",
)
async def reason_and_plan_session(session_id: str) -> SessionResponse:
    """Invokes MockReasoningEngine and creates grounded WorkflowPlan."""
    from src.audio.backend_integration import audio_backend_manager
    audio_backend_manager.execute_reasoning_and_plan(session_id=session_id)
    return _to_response(session_repository.get(session_id))


@router.post(
    "/{session_id}/audio/approve",
    response_model=SessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Grant human approval for pending consequential workflow step",
)
async def approve_session_workflow(
    session_id: str,
    approver: str = Query("lead-engineer@academia.ai", description="Approver identity"),
    comment: str = Query("Approved for execution", description="Approval comment"),
) -> SessionResponse:
    """Approves Human-in-the-Loop gate and resumes workflow execution."""
    from src.audio.backend_integration import audio_backend_manager
    audio_backend_manager.approve_and_complete_workflow(
        session_id=session_id,
        approver=approver,
        comment=comment,
    )
    return _to_response(session_repository.get(session_id))


@router.post(
    "/{session_id}/audio/reject",
    response_model=SessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject pending consequential workflow step and cancel workflow",
)
async def reject_session_workflow(
    session_id: str,
    rejector: str = Query("security-auditor@academia.ai", description="Rejector identity"),
    comment: str = Query("Disallowed operation", description="Rejection reason"),
) -> SessionResponse:
    """Rejects Human-in-the-Loop gate and halts workflow."""
    from src.audio.backend_integration import audio_backend_manager
    audio_backend_manager.reject_and_cancel_workflow(
        session_id=session_id,
        rejector=rejector,
        comment=comment,
    )
    return _to_response(session_repository.get(session_id))

@router.post(
    "/{session_id}/audio/cancel",
    response_model=SessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel active audio and workflow session",
)
async def cancel_session_audio(
    session_id: str,
    reason: str = Query("user_cancelled", description="Cancellation reason"),
) -> SessionResponse:
    """Cancels audio pipeline, flushes buffers, and cancels pending workflows."""
    from src.audio.backend_integration import audio_backend_manager
    session = session_repository.get(session_id)
    audio_backend_manager.cancel_workflow(session_id=session.session_id, reason=reason)
    return _to_response(session_repository.get(session_id))


@router.post(
    "/{session_id}/audio/cleanup",
    response_model=SessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Clean up audio and workflow resources for session",
)
async def cleanup_session_audio(
    session_id: str,
    force: bool = Query(False, description="Force cleanup even if session is active"),
) -> SessionResponse:
    """Safely cleans up pipelines, bridges, and workflow plans for session (Section 8)."""
    from src.audio.backend_integration import audio_backend_manager
    session = session_repository.get(session_id)
    audio_backend_manager.cleanup_session(session_id=session.session_id, force=force)
    return _to_response(session_repository.get(session_id))

