"""Deterministic Fake Transcriber for AI Voice Co-Pilot (W2 - STT).

This transcriber implements the BaseSTTAdapter interface in mock mode without
requiring external cloud APIs or credentials. It guarantees strict determinism:
identical audio chunk sequences produce identical TranscriptEvents (matching
event_id, timestamps, confidence, text, and is_final flags).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import List, Optional, Sequence

from voice_stt.adapter import (
    BaseSTTAdapter,
    STTAdapterConfig,
    STTAdapterState,
)
from voice_stt.schemas import (
    AudioChunk,
    STTErrorDetail,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
    WordTiming,
)

# Canonical sample vocabulary for hash-based deterministic transcription
DEFAULT_VOCABULARY: Sequence[str] = (
    "explain",
    "this",
    "technical",
    "error",
    "in",
    "code",
    "find",
    "my",
    "project",
    "report",
    "summarize",
    "the",
    "active",
    "window",
    "content",
    "analyze",
    "spreadsheet",
    "data",
    "voice",
    "copilot",
    "ready",
    "to",
    "assist",
    "workspace",
)


class DeterministicFakeTranscriber(BaseSTTAdapter):
    """Deterministic, provider-neutral STT transcriber for local testing and CI/CD.

    Guarantees:
    - Same input stream -> Identical TranscriptEvent sequence.
    - Zero external network dependencies or API keys.
    - Deterministic event IDs, timestamps, words, and confidence scores.
    - Generates realistic streaming flow: interim hypothesis -> finalized segment.
    """

    def __init__(
        self,
        config: Optional[STTAdapterConfig] = None,
        script: Optional[Sequence[str]] = None,
        seed: int = 42,
        inject_error_at_chunk: Optional[int] = None,
        error_detail: Optional[STTErrorDetail] = None,
    ) -> None:
        """Initialize the deterministic fake transcriber.

        Args:
            config: Optional adapter configuration.
            script: Optional sequence of target phrases/sentences. If provided,
                chunks progressively advance through this script.
            seed: Numerical seed ensuring deterministic event IDs and metrics.
            inject_error_at_chunk: Sequence index of chunk at which to emit an error event.
            error_detail: Custom error information to emit when error injection triggers.
        """
        super().__init__(config)
        self.script: Optional[List[str]] = list(script) if script else None
        self.seed = seed
        self.inject_error_at_chunk = inject_error_at_chunk
        self.error_detail = error_detail or STTErrorDetail(
            code="SIMULATED_TRANSCRIBER_ERROR",
            message="Deterministic simulated transcriber failure triggered.",
            retryable=True,
            details={"seed": seed},
        )

        # Internal state tracking
        self._current_script_idx: int = 0
        self._current_word_idx: int = 0
        self._elapsed_time: float = 0.0
        self._accumulated_words: List[str] = []
        self._active_sentence_words: List[str] = []

    def _deterministic_uuid(self, salt: str) -> str:
        """Derive an RFC-4122 compliant deterministic UUID5 string."""
        namespace = uuid.UUID("12345678-1234-5678-1234-567812345678")
        token = f"{self.seed}:{salt}"
        return str(uuid.uuid5(namespace, token))

    def _hash_bytes(self, data: bytes) -> int:
        """Produce a stable 64-bit integer hash from bytes and seed."""
        h = hashlib.sha256(data + self.seed.to_bytes(4, byteorder="big")).digest()
        return int.from_bytes(h[:8], byteorder="big")

    def initialize(self, session_id: Optional[str] = None) -> None:
        """Prepare transcriber for a deterministic session."""
        fixed_session_id = session_id or f"mock-session-{self._deterministic_uuid('session')[:8]}"
        super().initialize(session_id=fixed_session_id)
        self.reset()
        self._state = STTAdapterState.READY

    def reset(self) -> None:
        """Reset internal sequence counters and pointers to ensure repeatability."""
        self._chunks_processed = 0
        self._events_emitted = 0
        self._current_script_idx = 0
        self._current_word_idx = 0
        self._elapsed_time = 0.0
        self._accumulated_words.clear()
        self._active_sentence_words.clear()
        self._last_error = None
        self._state = STTAdapterState.READY

    def transcribe_chunk(
        self,
        chunk: AudioChunk | bytes,
        is_last: bool = False,
    ) -> List[TranscriptEvent]:
        """Process an audio chunk deterministically and return transcript events.

        Args:
            chunk: AudioChunk or raw audio bytes.
            is_last: End-of-stream flag.

        Returns:
            List of TranscriptEvent objects.
        """
        if self._state == STTAdapterState.CLOSED:
            raise RuntimeError("Cannot transcribe on a closed STT adapter.")

        audio = self._coerce_audio_chunk(chunk, sequence_number=self._chunks_processed, is_last=is_last)
        chunk_seq = audio.sequence_number
        self._state = STTAdapterState.PROCESSING

        # Check for simulated error injection
        if self.inject_error_at_chunk is not None and chunk_seq == self.inject_error_at_chunk:
            self._state = STTAdapterState.ERROR
            self._last_error = self.error_detail
            error_event = TranscriptEvent(
                event_id=self._deterministic_uuid(f"err-{chunk_seq}"),
                event_type=TranscriptEventType.ERROR,
                sequence_number=self._events_emitted,
                timestamp=self._elapsed_time,
                session_id=self._session_id,
                error=self.error_detail,
                metadata={"chunk_seq": chunk_seq, "seed": self.seed},
            )
            self._events_emitted += 1
            self._chunks_processed += 1
            return [error_event]

        # Calculate chunk duration and time offsets
        chunk_duration = audio.duration_ms / 1000.0 if audio.duration_ms > 0 else 0.1
        chunk_start = self._elapsed_time
        chunk_end = chunk_start + chunk_duration
        self._elapsed_time = chunk_end

        events: List[TranscriptEvent] = []

        if self.script is not None:
            events.extend(self._process_scripted_chunk(audio, chunk_start, chunk_end))
        else:
            events.extend(self._process_hash_chunk(audio, chunk_start, chunk_end))

        self._chunks_processed += 1
        self._state = STTAdapterState.READY
        return events

    def _process_scripted_chunk(
        self,
        audio: AudioChunk,
        chunk_start: float,
        chunk_end: float,
    ) -> List[TranscriptEvent]:
        """Emit deterministic events driven by pre-configured script."""
        events: List[TranscriptEvent] = []
        if not self.script or self._current_script_idx >= len(self.script):
            # Script exhausted; return empty or final heartbeat
            if audio.is_last and self._active_sentence_words:
                events.append(self._flush_active_sentence(chunk_start, chunk_end))
            return events

        target_sentence = self.script[self._current_script_idx]
        tokens = target_sentence.strip().split()

        if self._current_word_idx < len(tokens):
            new_word = tokens[self._current_word_idx]
            self._active_sentence_words.append(new_word)
            self._current_word_idx += 1

            is_sentence_complete = (
                self._current_word_idx >= len(tokens)
                or audio.is_last
                or (self._current_script_idx == len(self.script) - 1 and audio.is_last)
            )

            # Check if interim results enabled and not yet complete
            if not is_sentence_complete and self.config.interim_results:
                interim_text = " ".join(self._active_sentence_words)
                interim_segment = TranscriptSegment(
                    segment_id=self._deterministic_uuid(f"seg-interim-{self._chunks_processed}"),
                    text=interim_text,
                    start_time=chunk_start,
                    end_time=chunk_end,
                    confidence=0.88,
                    is_final=False,
                    language=self.config.language,
                )
                events.append(
                    TranscriptEvent(
                        event_id=self._deterministic_uuid(f"evt-interim-{self._chunks_processed}"),
                        event_type=TranscriptEventType.INTERIM,
                        sequence_number=self._events_emitted,
                        timestamp=chunk_end,
                        session_id=self._session_id,
                        segment=interim_segment,
                        metadata={"words_in_flight": len(self._active_sentence_words)},
                    )
                )
                self._events_emitted += 1

            if is_sentence_complete:
                events.append(self._flush_active_sentence(chunk_start, chunk_end))
                self._current_script_idx += 1
                self._current_word_idx = 0

        return events

    def _flush_active_sentence(self, chunk_start: float, chunk_end: float) -> TranscriptEvent:
        """Create a finalized TranscriptEvent for the active sentence."""
        sentence_text = " ".join(self._active_sentence_words)
        word_count = max(1, len(self._active_sentence_words))
        time_per_word = max(0.01, (chunk_end - chunk_start) / word_count)

        words_timing = [
            WordTiming(
                word=w,
                start_time=chunk_start + i * time_per_word,
                end_time=chunk_start + (i + 1) * time_per_word,
                confidence=0.95,
            )
            for i, w in enumerate(self._active_sentence_words)
        ]

        final_segment = TranscriptSegment(
            segment_id=self._deterministic_uuid(f"seg-final-{self._chunks_processed}"),
            text=sentence_text,
            start_time=chunk_start,
            end_time=chunk_end,
            confidence=0.96,
            is_final=True,
            language=self.config.language,
            words=words_timing,
        )
        evt = TranscriptEvent(
            event_id=self._deterministic_uuid(f"evt-final-{self._chunks_processed}"),
            event_type=TranscriptEventType.FINAL,
            sequence_number=self._events_emitted,
            timestamp=chunk_end,
            session_id=self._session_id,
            segment=final_segment,
            metadata={"sentence_index": self._current_script_idx},
        )
        self._events_emitted += 1
        self._active_sentence_words.clear()
        return evt

    def _process_hash_chunk(
        self,
        audio: AudioChunk,
        chunk_start: float,
        chunk_end: float,
    ) -> List[TranscriptEvent]:
        """Emit deterministic events derived from audio byte content hash."""
        events: List[TranscriptEvent] = []
        h = self._hash_bytes(audio.data)

        # Deterministically select word from vocabulary
        vocab_len = len(DEFAULT_VOCABULARY)
        word_idx = h % vocab_len
        selected_word = DEFAULT_VOCABULARY[word_idx]

        self._active_sentence_words.append(selected_word)

        # Finalize sentence every 3 chunks or when is_last is True
        should_finalize = (len(self._active_sentence_words) >= 3) or audio.is_last

        if not should_finalize and self.config.interim_results:
            interim_text = " ".join(self._active_sentence_words)
            # Confidence derived deterministically: 0.80 to 0.90
            conf = 0.80 + ((h % 100) / 1000.0)
            interim_segment = TranscriptSegment(
                segment_id=self._deterministic_uuid(f"hash-seg-interim-{audio.sequence_number}"),
                text=interim_text,
                start_time=chunk_start,
                end_time=chunk_end,
                confidence=round(conf, 4),
                is_final=False,
                language=self.config.language,
            )
            events.append(
                TranscriptEvent(
                    event_id=self._deterministic_uuid(f"hash-evt-interim-{audio.sequence_number}"),
                    event_type=TranscriptEventType.INTERIM,
                    sequence_number=self._events_emitted,
                    timestamp=chunk_end,
                    session_id=self._session_id,
                    segment=interim_segment,
                )
            )
            self._events_emitted += 1
        elif should_finalize:
            final_text = " ".join(self._active_sentence_words)
            # Final confidence derived deterministically: 0.92 to 0.99
            conf = 0.92 + ((h % 70) / 1000.0)
            word_count = len(self._active_sentence_words)
            time_per_word = max(0.01, (chunk_end - chunk_start) / max(1, word_count))

            words_timing = [
                WordTiming(
                    word=w,
                    start_time=chunk_start + i * time_per_word,
                    end_time=chunk_start + (i + 1) * time_per_word,
                    confidence=round(conf, 4),
                )
                for i, w in enumerate(self._active_sentence_words)
            ]

            final_segment = TranscriptSegment(
                segment_id=self._deterministic_uuid(f"hash-seg-final-{audio.sequence_number}"),
                text=final_text,
                start_time=chunk_start,
                end_time=chunk_end,
                confidence=round(conf, 4),
                is_final=True,
                language=self.config.language,
                words=words_timing,
            )
            events.append(
                TranscriptEvent(
                    event_id=self._deterministic_uuid(f"hash-evt-final-{audio.sequence_number}"),
                    event_type=TranscriptEventType.FINAL,
                    sequence_number=self._events_emitted,
                    timestamp=chunk_end,
                    session_id=self._session_id,
                    segment=final_segment,
                )
            )
            self._events_emitted += 1
            self._active_sentence_words.clear()

        return events
