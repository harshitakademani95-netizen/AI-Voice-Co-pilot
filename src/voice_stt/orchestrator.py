"""Transcription Orchestrator for AI Voice Co-Pilot (W2 - STT, Day 8, 9, 10, 11 & 12).

This module coordinates incoming audio chunks, passes them to a provider-neutral
STT adapter (defaulting to DeterministicFakeTranscriber for offline/mock execution),
and routes the resulting TranscriptEvents through the OrderedSegmentAccumulator to
produce structured, chronological speech-to-text outputs with robust timeout
handling, bounded retries, error normalization, interim-to-final reconciliation,
duplicate suppression, and out-of-order event handling.
"""

from __future__ import annotations

import concurrent.futures
import re
import time
from typing import Any, Dict, Iterable, Iterator, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.audio.preprocessing import AudioPreprocessor
from src.schemas.audio import AudioError
from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.adapter import (
    BaseSTTAdapter,
    STTAdapterState,
    STTAdapterStatus,
)
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.schemas import (
    AudioChunk,
    STTErrorDetail,
    STTValidationError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


def sanitize_error_message(message: str) -> str:
    """Mask credentials, tokens, or API keys in error strings."""
    redacted = re.sub(r"sk-[a-zA-Z0-9]{20,}", "[REDACTED_API_KEY]", message)
    redacted = re.sub(r"Bearer\s+[a-zA-Z0-9_\-\.]+", "Bearer [REDACTED_TOKEN]", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"password\s*[:=]\s*\S+", "password=[REDACTED_PASSWORD]", redacted, flags=re.IGNORECASE)
    return redacted


def normalize_stt_error(
    exc: Any,
    request_id: Optional[str] = None,
    default_code: str = "INTERNAL_ERROR",
) -> STTErrorDetail:
    """Convert any exception, dictionary, or error detail into a normalized STTErrorDetail.

    Ensures provider-neutral error classification, credentials masking, and standard
    error shape conforming to API Specifications & Interface Contracts (doc 04), Section 5.
    """
    if isinstance(exc, STTErrorDetail):
        return exc

    if isinstance(exc, dict):
        err_dict = exc.get("error", exc)
        raw_msg = sanitize_error_message(str(err_dict.get("message", "Unknown error")))
        return STTErrorDetail(
            code=str(err_dict.get("code", default_code)),
            message=raw_msg,
            request_id=err_dict.get("request_id", request_id),
            retryable=bool(err_dict.get("retryable", False)),
            details=err_dict.get("details", {}),
        )

    if isinstance(exc, AudioError):
        raw_msg = sanitize_error_message(getattr(exc, "message", str(exc)))
        code = getattr(exc, "code", "AUDIO_ERROR")
        req_id = getattr(exc, "request_id", None) or request_id
        details = getattr(exc, "details", {})
        retryable = "TIMEOUT" in code.upper() or "DROPOUT" in code.upper()
        return STTErrorDetail(
            code=code,
            message=raw_msg,
            request_id=req_id,
            retryable=retryable,
            details=details,
        )

    if isinstance(exc, STTValidationError):
        raw_msg = sanitize_error_message(exc.message)
        return STTErrorDetail(
            code="VALIDATION_ERROR",
            message=raw_msg,
            request_id=request_id,
            retryable=False,
            details=exc.details,
        )

    if isinstance(exc, (TimeoutError, concurrent.futures.TimeoutError)):
        raw_msg = sanitize_error_message(str(exc) or "Transcription operation timed out.")
        return STTErrorDetail(
            code="TRANSCRIPTION_TIMEOUT",
            message=raw_msg,
            request_id=request_id,
            retryable=True,
            details={"error_type": type(exc).__name__},
        )

    if isinstance(exc, (ConnectionError, ConnectionResetError, ConnectionRefusedError)):
        raw_msg = sanitize_error_message(str(exc) or "Network connection failed.")
        return STTErrorDetail(
            code="SERVICE_UNAVAILABLE",
            message=raw_msg,
            request_id=request_id,
            retryable=True,
            details={"error_type": type(exc).__name__},
        )

    if isinstance(exc, (ValueError, TypeError)):
        raw_msg = sanitize_error_message(str(exc) or "Invalid payload or parameters.")
        return STTErrorDetail(
            code="INVALID_PAYLOAD",
            message=raw_msg,
            request_id=request_id,
            retryable=False,
            details={"error_type": type(exc).__name__},
        )

    # Generic or unexpected exceptions
    raw_msg = sanitize_error_message(str(exc) or "An unexpected transcription error occurred.")
    lower_msg = raw_msg.lower()

    if "timeout" in lower_msg:
        code = "TRANSCRIPTION_TIMEOUT"
        retryable = True
    elif "rate limit" in lower_msg or "429" in lower_msg:
        code = "RATE_LIMITED"
        retryable = True
    elif "503" in lower_msg or "unavailable" in lower_msg or "connection" in lower_msg:
        code = "SERVICE_UNAVAILABLE"
        retryable = True
    elif "unauthorized" in lower_msg or "unauthenticated" in lower_msg or "forbidden" in lower_msg or "401" in lower_msg:
        code = "UNAUTHENTICATED"
        retryable = False
    elif "closed" in lower_msg:
        code = "ADAPTER_CLOSED"
        retryable = False
    else:
        code = default_code
        retryable = False

    return STTErrorDetail(
        code=code,
        message=raw_msg,
        request_id=request_id,
        retryable=retryable,
        details={"error_type": type(exc).__name__},
    )


class OrchestratorClosedError(RuntimeError):
    """Raised or emitted when transcription is attempted on a closed orchestrator."""

    def __init__(
        self,
        message: str = "Cannot process audio on a closed TranscriptionOrchestrator.",
    ) -> None:
        super().__init__(message)
        self.code = "ADAPTER_CLOSED"
        self.retryable = False


class RetryConfig(BaseModel):
    """Configuration for bounded retries and timeout handling in TranscriptionOrchestrator.

    Attributes:
        max_retries: Maximum number of retry attempts on retryable failures (>= 0).
        retry_delay: Base delay between retries in seconds (>= 0.0). Defaults to 0.0 for deterministic testing.
        backoff_factor: Multiplicative exponential backoff factor (>= 1.0).
        timeout_seconds: Optional per-operation timeout limit in seconds (> 0.0).
    """

    model_config = ConfigDict(extra="forbid")

    max_retries: int = Field(
        default=3,
        ge=0,
        description="Maximum retry attempts on retryable failures (>= 0).",
    )
    retry_delay: float = Field(
        default=0.0,
        ge=0.0,
        description="Base delay between retries in seconds (>= 0.0).",
    )
    backoff_factor: float = Field(
        default=1.0,
        ge=1.0,
        description="Multiplicative backoff factor (>= 1.0).",
    )
    timeout_seconds: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Optional timeout limit in seconds (> 0.0).",
    )


