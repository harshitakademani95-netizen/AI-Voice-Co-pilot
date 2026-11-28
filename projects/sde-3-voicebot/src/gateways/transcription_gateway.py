"""Backend Transcription Gateway connecting the backend service to the speech-to-text pipeline.

This gateway serves as the single integration point between the backend and the
transcription module (voice_stt.adapter, voice_stt.fake_transcriber, voice_stt.accumulator).
It provides request/response validation, adapter lifecycle management, multi-session
segment accumulation, bounded ThreadPoolExecutor timeout enforcement, retry with exponential backoff,
circuit breaker protection, structured logging, resilience telemetry, and domain exception mapping.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Union

from src.config import settings
from src.core.errors import (
    CircuitBreakerOpenError,
    GatewayTimeoutError,
    TranscriptionGatewayError,
    TranscriptionModuleUnavailableError,
)
from src.gateways.resilience import CircuitBreaker, retry_with_backoff

try:
    from src.voice_stt.accumulator import OrderedSegmentAccumulator
    from src.voice_stt.adapter import (
        BaseSTTAdapter,
        STTAdapterConfig,
        STTAdapterState,
        STTAdapterStatus,
    )
    from src.voice_stt.fake_transcriber import DeterministicFakeTranscriber
    from src.voice_stt.provider_factory import get_stt_adapter
    from src.voice_stt.schemas import (
        AudioChunk as STTAudioChunk,
        STTErrorDetail,
        TranscriptEvent,
        TranscriptEventType,
        TranscriptSegment,
    )
except ImportError:
    from voice_stt.accumulator import OrderedSegmentAccumulator
    from voice_stt.adapter import (
        BaseSTTAdapter,
        STTAdapterConfig,
        STTAdapterState,
        STTAdapterStatus,
    )
    from voice_stt.fake_transcriber import DeterministicFakeTranscriber
    from voice_stt.provider_factory import get_stt_adapter
    from voice_stt.schemas import (
        AudioChunk as STTAudioChunk,
        STTErrorDetail,
        TranscriptEvent,
        TranscriptEventType,
        TranscriptSegment,
    )

logger = logging.getLogger("backend.gateways.transcription")


class TranscriptionGateway:
    """Gateway orchestrating backend communication with the speech-to-text adapter and accumulator.

    Guarantees:
    - Safe transformation of incoming audio slices (raw bytes, W1 AudioChunks, or STT AudioChunks).
    - Delegation to the active BaseSTTAdapter (default: DeterministicFakeTranscriber or pluggable Deepgram).
    - Real timeout enforcement via bounded ThreadPoolExecutor.
    - Resilience protection via retry_with_backoff and CircuitBreaker.
    - Session-isolated OrderedSegmentAccumulator tracking for chronological segment assembly.
    - Translation of internal exceptions into typed AppError envelopes.
    """

    def __init__(
        self,
        adapter: Optional[BaseSTTAdapter] = None,
        config: Optional[STTAdapterConfig] = None,
        timeout_seconds: float = 10.0,
        max_workers: int = 4,
        circuit_breaker: Optional[CircuitBreaker] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config or STTAdapterConfig(language="en", sample_rate=16000, interim_results=True)
        self.timeout_seconds = timeout_seconds
        self.sleep_fn = sleep_fn

        # Instantiate or adopt STT adapter
        if adapter is not None:
            self.adapter: BaseSTTAdapter = adapter
        else:
            try:
                self.adapter = get_stt_adapter(
                    provider=getattr(settings, "stt_provider", "mock"),
                    config=self.config,
                )
            except Exception:
                self.adapter = DeterministicFakeTranscriber(self.config)

        self.adapter.initialize()

        self._is_available: bool = True
        self._accumulators: Dict[str, OrderedSegmentAccumulator] = {}
        self._total_chunks_transcribed: int = 0
        self._total_events_emitted: int = 0
        self._last_error: Optional[str] = None

        # Bounded executor for real enforced timeouts
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="trans-gw-")

        # Circuit breaker resilience
        self.circuit_breaker = circuit_breaker or CircuitBreaker(failure_threshold=5, recovery_timeout_sec=30.0)

        # Telemetry metrics
        self._lock = threading.Lock()
        self._total_calls: int = 0
        self._error_count: int = 0
        self._total_latency_ms: float = 0.0
        self._last_success_at: Optional[str] = None

    @property
    def is_available(self) -> bool:
        """Indicates whether the underlying transcription module is reachable and operational."""
        return self._is_available and (self.adapter.state not in (STTAdapterState.ERROR, STTAdapterState.CLOSED))

    def set_available(self, available: bool) -> None:
        """Sets the operational availability state of the transcription module."""
        self._is_available = available

    def _record_telemetry(self, success: bool, latency_ms: float) -> None:
        """Thread-safely updates gateway invocation counters and telemetry."""
        with self._lock:
            self._total_calls += 1
            self._total_latency_ms += latency_ms
            if success:
                self._last_success_at = datetime.now(timezone.utc).isoformat()
            else:
                self._error_count += 1

    def get_or_create_accumulator(self, session_id: str) -> OrderedSegmentAccumulator:
        """Retrieves or creates the OrderedSegmentAccumulator for a given session."""
        if session_id not in self._accumulators:
            self._accumulators[session_id] = OrderedSegmentAccumulator()
        return self._accumulators[session_id]

    def _normalize_audio_chunk(
        self,
        chunk: Any,
        is_last: bool = False,
        sequence_number: int = 0,
        sample_rate: int = 16000,
    ) -> bytes:
        """Normalizes heterogeneous chunk inputs (raw bytes, W1 AudioChunk, STTAudioChunk) into bytes."""
        if chunk is None:
            raise TranscriptionGatewayError("Audio chunk cannot be None.", code="EMPTY_AUDIO_CHUNK")

        if isinstance(chunk, (bytes, bytearray)):
            raw = bytes(chunk)
            if len(raw) == 0:
                raise TranscriptionGatewayError("Audio data payload cannot be empty.", code="EMPTY_AUDIO_CHUNK")
            return raw

        if hasattr(chunk, "data"):
            raw = bytes(chunk.data)
            if len(raw) == 0:
                raise TranscriptionGatewayError("Audio chunk data cannot be empty.", code="EMPTY_AUDIO_CHUNK")
            return raw

        raise TranscriptionGatewayError(
            f"Unsupported audio chunk format: {type(chunk).__name__}. Expected bytes or AudioChunk instance.",
            code="UNSUPPORTED_AUDIO_CHUNK",
        )

    def transcribe_chunk(
        self,
        chunk: Any,
        is_last: bool = False,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> List[TranscriptEvent]:
        """Submits a single audio chunk to the STT adapter and processes emitted events.

        Protected by bounded ThreadPoolExecutor timeout, retry with backoff, and CircuitBreaker.
        """
        start_time = time.monotonic()
        effective_timeout = timeout if timeout is not None else self.timeout_seconds

        if not self._is_available:
            self._last_error = "Transcription module is currently unavailable"
            logger.error("Transcription module unavailable", extra={"correlation_id": correlation_id})
            self._record_telemetry(success=False, latency_ms=0.0)
            raise TranscriptionModuleUnavailableError(details={"correlation_id": correlation_id})

        if chunk is None:
            self._record_telemetry(success=False, latency_ms=0.0)
            raise TranscriptionGatewayError(
                message="Audio chunk cannot be None.",
                details={"correlation_id": correlation_id},
                code="EMPTY_AUDIO_CHUNK",
            )

        raw_bytes = self._normalize_audio_chunk(
            chunk=chunk,
            is_last=is_last,
            sequence_number=self._total_chunks_transcribed,
            sample_rate=self.config.sample_rate,
        )

        # Check deadline before execution
        elapsed = time.monotonic() - start_time
        if elapsed >= effective_timeout:
            self._record_telemetry(success=False, latency_ms=elapsed * 1000.0)
            raise GatewayTimeoutError(
                message=f"Transcription exceeded timeout limit of {effective_timeout:.2f}s (elapsed: {elapsed:.2f}s).",
                details={"elapsed_seconds": elapsed, "timeout_seconds": effective_timeout, "correlation_id": correlation_id},
            )

        # Inner adapter call with bounded ThreadPoolExecutor timeout
        def _call_adapter_with_timeout() -> List[TranscriptEvent]:
            call_start = time.monotonic()
            rem = max(0.001, effective_timeout - (call_start - start_time))
            future = self._executor.submit(self.adapter.transcribe_chunk, raw_bytes, is_last=is_last)
            try:
                return future.result(timeout=rem)
            except FutureTimeoutError:
                future.cancel()
                el = time.monotonic() - start_time
                raise GatewayTimeoutError(
                    message=f"Transcription exceeded timeout limit of {effective_timeout:.2f}s (elapsed: {el:.2f}s).",
                    details={"elapsed_seconds": el, "timeout_seconds": effective_timeout, "correlation_id": correlation_id},
                )
            except Exception as exc:
                if isinstance(exc, (TranscriptionGatewayError, GatewayTimeoutError, TranscriptionModuleUnavailableError)):
                    raise exc
                raise TranscriptionGatewayError(
                    message=f"Transcription adapter failed: {str(exc)}",
                    details={"error": str(exc), "correlation_id": correlation_id},
                ) from exc

        # Retry wrapper
        def _execute_with_retry() -> List[TranscriptEvent]:
            return retry_with_backoff(
                _call_adapter_with_timeout,
                max_attempts=3,
                base_delay=0.05,
                sleep_fn=self.sleep_fn,
            )

        # Execute through Circuit Breaker (protecting downstream STT module)
        try:
            events = self.circuit_breaker.execute(_execute_with_retry)
        except CircuitBreakerOpenError as exc:
            total_elapsed = time.monotonic() - start_time
            self._last_error = str(exc)
            self._record_telemetry(success=False, latency_ms=total_elapsed * 1000.0)
            raise TranscriptionModuleUnavailableError(
                message="Transcription module is currently unavailable (circuit breaker OPEN).",
                details={"circuit_state": self.circuit_breaker.state, "correlation_id": correlation_id},
            ) from exc
        except Exception as exc:
            total_elapsed = time.monotonic() - start_time
            self._last_error = str(exc)
            self._record_telemetry(success=False, latency_ms=total_elapsed * 1000.0)
            raise

        # Validate responses and feed into session accumulator
        validated_events: List[TranscriptEvent] = []
        for event in events:
            if not hasattr(event, "event_type") or not hasattr(event, "sequence_number"):
                raise TranscriptionGatewayError(
                    f"Adapter returned unexpected response type: {type(event).__name__} (expected TranscriptEvent)."
                )
            validated_events.append(event)

            if session_id and event.event_type in (TranscriptEventType.INTERIM, TranscriptEventType.FINAL):
                acc = self.get_or_create_accumulator(session_id)
                acc.ingest_event(event)

        total_elapsed = time.monotonic() - start_time
        if total_elapsed >= effective_timeout:
            self._record_telemetry(success=False, latency_ms=total_elapsed * 1000.0)
            raise GatewayTimeoutError(
                message=f"Transcription exceeded timeout limit of {effective_timeout:.2f}s (elapsed: {total_elapsed:.2f}s).",
                details={"elapsed_seconds": total_elapsed, "timeout_seconds": effective_timeout, "correlation_id": correlation_id},
            )

        self._total_chunks_transcribed += 1
        self._total_events_emitted += len(validated_events)
        self._last_error = None
        self._record_telemetry(success=True, latency_ms=total_elapsed * 1000.0)

        logger.info(
            "Chunk successfully transcribed",
            extra={
                "correlation_id": correlation_id,
                "session_id": session_id,
                "events_count": len(validated_events),
                "duration_ms": total_elapsed * 1000.0,
            },
        )
        return validated_events

    def transcribe_stream(
        self,
        chunks: Iterable[Any],
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> List[TranscriptEvent]:
        """Transcribes an entire sequence of audio chunks, returning all generated events."""
        all_events: List[TranscriptEvent] = []
        chunk_list = list(chunks)
        total = len(chunk_list)

        if total == 0:
            return []

        for idx, chunk in enumerate(chunk_list):
            is_last = (idx == total - 1)
            events = self.transcribe_chunk(
                chunk=chunk,
                is_last=is_last,
                session_id=session_id,
                correlation_id=correlation_id,
                timeout=timeout,
            )
            all_events.extend(events)

        return all_events

    def get_session_transcript(self, session_id: str) -> str:
        """Returns the full accumulated transcript for a session."""
        if session_id not in self._accumulators:
            return ""
        return self._accumulators[session_id].get_full_transcript()

    def get_status(self) -> Dict[str, Any]:
        """Returns the real-time operational status and metrics of the transcription gateway."""
        adapter_status: STTAdapterStatus = self.adapter.get_status()
        with self._lock:
            avg_latency = round(self._total_latency_ms / self._total_calls, 2) if self._total_calls > 0 else 0.0
            return {
                "gateway": "TranscriptionGateway",
                "is_available": self.is_available,
                "circuit_state": self.circuit_breaker.state,
                "total_calls": self._total_calls,
                "error_count": self._error_count,
                "avg_latency_ms": avg_latency,
                "last_success_at": self._last_success_at,
                "adapter_state": adapter_status.state.value,
                "adapter_model": self.config.model_name,
                "adapter_language": self.config.language,
                "total_chunks_transcribed": self._total_chunks_transcribed,
                "total_events_emitted": self._total_events_emitted,
                "active_accumulators_count": len(self._accumulators),
                "last_error": self._last_error,
            }

    def health_check(self) -> bool:
        """Verifies health by running a synthetic transcription probe."""
        if not self.is_available:
            return False
        try:
            prev_chunks = self._total_chunks_transcribed
            prev_events = self._total_events_emitted
            probe_bytes = b"\x00" * 640
            events = self.transcribe_chunk(probe_bytes, is_last=True)
            self._total_chunks_transcribed = prev_chunks
            self._total_events_emitted = prev_events
            return isinstance(events, list)
        except Exception:
            return False

    def reset(self) -> None:
        """Resets gateway metrics and session accumulators."""
        self._accumulators.clear()
        self._total_chunks_transcribed = 0
        self._total_events_emitted = 0
        self._last_error = None
        self.circuit_breaker.reset()
        if hasattr(self.adapter, "reset"):
            self.adapter.reset()

    def close(self) -> None:
        """Closes gateway resources and shuts down bounded thread executor."""
        self._is_available = False
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        if hasattr(self.adapter, "close"):
            self.adapter.close()


_transcription_gateway_instance: Optional[TranscriptionGateway] = None


def get_transcription_gateway() -> TranscriptionGateway:
    """Returns the singleton TranscriptionGateway instance."""
    global _transcription_gateway_instance
    if _transcription_gateway_instance is None:
        _transcription_gateway_instance = TranscriptionGateway()
    return _transcription_gateway_instance
