"""Transcript Schemas and Validation Models for AI Voice Co-Pilot (W2 - STT).

This module defines the single authoritative source of truth for speech-to-text
data contracts across the platform:
- `TranscriptSegment`: Individual timestamped transcription span (interim or final).
- `TranscriptEvent`: Streaming event emitted by STT transcribers/adapters.
- `WordTiming`: Word-level alignment and confidence score.
- `STTErrorDetail`: Structured error model conforming to API Specifications & Interface Contracts (doc 04), Section 5 standard error format.
- `AudioChunk`: Structured audio slice contract for streaming input.

Time Measurement Conventions:
- Audio Time: `start_time` and `end_time` in `TranscriptSegment` and `WordTiming`
  measure the elapsed duration in seconds relative to the audio stream onset.
- Event Emission Time: `timestamp` in `TranscriptEvent` represents event emission time.
  Real adapters emit wall-clock POSIX time; the deterministic fake uses a simulated clock
  (seconds since stream start) so runs are reproducible.
These two representations are never conflated.
"""

from __future__ import annotations

import math
import re
import time
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class STTValidationError(ValueError):
    """Raised when an STT schema fails validation constraints with a human-readable explanation."""

    def __init__(self, message: str, field_name: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.field_name = field_name
        self.details = details or {}


class TranscriptEventType(str, Enum):
    """Enumeration of speech-to-text stream event lifecycle types.

    Active lifecycle events emitted by the mock pipeline:
    - INTERIM: Tentative partial hypothesis in flight.
    - FINAL: Committed, immutable segment of finalized speech.
    - ERROR: Pipeline or transcriber failure payload.
    - STREAM_COMPLETED: Stream termination delimiter emitted after last chunk.

    Reserved for real provider adapters (not emitted in mock mode):
    - SPEECH_STARTED: Voice Activity Detection (VAD) speech onset trigger.
    - SPEECH_ENDED: Voice Activity Detection (VAD) speech silence/offset trigger.
    """

    INTERIM = "interim"
    FINAL = "final"
    ERROR = "error"
    SPEECH_STARTED = "speech_started"
    SPEECH_ENDED = "speech_ended"
    STREAM_COMPLETED = "stream_completed"


class WordTiming(BaseModel):
    """Word-level alignment, boundary timestamps, and confidence score.

    Attributes:
        word: The textual token or word transcribed (non-empty string).
        start_time: Word onset in seconds relative to audio stream onset (finite, >= 0.0).
        end_time: Word offset in seconds relative to audio stream onset (finite, >= start_time).
        confidence: Normalized confidence probability in range [0.0, 1.0].
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    word: str = Field(
        ...,
        min_length=1,
        description="Transcribed token/word (non-empty string).",
    )
    start_time: float = Field(
        ...,
        ge=0.0,
        description="Word onset time in seconds relative to audio stream start (audio time, finite, >= 0.0).",
    )
    end_time: float = Field(
        ...,
        ge=0.0,
        description="Word offset time in seconds relative to audio stream start (audio time, finite, >= start_time).",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for this word (unit: normalized ratio [0.0, 1.0]).",
    )

    @field_validator("start_time", "end_time", "confidence")
    @classmethod
    def validate_finite_floats(cls, v: float, info: Any) -> float:
        if not math.isfinite(v):
            raise STTValidationError(
                f"Field '{info.field_name}' must be a finite numerical value, got {v}.",
                field_name=info.field_name,
            )
        return v

    @model_validator(mode="after")
    def validate_time_boundaries(self) -> WordTiming:
        if self.end_time < self.start_time:
            raise STTValidationError(
                f"Word end_time ({self.end_time:.3f}s) cannot be earlier than start_time ({self.start_time:.3f}s).",
                field_name="end_time",
                details={"start_time": self.start_time, "end_time": self.end_time},
            )
        return self


class STTErrorDetail(BaseModel):
    """Standardized error structure conforming to API Specifications & Interface Contracts (doc 04), Section 5.

    Attributes:
        code: Machine-readable error code (e.g., 'INVALID_PAYLOAD', 'AUDIO_DECODE_FAILED').
        message: Human-readable error description explaining what went wrong.
        request_id: Optional correlation request identifier conforming to doc 04, Section 5.
        retryable: Flag indicating if the caller can safely retry the operation.
        details: Optional dictionary of supplementary diagnostic properties.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(
        ...,
        min_length=1,
        description="Standardized machine-readable error code string (e.g. 'INVALID_PAYLOAD').",
    )
    message: str = Field(
        ...,
        min_length=1,
        description="Human-readable explanation of the error.",
    )
    request_id: Optional[str] = Field(
        default=None,
        description="Optional correlation request identifier conforming to doc 04, Section 5.",
    )
    retryable: bool = Field(
        default=False,
        description="Indicates whether client retry could resolve the failure.",
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Supplementary diagnostic context for troubleshooting.",
    )

    def to_api_error(self) -> Dict[str, Any]:
        """Convert error to standard API error envelope per API Specifications & Interface Contracts (doc 04), Section 5.

        Returns:
            Dictionary containing the mandatory top-level "error" key with "code",
            "message", "request_id", alongside "retryable" and "details".
        """
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "request_id": self.request_id,
                "retryable": self.retryable,
                "details": self.details,
            }
        }

    @field_validator("message")
    @classmethod
    def validate_no_secrets_in_error(cls, v: str) -> str:
        # PRD / API Specifications & Interface Contracts (doc 04) Security requirement: Never leak credentials or API keys in errors
        sensitive_patterns = [r"sk-[a-zA-Z0-9]{20,}", r"Bearer\s+[a-zA-Z0-9_\-\.]+", r"password\s*[:=]\s*\S+"]
        for pattern in sensitive_patterns:
            if re.search(pattern, v, flags=re.IGNORECASE):
                raise STTValidationError("Error message contains sensitive credential data.", field_name="message")
        return v


