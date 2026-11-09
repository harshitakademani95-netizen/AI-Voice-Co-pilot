"""Session lifecycle, idempotent command handling, mock routes, and SSE streaming."""
import asyncio
import json
from typing import Optional
from fastapi import APIRouter, Header, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from src.core.idempotency import idempotency_manager
from src.models.session import (
    SessionCreateRequest,
    SessionEvent,
    SessionEventCreateRequest,
    SessionEventsResponse,
    SessionListResponse,
    SessionPauseRequest,
    SessionResponse,
    SessionResumeRequest,
    SessionState,
    SessionStopRequest,
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
        expires_at=getattr(session, "expires_at", None),
        metadata=session.metadata,
        events_count=len(session.events),
        events=session.events,
    )


def _format_sse(event: SessionEvent) -> str:
    """Formats a SessionEvent as an SSE data frame."""
    payload = json.dumps(event.model_dump())
    return f"id: {event.event_id}\nevent: {event.event_type}\ndata: {payload}\n\n"


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new session",
    description="Initializes a session in the 'created' state with optional metadata and idempotency key support.",
)
async def create_session(
    request: Request,
    body: Optional[SessionCreateRequest] = None,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    req = body or SessionCreateRequest()
    key = idempotency_key or x_idempotency_key or getattr(request.state, "idempotency_key", None)
    correlation_id = getattr(request.state, "correlation_id", None)

    if key:
        body_dict = req.model_dump()
        req_hash = idempotency_manager.compute_request_hash(
            method=request.method,
            path=request.url.path,
            body=body_dict,
        )
        cached = idempotency_manager.check(key, req_hash)
        if cached is not None:
            cached_status, cached_data = cached
            return JSONResponse(status_code=cached_status, content=cached_data)

    try:
        session = session_repository.create(
            session_id=req.session_id,
            metadata=req.metadata,
            correlation_id=correlation_id,
        )
        resp = _to_response(session)

        if key:
            idempotency_manager.record(
                key=key,
                request_hash=req_hash,
                status_code=status.HTTP_201_CREATED,
                response_data=resp.model_dump(),
            )

        return resp
    except Exception:
        if key:
            idempotency_manager.cancel_in_flight(key)
        raise


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
    description="Enforces lifecycle state machine transitions (created, active, paused, stopping, stopped, completed, failed, expired).",
)
async def transition_session(
    session_id: str,
    req_body: SessionTransitionRequest,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    key = idempotency_key or x_idempotency_key or getattr(request.state, "idempotency_key", None)
    correlation_id = getattr(request.state, "correlation_id", None)

    if key:
        body_dict = req_body.model_dump()
        req_hash = idempotency_manager.compute_request_hash(
            method=request.method,
            path=request.url.path,
            body=body_dict,
        )
        cached = idempotency_manager.check(key, req_hash)
        if cached is not None:
            cached_status, cached_data = cached
            return JSONResponse(status_code=cached_status, content=cached_data)

    try:
        session = session_repository.transition(
            session_id=session_id,
            to_state=req_body.to_state,
            reason=req_body.reason,
            correlation_id=correlation_id,
        )
        resp = _to_response(session)

        if key:
            idempotency_manager.record(
                key=key,
                request_hash=req_hash,
                status_code=status.HTTP_200_OK,
                response_data=resp.model_dump(),
            )

        return resp
    except Exception:
        if key:
            idempotency_manager.cancel_in_flight(key)
        raise


@router.post(
    "/{session_id}/pause",
    response_model=SessionResponse,
    summary="Pause active session",
    description="Transitions an active session to paused state. Emits 'session_paused' event.",
)
async def pause_session(
    session_id: str,
    request: Request,
    body: Optional[SessionPauseRequest] = None,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    key = idempotency_key or x_idempotency_key or getattr(request.state, "idempotency_key", None)
    correlation_id = getattr(request.state, "correlation_id", None)
    req = body or SessionPauseRequest()

    if key:
        body_dict = req.model_dump()
        req_hash = idempotency_manager.compute_request_hash(
            method=request.method,
            path=request.url.path,
            body=body_dict,
        )
        cached = idempotency_manager.check(key, req_hash)
        if cached is not None:
            cached_status, cached_data = cached
            return JSONResponse(status_code=cached_status, content=cached_data)

    try:
        session = session_repository.pause(
            session_id=session_id,
            reason=req.reason,
            correlation_id=correlation_id,
        )
        resp = _to_response(session)

        if key:
            idempotency_manager.record(
                key=key,
                request_hash=req_hash,
                status_code=status.HTTP_200_OK,
                response_data=resp.model_dump(),
            )

        return resp
    except Exception:
        if key:
            idempotency_manager.cancel_in_flight(key)
        raise


@router.post(
    "/{session_id}/resume",
    response_model=SessionResponse,
    summary="Resume paused session",
    description="Transitions a paused session back to active state. Emits 'session_resumed' event.",
)
async def resume_session(
    session_id: str,
    request: Request,
    body: Optional[SessionResumeRequest] = None,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    key = idempotency_key or x_idempotency_key or getattr(request.state, "idempotency_key", None)
    correlation_id = getattr(request.state, "correlation_id", None)
    req = body or SessionResumeRequest()

    if key:
        body_dict = req.model_dump()
        req_hash = idempotency_manager.compute_request_hash(
            method=request.method,
            path=request.url.path,
            body=body_dict,
        )
        cached = idempotency_manager.check(key, req_hash)
        if cached is not None:
            cached_status, cached_data = cached
            return JSONResponse(status_code=cached_status, content=cached_data)

    try:
        session = session_repository.resume(
            session_id=session_id,
            reason=req.reason,
            correlation_id=correlation_id,
        )
        resp = _to_response(session)

        if key:
            idempotency_manager.record(
                key=key,
                request_hash=req_hash,
                status_code=status.HTTP_200_OK,
                response_data=resp.model_dump(),
            )

        return resp
    except Exception:
        if key:
            idempotency_manager.cancel_in_flight(key)
        raise


@router.post(
    "/{session_id}/stop",
    response_model=SessionResponse,
    summary="Stop session",
    description="Transitions session to terminal 'stopped' state. Emits 'session_stopped' event.",
)
async def stop_session(
    session_id: str,
    request: Request,
    body: Optional[SessionStopRequest] = None,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    key = idempotency_key or x_idempotency_key or getattr(request.state, "idempotency_key", None)
    correlation_id = getattr(request.state, "correlation_id", None)
    req = body or SessionStopRequest()

    if key:
        body_dict = req.model_dump()
        req_hash = idempotency_manager.compute_request_hash(
            method=request.method,
            path=request.url.path,
            body=body_dict,
        )
        cached = idempotency_manager.check(key, req_hash)
        if cached is not None:
            cached_status, cached_data = cached
            return JSONResponse(status_code=cached_status, content=cached_data)

    try:
        session = session_repository.stop(
            session_id=session_id,
            reason=req.reason,
            correlation_id=correlation_id,
        )
        resp = _to_response(session)

        if key:
            idempotency_manager.record(
                key=key,
                request_hash=req_hash,
                status_code=status.HTTP_200_OK,
                response_data=resp.model_dump(),
            )

        return resp
    except Exception:
        if key:
            idempotency_manager.cancel_in_flight(key)
        raise


@router.post(
    "/{session_id}/events",
    response_model=SessionEvent,
    status_code=status.HTTP_201_CREATED,
    summary="Record a mock event in session",
    description="Appends a mock event into the session event stream and broadcasts to active SSE subscribers.",
)
async def record_session_event(
    session_id: str,
    request: Request,
    event_body: SessionEventCreateRequest,
) -> SessionEvent:
    correlation_id = getattr(request.state, "correlation_id", None)
    return session_repository.add_event(
        session_id=session_id,
        event_type=event_body.event_type,
        payload=event_body.payload,
        correlation_id=correlation_id,
    )


@router.get(
    "/{session_id}/events",
    response_model=SessionEventsResponse,
    summary="Retrieve session events",
    description="Fetches ordered event history for a given session with optional pagination. If Accept header requests 'text/event-stream', streams events via SSE.",
)
async def get_session_events(
    session_id: str,
    request: Request,
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
    last_event_id_query: Optional[str] = Query(None, alias="last_event_id"),
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Max events to return"),
    offset: int = Query(0, ge=0, description="Number of events to skip"),
):
    session = session_repository.get(session_id)
    accept_header = request.headers.get("accept", "")

    # If client explicitly requests text/event-stream on /events, serve as SSE
    if "text/event-stream" in accept_header:
        return await stream_session_events(
            session_id=session_id,
            request=request,
            last_event_id=last_event_id,
            last_event_id_query=last_event_id_query,
        )

    all_events = session.events
    sliced = all_events[offset:]
    if limit is not None:
        sliced = sliced[:limit]

    return SessionEventsResponse(
        session_id=session.session_id,
        events_count=len(sliced),
        events=sliced,
    )


@router.get(
    "/{session_id}/events/stream",
    summary="Stream session events via Server-Sent Events (SSE)",
    description="Dedicated SSE stream endpoint. Streams historic events in sequence order, then streams real-time events as they occur. Supports reconnection via Last-Event-ID.",
)
async def stream_session_events(
    session_id: str,
    request: Request,
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
    last_event_id_query: Optional[str] = Query(None, alias="last_event_id"),
):
    session = session_repository.get(session_id)
    reconnect_id = last_event_id or last_event_id_query
    initial_events = list(session.events)
    if reconnect_id:
        target = reconnect_id.strip()
        found_idx = next(
            (i for i, ev in enumerate(initial_events) if ev.event_id == target or str(ev.sequence_number) == target),
            None,
        )
        if found_idx is not None:
            initial_events = initial_events[found_idx + 1 :]

    async def sse_event_generator():
        queue = session_repository.subscribe(session_id)
        try:
            for evt in initial_events:
                yield _format_sse(evt)

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield _format_sse(event)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            pass
        finally:
            session_repository.unsubscribe(session_id, queue)

    return StreamingResponse(
        sse_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/mock/quickstart",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Quickstart mock session",
    description="Creates a session, transitions it to 'active', and fires an initial mock voice transcription event.",
)
async def quickstart_mock_session(request: Request) -> SessionResponse:
    correlation_id = getattr(request.state, "correlation_id", None)
    session = session_repository.create(
        metadata={"mock_flow": "quickstart", "client": "ai-copilot-mock-client"},
        correlation_id=correlation_id,
    )
    session = session_repository.transition(
        session_id=session.session_id,
        to_state=SessionState.ACTIVE,
        reason="Mock user speech initiated",
        correlation_id=correlation_id,
    )
    session_repository.add_event(
        session_id=session.session_id,
        event_type="mock_voice_transcript",
        payload={
            "transcript": "Explain this python error in my terminal",
            "confidence": 0.98,
            "language": "en",
        },
        correlation_id=correlation_id,
    )
    updated_session = session_repository.get(session.session_id)
    return _to_response(updated_session)
