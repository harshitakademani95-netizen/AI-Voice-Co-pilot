"""
Transcription Module Integration Bridge (Week 3, Day 19).

Connects the Audio & VAD pipeline (Workstream W1) directly to the Speech-to-Text (STT)
transcription pipeline (Workstream W2) without requiring cloud APIs or physical microphones:
- Normalized AudioEvent handoff (SPEECH_START -> AUDIO_CHUNK* -> SPEECH_END).
- Session ID and Correlation ID propagation.
- Deterministic mock STT transcription using DeterministicFakeTranscriber.
- Live hypothesis and finalized segment accumulation via OrderedSegmentAccumulator.
- Safe handling of device loss, stream cancellation, and transcription errors.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set
import uuid

from src.schemas.audio import AudioChunk, AudioError, AudioEvent, AudioEventType, AudioFormat

logger = logging.getLogger(__name__)

import sys
from pathlib import Path

# Ensure voice_stt can be discovered consistently across environments
_curr_path = Path(__file__).resolve().parent
_src_path = _curr_path.parent
_proj_path = _src_path.parent
for _p in [str(_src_path), str(_proj_path)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from src.voice_stt.accumulator import OrderedSegmentAccumulator
    from src.voice_stt.adapter import BaseSTTAdapter, STTAdapterState
    from src.voice_stt.fake_transcriber import DeterministicFakeTranscriber
    from src.voice_stt.schemas import (
        STTErrorDetail,
        STTValidationError,
        TranscriptEvent,
        TranscriptEventType,
        TranscriptSegment,
    )
except ImportError:
    try:
        from voice_stt.accumulator import OrderedSegmentAccumulator
        from voice_stt.adapter import BaseSTTAdapter, STTAdapterState
        from voice_stt.fake_transcriber import DeterministicFakeTranscriber
        from voice_stt.schemas import (
            STTErrorDetail,
            STTValidationError,
            TranscriptEvent,
            TranscriptEventType,
            TranscriptSegment,
        )
    except ImportError as err:
        raise ImportError(
            f"AudioTranscriptionBridge requires the voice_stt module, which could not be loaded: {err}. "
            "Please ensure pydantic is installed (`pip install 'pydantic>=2,<3'`) and that "
            "'projects/sde-3-voicebot/src' or the project root is added to PYTHONPATH."
        ) from err


class AudioTranscriptionBridge:
    """
    Bridge connecting normalized audio events to the team's Speech-to-Text module.

    Maintains session isolation, routes speech chunks to the STT adapter,
    accumulates streaming hypotheses into full transcripts, and handles errors and cancellation safely.
    """

    def __init__(
        self,
        pipeline: Optional[Any] = None,
        transcriber: Optional[BaseSTTAdapter] = None,
        accumulator: Optional[OrderedSegmentAccumulator] = None,
        auto_feed: bool = True,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        self.pipeline = pipeline
        self.session_id: str = session_id or (pipeline.session_id if pipeline else f"sess-stt-{uuid.uuid4().hex[:8]}")
        self.correlation_id: str = correlation_id or (pipeline.correlation_id if pipeline else f"corr-stt-{uuid.uuid4().hex[:8]}")

        self.transcriber: BaseSTTAdapter = transcriber or DeterministicFakeTranscriber(seed=42)
        self.accumulator: OrderedSegmentAccumulator = accumulator or OrderedSegmentAccumulator()

        self._transcript_events: List[TranscriptEvent] = []
        self._errors: List[Dict[str, Any]] = []
        self._is_cancelled: bool = False
        self._active_segment_id: Optional[str] = None
        self._speech_chunks_transcribed: int = 0
        self._total_audio_events_received: int = 0
        self._reconnection_count: int = 0
        self._transcribed_chunk_keys: Set[Any] = set()

        # Initialize transcriber session
        try:
            self.transcriber.initialize(session_id=self.session_id)
        except Exception as exc:
            logger.warning("Transcriber initialization error: %s", exc)
            self._errors.append({"type": "init_error", "error": str(exc)})

        # If pipeline supplied and auto_feed requested, register callback
        if self.pipeline is not None and auto_feed:
            prev_callback = getattr(self.pipeline, "_on_event_callback", None)

            def chained_callback(evt: AudioEvent) -> None:
                if prev_callback is not None:
                    try:
                        prev_callback(evt)
                    except Exception as exc:
                        logger.warning("Pipeline event callback error: %s", exc)
                self.feed_audio_event(evt)

            self.pipeline._on_event_callback = chained_callback

    @property
    def is_cancelled(self) -> bool:
        """True if the transcription session was cancelled."""
        return self._is_cancelled

    @property
    def _transcribed_chunk_seqs(self) -> Set[int]:
        """Backward-compatible view of sequence IDs that have been transcribed."""
        return {key[3] for key in self._transcribed_chunk_keys}

    @property
    def active_segment_id(self) -> Optional[str]:
        """Current speech segment ID being transcribed, or None if in silence."""
        return self._active_segment_id

    def reset(self) -> None:
        """Reset internal accumulator and transcriber state."""
        self._transcript_events.clear()
        self._errors.clear()
        self._is_cancelled = False
        self._active_segment_id = None
        self._speech_chunks_transcribed = 0
        self._total_audio_events_received = 0
        self._reconnection_count = 0
        self._transcribed_chunk_keys.clear()
        try:
            self.transcriber.reset()
        except Exception as exc:
            logger.warning("Transcriber reset error: %s", exc)
        self.accumulator.reset()

    def start_new_session(self, session_id: str, correlation_id: Optional[str] = None) -> None:
        """
        Explicitly begin a new session, resetting cancellation and accumulator state (Week 3, B4).
        """
        self.session_id = session_id
        if correlation_id:
            self.correlation_id = correlation_id
        self._is_cancelled = False
        self._active_segment_id = None
        self._speech_chunks_transcribed = 0
        self._total_audio_events_received = 0
        self._reconnection_count = 0
        self._transcribed_chunk_keys.clear()
        self._transcript_events.clear()
        self._errors.clear()
        self.accumulator.reset()
        try:
            self.transcriber.initialize(session_id=self.session_id)
        except Exception as exc:
            logger.warning("Transcriber re-initialization error: %s", exc)

    def feed_audio_event(self, event: AudioEvent) -> List[TranscriptEvent]:
        """
        Ingest a normalized AudioEvent from the audio pipeline and route to STT.

        Handles:
        - SPEECH_START: Prepares speech segment tracking and aligns session IDs.
        - AUDIO_CHUNK: Transcribes speech-bearing frames through STT adapter (no duplicates).
        - SPEECH_END: Finalizes segment with end-of-speech delimiter.
        - DEVICE_LOST: Safe handling of hardware loss without throwing.
        - CANCELLED: Purges in-flight state and halts future transcription.
        """
        if not isinstance(event, AudioEvent):
            raise AudioError("Expected an AudioEvent instance.", code="INVALID_PAYLOAD")

        self._total_audio_events_received += 1
        generated_events: List[TranscriptEvent] = []

        # 1. Cancellation handling (Week 3, B3)
        if event.event_type == AudioEventType.CANCELLED:
            self._is_cancelled = True
            self._active_segment_id = None
            # Discard all unfinished speech and pending transcript content
            self.accumulator.reset()
            self._transcript_events.clear()
            return []

        # 2. If cancelled and event is for the same session, discard all subsequent chunks
        if self._is_cancelled:
            # If a SPEECH_START with a new session arrives, start a new session (Week 3, B4)
            if event.event_type == AudioEventType.SPEECH_START and event.session_id != self.session_id:
                self.start_new_session(event.session_id, event.correlation_id)
            else:
                return []

        # 3. Device loss handling (Week 3, B5)
        if event.event_type == AudioEventType.DEVICE_LOST:
            self._active_segment_id = None
            self._errors.append({
                "type": "device_lost",
                "event_id": event.event_id,
                "metadata": event.metadata,
            })
            return []

        # 3b. Device reconnection handling (Section 2)
        if event.event_type == AudioEventType.DEVICE_RECONNECTED:
            self._active_segment_id = None
            self._reconnection_count += 1
            self._errors.append({
                "type": "device_reconnected",
                "event_id": event.event_id,
                "metadata": event.metadata,
            })
            return []

        # 4. Speech onset handling: establish active speech segment and session alignment
        if event.event_type == AudioEventType.SPEECH_START:
            self._active_segment_id = event.segment_id
            # Synchronize session IDs if changed
            if event.session_id and event.session_id != self.session_id:
                self.start_new_session(event.session_id, event.correlation_id)
            self._active_segment_id = event.segment_id

        # 5. Normalized audio chunk handling (Section 2 & B7: composite dedup key)
        elif event.event_type == AudioEventType.AUDIO_CHUNK:
            # Transcribe only if marked as speech or within an active speech segment
            if (event.is_speech or self._active_segment_id is not None) and event.chunk is not None:
                # Composite deduplication key: session + reconnection gen + segment + sequence_id
                dedup_key = (
                    self.session_id,
                    self._reconnection_count,
                    event.segment_id or self._active_segment_id,
                    event.chunk.sequence_id,
                )
                if dedup_key not in self._transcribed_chunk_keys:
                    self._transcribed_chunk_keys.add(dedup_key)
                    evts = self._transcribe_chunk_safe(event.chunk, is_last=False)
                    generated_events.extend(evts)

        # 6. Speech end handling (Section 6: finalize through transcriber flush)
        elif event.event_type == AudioEventType.SPEECH_END:
            # First, attempt to flush active sentence directly from the mock transcriber
            if hasattr(self.transcriber, "flush"):
                try:
                    flushed = self.transcriber.flush()
                    for fev in flushed:
                        if hasattr(fev, "session_id") and not fev.session_id:
                            object.__setattr__(fev, "session_id", self.session_id)
                        self._transcript_events.append(fev)
                        self.accumulator.ingest_event(fev)
                        generated_events.append(fev)
                except Exception as exc:
                    logger.warning("Transcriber flush error on speech_end: %s", exc)

            # If transcriber didn't emit a final event, finalize from accumulator interim
            if not generated_events:
                interim = self.accumulator.get_interim_segment()
                if interim is not None and getattr(interim, "text", "").strip():
                    final_seg = TranscriptSegment(
                        segment_id=interim.segment_id or f"seg-final-{self.session_id}-{len(self.accumulator.get_final_segments())}",
                        start_time=interim.start_time,
                        end_time=interim.end_time,
                        text=interim.text,
                        confidence=interim.confidence,
                        is_final=True,
                        words=getattr(interim, "words", []),
                    )
                    final_event = TranscriptEvent(
                        event_id=f"evt-final-{uuid.uuid4().hex[:8]}",
                        event_type=TranscriptEventType.FINAL,
                        sequence_number=len(self._transcript_events),
                        timestamp=event.timestamp,
                        session_id=self.session_id,
                        segment=final_seg,
                    )
                    self._transcript_events.append(final_event)
                    self.accumulator.ingest_event(final_event)
                    generated_events.append(final_event)
            self._active_segment_id = None

        return generated_events

    def _transcribe_chunk_safe(self, chunk: AudioChunk, is_last: bool = False) -> List[TranscriptEvent]:
        """
        Safely invoke transcriber, record errors, and ingest into accumulator.
        Defensively copies metadata to prevent mutation of the original AudioChunk (Week 3, B14).
        """
        try:
            # Copy metadata before adding bridge-specific information (B14)
            chunk_metadata = dict(chunk.metadata) if chunk.metadata else {}
            chunk_metadata["is_last"] = is_last
            chunk_metadata["session_id"] = self.session_id
            chunk_metadata["correlation_id"] = self.correlation_id
            if self._active_segment_id:
                chunk_metadata["segment_id"] = self._active_segment_id

            # Create wrapped chunk with copied metadata so original chunk is unmodified
            wrapped_chunk = AudioChunk(
                sequence_id=chunk.sequence_id,
                timestamp=chunk.timestamp,
                data=chunk.data,
                format=chunk.format,
                metadata=chunk_metadata,
            )

            events = self.transcriber.transcribe_chunk(wrapped_chunk, is_last=is_last)
            self._speech_chunks_transcribed += 1

            for ev in events:
                # Retain session tracking on generated transcript events
                if hasattr(ev, "session_id") and not ev.session_id:
                    object.__setattr__(ev, "session_id", self.session_id)

                self._transcript_events.append(ev)
                self.accumulator.ingest_event(ev)

            return events

        except Exception as exc:
            logger.warning("Transcription error on chunk %s: %s", chunk.sequence_id, exc)
            self._errors.append({
                "type": "transcription_error",
                "error": str(exc),
                "chunk_seq": chunk.sequence_id,
            })
            return []

    def get_full_transcript(self) -> str:
        """
        Return the complete accumulated transcript text.
        Returns empty string if the session is cancelled (Week 3, B3).
        """
        if self._is_cancelled:
            return ""
        return self.accumulator.get_full_transcript()

    def get_final_segments(self) -> List[TranscriptSegment]:
        """
        Return all finalized transcript segments in temporal order.
        Returns empty list if the session is cancelled (Week 3, B3).
        """
        if self._is_cancelled:
            return []
        return self.accumulator.get_final_segments()

    def get_interim_segment(self) -> Optional[TranscriptSegment]:
        """
        Return the current in-flight interim hypothesis segment, if any.
        Returns None if the session is cancelled (Week 3, B3).
        """
        if self._is_cancelled:
            return None
        return self.accumulator.get_interim_segment()

    def get_transcript_events(self) -> List[TranscriptEvent]:
        """Return all transcript events emitted by the transcriber."""
        return list(self._transcript_events)

    def get_status(self) -> Dict[str, Any]:
        """Aggregate bridge status, segment count, confidence, and telemetry."""
        return {
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "active_segment_id": self._active_segment_id,
            "is_cancelled": self._is_cancelled,
            "total_audio_events_received": self._total_audio_events_received,
            "speech_chunks_transcribed": self._speech_chunks_transcribed,
            "transcript_events_count": len(self._transcript_events),
            "final_segments_count": len(self.get_final_segments()),
            "full_transcript": self.get_full_transcript(),
            "average_confidence": round(self.accumulator.get_average_confidence(), 4) if not self._is_cancelled else 0.0,
            "errors_count": len(self._errors),
        }
