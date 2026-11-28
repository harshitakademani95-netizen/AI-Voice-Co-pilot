"""Comprehensive Hardening & Resilience Acceptance Test Suite for Week 3 Day 15.

Tests:
1. Enforced Timeouts (ThreadPoolExecutor, 504 on deadline, non-hanging shutdown).
2. Resilience (retry_with_backoff, CircuitBreaker state machine, injectable clock/sleep).
3. Input Limits (MAX_AUDIO_BYTES 413, MAX_CHUNKS_PER_REQUEST 413, malformed base64 400).
4. Pluggable STT Provider (mock default, deepgram provider, httpx.MockTransport, validation).
5. Transcript Readback (GET /sessions/{id}/transcript and /api/v1 twin, 200/404).
6. Gateway Telemetry (circuit_state, total_calls, error_count, avg_latency_ms, last_success_at).
"""
import base64
import json
import time
from typing import Any, Dict, List
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.config import settings
from src.core.errors import (
    AudioFormatUnsupportedError,
    AudioGatewayError,
    AudioModuleUnavailableError,
    CircuitBreakerOpenError,
    GatewayTimeoutError,
    PayloadTooLargeError,
    SessionNotFoundError,
    TranscriptionGatewayError,
    TranscriptionModuleUnavailableError,
)
from src.gateways.audio_gateway import AudioGateway, get_audio_gateway
from src.gateways.resilience import CircuitBreaker, CircuitState, retry_with_backoff
from src.gateways.transcription_gateway import TranscriptionGateway, get_transcription_gateway
from voice_stt.adapter import BaseSTTAdapter, STTAdapterConfig
from voice_stt.deepgram_adapter import DeepgramSTTAdapter
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.provider_factory import get_stt_adapter


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# ============================================================================
# PHASE 1: ENFORCED TIMEOUTS
# ============================================================================

class SlowAudioChunker:
    """Mock chunker that artificially blocks to test enforced ThreadPoolExecutor timeout."""
    def __init__(self, delay_sec: float = 0.5):
        self.delay_sec = delay_sec

    def chunk_stream(self, data: bytes):
        time.sleep(self.delay_sec)
        return []


