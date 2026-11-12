"""Provider-Neutral Speech-To-Text Adapter Interface.

This module provides the abstract base class and contract definitions for
speech-to-text engines in AI Voice Co-Pilot (W2). It abstracts underlying
providers (e.g. Whisper, Google Cloud Speech, Deepgram, or Mock transcribers)
ensuring higher-level orchestrators are completely decoupled from concrete
STT implementations and paid APIs.

Architecture Contract:
1. Inputs:
   - Streaming slices of audio (`AudioChunk` or raw `bytes`).
   - Slices indicate sample rate, sequence counter, and end-of-speech flag (`is_last`).
2. Outputs:
   - Synchronous or streamed `TranscriptEvent` sequences.
   - Events conform strictly to `TranscriptEventType` ('interim', 'final', 'error', 'stream_completed').
   - Lifecycle events 'speech_started' and 'speech_ended' are reserved for real provider adapters.
3. Extensibility:
   - Future commercial engines (e.g. OpenAI Whisper, Deepgram Nova-2, Google Cloud STT)
     can be integrated by subclassing `BaseSTTAdapter` without modifying `OrderedSegmentAccumulator`
     or transcript schemas.
4. Offline / Mock Mode:
   - Full mock execution without paid API keys, network traffic, or hardware microphones.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Iterable, Iterator, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from voice_stt.schemas import (
    AudioChunk,
    STTErrorDetail,
    TranscriptEvent,
)


class STTAdapterState(str, Enum):
    """Operational states of an STT adapter."""

    UNINITIALIZED = "uninitialized"
    READY = "ready"
    PROCESSING = "processing"
    ERROR = "error"
    CLOSED = "closed"


class STTAdapterConfig(BaseModel):
    """Provider-neutral configuration for STT adapters.

    Attributes:
        language: Target spoken language code (e.g. 'en', 'es', 'auto').
        sample_rate: Expected audio sampling rate in Hz (default: 16000).
        interim_results: Whether to emit low-latency interim hypothesis events.
        model_name: Optional provider model designation (e.g., 'whisper-large-v3', 'mock-v1').
        punctuate: Whether automatic punctuation and capitalization should be applied.
        extra_options: Optional provider-specific configuration flags.
    """

    model_config = ConfigDict(extra="forbid")

    language: str = Field(
        default="en",
        description="Target spoken language (ISO 639-1 tag).",
    )
    sample_rate: int = Field(
        default=16000,
        gt=0,
        description="Audio sampling rate in Hz.",
    )
    interim_results: bool = Field(
        default=True,
        description="Enable streaming interim transcription events before finalization.",
    )
    model_name: str = Field(
        default="mock-stt-v1",
        description="Logical model name or identifier.",
    )
    punctuate: bool = Field(
        default=True,
        description="Enable punctuation restoration in transcription.",
    )
    extra_options: Dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific tuning parameters.",
    )


class STTAdapterStatus(BaseModel):
    """Real-time operational health and telemetry status of an adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: STTAdapterState = Field(
        ...,
        description="Current operational lifecycle state.",
    )
    chunks_processed: int = Field(
        default=0,
        ge=0,
        description="Total audio chunks consumed in current session.",
    )
    events_emitted: int = Field(
        default=0,
        ge=0,
        description="Total transcript events emitted in current session.",
    )
    active_session_id: Optional[str] = Field(
        default=None,
        description="Active streaming session identifier.",
    )
    last_error: Optional[STTErrorDetail] = Field(
        default=None,
        description="Most recent error encountered if in error state.",
    )


class BaseSTTAdapter(ABC):
    """Abstract Base Class establishing the provider-neutral STT adapter interface.

    All speech-to-text engines (real or mock) implement this contract, ensuring
    orchestration layers (W1, agents, desktop apps) interact uniformly with STT.
    """

    def __init__(self, config: Optional[STTAdapterConfig] = None) -> None:
        self.config = config or STTAdapterConfig()
        self._state: STTAdapterState = STTAdapterState.UNINITIALIZED
        self._chunks_processed: int = 0
        self._events_emitted: int = 0
        self._session_id: Optional[str] = None
        self._last_error: Optional[STTErrorDetail] = None

    @property
    def state(self) -> STTAdapterState:
        """Current lifecycle state."""
        return self._state

    @property
    def session_id(self) -> Optional[str]:
        """Active session ID."""
        return self._session_id

    def initialize(self, session_id: Optional[str] = None) -> None:
        """Initialize resources and prepare adapter for transcription.

        Args:
            session_id: Optional caller-provided session ID. Generated if omitted.
        """
        self._session_id = session_id or f"stt-session-{uuid4().hex[:8]}"
        self._chunks_processed = 0
        self._events_emitted = 0
        self._last_error = None
        self._state = STTAdapterState.READY

    @abstractmethod
    def transcribe_chunk(
        self,
        chunk: AudioChunk | bytes,
        is_last: bool = False,
    ) -> List[TranscriptEvent]:
        """Process a single audio chunk and return zero or more transcript events.

        Args:
            chunk: AudioChunk instance or raw audio bytes.
            is_last: Flag indicating whether this chunk marks the end of the stream.

        Returns:
            List of TranscriptEvent objects (interim, final, or error).
        """
        pass

    def transcribe_stream(
        self,
        stream: Iterable[AudioChunk | bytes],
    ) -> Iterator[TranscriptEvent]:
        """Consume an iterable stream of audio chunks and yield transcript events.

        Uses one-item lookahead so the final chunk of the stream is treated with
        is_last=True, flushing any pending words. An empty stream yields nothing.

        Args:
            stream: Iterable yielding AudioChunk objects or raw audio bytes.

        Yields:
            TranscriptEvent instances as transcription progresses.
        """
        it = iter(stream)
        try:
            prev = next(it)
        except StopIteration:
            return

        for current in it:
            events = self.transcribe_chunk(prev, is_last=getattr(prev, "is_last", False))
            for event in events:
                yield event
            prev = current

        events = self.transcribe_chunk(prev, is_last=True)
        for event in events:
            yield event

    @abstractmethod
    def reset(self) -> None:
        """Reset internal accumulator, buffer, and sequence counters for a fresh session."""
        pass

    def close(self) -> None:
        """Release any allocated provider or streaming resources."""
        self._state = STTAdapterState.CLOSED

    def get_status(self) -> STTAdapterStatus:
        """Query current adapter telemetry and state."""
        return STTAdapterStatus(
            state=self._state,
            chunks_processed=self._chunks_processed,
            events_emitted=self._events_emitted,
            active_session_id=self._session_id,
            last_error=self._last_error,
        )

    def _coerce_audio_chunk(
        self,
        chunk: AudioChunk | bytes,
        sequence_number: int,
        is_last: bool = False,
    ) -> AudioChunk:
        """Helper to normalize raw bytes into a strongly-typed AudioChunk."""
        if isinstance(chunk, AudioChunk):
            if is_last and not chunk.is_last:
                return chunk.model_copy(update={"is_last": True})
            return chunk
        elif isinstance(chunk, (bytes, bytearray)):
            return AudioChunk(
                data=bytes(chunk),
                sequence_number=sequence_number,
                timestamp=self._chunks_processed * 0.1,
                duration_ms=100.0,
                sample_rate=self.config.sample_rate,
                is_last=is_last,
            )
        else:
            raise TypeError(f"Expected AudioChunk or bytes, received {type(chunk).__name__}")

    def __enter__(self) -> BaseSTTAdapter:
        self.initialize()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