class TranscriptionOrchestrator:
    """Coordinates audio ingestion, adapter transcription, and segment accumulation.

    Responsibilities:
    1. Provider-Neutral Decoupling: Directs incoming audio slices (AudioChunk or raw
       PCM bytes) to an implementation of BaseSTTAdapter.
    2. Mock-Mode by Default: Defaults to DeterministicFakeTranscriber so no external
       cloud APIs, network connections, or paid keys are required.
    3. State Accumulation: Integrates with OrderedSegmentAccumulator to automatically
       collect, order, and deduplicate interim and final transcript segments.
    4. Timeout & Retry Resilience: Bounded retries for transient failures and strict
       timeout enforcement.
    5. Lifecycle Management: Coordinates initialization, per-session resetting,
       and graceful teardown of streaming resources.
    """

    def __init__(
        self,
        adapter: Optional[BaseSTTAdapter] = None,
        accumulator: Optional[OrderedSegmentAccumulator] = None,
        session_id: Optional[str] = None,
        retry_config: Optional[RetryConfig] = None,
        preprocessor: Optional[AudioPreprocessor] = None,
    ) -> None:
        """Initialize the transcription orchestrator.

        Args:
            adapter: Optional provider-neutral STT adapter. Defaults to DeterministicFakeTranscriber.
            accumulator: Optional segment accumulator. Defaults to a fresh OrderedSegmentAccumulator.
            session_id: Optional identifier for the streaming session.
            retry_config: Optional RetryConfig for bounded retries and timeouts.
            preprocessor: Optional AudioPreprocessor for standardizing incoming audio.
        """
        self._adapter: BaseSTTAdapter = adapter if adapter is not None else DeterministicFakeTranscriber()
        self._accumulator: OrderedSegmentAccumulator = (
            accumulator if accumulator is not None else OrderedSegmentAccumulator()
        )
        self._session_id: str = session_id or f"orch-session-{uuid4().hex[:8]}"
        self._retry_config: RetryConfig = retry_config or RetryConfig()
        self._preprocessor: Optional[AudioPreprocessor] = preprocessor
        self._retries_attempted: int = 0
        self._timeouts_encountered: int = 0
        self._initialized: bool = False

    @property
    def preprocessor(self) -> Optional[AudioPreprocessor]:
        """Optional audio preprocessor instance."""
        return self._preprocessor

    @property
    def retry_config(self) -> RetryConfig:
        """Active retry and timeout configuration."""
        return self._retry_config

    @property
    def retries_attempted(self) -> int:
        """Total retry attempts performed in current session."""
        return self._retries_attempted

    @property
    def timeouts_encountered(self) -> int:
        """Total timeout events detected in current session."""
        return self._timeouts_encountered

    @property
    def adapter(self) -> BaseSTTAdapter:
        """Underlying provider-neutral STT adapter."""
        return self._adapter

    @property
    def accumulator(self) -> OrderedSegmentAccumulator:
        """Underlying ordered segment accumulator."""
        return self._accumulator

    @property
    def session_id(self) -> str:
        """Active session identifier."""
        return self._session_id

    @property
    def state(self) -> STTAdapterState:
        """Current operational state of the underlying adapter."""
        return self._adapter.state

    def initialize(self, session_id: Optional[str] = None) -> None:
        """Initialize orchestrator resources and prepare adapter and accumulator.

        Args:
            session_id: Optional new session ID. Reuses current ID if omitted.
        """
        if session_id:
            self._session_id = session_id
        self._adapter.initialize(session_id=self._session_id)
        self._accumulator.reset()
        self._initialized = True

    def _execute_with_timeout(
        self,
        func: Any,
        *args: Any,
        timeout: float,
        **kwargs: Any,
    ) -> Any:
        """Execute a callable with a strict timeout using ThreadPoolExecutor.

        Note:
            In CPython, an already-executing thread cannot be forcefully terminated
            from the outside without risking interpreter-level deadlocks or resource
            corruption. To ensure the calling thread returns immediately without
            blocking on slow worker tasks, the ThreadPoolExecutor is managed
            explicitly and terminated with `shutdown(wait=False, cancel_futures=True)`.
            Production network-backed adapters should implement native socket/HTTP
            timeouts or cooperative cancellation tokens.
        """
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(func, *args, **kwargs)
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            executor.shutdown(wait=False, cancel_futures=True)
            raise TimeoutError(f"Transcription operation timed out after {timeout} seconds.")
        except Exception:
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=False, cancel_futures=True)

    def process_chunk(
        self,
        chunk: AudioChunk | bytes,
        is_last: bool = False,
    ) -> List[TranscriptEvent]:
        """Process an audio chunk through the adapter with timeout handling and bounded retries.

        Args:
            chunk: AudioChunk dataclass instance or raw audio bytes.
            is_last: Flag indicating whether this chunk marks the end of speech/stream.

        Returns:
            List of TranscriptEvent objects emitted by the adapter for this chunk.
        """
        if not self._initialized:
            self.initialize()

        if self._adapter.state == STTAdapterState.CLOSED:
            raise OrchestratorClosedError("Cannot process audio on a closed TranscriptionOrchestrator.")

        max_attempts = 1 + self._retry_config.max_retries
        attempt = 0
        last_error_detail: Optional[STTErrorDetail] = None

        while attempt < max_attempts:
            try:
                # Preprocess audio chunk inside try block so corrupt/invalid audio is normalized into an error event
                active_chunk = chunk
                if self._preprocessor is not None and isinstance(chunk, AudioChunk):
                    active_chunk = self._preprocessor.process_chunk(chunk)

                if self._retry_config.timeout_seconds is not None:
                    events = self._execute_with_timeout(
                        self._adapter.transcribe_chunk,
                        active_chunk,
                        is_last=is_last,
                        timeout=self._retry_config.timeout_seconds,
                    )
                else:
                    events = self._adapter.transcribe_chunk(active_chunk, is_last=is_last)

                # Check if adapter returned an error event in the list
                error_event = next((e for e in events if e.event_type == TranscriptEventType.ERROR), None)
                if error_event is not None and error_event.error is not None:
                    is_simulated = error_event.error.code == "SIMULATED_TRANSCRIBER_ERROR"
                    if error_event.error.retryable and not is_simulated and (attempt + 1 < max_attempts):
                        attempt += 1
                        self._retries_attempted += 1
                        if self._retry_config.retry_delay > 0:
                            time.sleep(self._retry_config.retry_delay * (self._retry_config.backoff_factor ** (attempt - 1)))
                        continue
                    else:
                        # Non-retryable error, simulated test injection, or retries exhausted: ingest events and return
                        for event in events:
                            self._accumulator.ingest_event(event)
                        return events

                # Successful processing: ingest events and return
                for event in events:
                    self._accumulator.ingest_event(event)
                return events

            except (AssertionError, NameError, SystemExit, KeyboardInterrupt):
                raise
            except Exception as exc:
                is_timeout = isinstance(exc, (TimeoutError, concurrent.futures.TimeoutError))
                if is_timeout:
                    self._timeouts_encountered += 1

                normalized_error = normalize_stt_error(exc, request_id=self._session_id)
                last_error_detail = normalized_error

                if normalized_error.retryable and (attempt + 1 < max_attempts):
                    attempt += 1
                    self._retries_attempted += 1
                    if self._retry_config.retry_delay > 0:
                        time.sleep(self._retry_config.retry_delay * (self._retry_config.backoff_factor ** (attempt - 1)))
                    continue
                else:
                    # Permanent error or retries exhausted
                    break

        # If loop exited due to exception failure:
        error_event = TranscriptEvent(
            event_id=str(uuid4()),
            event_type=TranscriptEventType.ERROR,
            sequence_number=self._accumulator.get_summary()["events_processed"],
            timestamp=time.time(),
            session_id=self._session_id,
            error=last_error_detail,
            metadata={
                "attempts_made": attempt + 1,
                "max_retries": self._retry_config.max_retries,
            },
        )
        self._accumulator.ingest_event(error_event)
        return [error_event]

    def process_stream(
        self,
        stream: Iterable[AudioChunk | bytes],
    ) -> Iterator[TranscriptEvent]:
        """Consume an iterable stream of audio chunks and yield transcript events.

        Guarantees that each stream chunk passes through the full orchestration pipeline:
        preprocessing (format conversion/normalization), timeout handling, bounded
        retries with backoff, error normalization, accumulator ordering, and duplicate
        suppression.

        Args:
            stream: Iterable yielding AudioChunk objects or raw audio bytes.

        Yields:
            TranscriptEvent instances as transcription progresses.
        """
        if not self._initialized:
            self.initialize()

        if self._adapter.state == STTAdapterState.CLOSED:
            normalized_error = normalize_stt_error(
                OrchestratorClosedError(),
                request_id=self._session_id,
                default_code="ADAPTER_CLOSED",
            )
            error_event = TranscriptEvent(
                event_id=str(uuid4()),
                event_type=TranscriptEventType.ERROR,
                sequence_number=self._accumulator.get_summary()["events_processed"],
                timestamp=time.time(),
                session_id=self._session_id,
                error=normalized_error,
                metadata={"closed": True},
            )
            self._accumulator.ingest_event(error_event)
            yield error_event
            return

        it = iter(stream)
        try:
            prev = next(it)
        except StopIteration:
            return

        for current in it:
            is_last = bool(prev.metadata.get("is_last", False)) if isinstance(prev, AudioChunk) else getattr(prev, "is_last", False)
            events = self.process_chunk(prev, is_last=is_last)
            for event in events:
                yield event
            prev = current

        # Final chunk of the stream marked with is_last=True
        events = self.process_chunk(prev, is_last=True)
        for event in events:
            yield event

    def ingest_event(self, event: TranscriptEvent) -> bool:
        """Ingest a TranscriptEvent directly into the orchestrator's accumulator.

        Enables out-of-order, delayed, or externally received transcript events
        to be processed, deduplicated, and chronologically ordered seamlessly.

        Args:
            event: TranscriptEvent to ingest.

        Returns:
            True if event was processed; False if suppressed as a duplicate.
        """
        if not self._initialized:
            self.initialize()
        return self._accumulator.ingest_event(event)

    def get_full_transcript(self, include_interim: bool = False) -> str:
        """Return the accumulated transcript string."""
        return self._accumulator.get_full_transcript(include_interim=include_interim)

    def get_transcript(self, include_interim: bool = False) -> str:
        """Return the accumulated transcript string (convenience alias for get_full_transcript)."""
        return self._accumulator.get_full_transcript(include_interim=include_interim)

    def get_final_segments(self) -> List[TranscriptSegment]:
        """Return defensive copy of committed final segments in chronological order."""
        return self._accumulator.get_final_segments()

    def get_interim_segment(self) -> Optional[TranscriptSegment]:
        """Return active interim segment, if any."""
        return self._accumulator.get_interim_segment()

    def get_average_confidence(self) -> float:
        """Return average confidence score across all committed final segments."""
        return self._accumulator.get_average_confidence()

    def get_total_duration(self) -> float:
        """Return total audio duration of committed segments in seconds."""
        return self._accumulator.get_total_duration()

    def get_summary(self) -> Dict[str, Any]:
        """Return consolidated diagnostic summary merging adapter and accumulator telemetry."""
        status = self.get_status()
        summary = self._accumulator.get_summary()
        summary["session_id"] = self._session_id
        summary["adapter_state"] = status.state.value
        summary["chunks_processed"] = status.chunks_processed
        summary["events_emitted"] = status.events_emitted
        summary["retries_attempted"] = self._retries_attempted
        summary["timeouts_encountered"] = self._timeouts_encountered
        summary["retry_config"] = self._retry_config.model_dump()
        return summary

    def get_status(self) -> STTAdapterStatus:
        """Return status and telemetry of the underlying adapter."""
        return self._adapter.get_status()

    def reset(self) -> None:
        """Reset internal accumulator and adapter sequence counters for a fresh session."""
        self._adapter.reset()
        self._accumulator.reset()
        self._retries_attempted = 0
        self._timeouts_encountered = 0

    def close(self) -> None:
        """Release underlying adapter and streaming resources."""
        self._adapter.close()

    def __enter__(self) -> TranscriptionOrchestrator:
        self.initialize()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
