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
import math
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

    if isinstance(exc, OrchestratorClosedError):
        raw_msg = sanitize_error_message(getattr(exc, "message", str(exc)))
        return STTErrorDetail(
            code="ADAPTER_CLOSED",
            message=raw_msg,
            request_id=request_id,
            retryable=False,
            details={"error_type": type(exc).__name__},
        )

    if isinstance(exc, OrchestratorCancelledError):
        raw_msg = sanitize_error_message(getattr(exc, "message", str(exc)))
        return STTErrorDetail(
            code="OPERATION_CANCELLED",
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
    elif "quota" in lower_msg:
        code = "QUOTA_EXCEEDED"
        retryable = False
    elif "rate limit" in lower_msg or "429" in lower_msg:
        code = "RATE_LIMITED"
        retryable = True
    elif "503" in lower_msg or "unavailable" in lower_msg or "connection" in lower_msg:
        code = "SERVICE_UNAVAILABLE"
        retryable = True
    elif "cancelled" in lower_msg or "canceled" in lower_msg:
        code = "OPERATION_CANCELLED"
        retryable = False
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


class OrchestratorCancelledError(RuntimeError):
    """Raised or emitted when transcription is attempted on a cancelled orchestrator."""

    def __init__(
        self,
        message: str = "Transcription operation was cancelled.",
    ) -> None:
        super().__init__(message)
        self.code = "OPERATION_CANCELLED"
        self.retryable = False


def is_supported_fallback_error(exc: Exception, error_detail: Optional[STTErrorDetail] = None) -> bool:
    """Determine whether an error qualifies for automatic mock provider fallback.

    Recognized provider failure scenarios (via structured types, codes, and attributes):
    1. HTTP 429 / quota / rate-limit errors.
    2. Network connection failures (connection resets, connection refusals, broken pipes).
    3. HTTP 503 / provider service unavailable / temporary service failures.
    4. Timeouts after retry exhaustion.

    Explicitly excluded from fallback (never masked):
    - Programming errors (ValueError, TypeError, KeyError, IndexError, AttributeError, NameError, AssertionError, NotImplementedError).
    - Invalid input & validation failures (STTValidationError, INVALID_PAYLOAD, VALIDATION_ERROR, BAD_REQUEST).
    - Unsupported configurations (UNSUPPORTED_CONFIGURATION, CONFIGURATION_ERROR).
    - Authentication & authorization failures (UNAUTHENTICATED, UNAUTHORIZED, FORBIDDEN, PERMISSION_DENIED).
    - Operational lifecycle states (OrchestratorClosedError, OrchestratorCancelledError, ADAPTER_CLOSED, OPERATION_CANCELLED).
    """
    # 1. Reject explicit programming and lifecycle exceptions immediately
    if isinstance(
        exc,
        (
            STTValidationError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            AttributeError,
            NameError,
            AssertionError,
            NotImplementedError,
            SyntaxError,
            LookupError,
            OrchestratorClosedError,
            OrchestratorCancelledError,
        ),
    ):
        return False

    # 2. Extract structured codes and HTTP statuses
    code = (error_detail.code.upper() if error_detail else "") or getattr(exc, "code", "").upper()
    status_code = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    if status_code is None and error_detail and error_detail.details:
        status_code = error_detail.details.get("status_code") or error_detail.details.get("http_status")

    # 3. Reject excluded structured error codes and HTTP client failure statuses
    excluded_codes = {
        "VALIDATION_ERROR",
        "INVALID_PAYLOAD",
        "INVALID_INPUT",
        "INVALID_ARGUMENT",
        "BAD_REQUEST",
        "UNSUPPORTED_CONFIGURATION",
        "CONFIGURATION_ERROR",
        "UNAUTHENTICATED",
        "UNAUTHORIZED",
        "PERMISSION_DENIED",
        "FORBIDDEN",
        "AUTH_ERROR",
        "ADAPTER_CLOSED",
        "OPERATION_CANCELLED",
        "CANCELLED",
        "CLOSED",
    }
    if code in excluded_codes:
        return False

    if isinstance(status_code, int) and status_code in (400, 401, 403, 404, 405, 422):
        return False

    # 4. Structured Quota / Rate-limit detection
    if isinstance(status_code, int) and status_code == 429:
        return True
    if code in ("QUOTA_EXCEEDED", "RATE_LIMITED", "RESOURCE_EXHAUSTED", "HTTP_429", "TOO_MANY_REQUESTS"):
        return True

    # 5. Structured Network failure detection
    if isinstance(
        exc,
        (
            ConnectionError,
            ConnectionResetError,
            ConnectionRefusedError,
            ConnectionAbortedError,
            BrokenPipeError,
        ),
    ):
        return True
    if code in (
        "NETWORK_ERROR",
        "CONNECTION_ERROR",
        "CONNECTION_RESET",
        "CONNECTION_REFUSED",
        "SOCKET_ERROR",
        "REMOTE_DISCONNECTED",
    ):
        return True

    # 6. Structured Provider Unavailable / 503 detection
    if isinstance(status_code, int) and status_code in (502, 503, 504):
        return True
    if code in ("SERVICE_UNAVAILABLE", "HTTP_503", "UNAVAILABLE", "BAD_GATEWAY", "GATEWAY_TIMEOUT"):
        return True

    # 7. Structured Timeout detection
    if isinstance(exc, (TimeoutError, concurrent.futures.TimeoutError)):
        return True
    if code in ("TRANSCRIPTION_TIMEOUT", "TIMEOUT", "DEADLINE_EXCEEDED"):
        return True

    # 8. Guarded message pattern fallback for untyped third-party errors
    msg = (error_detail.message if error_detail else str(exc)).lower()

    # Never trigger on programming/auth words in message
    if any(
        term in msg
        for term in (
            "unauthorized",
            "forbidden",
            "invalid argument",
            "validation error",
            "cancelled",
            "canceled",
            "closed",
            "unsupported",
        )
    ):
        return False

    if any(term in msg for term in ("quota", "429", "rate limit", "resource exhausted", "insufficient_quota")):
        return True

    if any(
        term in msg
        for term in (
            "connection reset",
            "connection refused",
            "connection failed",
            "connection error",
            "network unreachable",
            "network error",
            "network failure",
            "connection abort",
            "remote end closed",
        )
    ):
        return True

    if any(term in msg for term in ("503", "service unavailable", "provider unavailable")):
        return True

    if any(term in msg for term in ("timed out", "timeout", "deadline exceeded")):
        return True

    return False


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
        min_confidence_threshold: Optional[float] = None,
        enable_fallback: bool = False,
        fallback_adapter: Optional[BaseSTTAdapter] = None,
    ) -> None:
        """Initialize the transcription orchestrator.

        Args:
            adapter: Optional provider-neutral STT adapter. Defaults to DeterministicFakeTranscriber.
            accumulator: Optional segment accumulator. Defaults to a fresh OrderedSegmentAccumulator.
            session_id: Optional identifier for the streaming session.
            retry_config: Optional RetryConfig for bounded retries and timeouts.
            preprocessor: Optional AudioPreprocessor for standardizing incoming audio.
            min_confidence_threshold: Optional minimum confidence threshold. If omitted,
                inherits from adapter.config.min_confidence_threshold if present, otherwise 0.50.
            enable_fallback: If True, enables automatic fallback to mock transcriber on supported failures.
            fallback_adapter: Optional custom fallback adapter instance (defaults to DeterministicFakeTranscriber).
        """
        self._session_id: str = session_id or f"orch-session-{uuid4().hex[:8]}"
        self._adapter: BaseSTTAdapter = adapter if adapter is not None else DeterministicFakeTranscriber()
        self._primary_adapter: BaseSTTAdapter = self._adapter
        self._enable_fallback: bool = enable_fallback or (fallback_adapter is not None)
        self._fallback_adapter: Optional[BaseSTTAdapter] = fallback_adapter
        self._is_fallback_active: bool = False
        self._fallback_triggered: bool = False
        self._fallback_reason: Optional[str] = None
        self._fallback_error: Optional[STTErrorDetail] = None
        self._is_cancelled: bool = False

        # Resolve confidence threshold priority:
        # 1. Explicit orchestrator parameter
        # 2. Inherited from adapter configuration (if exposed)
        # 3. Default fallback 0.50
        if min_confidence_threshold is not None:
            resolved_threshold = min_confidence_threshold
        elif (
            hasattr(self._adapter, "config")
            and getattr(self._adapter.config, "min_confidence_threshold", None) is not None
        ):
            resolved_threshold = self._adapter.config.min_confidence_threshold
        else:
            resolved_threshold = 0.50

        if (
            not isinstance(resolved_threshold, (int, float))
            or not math.isfinite(resolved_threshold)
            or resolved_threshold < 0.0
            or resolved_threshold > 1.0
        ):
            raise STTValidationError(
                f"Confidence threshold must be a finite float in range [0.0, 1.0], got {resolved_threshold}.",
                field_name="min_confidence_threshold",
            )

        if accumulator is not None:
            self._accumulator = accumulator
            if min_confidence_threshold is not None:
                self._accumulator.min_confidence_threshold = resolved_threshold
        else:
            self._accumulator = OrderedSegmentAccumulator(
                session_id=self._session_id,
                min_confidence_threshold=resolved_threshold,
            )

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

    @property
    def is_cancelled(self) -> bool:
        """True if the current transcription operation has been cancelled."""
        return self._is_cancelled

    @property
    def enable_fallback(self) -> bool:
        """Whether mock provider fallback is enabled."""
        return self._enable_fallback

    @property
    def is_fallback_active(self) -> bool:
        """Whether the orchestrator is currently routed through the fallback adapter."""
        return self._is_fallback_active

    @property
    def fallback_triggered(self) -> bool:
        """Whether fallback was triggered during the current session."""
        return self._fallback_triggered

    @property
    def fallback_reason(self) -> Optional[str]:
        """Failure reason/code that triggered fallback, if any."""
        return self._fallback_reason

    @property
    def fallback_error(self) -> Optional[STTErrorDetail]:
        """Normalized error detail that triggered fallback, if any."""
        return self._fallback_error

    def cancel(self) -> None:
        """Cancel the current in-flight transcription operation.

        Idempotent: can be called multiple times safely.
        Stops further chunk processing, clears uncommitted interim hypotheses
        from the accumulator so no misleading final events are emitted, and
        notifies the underlying adapter to cancel/release resources.
        Session ID remains intact.
        """
        self._is_cancelled = True
        self._accumulator.clear_interim()
        if hasattr(self._adapter, "cancel") and callable(self._adapter.cancel):
            self._adapter.cancel()

    def _activate_fallback_and_process(
        self,
        chunk: AudioChunk | bytes,
        is_last: bool,
        trigger_error: STTErrorDetail,
    ) -> List[TranscriptEvent]:
        """Switch to fallback mock transcriber and transcribe the given chunk."""
        self._is_fallback_active = True
        self._fallback_triggered = True
        self._fallback_reason = trigger_error.code
        self._fallback_error = trigger_error

        # Prepare fallback adapter if not already created
        if self._fallback_adapter is None:
            self._fallback_adapter = DeterministicFakeTranscriber()

        self._fallback_adapter.initialize(session_id=self._session_id)
        self._adapter = self._fallback_adapter

        if self._is_cancelled:
            return []

        try:
            events = self._adapter.transcribe_chunk(chunk, is_last=is_last)
        except Exception as exc:
            normalized_fallback_err = normalize_stt_error(exc, request_id=self._session_id)
            err_event = TranscriptEvent(
                event_id=str(uuid4()),
                event_type=TranscriptEventType.ERROR,
                sequence_number=self._accumulator.get_summary()["events_processed"],
                timestamp=time.time(),
                session_id=self._session_id,
                error=normalized_fallback_err,
                metadata={"fallback_failure": True},
            )
            self._accumulator.ingest_event(err_event)
            return [err_event]

        if self._is_cancelled:
            return []

        for event in events:
            if self._session_id and (
                event.session_id == "default-session"
                or event.session_id == getattr(self._adapter, "session_id", None)
            ):
                object.__setattr__(event, "session_id", self._session_id)
            if event.metadata is not None:
                event.metadata["fallback_active"] = True
            self._accumulator.ingest_event(event)

        return events

    def initialize(self, session_id: Optional[str] = None) -> None:
        """Initialize orchestrator resources and prepare adapter and accumulator.

        Args:
            session_id: Optional new session ID. Reuses current ID if omitted.
        """
        if session_id:
            self._session_id = session_id
        self._adapter.initialize(session_id=self._session_id)
        self._accumulator.reset(session_id=self._session_id)
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
        if self._is_cancelled:
            raise OrchestratorCancelledError("Transcription operation was cancelled.")

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

                if self._is_cancelled:
                    return []

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
                        if (
                            self._enable_fallback
                            and not self._is_fallback_active
                            and is_supported_fallback_error(Exception(error_event.error.message), error_event.error)
                        ):
                            return self._activate_fallback_and_process(active_chunk, is_last, error_event.error)

                        # Non-retryable error, simulated test injection, or retries exhausted: ingest events and return
                        for event in events:
                            if self._session_id and (
                                event.session_id == "default-session"
                                or event.session_id == getattr(self._adapter, "session_id", None)
                            ):
                                object.__setattr__(event, "session_id", self._session_id)
                            self._accumulator.ingest_event(event)
                        return events

                # Successful processing: ingest events and return
                for event in events:
                    if self._session_id and (
                        event.session_id == "default-session"
                        or event.session_id == getattr(self._adapter, "session_id", None)
                    ):
                        object.__setattr__(event, "session_id", self._session_id)
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
                    if (
                        self._enable_fallback
                        and not self._is_fallback_active
                        and is_supported_fallback_error(exc, normalized_error)
                    ):
                        return self._activate_fallback_and_process(active_chunk, is_last, normalized_error)
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
        if self._is_cancelled:
            return

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
            if self._is_cancelled:
                return
            is_last = bool(prev.metadata.get("is_last", False)) if isinstance(prev, AudioChunk) else getattr(prev, "is_last", False)
            try:
                events = self.process_chunk(prev, is_last=is_last)
            except OrchestratorCancelledError:
                return
            for event in events:
                if self._is_cancelled:
                    return
                yield event
            prev = current

        # Final chunk of the stream marked with is_last=True
        if self._is_cancelled:
            return
        try:
            events = self.process_chunk(prev, is_last=True)
        except OrchestratorCancelledError:
            return
        for event in events:
            if self._is_cancelled:
                return
            yield event

    def ingest_event(self, event: TranscriptEvent) -> bool:
        """Ingest a TranscriptEvent directly into the orchestrator's accumulator.

        Enables out-of-order, delayed, or externally received transcript events
        to be processed, deduplicated, and chronologically ordered seamlessly.

        Args:
            event: TranscriptEvent to ingest.

        Returns:
            True if event was processed; False if suppressed as a duplicate or cancelled.
        """
        if self._is_cancelled:
            return False
        if not self._initialized:
            self.initialize()
        if self._session_id and event.session_id == "default-session":
            object.__setattr__(event, "session_id", self._session_id)
        return self._accumulator.ingest_event(event)

    @property
    def min_confidence_threshold(self) -> float:
        """Minimum confidence threshold configured on the accumulator."""
        return self._accumulator.min_confidence_threshold

    @min_confidence_threshold.setter
    def min_confidence_threshold(self, value: float) -> None:
        """Dynamically update minimum confidence threshold on the accumulator."""
        self._accumulator.min_confidence_threshold = value

    def get_low_confidence_segments(self) -> List[TranscriptSegment]:
        """Return defensive copy of quarantined low-confidence segments."""
        return self._accumulator.get_low_confidence_segments()

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
        summary["is_cancelled"] = self._is_cancelled
        summary["fallback_active"] = self._is_fallback_active
        summary["fallback_triggered"] = self._fallback_triggered
        summary["fallback_reason"] = self._fallback_reason
        summary["fallback_error"] = self._fallback_error.model_dump() if self._fallback_error else None
        return summary

    def get_status(self) -> STTAdapterStatus:
        """Return status and telemetry of the underlying adapter."""
        return self._adapter.get_status()

    def reset(self) -> None:
        """Reset internal accumulator and adapter sequence counters for a fresh session."""
        if self._is_fallback_active and self._primary_adapter is not None:
            self._adapter = self._primary_adapter
        self._adapter.reset()
        self._accumulator.reset(session_id=self._session_id)
        self._retries_attempted = 0
        self._timeouts_encountered = 0
        self._is_cancelled = False
        self._is_fallback_active = False
        self._fallback_triggered = False
        self._fallback_reason = None
        self._fallback_error = None

    def close(self) -> None:
        """Release underlying adapter and streaming resources."""
        self._adapter.close()

    def __enter__(self) -> TranscriptionOrchestrator:
        self.initialize()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
