"""Transcript Schemas and Validation Models for AI Voice Co-Pilot (W2 - STT).

This module defines the single authoritative source of truth for speech-to-text
data contracts across the platform:
- `TranscriptSegment`: Individual timestamped transcription span (interim or final).
- `TranscriptEvent`: Streaming event emitted by STT transcribers/adapters.
- `WordTiming`: Word-level alignment and confidence score.
- `STTErrorDetail`: Structured error model conforming to Section 5 SDD standard error format.
- `AudioChunk`: Structured audio slice contract for streaming input.

All schemas enforce strict validation rules and units (seconds for timestamps,
normalized 0.0-1.0 floats for confidence). Invalid payloads are rejected with
clear, actionable error messages.
"""

from __future__ import annotations

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
    """Enumeration of speech-to-text stream event types."""

    INTERIM = "interim"
    FINAL = "final"
    ERROR = "error"
    SPEECH_STARTED = "speech_started"
    SPEECH_ENDED = "speech_ended"


class WordTiming(BaseModel):
    """Word-level alignment, boundary timestamps, and confidence score.

    Attributes:
        word: The textual token or word transcribed.
        start_time: Start offset in seconds relative to stream onset (>= 0.0).
        end_time: End offset in seconds relative to stream onset (>= start_time).
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
        description="Word onset time in seconds relative to audio stream start (unit: seconds, >= 0.0).",
    )
    end_time: float = Field(
        ...,
        ge=0.0,
        description="Word offset time in seconds relative to audio stream start (unit: seconds, >= start_time).",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for this word (unit: normalized ratio [0.0, 1.0]).",
    )

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
    """Standardized error structure conforming to SDD Section 5.

    Attributes:
        code: Machine-readable error code (e.g., 'INVALID_REQUEST', 'AUDIO_DECODE_FAILED').
        message: Human-readable error description explaining what went wrong.
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
    retryable: bool = Field(
        default=False,
        description="Indicates whether client retry could resolve the failure.",
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Supplementary diagnostic context for troubleshooting.",
    )


class TranscriptSegment(BaseModel):
    """An individual transcription segment representing a span of speech.

    Attributes:
        segment_id: Unique identifier for the segment (UUID or alphanumeric key).
        text: Transcribed text content.
        start_time: Segment onset timestamp in seconds from stream start (>= 0.0).
        end_time: Segment offset timestamp in seconds from stream start (>= start_time).
        confidence: Transcription confidence score in range [0.0, 1.0].
        is_final: True if segment is finalized/immutable; False if interim/tentative.
        language: BCP-47 / ISO language code (e.g., 'en', 'en-US', 'es').
        words: Optional list of word-level timings and confidence scores.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    segment_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this segment.",
    )
    text: str = Field(
        ...,
        description="Transcribed speech text (may be empty only for non-textual events).",
    )
    start_time: float = Field(
        ...,
        ge=0.0,
        description="Segment start time in seconds from stream beginning (unit: seconds, >= 0.0).",
    )
    end_time: float = Field(
        ...,
        ge=0.0,
        description="Segment end time in seconds from stream beginning (unit: seconds, >= start_time).",
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
    def validate_segment_boundaries(self) -> TranscriptSegment:
        if self.end_time < self.start_time:
            raise STTValidationError(
                f"Segment end_time ({self.end_time:.3f}s) cannot be earlier than start_time ({self.start_time:.3f}s).",
                field_name="end_time",
                details={"start_time": self.start_time, "end_time": self.end_time},
            )
        # Ensure words fall within the segment boundary
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
        event_id: Unique event identifier.
        event_type: Nature of event ('interim', 'final', 'error', 'speech_started', 'speech_ended').
        sequence_number: Monotonically non-decreasing counter for ordering in stream (>= 0).
        timestamp: Wall-clock POSIX epoch timestamp when the event was generated (unit: seconds).
        session_id: Optional identifier associating event with a user session.
        segment: Associated TranscriptSegment (required for 'interim' and 'final').
        error: Associated STTErrorDetail (required when event_type is 'error').
        metadata: Provider-neutral metadata dictionary for diagnostics or downstream routing.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    event_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique event UUID.",
    )
    event_type: TranscriptEventType = Field(
        ...,
        description="Type of transcript event: 'interim', 'final', 'error', 'speech_started', 'speech_ended'.",
    )
    sequence_number: int = Field(
        ...,
        ge=0,
        description="Monotonically increasing sequence index within stream session (>= 0).",
    )
    timestamp: float = Field(
        default_factory=time.time,
        ge=0.0,
        description="Wall-clock POSIX generation timestamp in seconds.",
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
        timestamp: Timestamp of the audio chunk onset in seconds (>= 0.0).
        duration_ms: Duration of the chunk in milliseconds (>= 0.0).
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
        description="Stream onset timestamp for this chunk in seconds (>= 0.0).",
    )
    duration_ms: float = Field(
        default=100.0,
        ge=0.0,
        description="Audio slice duration in milliseconds (>= 0.0).",
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

    @field_validator("data", mode="before")
    @classmethod
    def validate_non_empty_bytes(cls, v: Any) -> bytes:
        if not isinstance(v, (bytes, bytearray)):
            raise STTValidationError("AudioChunk data must be bytes or bytearray.", field_name="data")
        return bytes(v)
