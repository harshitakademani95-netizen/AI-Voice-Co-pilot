"""API routes for Backend Audio and Transcription Gateways and Session Audio Ingestion."""
import base64
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.config import settings
from src.core.idempotency import idempotency_manager
from src.core.errors import (
    AudioFormatUnsupportedError,
    AudioGatewayError,
    PayloadTooLargeError,
    SessionNotFoundError,
    SessionValidationError,
    TranscriptionGatewayError,
)
from src.gateways.schemas import (
    AudioProcessRequest,
    SessionAudioIngestRequest,
    TranscriptionProcessRequest,
)
from src.gateways.service import get_gateway_service

try:
    from src.schemas.audio import (
        ALL_SUPPORTED_ENCODINGS,
        SUPPORTED_SAMPLE_RATES,
        AudioFormat,
    )
except ImportError:
    from schemas.audio import (
        ALL_SUPPORTED_ENCODINGS,
        SUPPORTED_SAMPLE_RATES,
        AudioFormat,
    )

logger = logging.getLogger("backend.routes.gateways")

router = APIRouter(tags=["Gateways & Module Integration"])


def _decode_audio_payload(audio_base64: Optional[str]) -> bytes:
    """Decodes base64-encoded audio data with validation."""
    if not audio_base64:
        raise AudioGatewayError(
            code="AUDIO_DATA_EMPTY",
            message="Audio data must not be empty.",
            details={"field": "audio_base64"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        data = base64.b64decode(audio_base64)
    except Exception as exc:
        raise AudioGatewayError(
            code="INVALID_BASE64_AUDIO",
            message=f"Failed to decode base64 audio data: {str(exc)}",
            details={"exception": str(exc)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if not data:
        raise AudioGatewayError(
            code="AUDIO_DATA_EMPTY",
            message="Decoded audio data is 0 bytes.",
            details={"field": "audio_base64"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if len(data) > settings.max_audio_bytes:
        raise PayloadTooLargeError(
            message=f"Decoded audio size ({len(data)} bytes) exceeds maximum limit of {settings.max_audio_bytes} bytes.",
            details={"size_bytes": len(data), "max_audio_bytes": settings.max_audio_bytes},
        )
    return data


def _parse_audio_format(fmt_str: str, sample_rate: int = 16000) -> AudioFormat:
    """Parses audio format name and sample rate into AudioFormat contract."""
    fmt_clean = fmt_str.strip().lower()

    # Map friendly alias names
    if fmt_clean in ("linear16", "pcm_16", "pcm_s16le", "pcm"):
        encoding = "pcm_s16le"
        sample_width = 2
    elif fmt_clean in ("pcm_u8", "pcm_8"):
        encoding = "pcm_u8"
        sample_width = 1
    elif fmt_clean in ("pcm_s32le", "pcm_32"):
        encoding = "pcm_s32le"
        sample_width = 4
    elif fmt_clean in ALL_SUPPORTED_ENCODINGS:
        encoding = fmt_clean
        sample_width = 2 if "16" in fmt_clean else (1 if "8" in fmt_clean else 4)
    else:
        supported = ["linear16", "pcm_s16le", "pcm_u8", "pcm_s32le"]
        raise AudioFormatUnsupportedError(
            format_name=fmt_str,
            supported_formats=supported,
        )

    try:
        return AudioFormat(
            sample_rate=sample_rate,
            channels=1,
            sample_width=sample_width,
            encoding=encoding,
        )
    except Exception as exc:
        raise AudioGatewayError(
            code="INVALID_AUDIO_FORMAT",
            message=str(exc),
            details={"format": fmt_str, "sample_rate": sample_rate},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@router.get(
    "/gateways/status",
    summary="Get status and telemetry for audio, transcription, and session integration",
)
async def get_gateways_status() -> Dict[str, Any]:
    """Returns telemetry and operational status for all backend gateways."""
    svc = get_gateway_service()
    return svc.get_status()


@router.post(
    "/audio/process",
    summary="Process and chunk raw audio data",
    status_code=status.HTTP_200_OK,
)
async def process_audio(payload: AudioProcessRequest) -> Dict[str, Any]:
    """Validates and chunks incoming raw audio using the Audio Gateway."""
    audio_bytes = _decode_audio_payload(payload.audio_base64)
    fmt = _parse_audio_format(payload.format, sample_rate=payload.sample_rate)

    svc = get_gateway_service()
    chunks = svc.audio_gateway.chunk_audio(
        raw_audio=audio_bytes,
        format_spec=fmt,
        chunk_duration_ms=payload.chunk_duration_ms or 20.0,
    )

    chunks_info = [
        {
            "sequence_id": c.sequence_id,
            "duration_ms": c.duration_ms,
            "format": {
                "sample_rate": c.format.sample_rate,
                "channels": c.format.channels,
                "encoding": c.format.encoding,
            },
            "is_final": (idx == len(chunks) - 1) if payload.is_last else False,
            "byte_length": len(c.data),
        }
        for idx, c in enumerate(chunks)
    ]

    return {
        "status": "success",
        "chunks_count": len(chunks),
        "chunks": chunks_info,
    }


@router.post(
    "/transcription/process",
    summary="Transcribe audio chunk via Transcription Gateway",
    status_code=status.HTTP_200_OK,
)
async def process_transcription(payload: TranscriptionProcessRequest) -> Dict[str, Any]:
    """Transcribes an audio chunk using the Transcription Gateway."""
    audio_bytes = _decode_audio_payload(payload.audio_base64)
    fmt = _parse_audio_format(payload.format)

    svc = get_gateway_service()
    # Chunk raw audio first
    chunks = svc.audio_gateway.chunk_audio(
        raw_audio=audio_bytes,
        format_spec=fmt,
    )

    events = []
    for idx, chunk in enumerate(chunks):
        is_last = payload.is_last and (idx == len(chunks) - 1)
        evs = svc.transcription_gateway.transcribe_chunk(
            chunk=chunk,
            is_last=is_last,
            session_id=payload.session_id,
        )
        for ev in evs:
            events.append(ev.model_dump() if hasattr(ev, "model_dump") else dict(ev))

    return {
        "status": "success",
        "events_count": len(events),
        "events": events,
    }


@router.post(
    "/sessions/{session_id}/audio",
    summary="Ingest audio directly into a session",
    status_code=status.HTTP_200_OK,
)
async def ingest_session_audio(
    session_id: str,
    payload: SessionAudioIngestRequest,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
    x_correlation_id: Optional[str] = Header(None),
) -> Any:
    """Ingests audio into an active session: chunked, transcribed, and broadcast via Session SSE events."""
    key = idempotency_key or x_idempotency_key or getattr(request.state, "idempotency_key", None)
    req_hash = None
    if key:
        body_dict = payload.model_dump()
        req_hash = idempotency_manager.compute_request_hash(
            method=request.method,
            path=request.url.path,
            body=body_dict,
        )
        cached = idempotency_manager.check(key, req_hash)
        if cached is not None:
            cached_status, cached_data = cached
            return JSONResponse(status_code=cached_status, content=cached_data)

    audio_bytes = _decode_audio_payload(payload.audio_base64)
    fmt = _parse_audio_format(payload.format)
    corr_id = payload.correlation_id or x_correlation_id

    svc = get_gateway_service()
    try:
        result = svc.process_session_audio(
            session_id=session_id,
            audio_data=audio_bytes,
            audio_format=fmt,
            is_last=payload.is_last,
            correlation_id=corr_id,
        )
        if key and req_hash:
            idempotency_manager.record(
                key=key,
                request_hash=req_hash,
                status_code=status.HTTP_200_OK,
                response_data=result,
            )
        return result
    except Exception:
        if key:
            idempotency_manager.cancel_in_flight(key)
        raise


@router.get(
    "/sessions/{session_id}/transcript",
    summary="Retrieve accumulated transcript for a session",
    status_code=status.HTTP_200_OK,
)
async def get_session_transcript(
    session_id: str,
    x_correlation_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """Retrieves the full transcript, segments, and metrics for an existing session."""
    svc = get_gateway_service()
    session = svc.session_repo.get(session_id)
    if not session:
        raise SessionNotFoundError(session_id)

    acc = svc.transcription_gateway.get_or_create_accumulator(session_id)
    full_transcript = acc.get_full_transcript(include_interim=True)
    final_segments = acc.get_final_segments()

    segments_data: List[Dict[str, Any]] = []
    if final_segments:
        for seg in final_segments:
            segments_data.append({
                "text": seg.text,
                "start_time": seg.start_time,
                "end_time": seg.end_time,
                "confidence": seg.confidence,
                "is_final": seg.is_final,
            })
    else:
        # Reconstruct from session event store if present
        transcript_events = [ev for ev in session.events if ev.event_type == "speech_transcript"]
        text_parts = []
        for ev in transcript_events:
            p = ev.payload
            segments_data.append({
                "text": p.get("text", ""),
                "start_time": p.get("start_time", 0.0),
                "end_time": p.get("end_time", 0.0),
                "confidence": p.get("confidence", 1.0),
                "is_final": p.get("is_final", True),
            })
            if p.get("text"):
                text_parts.append(p.get("text"))
        if not full_transcript and text_parts:
            full_transcript = " ".join(text_parts)

    chunks_processed = session.metadata.get("chunks_processed", len(segments_data))
    last_updated = session.updated_at or (session.events[-1].timestamp if session.events else session.created_at)

    return {
        "session_id": session_id,
        "full_transcript": full_transcript,
        "segments": segments_data,
        "chunks_processed": chunks_processed,
        "last_updated": last_updated,
    }


class PipelineProcessRequest(BaseModel):
    session_id: Optional[str] = None
    audio_base64: Optional[str] = None
    user_query: Optional[str] = None
    format: str = "linear16"
    sample_rate: int = 16000
    prompt_version: str = "v1.0.0"
    context_items: Optional[List[Dict[str, Any]]] = None


def _execute_pipeline_core(
    session_id: str,
    payload: PipelineProcessRequest,
    correlation_id: Optional[str],
) -> Dict[str, Any]:
    svc = get_gateway_service()
    session = svc.session_repo.get(session_id)
    if not session:
        raise SessionNotFoundError(session_id)

    audio_bytes: Optional[bytes] = None
    fmt: Optional[AudioFormat] = None

    if payload.audio_base64:
        audio_bytes = _decode_audio_payload(payload.audio_base64)
        fmt = _parse_audio_format(payload.format, sample_rate=payload.sample_rate)

    return svc.execute_pipeline(
        session_id=session_id,
        audio_data=audio_bytes,
        user_query=payload.user_query,
        audio_format=fmt,
        context_items=payload.context_items,
        correlation_id=correlation_id,
        prompt_version=payload.prompt_version,
    )


@router.post(
    "/sessions/{session_id}/pipeline",
    summary="Execute full end-to-end pipeline: Audio -> STT -> Reasoning -> Workflow Policy",
    status_code=status.HTTP_200_OK,
)
async def process_pipeline_session(
    session_id: str,
    payload: PipelineProcessRequest,
    x_correlation_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """Coordinates Audio, Transcription, Reasoning, and Workflow gateways for a session (via path session_id)."""
    return _execute_pipeline_core(session_id, payload, x_correlation_id)


@router.post(
    "/pipeline/process",
    summary="Execute full end-to-end pipeline via request body",
    status_code=status.HTTP_200_OK,
)
async def process_pipeline_alias(
    payload: PipelineProcessRequest,
    x_correlation_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """Alias for pipeline execution obtaining session_id from the request body."""
    target_session_id = payload.session_id
    if not target_session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_id must be provided in request body when calling /pipeline/process.",
        )
    return _execute_pipeline_core(target_session_id, payload, x_correlation_id)


