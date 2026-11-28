"""Backend Audio Gateway connecting the backend service to the audio processing pipeline.

This gateway serves as the single integration point between the backend and the
audio module (src.audio.chunker, src.audio.mock_source, src.schemas.audio).
It provides request/response validation, bounded ThreadPoolExecutor timeout enforcement,
input payload/chunk limits, structured logging, resilience telemetry, and domain exception mapping.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
import logging
import math
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from src.config import settings
from src.core.errors import (
    AudioFormatUnsupportedError,
    AudioGatewayError,
    AudioModuleUnavailableError,
    CircuitBreakerOpenError,
    GatewayTimeoutError,
    PayloadTooLargeError,
)
from src.gateways.resilience import CircuitBreaker, retry_with_backoff

try:
    from src.audio.chunker import AudioChunker
    from src.audio.mock_source import MockMicrophone
    from src.schemas.audio import (
        ALL_SUPPORTED_ENCODINGS,
        SUPPORTED_CHANNELS,
        SUPPORTED_SAMPLE_RATES,
        SUPPORTED_SAMPLE_WIDTHS,
        AudioChunk,
        AudioError,
        AudioFormat,
    )
except ImportError:  # Fallback for environments where src is root
    from audio.chunker import AudioChunker
    from audio.mock_source import MockMicrophone
    from schemas.audio import (
        ALL_SUPPORTED_ENCODINGS,
        SUPPORTED_CHANNELS,
        SUPPORTED_SAMPLE_RATES,
        SUPPORTED_SAMPLE_WIDTHS,
        AudioChunk,
        AudioError,
        AudioFormat,
    )

logger = logging.getLogger("backend.gateways.audio")


class AudioGateway:
    """Gateway orchestrating backend communication with the audio ingestion and chunking module.

    Guarantees:
    - Safe validation of all raw audio inputs and format specifications.
    - Delegation to actual AudioChunker and MockMicrophone classes.
    - Translation of internal AudioError exceptions into typed AppError envelopes.
    - Real timeout enforcement via bounded ThreadPoolExecutor.
    - Enforcement of MAX_AUDIO_BYTES and MAX_CHUNKS_PER_REQUEST.
    - Monotonic metrics and operational telemetry.
    """

    def __init__(
        self,
        default_sample_rate: int = 16000,
        default_channels: int = 1,
        default_sample_width: int = 2,
        default_encoding: str = "pcm_s16le",
        chunker_instance: Optional[AudioChunker] = None,
        timeout_seconds: float = 10.0,
        max_audio_bytes: Optional[int] = None,
        max_chunks_per_request: Optional[int] = None,
        max_workers: int = 4,
        circuit_breaker: Optional[CircuitBreaker] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.default_sample_rate = default_sample_rate
        self.default_channels = default_channels
        self.default_sample_width = default_sample_width
        self.default_encoding = default_encoding
        self.timeout_seconds = timeout_seconds
        self.sleep_fn = sleep_fn
        self.max_audio_bytes = max_audio_bytes or getattr(settings, "max_audio_bytes", 1000000)
        self.max_chunks_per_request = max_chunks_per_request or getattr(settings, "max_chunks_per_request", 500)

        self._custom_chunker = chunker_instance
        self._is_available: bool = True
        self._total_chunks_produced: int = 0
        self._total_bytes_processed: int = 0
        self._last_error: Optional[str] = None

        # Bounded executor for real enforced timeouts
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="audio-gw-")
        self.circuit_breaker = circuit_breaker or CircuitBreaker(failure_threshold=5, recovery_timeout_sec=30.0)

        # Telemetry metrics
        self._lock = threading.Lock()
        self._total_calls: int = 0
        self._error_count: int = 0
        self._total_latency_ms: float = 0.0
        self._last_success_at: Optional[str] = None

    @property
    def is_available(self) -> bool:
        """Indicates whether the underlying audio module is reachable and active."""
        return self._is_available and (self.circuit_breaker.state != "OPEN")

    def set_available(self, available: bool) -> None:
        """Sets the availability state of the audio module (useful for failover/simulation)."""
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

    def validate_audio_format(
        self,
        sample_rate: Optional[int] = None,
        channels: Optional[int] = None,
        sample_width: Optional[int] = None,
        encoding: Optional[str] = None,
    ) -> AudioFormat:
        """Validates audio format parameters against supported voice pipeline standards.

        Raises:
            AudioFormatUnsupportedError: If any parameter falls outside supported voice contracts.
        """
        rate = sample_rate if sample_rate is not None else self.default_sample_rate
        chan = channels if channels is not None else self.default_channels
        width = sample_width if sample_width is not None else self.default_sample_width
        enc = encoding if encoding is not None else self.default_encoding

        if not isinstance(rate, int) or isinstance(rate, bool) or rate <= 0 or rate not in SUPPORTED_SAMPLE_RATES:
            raise AudioFormatUnsupportedError(
                message=f"Unsupported audio sample rate: {rate} Hz. Must be one of {sorted(list(SUPPORTED_SAMPLE_RATES))}.",
                details={"sample_rate": rate, "supported": sorted(list(SUPPORTED_SAMPLE_RATES))},
            )

        if not isinstance(chan, int) or isinstance(chan, bool) or chan not in SUPPORTED_CHANNELS:
            raise AudioFormatUnsupportedError(
                message=f"Unsupported channel count: {chan}. Supported channels are {sorted(list(SUPPORTED_CHANNELS))}.",
                details={"channels": chan, "supported": sorted(list(SUPPORTED_CHANNELS))},
            )

        if not isinstance(width, int) or isinstance(width, bool) or width not in SUPPORTED_SAMPLE_WIDTHS:
            raise AudioFormatUnsupportedError(
                message=f"Unsupported sample width: {width} bytes. Supported widths are {sorted(list(SUPPORTED_SAMPLE_WIDTHS))}.",
                details={"sample_width": width, "supported": sorted(list(SUPPORTED_SAMPLE_WIDTHS))},
            )

        if not isinstance(enc, str) or enc not in ALL_SUPPORTED_ENCODINGS:
            raise AudioFormatUnsupportedError(
                message=f"Unsupported audio encoding '{enc}'. Supported encodings: {sorted(list(ALL_SUPPORTED_ENCODINGS))}.",
                details={"encoding": enc, "supported": sorted(list(ALL_SUPPORTED_ENCODINGS))},
            )

        try:
            return AudioFormat(sample_rate=rate, channels=chan, sample_width=width, encoding=enc)
        except AudioError as err:
            raise AudioFormatUnsupportedError(message=err.message, details=err.details) from err

    def chunk_audio(
        self,
        audio_data: Optional[bytes | bytearray] = None,
        format_spec: Optional[AudioFormat] = None,
        chunk_duration_ms: float = 20.0,
        correlation_id: Optional[str] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> List[AudioChunk]:
        """Validates and chunks continuous raw audio data into deterministic AudioChunk instances.

        Enforces timeouts via bounded ThreadPoolExecutor and payload size/chunk limits.
        """
        start_time = time.monotonic()
        effective_timeout = timeout if timeout is not None else kwargs.get("timeout_sec", self.timeout_seconds)
        raw_payload = audio_data if audio_data is not None else kwargs.get("raw_audio")

        if not self._is_available:
            self._last_error = "Audio module is currently unavailable"
            logger.error(
                "Audio module unavailable",
                extra={"correlation_id": correlation_id, "error": self._last_error},
            )
            self._record_telemetry(success=False, latency_ms=0.0)
            raise AudioModuleUnavailableError(details={"correlation_id": correlation_id})

        # Input validation
        if raw_payload is None:
            self._record_telemetry(success=False, latency_ms=0.0)
            raise AudioGatewayError(
                code="AUDIO_EMPTY_DATA",
                message="Audio payload cannot be None.",
                details={"correlation_id": correlation_id},
            )

        if not isinstance(raw_payload, (bytes, bytearray)):
            self._record_telemetry(success=False, latency_ms=0.0)
            raise AudioGatewayError(
                code="INVALID_AUDIO_DATA_TYPE",
                message=f"Audio data must be bytes or bytearray (received: {type(raw_payload).__name__}).",
                details={"correlation_id": correlation_id},
            )

        if len(raw_payload) == 0:
            self._record_telemetry(success=False, latency_ms=0.0)
            raise AudioGatewayError(
                code="AUDIO_EMPTY_DATA",
                message="Audio payload cannot be empty.",
                details={"correlation_id": correlation_id},
            )

        # Enforce MAX_AUDIO_BYTES
        if len(raw_payload) > self.max_audio_bytes:
            self._record_telemetry(success=False, latency_ms=0.0)
            raise PayloadTooLargeError(
                message=f"Audio payload size ({len(raw_payload)} bytes) exceeds maximum limit of {self.max_audio_bytes} bytes.",
                details={"payload_bytes": len(raw_payload), "max_audio_bytes": self.max_audio_bytes, "correlation_id": correlation_id},
            )

        if not isinstance(chunk_duration_ms, (int, float)) or isinstance(chunk_duration_ms, bool) or not math.isfinite(chunk_duration_ms) or chunk_duration_ms <= 0:
            self._record_telemetry(success=False, latency_ms=0.0)
            raise AudioGatewayError(
                message=f"Chunk duration must be a positive finite number (received: {chunk_duration_ms}).",
                details={"chunk_duration_ms": chunk_duration_ms, "correlation_id": correlation_id},
            )

        # Resolve format
        effective_format = format_spec if format_spec is not None else kwargs.get("format")
        if effective_format is None:
            effective_format = self.validate_audio_format()

        # Enforce MAX_CHUNKS_PER_REQUEST pre-check
        bytes_per_sample = effective_format.sample_width * effective_format.channels
        samples_per_chunk = int(round(effective_format.sample_rate * (chunk_duration_ms / 1000.0)))
        bytes_per_chunk = samples_per_chunk * bytes_per_sample
        if bytes_per_chunk > 0:
            estimated_chunks = math.ceil(len(raw_payload) / bytes_per_chunk)
            if estimated_chunks > self.max_chunks_per_request:
                self._record_telemetry(success=False, latency_ms=0.0)
                raise PayloadTooLargeError(
                    message=f"Audio request would produce {estimated_chunks} chunks, exceeding maximum limit of {self.max_chunks_per_request} chunks.",
                    details={"estimated_chunks": estimated_chunks, "max_chunks": self.max_chunks_per_request, "correlation_id": correlation_id},
                )

        # Check deadline before execution
        elapsed = time.monotonic() - start_time
        if elapsed >= effective_timeout:
            self._record_telemetry(success=False, latency_ms=elapsed * 1000.0)
            raise GatewayTimeoutError(
                message=f"Audio chunking exceeded timeout limit of {effective_timeout:.2f}s (elapsed: {elapsed:.2f}s).",
                details={"elapsed_seconds": elapsed, "timeout_seconds": effective_timeout, "correlation_id": correlation_id},
            )

        # Check if circuit breaker is already open
        if self.circuit_breaker.state == "OPEN":
            self._last_error = "Audio module is currently unavailable (circuit breaker OPEN)"
            self._record_telemetry(success=False, latency_ms=0.0)
            raise AudioModuleUnavailableError(
                message="Audio module is currently unavailable (circuit breaker OPEN).",
                details={"circuit_state": self.circuit_breaker.state, "correlation_id": correlation_id},
            )

        # Execute chunking through bounded ThreadPoolExecutor for enforced timeout
        def _execute_chunking() -> List[AudioChunk]:
            chunker = self._custom_chunker or AudioChunker(
                audio_format=effective_format,
                chunk_duration_ms=chunk_duration_ms,
            )
            return list(chunker.chunk_stream(bytes(raw_payload)))

        def _execute_chunking_with_breaker() -> List[AudioChunk]:
            future = self._executor.submit(_execute_chunking)
            remaining_timeout = max(0.001, effective_timeout - (time.monotonic() - start_time))
            try:
                return future.result(timeout=remaining_timeout)
            except FutureTimeoutError:
                future.cancel()
                total_elapsed = time.monotonic() - start_time
                raise GatewayTimeoutError(
                    message=f"Audio chunking exceeded timeout limit of {effective_timeout:.2f}s (elapsed: {total_elapsed:.2f}s).",
                    details={"elapsed_seconds": total_elapsed, "timeout_seconds": effective_timeout, "correlation_id": correlation_id},
                )

        try:
            chunks = self.circuit_breaker.execute(_execute_chunking_with_breaker)
        except CircuitBreakerOpenError as exc:
            total_elapsed = time.monotonic() - start_time
            self._last_error = str(exc)
            self._record_telemetry(success=False, latency_ms=total_elapsed * 1000.0)
            raise AudioModuleUnavailableError(
                message="Audio module is currently unavailable (circuit breaker OPEN).",
                details={"circuit_state": self.circuit_breaker.state, "correlation_id": correlation_id},
            ) from exc
        except AudioError as err:
            total_elapsed = time.monotonic() - start_time
            self._last_error = str(err)
            self._record_telemetry(success=False, latency_ms=total_elapsed * 1000.0)
            logger.error("Audio chunker error", extra={"correlation_id": correlation_id, "error": str(err)})
            if err.code in ("INVALID_SAMPLE_RATE", "INVALID_CHANNELS", "INVALID_SAMPLE_WIDTH", "INVALID_ENCODING"):
                raise AudioFormatUnsupportedError(message=err.message, details=err.details) from err
            raise AudioGatewayError(message=err.message, details=err.details) from err
        except Exception as err:
            total_elapsed = time.monotonic() - start_time
            self._record_telemetry(success=False, latency_ms=total_elapsed * 1000.0)
            raise

        # Post-check actual chunk count limit
        if len(chunks) > self.max_chunks_per_request:
            self._record_telemetry(success=False, latency_ms=0.0)
            raise PayloadTooLargeError(
                message=f"Audio request produced {len(chunks)} chunks, exceeding maximum limit of {self.max_chunks_per_request} chunks.",
                details={"chunks_count": len(chunks), "max_chunks": self.max_chunks_per_request, "correlation_id": correlation_id},
            )

        total_elapsed = time.monotonic() - start_time
        if total_elapsed >= effective_timeout:
            self._record_telemetry(success=False, latency_ms=total_elapsed * 1000.0)
            raise GatewayTimeoutError(
                message=f"Audio chunking exceeded timeout limit of {effective_timeout:.2f}s (elapsed: {total_elapsed:.2f}s).",
                details={"elapsed_seconds": total_elapsed, "timeout_seconds": effective_timeout, "correlation_id": correlation_id},
            )

        self._total_chunks_produced += len(chunks)
        self._total_bytes_processed += len(raw_payload)
        self._last_error = None
        self._record_telemetry(success=True, latency_ms=total_elapsed * 1000.0)

        logger.info(
            "Audio successfully chunked",
            extra={
                "correlation_id": correlation_id,
                "chunks_count": len(chunks),
                "bytes_processed": len(raw_payload),
                "duration_ms": total_elapsed * 1000.0,
            },
        )
        return chunks

    def generate_synthetic_stream(
        self,
        duration_sec: float = 1.0,
        chunk_duration_ms: float = 20.0,
        frequency_hz: float = 440.0,
        amplitude: float = 0.5,
        format_spec: Optional[AudioFormat] = None,
        correlation_id: Optional[str] = None,
    ) -> List[AudioChunk]:
        """Generates deterministic mock microphone audio chunks for offline simulation and tests."""
        if not self._is_available:
            self._record_telemetry(success=False, latency_ms=0.0)
            raise AudioModuleUnavailableError(details={"correlation_id": correlation_id})

        start_time = time.monotonic()
        effective_format = format_spec if format_spec is not None else self.validate_audio_format()

        try:
            mic = MockMicrophone(
                audio_format=effective_format,
                chunk_duration_ms=chunk_duration_ms,
                frequency_hz=frequency_hz,
                amplitude=amplitude,
                total_duration_sec=duration_sec,
            )
            chunks = list(mic.stream(simulate_realtime=False))
            self._total_chunks_produced += len(chunks)
            elapsed = time.monotonic() - start_time
            self._record_telemetry(success=True, latency_ms=elapsed * 1000.0)
            return chunks
        except AudioError as err:
            elapsed = time.monotonic() - start_time
            self._record_telemetry(success=False, latency_ms=elapsed * 1000.0)
            raise AudioGatewayError(message=err.message, details=err.details) from err

    def get_status(self) -> Dict[str, Any]:
        """Returns the real-time operational status and metrics of the audio gateway."""
        with self._lock:
            avg_latency = round(self._total_latency_ms / self._total_calls, 2) if self._total_calls > 0 else 0.0
            return {
                "gateway": "AudioGateway",
                "is_available": self.is_available,
                "circuit_state": self.circuit_breaker.state,
                "total_calls": self._total_calls,
                "error_count": self._error_count,
                "avg_latency_ms": avg_latency,
                "last_success_at": self._last_success_at,
                "total_chunks_produced": self._total_chunks_produced,
                "total_bytes_processed": self._total_bytes_processed,
                "default_format": {
                    "sample_rate": self.default_sample_rate,
                    "channels": self.default_channels,
                    "sample_width": self.default_sample_width,
                    "encoding": self.default_encoding,
                },
                "last_error": self._last_error,
            }

    def health_check(self) -> bool:
        """Verifies vitality by running a minimal synthetic chunk test."""
        if not self._is_available:
            return False
        try:
            test_format = AudioFormat(sample_rate=16000, channels=1, sample_width=2, encoding="pcm_s16le")
            test_bytes = b"\x00" * 640  # 20ms of 16kHz 16-bit mono
            chunks = self.chunk_audio(test_bytes, format_spec=test_format, chunk_duration_ms=20.0)
            return len(chunks) == 1
        except Exception:
            return False

    def close(self) -> None:
        """Cleans up gateway resources and shuts down bounded thread executor."""
        self._is_available = False
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


_audio_gateway_instance: Optional[AudioGateway] = None


def get_audio_gateway() -> AudioGateway:
    """Returns the singleton AudioGateway instance."""
    global _audio_gateway_instance
    if _audio_gateway_instance is None:
        _audio_gateway_instance = AudioGateway()
    return _audio_gateway_instance