class TranscriptSegment(BaseModel):
    """An individual transcription segment representing a span of speech.

    Attributes:
        segment_id: Stable identifier for the segment (UUID or alphanumeric key).
        text: Transcribed text content.
            Policy: Final segments must contain non-empty text; interim segments may be empty.
        start_time: Segment onset timestamp in seconds from stream beginning (audio time, finite, >= 0.0).
        end_time: Segment offset timestamp in seconds from stream beginning (audio time, finite, >= start_time).
        confidence: Transcription confidence score in normalized range [0.0, 1.0].
        is_final: True if segment is finalized/immutable; False if interim/tentative.
        language: BCP-47 / ISO language code (e.g., 'en', 'en-US', 'es').
        words: Optional list of word-level timings and confidence scores.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    segment_id: str = Field(
        default_factory=lambda: str(uuid4()),
        min_length=1,
        description="Stable identifier for this segment.",
    )
    text: str = Field(
        ...,
        description="Transcribed speech text (non-empty for final segments; may be empty for interim pauses).",
    )
    start_time: float = Field(
        ...,
        ge=0.0,
        description="Segment start time in seconds from stream beginning (audio time, finite, >= 0.0).",
    )
    end_time: float = Field(
        ...,
        ge=0.0,
        description="Segment end time in seconds from stream beginning (audio time, finite, >= start_time).",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Statistical confidence score (unit: normalized ratio [0.0, 1.0]).",
    )
    is_final: bool = Field(
        default=False,
        description="True if segment is committed and final; False if interim/subject to update.",
    )
    language: str = Field(
        default="en",
        description="Language identifier tag (ISO 639-1 / BCP-47, e.g. 'en', 'en-US').",
    )
    words: List[WordTiming] = Field(
        default_factory=list,
        description="Optional list of word-level timestamps and confidence scores.",
    )

    @field_validator("start_time", "end_time", "confidence")
    @classmethod
    def validate_finite_numbers(cls, v: float, info: Any) -> float:
        if not math.isfinite(v):
            raise STTValidationError(
                f"Field '{info.field_name}' must be a finite numerical value, got {v}.",
                field_name=info.field_name,
            )
        return v

    @field_validator("segment_id")
    @classmethod
    def validate_segment_id_not_blank(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise STTValidationError("Segment identifier cannot be empty or whitespace.", field_name="segment_id")
        return trimmed

    @field_validator("language")
    @classmethod
    def validate_language_code(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise STTValidationError("Language code cannot be empty.", field_name="language")
        if not re.match(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})?$", trimmed):
            raise STTValidationError(
                f"Invalid language format '{v}'. Expected ISO 639-1 / BCP-47 format (e.g. 'en', 'en-US').",
                field_name="language",
            )
        return trimmed

    @model_validator(mode="after")
    def validate_segment_boundaries_and_text(self) -> TranscriptSegment:
        if self.end_time < self.start_time:
            raise STTValidationError(
                f"Segment end_time ({self.end_time:.3f}s) cannot be earlier than start_time ({self.start_time:.3f}s).",
                field_name="end_time",
                details={"start_time": self.start_time, "end_time": self.end_time},
            )

        # Policy: Final segments must have non-empty text content
        if self.is_final and not self.text.strip():
            raise STTValidationError(
                "Final segment text must not be empty or whitespace-only.",
                field_name="text",
            )

        # Ensure word timings fall within the segment boundary
        for w in self.words:
            if w.start_time < self.start_time - 0.01 or w.end_time > self.end_time + 0.01:
                raise STTValidationError(
                    f"Word timing [{w.start_time:.3f}s, {w.end_time:.3f}s] exceeds segment boundary "
                    f"[{self.start_time:.3f}s, {self.end_time:.3f}s].",
                    field_name="words",
                )
        return self


class TranscriptEvent(BaseModel):
    """Streaming speech-to-text event emitted during audio processing.

    Attributes:
        event_id: Unique event identifier (stable within session).
        event_type: Nature of event ('interim', 'final', 'error', 'speech_started', 'speech_ended', 'stream_completed').
        sequence_number: Monotonically non-decreasing counter for ordering in stream (>= 0).
        timestamp: Event emission timestamp in seconds (finite, >= 0.0). Real adapters emit wall-clock POSIX time; the deterministic fake uses a simulated clock (seconds since stream start) so runs are reproducible.
        session_id: Optional identifier associating event with a user session.
        segment: Associated TranscriptSegment (required for 'interim' and 'final').
        error: Associated STTErrorDetail (required when event_type is 'error').
        metadata: Provider-neutral metadata dictionary for diagnostics or downstream routing.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    event_id: str = Field(
        default_factory=lambda: str(uuid4()),
        min_length=1,
        description="Unique event UUID.",
    )
    event_type: TranscriptEventType = Field(
        ...,
        description="Type of transcript event: 'interim', 'final', 'error', 'speech_started', 'speech_ended', 'stream_completed'.",
    )
    sequence_number: int = Field(
        ...,
        ge=0,
        description="Monotonically increasing sequence index within stream session (>= 0).",
    )
    timestamp: float = Field(
        default_factory=time.time,
        ge=0.0,
        description="Event emission timestamp in seconds (finite, >= 0.0). Real adapters emit wall-clock POSIX time; the deterministic fake uses a simulated clock (seconds since stream start) so runs are reproducible.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Optional correlation identifier linking event to an active user session.",
    )
    segment: Optional[TranscriptSegment] = Field(
        default=None,
        description="Transcribed segment payload (mandatory for interim and final events).",
    )
    error: Optional[STTErrorDetail] = Field(
        default=None,
        description="Structured error diagnostic information (mandatory when event_type is 'error').",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-neutral diagnostic or telemetry attributes.",
    )

    @field_validator("timestamp")
    @classmethod
    def validate_finite_timestamp(cls, v: float) -> float:
        if not math.isfinite(v):
            raise STTValidationError("Event timestamp must be a finite number.", field_name="timestamp")
        return v

    @model_validator(mode="after")
    def validate_event_consistency(self) -> TranscriptEvent:
        # Check interim / final requires segment
        if self.event_type in (TranscriptEventType.INTERIM, TranscriptEventType.FINAL):
            if self.segment is None:
                raise STTValidationError(
                    f"Events of type '{self.event_type.value}' require a non-null 'segment' payload.",
                    field_name="segment",
                )
            # Consistency between event_type and segment.is_final
            if self.event_type == TranscriptEventType.FINAL and not self.segment.is_final:
                raise STTValidationError(
                    "TranscriptEvent is marked 'final' but its segment.is_final is False.",
                    field_name="segment.is_final",
                )
            if self.event_type == TranscriptEventType.INTERIM and self.segment.is_final:
                raise STTValidationError(
                    "TranscriptEvent is marked 'interim' but its segment.is_final is True.",
                    field_name="segment.is_final",
                )

        # Check error events require error detail
        if self.event_type == TranscriptEventType.ERROR:
            if self.error is None:
                raise STTValidationError(
                    "Events of type 'error' require a non-null 'error' payload.",
                    field_name="error",
                )
        return self


