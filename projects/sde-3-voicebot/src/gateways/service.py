"""Backend Gateway Service coordinating all Four Module Gateways with Session Management."""
from datetime import datetime, timezone
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from src.context.schemas import ContextItem, ReasoningRequest, ReasoningResult
from src.core.errors import (
    AppError,
    AudioGatewayError,
    AudioModuleUnavailableError,
    InvalidStateTransitionError,
    SessionNotFoundError,
    TranscriptionGatewayError,
    TranscriptionModuleUnavailableError,
)
from src.gateways.audio_gateway import AudioGateway, get_audio_gateway
from src.gateways.reasoning_gateway import ReasoningGateway, get_reasoning_gateway
from src.gateways.transcription_gateway import TranscriptionGateway, get_transcription_gateway
from src.gateways.workflow_gateway import WorkflowGateway, get_workflow_gateway
from src.repositories.session_repository import InMemorySessionRepository, session_repository

try:
    from src.schemas.audio import AudioFormat
except ImportError:
    from schemas.audio import AudioFormat

logger = logging.getLogger("backend.gateway_service")


class BackendGatewayService:
    """Coordinator service bridging Audio, Transcription, Reasoning, and Workflow Gateways with Session Management."""

    def __init__(
        self,
        audio_gateway: Optional[AudioGateway] = None,
        transcription_gateway: Optional[TranscriptionGateway] = None,
        reasoning_gateway: Optional[ReasoningGateway] = None,
        workflow_gateway: Optional[WorkflowGateway] = None,
        session_repo: Optional[InMemorySessionRepository] = None,
    ) -> None:
        self.audio_gateway = audio_gateway or get_audio_gateway()
        self.transcription_gateway = transcription_gateway or get_transcription_gateway()
        self.reasoning_gateway = reasoning_gateway or get_reasoning_gateway()
        self.workflow_gateway = workflow_gateway or get_workflow_gateway()
        self.session_repo = session_repo or session_repository

    def health_check(self) -> Dict[str, Any]:
        """Runs health checks on all four dependent module gateways and repository."""
        audio_healthy = self.audio_gateway.health_check()
        trans_healthy = self.transcription_gateway.health_check()
        reason_healthy = self.reasoning_gateway.health_check()
        workflow_healthy = self.workflow_gateway.health_check()
        repo_healthy = self.session_repo.is_healthy()

        all_healthy = audio_healthy and trans_healthy and reason_healthy and workflow_healthy and repo_healthy

        return {
            "status": "healthy" if all_healthy else "degraded",
            "audio_gateway": {"status": "healthy" if audio_healthy else "unhealthy"},
            "transcription_gateway": {"status": "healthy" if trans_healthy else "unhealthy"},
            "reasoning_gateway": {"status": "healthy" if reason_healthy else "unhealthy"},
            "workflow_gateway": {"status": "healthy" if workflow_healthy else "unhealthy"},
            "session_repository": {"status": "healthy" if repo_healthy else "unhealthy"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_status(self) -> Dict[str, Any]:
        """Returns runtime telemetry for all four module gateways and interfaces."""
        return {
            "audio_gateway": self.audio_gateway.get_status(),
            "transcription_gateway": self.transcription_gateway.get_status(),
            "reasoning_gateway": self.reasoning_gateway.get_status(),
            "workflow_gateway": self.workflow_gateway.get_status(),
            "health": self.health_check(),
        }

    def process_session_audio(
        self,
        session_id: str,
        audio_data: bytes,
        audio_format: Optional[AudioFormat] = None,
        is_last: bool = False,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ingests audio for a session, chunks it via AudioGateway, transcribes

        via TranscriptionGateway, and publishes events to SessionRepository.
        """
        # 1. Validate session existence and state
        session = self.session_repo.get(session_id)
        if not session:
            raise SessionNotFoundError(session_id)

        current_state = session.state.value if hasattr(session.state, "value") else str(session.state)
        if current_state in ("stopped", "completed", "failed", "expired"):
            raise InvalidStateTransitionError(
                current_state=current_state,
                target_state="audio_processing",
                reason=f"Session {session_id} is in terminal state '{current_state}' and cannot process audio.",
            )
        if current_state == "paused":
            raise InvalidStateTransitionError(
                current_state=current_state,
                target_state="audio_processing",
                reason=f"Session {session_id} is paused; resume session before sending audio.",
            )

        # 2. Chunk audio via Audio Gateway -> Audio Module (AudioChunker)
        chunks = self.audio_gateway.chunk_audio(
            raw_audio=audio_data,
            format_spec=audio_format,
            correlation_id=correlation_id,
        )

        # 3. Transcribe chunks via Transcription Gateway -> STT Module
        transcript_events: List[Dict[str, Any]] = []
        for idx, chunk in enumerate(chunks):
            chunk_is_last = is_last and (idx == len(chunks) - 1)
            events = self.transcription_gateway.transcribe_chunk(
                chunk=chunk,
                is_last=chunk_is_last,
                session_id=session_id,
                correlation_id=correlation_id,
            )
            for event in events:
                event_dict = event.model_dump() if hasattr(event, "model_dump") else dict(event)
                transcript_events.append(event_dict)

                seg = getattr(event, "segment", None)
                text = getattr(seg, "text", "") if seg else ""
                is_final_seg = getattr(seg, "is_final", False) if seg else False
                start_time = getattr(seg, "start_time", 0.0) if seg else 0.0
                end_time = getattr(seg, "end_time", 0.0) if seg else 0.0
                confidence = getattr(seg, "confidence", 1.0) if seg else 1.0

                # Record event into session and broadcast to SSE listeners
                self.session_repo.add_event(
                    session_id=session_id,
                    event_type="speech_transcript",
                    payload={
                        "text": text,
                        "is_final": is_final_seg,
                        "start_time": start_time,
                        "end_time": end_time,
                        "confidence": confidence,
                        "correlation_id": correlation_id,
                    },
                    correlation_id=correlation_id,
                )

        full_transcript = self.transcription_gateway.get_session_transcript(session_id)
        session.metadata["chunks_processed"] = session.metadata.get("chunks_processed", 0) + len(chunks)
        session.metadata["full_transcript"] = full_transcript
        session.updated_at = datetime.now(timezone.utc).isoformat()

        return {
            "session_id": session_id,
            "status": "success",
            "chunks_processed": len(chunks),
            "events_count": len(transcript_events),
            "transcript_events": transcript_events,
            "full_transcript": full_transcript,
        }

    def execute_pipeline(
        self,
        session_id: str,
        audio_data: Optional[bytes] = None,
        user_query: Optional[str] = None,
        audio_format: Optional[AudioFormat] = None,
        context_items: Optional[List[Any]] = None,
        correlation_id: Optional[str] = None,
        prompt_version: str = "v1.0.0",
    ) -> Dict[str, Any]:
        """Executes the full Day 21 End-to-End Pipeline: Audio -> STT -> Reasoning -> Workflow Policy -> Session Events."""
        # 1. Process Audio & Transcription if audio is passed
        transcript_text = ""
        chunks_count = 0
        if audio_data and len(audio_data) > 0:
            audio_res = self.process_session_audio(
                session_id=session_id,
                audio_data=audio_data,
                audio_format=audio_format,
                is_last=True,
                correlation_id=correlation_id,
            )
            transcript_text = audio_res.get("full_transcript", "")
            chunks_count = audio_res.get("chunks_processed", 0)

        # 2. Determine effective reasoning query
        effective_query = (user_query or transcript_text or "What can I do?").strip()

        # 3. Reasoning Gateway -> Reasoning Module
        c_items = []
        if context_items:
            for item in context_items:
                if isinstance(item, ContextItem):
                    c_items.append(item)
                elif isinstance(item, dict):
                    c_items.append(ContextItem(**item))

        reason_req = ReasoningRequest(
            request_id=f"req-pipe-{correlation_id or 'default'}",
            session_id=session_id,
            user_query=effective_query,
            context_items=c_items,
            prompt_version=prompt_version,
        )
        reason_res: ReasoningResult = self.reasoning_gateway.reason(
            request=reason_req,
            correlation_id=correlation_id,
        )

        # Record reasoning event on session
        self.session_repo.add_event(
            session_id=session_id,
            event_type="reasoning_completed",
            payload={
                "intent": getattr(reason_res, "intent", None),
                "risk_category": reason_res.risk_level.value if hasattr(reason_res.risk_level, "value") else str(reason_res.risk_level),
                "requires_approval": reason_res.requires_approval,
                "action_type": reason_res.action_type,
                "confidence": reason_res.confidence,
            },
            correlation_id=correlation_id,
        )

        # 4. Workflow Gateway Policy Check
        workflow_info: Dict[str, Any] = {
            "policy_evaluated": True,
            "requires_approval": reason_res.requires_approval,
            "approval_id": None,
        }

        if reason_res.requires_approval and reason_res.action_type:
            policy_res = self.workflow_gateway.evaluate_policy(
                action_type=reason_res.action_type,
                parameters={"query": effective_query},
                session_id=session_id,
            )
            workflow_info["approval_id"] = policy_res.get("approval_id")

            # Record approval event on session
            self.session_repo.add_event(
                session_id=session_id,
                event_type="approval_requested",
                payload={
                    "approval_id": workflow_info["approval_id"],
                    "action_type": reason_res.action_type,
                    "risk_level": reason_res.risk_level.value if hasattr(reason_res.risk_level, "value") else str(reason_res.risk_level),
                },
                correlation_id=correlation_id,
            )

        return {
            "session_id": session_id,
            "status": "requires_approval" if reason_res.requires_approval else "completed",
            "approval_id": workflow_info.get("approval_id"),
            "audio_chunks_processed": chunks_count,
            "chunks_count": chunks_count,
            "transcript": transcript_text,
            "reasoning": reason_res.model_dump(),
            "workflow": workflow_info,
            "events_recorded": len(self.session_repo.get(session_id).events),
        }

    async def stream_session_audio(
        self,
        session_id: str,
        audio_stream: AsyncIterator[bytes],
        audio_format: Optional[AudioFormat] = None,
        correlation_id: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Asynchronously streams chunks and yields transcription events as they are produced."""
        session = self.session_repo.get(session_id)
        if not session:
            raise SessionNotFoundError(session_id)

        async for audio_chunk_bytes in audio_stream:
            chunks = self.audio_gateway.chunk_audio(audio_chunk_bytes, format_spec=audio_format)
            for chunk in chunks:
                events = self.transcription_gateway.transcribe_chunk(
                    chunk=chunk,
                    session_id=session_id,
                    correlation_id=correlation_id,
                )
                for event in events:
                    event_dict = event.model_dump() if hasattr(event, "model_dump") else dict(event)
                    self.session_repo.add_event(
                        session_id=session_id,
                        event_type="speech_transcript",
                        payload=event_dict,
                        correlation_id=correlation_id,
                    )
                    yield event_dict

    def close(self) -> None:
        """Closes all gateway connections and cleans up resources."""
        self.audio_gateway.close()
        self.transcription_gateway.close()
        self.reasoning_gateway.close()
        self.workflow_gateway.close()


# Singleton Gateway Service
_gateway_service_instance: Optional[BackendGatewayService] = None


def get_gateway_service() -> BackendGatewayService:
    """Returns the singleton BackendGatewayService coordinator."""
    global _gateway_service_instance
    if _gateway_service_instance is None:
        _gateway_service_instance = BackendGatewayService()
    return _gateway_service_instance
