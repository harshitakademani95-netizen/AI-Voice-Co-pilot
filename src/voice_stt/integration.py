"""Integration Bridges for AI Voice Co-Pilot (W3 Days 19–20).

This module bridges:
1. Day 19 (Audio-to-STT): Connects Week 1 authentic AudioPipeline (or AudioChunker)
   to the Week 2/3 TranscriptionOrchestrator, enforcing session association,
   monotonic sequencing, audio-to-text timing alignment, and cancellation propagation.
2. Day 20 (STT-to-Backend): Connects Week 2/3 TranscriptEvents (INTERIM, REVISION,
   FINALIZATION, ERROR) to the Week 5 authentic InMemorySessionRepository event stream,
   enforcing payload shape, ISO-8601 UTC timestamps, duplicate suppression, and
   graceful failure handling when backend sessions are missing or inactive.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Set, Tuple

from src.audio.pipeline import AudioPipeline
from src.audio.vad import VADEvent, VADEventType
from src.core.errors import AppError, InvalidStateTransitionError, SessionNotFoundError
from src.models.session import Session, SessionEvent, SessionState
from src.repositories.session_repository import InMemorySessionRepository, session_repository
from src.schemas.audio import AudioChunk, AudioError
from voice_stt.orchestrator import OrchestratorCancelledError, TranscriptionOrchestrator
from voice_stt.schemas import (
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)

# Canonical mapping of STT lifecycle events to backend event stream names
STT_BACKEND_EVENT_TYPE_MAP: Dict[TranscriptEventType, str] = {
    TranscriptEventType.INTERIM: "voice_stt.interim",
    TranscriptEventType.REVISION: "voice_stt.revision",
    TranscriptEventType.FINALIZATION: "voice_stt.finalization",
    TranscriptEventType.FINAL: "voice_stt.finalization",
    TranscriptEventType.ERROR: "voice_stt.error",
}


class BackendEventStreamBridge:
    """Bridges STT TranscriptEvents into the authentic Week 5 backend session event stream.

    Responsibilities:
    1. Forward transcript lifecycle events (INTERIM, REVISION, FINALIZATION, ERROR).
    2. Enforce duplicate suppression so the repository stream is not polluted.
    3. Preserve session IDs, event IDs, confidence scores, and audio timestamps.
    4. Isolate backend failures (missing session, terminal state) so the STT accumulator is never corrupted.
    5. Maintain telemetry of published events and publication failures.
    """

    def __init__(
        self,
        repository: Optional[InMemorySessionRepository] = None,
        session_id: Optional[str] = None,
        auto_create_session: bool = False,
    ) -> None:
        """Initialize backend event bridge.

        Args:
            repository: Target InMemorySessionRepository. Defaults to singleton session_repository.
            session_id: Default session identifier.
            auto_create_session: If True, creates and activates session if not found in repository.
        """
        self.repository: InMemorySessionRepository = repository if repository is not None else session_repository
        self.default_session_id: Optional[str] = session_id
        self.auto_create_session: bool = auto_create_session
        self._published_event_ids: Set[str] = set()
        self._published_events: List[SessionEvent] = []
        self._publish_failures: List[Dict[str, Any]] = []

    @property
    def published_events(self) -> List[SessionEvent]:
        """Defensive copy of all successfully published session events."""
        return list(self._published_events)

    @property
    def publish_failures(self) -> List[Dict[str, Any]]:
        """Log of all publication failures with diagnostics."""
        return list(self._publish_failures)

    def publish_event(
        self,
        event: TranscriptEvent,
        session_id: Optional[str] = None,
    ) -> Optional[SessionEvent]:
        """Publish a single TranscriptEvent to the backend session repository.

        Args:
            event: The TranscriptEvent to publish.
            session_id: Optional session override.

        Returns:
            SessionEvent if published; None if duplicate or publication failed.
        """
        if event is None:
            return None

        # 1. Duplicate suppression: prevent duplicate events from reaching repository
        if event.event_id in self._published_event_ids:
            return None

        target_sid = session_id or event.session_id or self.default_session_id
        if not target_sid:
            self._record_failure(event, "Missing session ID for event publication.")
            return None

        # 2. Map STT event type to backend canonical event type
        backend_event_type = STT_BACKEND_EVENT_TYPE_MAP.get(
            event.event_type,
            f"voice_stt.{event.event_type.value}",
        )

        # 3. Format structured payload preserving timing, confidence, text, and metadata
        payload: Dict[str, Any] = {
            "source_event_id": event.event_id,
            "source_timestamp": event.timestamp,
            "sequence_number": event.sequence_number,
            "stt_event_type": event.event_type.value,
            "session_id": target_sid,
        }

        if event.segment is not None:
            payload.update(
                {
                    "transcript": event.segment.text,
                    "confidence": event.segment.confidence,
                    "start_time": event.segment.start_time,
                    "end_time": event.segment.end_time,
                    "is_final": event.segment.is_final,
                    "segment_id": event.segment.segment_id,
                }
            )
        else:
            payload.update(
                {
                    "transcript": "",
                    "confidence": 0.0,
                    "start_time": 0.0,
                    "end_time": 0.0,
                    "is_final": event.event_type in (TranscriptEventType.FINAL, TranscriptEventType.FINALIZATION),
                }
            )

        if event.error is not None:
            payload["error"] = event.error.model_dump()

        if event.metadata:
            payload["metadata"] = dict(event.metadata)

        # 4. Attempt publication with fault isolation
        try:
            # Check if session exists or needs auto-creation
            try:
                self.repository.get(target_sid)
            except SessionNotFoundError:
                if self.auto_create_session:
                    self.repository.create(session_id=target_sid)
                    self.repository.transition(session_id=target_sid, to_state=SessionState.ACTIVE)
                else:
                    raise

            if hasattr(self.repository, "add_event"):
                session_evt = self.repository.add_event(
                    session_id=target_sid,
                    event_type=backend_event_type,
                    payload=payload,
                )
            elif hasattr(self.repository, "record_event"):
                session_evt = self.repository.record_event(
                    session_id=target_sid,
                    event_type=backend_event_type,
                    payload=payload,
                )
            else:
                raise AttributeError("Repository exposes neither 'add_event' nor 'record_event'.")
            self._published_event_ids.add(event.event_id)
            self._published_events.append(session_evt)
            return session_evt

        except (SessionNotFoundError, InvalidStateTransitionError, AppError) as exc:
            self._record_failure(event, str(exc), error_type=type(exc).__name__, session_id=target_sid)
            return None
        except Exception as exc:
            self._record_failure(event, f"Unexpected backend failure: {exc}", error_type=type(exc).__name__, session_id=target_sid)
            return None

    def publish_events(
        self,
        events: Iterable[TranscriptEvent],
        session_id: Optional[str] = None,
    ) -> List[SessionEvent]:
        """Publish an iterable of TranscriptEvents, returning all successfully published events."""
        results: List[SessionEvent] = []
        for evt in events:
            res = self.publish_event(evt, session_id=session_id)
            if res is not None:
                results.append(res)
        return results

    def _record_failure(
        self,
        event: TranscriptEvent,
        reason: str,
        error_type: str = "ValidationError",
        session_id: Optional[str] = None,
    ) -> None:
        self._publish_failures.append(
            {
                "event_id": event.event_id,
                "session_id": session_id or event.session_id,
                "reason": reason,
                "error_type": error_type,
                "event_type": event.event_type.value,
            }
        )
        logger.warning(f"Backend event publication skipped for event {event.event_id}: {reason}")


class AudioSTTBridge:
    """Bridges the authentic Week 1 AudioPipeline into the Week 2/3 TranscriptionOrchestrator.

    Responsibilities:
    1. Connect audio capture and VAD events directly to the STT pipeline.
    2. Maintain strict monotonic sequence numbering and timestamp alignment.
    3. Forward generated TranscriptEvents to an optional BackendEventStreamBridge.
    4. Coordinate lifecycle cancellation: stopping audio capture and cancelling orchestrator simultaneously.
    5. Discard late audio chunks or results once cancelled.
    """

    def __init__(
        self,
        orchestrator: TranscriptionOrchestrator,
        pipeline: Optional[AudioPipeline] = None,
        session_id: Optional[str] = None,
        backend_bridge: Optional[BackendEventStreamBridge] = None,
    ) -> None:
        """Initialize the Audio-to-STT Bridge.

        Args:
            orchestrator: The TranscriptionOrchestrator instance.
            pipeline: Optional authentic AudioPipeline instance.
            session_id: Session identifier. Defaults to orchestrator's session ID.
            backend_bridge: Optional BackendEventStreamBridge to receive transcript events.
        """
        self.orchestrator: TranscriptionOrchestrator = orchestrator
        self.session_id: str = session_id or orchestrator.session_id
        self.pipeline: AudioPipeline = pipeline if pipeline is not None else AudioPipeline()
        self.backend_bridge: Optional[BackendEventStreamBridge] = backend_bridge
        self._is_cancelled: bool = False
        self._chunks_processed: int = 0
        self._seen_sequence_ids: Set[int] = set()

    @property
    def is_cancelled(self) -> bool:
        """True if the bridge or orchestrator has been cancelled."""
        return self._is_cancelled or self.orchestrator.is_cancelled

    @property
    def chunks_processed(self) -> int:
        """Total audio chunks processed through the bridge."""
        return self._chunks_processed

    def start(self) -> None:
        """Start the audio pipeline and initialize the orchestrator session."""
        self.orchestrator.initialize(session_id=self.session_id)
        self.pipeline.start()
        self._is_cancelled = False

    def cancel(self) -> None:
        """Cancel audio capture and transcription immediately and idempotently."""
        self._is_cancelled = True
        try:
            self.pipeline.stop()
        except Exception:
            pass
        self.orchestrator.cancel()

    def stop(self) -> None:
        """Gracefully stop audio pipeline and finalize orchestrator."""
        try:
            self.pipeline.stop()
        except Exception:
            pass

    def process_step(self) -> Optional[Tuple[Optional[AudioChunk], List[TranscriptEvent]]]:
        """Execute a single step: capture from AudioPipeline, evaluate VAD, and transcribe.

        Returns:
            Tuple of (AudioChunk, List[TranscriptEvent]) if chunk was available; None if empty/ended.
        """
        if self.is_cancelled:
            return None

        step_result = self.pipeline.process_step()
        if step_result is None:
            return None

        chunk, vad_event = step_result
        if chunk is None:
            return None

        events = self.process_chunk(chunk, vad_event=vad_event)
        return chunk, events

    def process_chunk(
        self,
        chunk: AudioChunk,
        vad_event: Optional[VADEvent] = None,
        is_last: bool = False,
    ) -> List[TranscriptEvent]:
        """Process an AudioChunk through the orchestrator with deduplication and metadata enrichment.

        Args:
            chunk: AudioChunk to process.
            vad_event: Optional accompanying VAD event.
            is_last: True if this chunk marks the end of speech/stream.

        Returns:
            List of generated TranscriptEvent objects.
        """
        if self.is_cancelled:
            return []

        # Duplicate suppression at the audio chunk level
        if chunk.sequence_id in self._seen_sequence_ids:
            return []
        self._seen_sequence_ids.add(chunk.sequence_id)

        # Ensure session ID is associated with the chunk metadata
        if not chunk.metadata:
            chunk = AudioChunk(
                sequence_id=chunk.sequence_id,
                timestamp=chunk.timestamp,
                data=chunk.data,
                format=chunk.format,
                metadata={"session_id": self.session_id},
            )
        else:
            chunk.metadata["session_id"] = self.session_id

        # Attach VAD context if provided
        if vad_event is not None:
            chunk.metadata["vad_event_type"] = vad_event.event_type.value
            chunk.metadata["is_speech"] = vad_event.is_speech
            if vad_event.event_type == VADEventType.SPEECH_END:
                is_last = True

        effective_is_last = is_last or bool(chunk.metadata.get("is_last", False)) or self.pipeline.lifecycle.is_end_of_stream

        try:
            events = self.orchestrator.process_chunk(chunk, is_last=effective_is_last)
        except OrchestratorCancelledError:
            return []

        if self.is_cancelled:
            return []

        self._chunks_processed += 1

        # Forward events to backend bridge if attached
        if self.backend_bridge is not None:
            self.backend_bridge.publish_events(events, session_id=self.session_id)

        return events

    def process_stream(
        self,
        chunks: Iterable[AudioChunk],
    ) -> Iterator[TranscriptEvent]:
        """Process a stream of AudioChunks through the bridge.

        Yields:
            TranscriptEvents emitted by the orchestrator.
        """
        if self.is_cancelled:
            return

        it = iter(chunks)
        try:
            prev = next(it)
        except StopIteration:
            return

        for current in it:
            if self.is_cancelled:
                return
            is_last = bool(prev.metadata.get("is_last", False))
            events = self.process_chunk(prev, is_last=is_last)
            for evt in events:
                if self.is_cancelled:
                    return
                yield evt
            prev = current

        if self.is_cancelled:
            return
        events = self.process_chunk(prev, is_last=True)
        for evt in events:
            if self.is_cancelled:
                return
            yield evt

    def get_transcript(self, include_interim: bool = False) -> str:
        """Return the accumulated transcript from the orchestrator."""
        return self.orchestrator.get_transcript(include_interim=include_interim)

    def get_summary(self) -> Dict[str, Any]:
        """Return diagnostic telemetry from orchestrator and audio pipeline."""
        summary = self.orchestrator.get_summary()
        summary["bridge_chunks_processed"] = self._chunks_processed
        summary["bridge_is_cancelled"] = self.is_cancelled
        summary["pipeline_status"] = self.pipeline.get_status()
        if self.backend_bridge:
            summary["backend_events_published"] = len(self.backend_bridge.published_events)
            summary["backend_publish_failures"] = len(self.backend_bridge.publish_failures)
        return summary