class AudioChunk(BaseModel):
    """Raw or PCM audio slice streamed into an STT adapter.

    Attributes:
        chunk_id: Unique identifier for the chunk.
        data: Binary audio payload (PCM, WAV, or Opus bytes).
        sequence_number: Sequence counter for chunk order verification (>= 0).
        timestamp: Timestamp of the audio chunk onset in seconds (audio time, finite, >= 0.0).
        duration_ms: Duration of the chunk in milliseconds (finite, >= 0.0).
        sample_rate: Sample rate in Hz (e.g. 16000).
        is_last: Flag indicating if this is the final chunk in the stream.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique chunk identifier.",
    )
    data: bytes = Field(
        ...,
        description="Raw audio byte content.",
    )
    sequence_number: int = Field(
        ...,
        ge=0,
        description="Monotonically non-decreasing chunk sequence number (>= 0).",
    )
    timestamp: float = Field(
        default=0.0,
        ge=0.0,
        description="Stream onset timestamp for this chunk in seconds (audio time, finite, >= 0.0).",
    )
    duration_ms: float = Field(
        default=100.0,
        ge=0.0,
        description="Audio slice duration in milliseconds (finite, >= 0.0).",
    )
    sample_rate: int = Field(
        default=16000,
        gt=0,
        description="Sampling frequency in Hz (typically 16000 for voice pipelines).",
    )
    is_last: bool = Field(
        default=False,
        description="True if this is the final stream packet / end-of-speech delimiter.",
    )

    @field_validator("timestamp", "duration_ms")
    @classmethod
    def validate_finite_floats(cls, v: float, info: Any) -> float:
        if not math.isfinite(v):
            raise STTValidationError(f"AudioChunk '{info.field_name}' must be finite.", field_name=info.field_name)
        return v

    @field_validator("data", mode="before")
    @classmethod
    def validate_non_empty_bytes(cls, v: Any) -> bytes:
        if not isinstance(v, (bytes, bytearray)):
            raise STTValidationError("AudioChunk data must be bytes or bytearray.", field_name="data")
        return bytes(v)