class SlowSTTAdapter(BaseSTTAdapter):
    """Mock adapter that artificially blocks to test enforced timeout."""
    def __init__(self, delay_sec: float = 0.5):
        super().__init__()
        self.delay_sec = delay_sec

    def transcribe_chunk(self, data, is_last=False):
        time.sleep(self.delay_sec)
        return []

    def reset(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_audio_gateway_slow_chunker_enforced_timeout_raises_504():
    """Slow module call exceeding deadline must raise GatewayTimeoutError (HTTP 504)."""
    slow_chunker = SlowAudioChunker(delay_sec=0.4)
    gw = AudioGateway(chunker_instance=slow_chunker, max_workers=2)
    try:
        raw_pcm = b"\x00\x01" * 320
        with pytest.raises(GatewayTimeoutError) as exc_info:
            gw.chunk_audio(raw_pcm, timeout_sec=0.05)
        assert exc_info.value.status_code == 504
        assert exc_info.value.code == "GATEWAY_TIMEOUT"
    finally:
        gw.close()


def test_audio_gateway_normal_call_succeeds():
    """Normal chunking finishes within deadline and produces valid chunks."""
    gw = AudioGateway()
    try:
        raw_pcm = b"\x00\x01" * 320 * 3  # 3 chunks @ 20ms
        chunks = gw.chunk_audio(raw_pcm, timeout_sec=2.0)
        assert len(chunks) == 3
        assert chunks[0].duration_ms == 20.0
    finally:
        gw.close()


def test_audio_gateway_executor_close_does_not_hang():
    """Closing the AudioGateway shuts down executor safely without hanging."""
    gw = AudioGateway(max_workers=2)
    assert gw._executor is not None
    gw.close()
    assert gw.is_available is False


def test_transcription_gateway_slow_adapter_enforced_timeout_raises_504():
    """Slow STT adapter exceeding deadline must raise GatewayTimeoutError."""
    slow_adapter = SlowSTTAdapter(delay_sec=0.4)
    gw = TranscriptionGateway(adapter=slow_adapter, max_workers=2)
    try:
        raw_pcm = b"\x00\x01" * 320
        with pytest.raises(GatewayTimeoutError) as exc_info:
            gw.transcribe_chunk(raw_pcm, timeout=0.05)
        assert exc_info.value.status_code == 504
        assert exc_info.value.code == "GATEWAY_TIMEOUT"
    finally:
        gw.close()


# ============================================================================
# PHASE 2: RESILIENCE (RETRY & CIRCUIT BREAKER)
# ============================================================================

def test_retry_with_backoff_succeeds_on_second_attempt():
    """Retry transient failures with exponential backoff and verify success."""
    attempts = 0
    sleeps: List[float] = []

    def mock_sleep(d: float):
        sleeps.append(d)

    def flaky_func():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise GatewayTimeoutError("Simulated upstream transient timeout")
        return "success"

    result = retry_with_backoff(flaky_func, max_attempts=3, base_delay=0.05, sleep_fn=mock_sleep)
    assert result == "success"
    assert attempts == 2
    assert len(sleeps) == 1
    assert sleeps[0] == 0.05


def test_retry_with_backoff_non_transient_error_not_retried():
    """Validation or client errors must fail immediately without retrying."""
    attempts = 0
    sleeps: List[float] = []

    def permanent_failure():
        nonlocal attempts
        attempts += 1
        raise AudioFormatUnsupportedError("Unsupported sample rate 99999")

    with pytest.raises(AudioFormatUnsupportedError):
        retry_with_backoff(permanent_failure, max_attempts=3, sleep_fn=sleeps.append)

    assert attempts == 1
    assert len(sleeps) == 0


def test_retry_with_backoff_exhaustion_preserves_original_error():
    """When retries are exhausted, the original exception is re-raised."""
    attempts = 0

    def always_fails():
        nonlocal attempts
        attempts += 1
        raise TranscriptionModuleUnavailableError("Downstream permanently down")

    with pytest.raises(TranscriptionModuleUnavailableError) as exc_info:
        retry_with_backoff(always_fails, max_attempts=3, base_delay=0.01, sleep_fn=lambda _: None)

    assert attempts == 3
    assert exc_info.value.code == "TRANSCRIPTION_MODULE_UNAVAILABLE"


def test_circuit_breaker_trips_to_open_after_5_failures():
    """5 consecutive failures trip CircuitBreaker from CLOSED to OPEN."""
    clock_time = 1000.0
    cb = CircuitBreaker(failure_threshold=5, recovery_timeout_sec=30.0, clock_fn=lambda: clock_time)
    assert cb.state == CircuitState.CLOSED

    def failing_call():
        raise RuntimeError("STT adapter failure")

    for i in range(5):
        with pytest.raises(RuntimeError):
            cb.execute(failing_call)

    assert cb.state == CircuitState.OPEN
    assert cb.failure_count == 5


def test_circuit_breaker_rejects_calls_when_open_503():
    """When OPEN, CircuitBreaker rejects calls immediately with HTTP 503 CircuitBreakerOpenError."""
    clock_time = 1000.0
    cb = CircuitBreaker(failure_threshold=5, recovery_timeout_sec=30.0, clock_fn=lambda: clock_time)

    # Trip to OPEN
    for _ in range(5):
        try:
            cb.execute(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        except RuntimeError:
            pass

    assert cb.state == CircuitState.OPEN

    mock_fn = MagicMock()
    with pytest.raises(CircuitBreakerOpenError) as exc_info:
        cb.execute(mock_fn)

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "CIRCUIT_BREAKER_OPEN"
    mock_fn.assert_not_called()


def test_circuit_breaker_transitions_to_half_open_after_30s():
    """After 30s recovery timeout, CircuitBreaker transitions to HALF-OPEN."""
    clock_time = 1000.0
    cb = CircuitBreaker(failure_threshold=5, recovery_timeout_sec=30.0, clock_fn=lambda: clock_time)

    # Trip to OPEN
    for _ in range(5):
        try:
            cb.execute(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        except RuntimeError:
            pass
    assert cb.state == CircuitState.OPEN

    # Advance clock by 31 seconds
    clock_time += 31.0
    assert cb.state == CircuitState.HALF_OPEN


def test_circuit_breaker_trial_success_closes_circuit():
    """Successful trial call in HALF-OPEN closes circuit and resets failure count."""
    clock_time = 1000.0
    cb = CircuitBreaker(failure_threshold=5, recovery_timeout_sec=30.0, clock_fn=lambda: clock_time)

    for _ in range(5):
        try:
            cb.execute(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        except RuntimeError:
            pass

    clock_time += 31.0
    assert cb.state == CircuitState.HALF_OPEN

    # Trial call succeeds
    res = cb.execute(lambda: "recovered")
    assert res == "recovered"
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


def test_circuit_breaker_trial_failure_returns_to_open():
    """Failing trial call in HALF-OPEN immediately returns circuit to OPEN."""
    clock_time = 1000.0
    cb = CircuitBreaker(failure_threshold=5, recovery_timeout_sec=30.0, clock_fn=lambda: clock_time)

    for _ in range(5):
        try:
            cb.execute(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        except RuntimeError:
            pass

    clock_time += 31.0
    assert cb.state == CircuitState.HALF_OPEN

    # Trial call fails
    with pytest.raises(RuntimeError):
        cb.execute(lambda: (_ for _ in ()).throw(RuntimeError("still down")))

    assert cb.state == CircuitState.OPEN


def test_circuit_breaker_injectable_clock_avoids_sleeping():
    """Injectable clock allows instant deterministic state transitions without wall-clock sleep."""
    simulated_time = 50.0
    cb = CircuitBreaker(recovery_timeout_sec=30.0, clock_fn=lambda: simulated_time)
    for _ in range(5):
        try:
            cb.execute(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        except RuntimeError:
            pass
    assert cb.state == CircuitState.OPEN

    # Jump time forward without sleeping
    simulated_time += 35.0
    assert cb.state == CircuitState.HALF_OPEN


# ============================================================================
# PHASE 3: INPUT LIMITS (HTTP 413)
# ============================================================================

def test_api_oversized_audio_returns_413(client: TestClient):
    """Audio payload > 1,000,000 bytes returns HTTP 413 PayloadTooLargeError."""
    # 1,000,050 bytes payload
    oversized_pcm = b"\x00" * 1000050
    b64_data = base64.b64encode(oversized_pcm).decode("utf-8")

    response = client.post(
        "/api/v1/audio/process",
        json={"audio_base64": b64_data, "format": "linear16"},
    )
    assert response.status_code == 413
    data = response.json()
    assert data["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert "limit" in data["error"]["message"].lower() or "maximum" in data["error"]["message"].lower()


def test_api_excessive_chunks_returns_413(client: TestClient):
    """Audio requests generating > 500 chunks return HTTP 413 PayloadTooLargeError."""
    # At 16kHz linear16 mono (32 bytes/ms), 5ms chunk = 160 bytes.
    # 501 chunks = 501 * 160 = 80,160 bytes.
    large_payload = b"\x00\x01" * (160 * 501 // 2)
    b64_data = base64.b64encode(large_payload).decode("utf-8")

    response = client.post(
        "/api/v1/audio/process",
        json={"audio_base64": b64_data, "format": "linear16", "chunk_duration_ms": 5.0},
    )
    assert response.status_code == 413
    data = response.json()
    assert data["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert "chunks" in data["error"]["message"]


def test_api_valid_audio_succeeds_200(client: TestClient):
    """Valid audio within limits processes successfully with HTTP 200."""
    pcm = b"\x00\x02" * 320 * 2  # 2 chunks
    b64_data = base64.b64encode(pcm).decode("utf-8")

    response = client.post(
        "/api/v1/audio/process",
        json={"audio_base64": b64_data, "format": "linear16"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert len(data["chunks"]) == 2


def test_api_malformed_base64_returns_400(client: TestClient):
    """Malformed base64 audio payload returns HTTP 400."""
    response = client.post(
        "/api/v1/audio/process",
        json={"audio_base64": "!!!INVALID_BASE64_BYTES@@@"},
    )
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] in ("INVALID_BASE64_AUDIO", "AUDIO_DECODE_ERROR", "INVALID_BASE64")


# ============================================================================
# PHASE 4: PLUGGABLE STT PROVIDER (MOCK & DEEPGRAM)
# ============================================================================

def test_stt_provider_mock_selected_by_default():
    """Default provider creates DeterministicFakeTranscriber without network."""
    adapter = get_stt_adapter()
    assert type(adapter).__name__ == "DeterministicFakeTranscriber"
    assert isinstance(adapter, BaseSTTAdapter)


def test_stt_provider_deepgram_selected_when_configured():
    """Provider 'deepgram' returns DeepgramSTTAdapter when API key is provided."""
    adapter = get_stt_adapter("deepgram", api_key="dg-mock-test-key-12345")
    assert type(adapter).__name__ == "DeepgramSTTAdapter"
    assert isinstance(adapter, BaseSTTAdapter)
    assert getattr(adapter, "api_key") == "dg-mock-test-key-12345"


def test_deepgram_adapter_mock_transport_returns_valid_transcript():
    """Deepgram adapter normalizes Deepgram JSON responses via httpx.MockTransport."""
    mock_response_data = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "transcript": "hello voice copilot",
                            "confidence": 0.98,
                            "words": [
                                {"word": "hello", "start": 0.0, "end": 0.3, "confidence": 0.99},
                                {"word": "voice", "start": 0.3, "end": 0.6, "confidence": 0.98},
                                {"word": "copilot", "start": 0.6, "end": 1.0, "confidence": 0.97},
                            ],
                        }
                    ]
                }
            ]
        },
        "is_final": True,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.deepgram.com" in str(request.url)
        assert request.headers.get("Authorization") == "Token test-key"
        return httpx.Response(200, json=mock_response_data)

    transport = httpx.MockTransport(handler)
    adapter = DeepgramSTTAdapter(api_key="test-key", transport=transport)
    adapter.initialize()

    events = adapter.transcribe_chunk(b"\x00\x01" * 320, is_last=True)
    assert len(events) >= 1
    final_event = events[0]
    assert final_event.segment is not None
    assert final_event.segment.text == "hello voice copilot"
    assert final_event.segment.confidence == 0.98
    assert len(final_event.segment.words) == 3


def test_deepgram_adapter_http_401_500_failure():
    """Deepgram HTTP 401/500 errors are caught and surfaced clearly."""
    def handler_401(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Invalid credentials")

    transport = httpx.MockTransport(handler_401)
    adapter = DeepgramSTTAdapter(api_key="bad-key", transport=transport)
    adapter.initialize()

    with pytest.raises(RuntimeError) as exc_info:
        adapter.transcribe_chunk(b"\x00\x01" * 320)
    assert "401" in str(exc_info.value)


def test_stt_provider_deepgram_missing_api_key_raises_error(monkeypatch):
    """Configuring deepgram without API key raises descriptive ValueError."""
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    with pytest.raises(ValueError) as exc_info:
        get_stt_adapter("deepgram", api_key="")
    assert "DEEPGRAM_API_KEY" in str(exc_info.value)


def test_stt_provider_invalid_provider_rejected():
    """Unsupported STT provider names are rejected with permitted choices."""
    with pytest.raises(ValueError) as exc_info:
        get_stt_adapter("unsupported_engine")
    assert "Permitted values are: ['deepgram', 'mock']" in str(exc_info.value)


# ============================================================================
# PHASE 5: TRANSCRIPT READBACK ENDPOINT
# ============================================================================

def test_get_transcript_endpoint_returns_200_with_full_details(client: TestClient):
    """GET /sessions/{session_id}/transcript returns complete transcript and segments."""
    # 1. Create session and activate
    res_create = client.post("/api/v1/sessions")
    assert res_create.status_code == 201
    sid = res_create.json()["session_id"]
    client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "active"})

    # 2. Ingest audio chunks
    raw_pcm = b"\x00\x02" * 320 * 3
    b64_audio = base64.b64encode(raw_pcm).decode("utf-8")
    res_audio = client.post(
        f"/api/v1/sessions/{sid}/audio",
        json={"audio_base64": b64_audio, "format": "linear16", "is_last": True},
    )
    assert res_audio.status_code == 200

    # 3. Read back saved transcript
    res_transcript = client.get(f"/sessions/{sid}/transcript")
    assert res_transcript.status_code == 200
    data = res_transcript.json()
    assert data["session_id"] == sid
    assert "full_transcript" in data
    assert isinstance(data["segments"], list)
    assert data["chunks_processed"] >= 1
    assert data["last_updated"] is not None


def test_get_transcript_endpoint_returns_404_for_unknown_session(client: TestClient):
    """GET /sessions/{nonexistent_id}/transcript returns HTTP 404."""
    response = client.get("/sessions/session-nonexistent-9999/transcript")
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["code"] == "SESSION_NOT_FOUND"


def test_get_transcript_dual_routing_works(client: TestClient):
    """Both /sessions/{id}/transcript and /api/v1/sessions/{id}/transcript work identically."""
    # Create and activate session
    res_create = client.post("/api/v1/sessions")
    sid = res_create.json()["session_id"]
    client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "active"})

    res_root = client.get(f"/sessions/{sid}/transcript")
    res_prefixed = client.get(f"/api/v1/sessions/{sid}/transcript")

    assert res_root.status_code == 200
    assert res_prefixed.status_code == 200
    assert res_root.json()["session_id"] == res_prefixed.json()["session_id"]


# ============================================================================
# PHASE 6: GATEWAY TELEMETRY IN STATUS ENDPOINT
# ============================================================================

def test_gateways_status_telemetry_updates_accurately(client: TestClient):
    """GET /api/v1/gateways/status returns telemetry fields for both gateways."""
    # Perform an audio operation to increment counters
    raw_pcm = b"\x00\x02" * 320
    b64_data = base64.b64encode(raw_pcm).decode("utf-8")
    client.post("/api/v1/audio/process", json={"audio_base64": b64_data, "format": "linear16"})

    response = client.get("/api/v1/gateways/status")
    assert response.status_code == 200
    data = response.json()

    audio_status = data["audio_gateway"]
    assert "circuit_state" in audio_status
    assert "total_calls" in audio_status
    assert "error_count" in audio_status
    assert "avg_latency_ms" in audio_status
    assert "last_success_at" in audio_status
    assert audio_status["total_calls"] >= 1
    assert audio_status["circuit_state"] == "CLOSED"

    trans_status = data["transcription_gateway"]
    assert "circuit_state" in trans_status
    assert "total_calls" in trans_status
    assert "error_count" in trans_status
    assert "avg_latency_ms" in trans_status
    assert "last_success_at" in trans_status
    assert trans_status["circuit_state"] == "CLOSED"
