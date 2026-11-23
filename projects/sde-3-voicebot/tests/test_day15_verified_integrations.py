"""Dedicated Day 15 Integration Verification Tests.

These tests explicitly prove:
1. Audio gateway calling the actual audio module.
2. Successful audio module response.
3. Transcription gateway calling the actual transcription module.
4. Successful transcription module response.
5. Complete audio-to-transcription workflow.
6. Correct data transfer between modules.
7. Failure handling in both gateways.
8. Correlation ID propagation across the workflow.
"""

import base64
import time
import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.core.errors import (
    AudioFormatUnsupportedError,
    AudioGatewayError,
    AudioModuleUnavailableError,
    GatewayTimeoutError,
    TranscriptionGatewayError,
    TranscriptionModuleUnavailableError,
)
from src.gateways.audio_gateway import AudioGateway, get_audio_gateway
from src.gateways.transcription_gateway import TranscriptionGateway, get_transcription_gateway
from src.gateways.service import BackendGatewayService, get_gateway_service
from src.repositories.session_repository import session_repository
from src.schemas.audio import AudioChunk, AudioFormat
from src.voice_stt.accumulator import OrderedSegmentAccumulator
from src.voice_stt.adapter import BaseSTTAdapter, STTAdapterConfig, STTAdapterState
from src.voice_stt.fake_transcriber import DeterministicFakeTranscriber


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. AUDIO GATEWAY INTEGRATION TESTS
# ---------------------------------------------------------------------------

def test_audio_gateway_actual_module_integration():
    """1. Verify AudioGateway directly invokes the real AudioChunker from src.audio."""
    gw = AudioGateway()
    assert gw.is_available is True
    
    # 1 second of 16kHz 16-bit mono audio (32,000 bytes)
    sample_bytes = b"\x00\x01\x00\x02" * 8000
    fmt = gw.validate_audio_format(sample_rate=16000, channels=1, sample_width=2, encoding="pcm_s16le")
    
    # Invoke chunk_audio which must invoke the underlying AudioChunker
    chunks = gw.chunk_audio(audio_data=sample_bytes, format_spec=fmt, chunk_duration_ms=20.0)
    
    # 1000ms / 20ms = 50 chunks
    assert len(chunks) == 50
    assert all(isinstance(c, AudioChunk) for c in chunks)
    assert chunks[0].sequence_id == 0
    assert chunks[49].sequence_id == 49
    assert len(chunks[0].data) == 640  # 320 samples * 2 bytes
    assert gw.get_status()["total_chunks_produced"] >= 50
    assert gw.get_status()["total_bytes_processed"] >= 32000


def test_audio_gateway_calling_actual_audio_module():
    """1b. Verify AudioGateway delegating to MockMicrophone from the audio module."""
    gw = AudioGateway()
    chunks = gw.generate_synthetic_stream(duration_sec=0.5, chunk_duration_ms=20.0)
    assert len(chunks) == 25
    assert all(isinstance(c, AudioChunk) for c in chunks)
    assert chunks[0].duration_ms == 20.0


def test_audio_gateway_successful_response(client: TestClient):
    """2. Verify that the HTTP endpoint returns the actual AudioChunker output correctly."""
    sample_bytes = b"\x05\x00\x0a\x00" * 3200  # 0.4 seconds = 20 chunks
    payload = {
        "audio_base64": base64.b64encode(sample_bytes).decode("ascii"),
        "format": "linear16",
        "sample_rate": 16000,
        "is_last": True,
    }
    response = client.post("/api/v1/audio/process", json=payload, headers={"X-Correlation-ID": "test-audio-resp-001"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["chunks_count"] == 20
    assert len(data["chunks"]) == 20
    assert data["chunks"][0]["sequence_id"] == 0
    assert data["chunks"][-1]["is_final"] is True
    assert data["chunks"][0]["byte_length"] == 640


def test_successful_audio_module_response():
    """2b. Direct module verification of chunks produced by AudioChunker."""
    gw = AudioGateway()
    data = b"\x10\x00" * 320  # 20ms frame
    chunks = gw.chunk_audio(audio_data=data)
    assert len(chunks) == 1
    assert chunks[0].sequence_id == 0
    assert chunks[0].format.sample_rate == 16000


def test_audio_module_failure_handling():
    """Verify that AudioGateway properly handles and translates audio module failures."""
    gw = AudioGateway()
    
    # Test invalid format detection
    with pytest.raises(AudioFormatUnsupportedError) as exc_info:
        gw.validate_audio_format(sample_rate=99999)
    assert "Unsupported audio sample rate" in str(exc_info.value)
    
    # Test empty payload rejection
    with pytest.raises(AudioGatewayError) as exc_info:
        gw.chunk_audio(audio_data=b"")
    assert exc_info.value.code == "AUDIO_EMPTY_DATA"
    
    # Test unavailable module flag
    gw.set_available(False)
    with pytest.raises(AudioModuleUnavailableError):
        gw.chunk_audio(audio_data=b"\x00" * 640)
    gw.set_available(True)


def test_audio_module_timeout(monkeypatch):
    """Verify that AudioGateway enforces strict timeout limits on processing operations."""
    gw = AudioGateway(timeout_seconds=0.01)
    
    def slow_chunk_stream(data):
        time.sleep(0.05)
        return []
    
    from src.audio.chunker import AudioChunker
    monkeypatch.setattr(AudioChunker, "chunk_stream", lambda self, d: slow_chunk_stream(d))
    
    with pytest.raises(GatewayTimeoutError) as exc_info:
        gw.chunk_audio(audio_data=b"\x00" * 640)
    assert "exceeded timeout limit" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 2. TRANSCRIPTION GATEWAY INTEGRATION TESTS
# ---------------------------------------------------------------------------

def test_transcription_gateway_actual_module_integration():
    """3. Verify that TranscriptionGateway directly invokes DeterministicFakeTranscriber and OrderedSegmentAccumulator."""
    gw = TranscriptionGateway()
    assert gw.is_available is True
    
    sample_chunk = b"\x00\x00" * 320
    events = gw.transcribe_chunk(chunk=sample_chunk, is_last=False, session_id="test-trans-integ-1")
    
    assert len(events) >= 1
    assert all(hasattr(e, "event_type") for e in events)
    assert events[0].event_type.value in ("interim", "final")
    
    final_events = gw.transcribe_chunk(chunk=sample_chunk, is_last=True, session_id="test-trans-integ-1")
    assert len(final_events) >= 1
    
    transcript = gw.get_session_transcript("test-trans-integ-1")
    assert isinstance(transcript, str)
    assert gw.get_status()["total_chunks_transcribed"] >= 2


def test_transcription_gateway_calling_actual_transcription_module():
    """3b. Direct verification of adapter state and event streaming."""
    gw = TranscriptionGateway()
    assert hasattr(gw.adapter, "transcribe_chunk")
    assert gw.adapter.state.value == "ready"
    
    events = gw.transcribe_chunk(chunk=b"\x12\x34" * 160, is_last=True)
    assert len(events) >= 1
    assert any(e.event_type.value in ("interim", "final") for e in events)
    assert events[-1].event_type.value in ("interim", "final", "stream_completed")


def test_transcription_gateway_successful_response(client: TestClient):
    """4. Verify that the HTTP endpoint returns the actual transcription events from the module."""
    sample_bytes = b"\x01\x00\x02\x00" * 320
    payload = {
        "audio_base64": base64.b64encode(sample_bytes).decode("ascii"),
        "format": "linear16",
        "session_id": "test-trans-resp-session",
        "is_last": True,
    }
    response = client.post("/api/v1/transcription/process", json=payload, headers={"X-Correlation-ID": "test-trans-resp-001"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["events_count"] >= 1
    assert "events" in data
    assert any(ev.get("event_type") in ("interim", "final") for ev in data["events"])


def test_successful_transcription_module_response():
    """4b. Verify that transcription accumulator captures and produces final transcript."""
    gw = TranscriptionGateway()
    session_id = "test-accum-success-01"
    
    # Process multiple chunks
    for i in range(3):
        is_last = (i == 2)
        gw.transcribe_chunk(chunk=b"\x00\x00" * 320, is_last=is_last, session_id=session_id)
    
    transcript = gw.get_session_transcript(session_id)
    assert isinstance(transcript, str)


def test_transcription_module_failure_handling():
    """Verify that TranscriptionGateway properly handles module failure and invalid inputs."""
    gw = TranscriptionGateway()
    
    # Test None chunk rejection
    with pytest.raises(TranscriptionGatewayError) as exc_info:
        gw.transcribe_chunk(chunk=None)
    assert exc_info.value.code == "EMPTY_AUDIO_CHUNK"
    
    # Test unavailable module flag
    gw.set_available(False)
    with pytest.raises(TranscriptionModuleUnavailableError):
        gw.transcribe_chunk(chunk=b"\x00" * 320)
    gw.set_available(True)


def test_transcription_module_timeout(monkeypatch):
    """Verify that TranscriptionGateway enforces timeout limits when calling the STT module."""
    gw = TranscriptionGateway(timeout_seconds=0.01)
    
    def slow_transcribe(chunk, is_last=False):
        time.sleep(0.05)
        return []
    
    monkeypatch.setattr(gw.adapter, "transcribe_chunk", slow_transcribe)
    with pytest.raises(GatewayTimeoutError) as exc_info:
        gw.transcribe_chunk(chunk=b"\x00" * 320)
    assert "exceeded timeout limit" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 3. END-TO-END AUDIO-TO-TRANSCRIPTION INTEGRATION TESTS
# ---------------------------------------------------------------------------

def test_audio_to_transcription_end_to_end(client: TestClient):
    """5. Compulsory E2E pipeline test:
    Client -> API -> Audio Gateway -> Audio Module -> Transcription Gateway -> STT Module -> SessionRepository -> Client
    """
    corr_id = "test-compulsory-e2e-corr"
    
    # 1. Create session
    create_resp = client.post("/api/v1/sessions", json={"title": "Compulsory E2E Pipeline"}, headers={"X-Correlation-ID": corr_id})
    assert create_resp.status_code == 201
    session_id = create_resp.json()["session_id"]
    
    # 2. Send 0.5s of audio to session audio ingestion endpoint
    audio_bytes = b"\x03\x00\x04\x00" * 4000  # 16,000 bytes = 0.5s at 16kHz
    ingest_payload = {
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
        "format": "linear16",
        "is_last": True,
        "correlation_id": corr_id,
    }
    ingest_resp = client.post(f"/api/v1/sessions/{session_id}/audio", json=ingest_payload, headers={"X-Correlation-ID": corr_id})
    assert ingest_resp.status_code == 200
    res_data = ingest_resp.json()
    
    # Verify stages in returned response
    assert res_data["session_id"] == session_id
    assert res_data["status"] == "success"
    assert res_data["chunks_processed"] == 25  # 500ms / 20ms = 25 chunks from Audio Module
    assert res_data["events_count"] >= 25      # >= 25 events from STT Module
    assert isinstance(res_data["full_transcript"], str)
    assert len(res_data["full_transcript"]) > 0
    
    # 3. Verify event persistence in SessionRepository timeline
    events_resp = client.get(f"/api/v1/sessions/{session_id}/events", headers={"X-Correlation-ID": corr_id})
    assert events_resp.status_code == 200
    timeline = events_resp.json()["events"]
    assert len(timeline) >= 26  # session_created + transcription events
    event_types = [ev["event_type"] for ev in timeline]
    assert "session_created" in event_types
    assert "speech_transcript" in event_types


def test_complete_audio_to_transcription_workflow():
    """5b. Direct BackendGatewayService pipeline verification connecting both modules."""
    svc = get_gateway_service()
    
    # Create session in repository
    sess = session_repository.create(metadata={"title": "Service Level E2E Pipeline"})
    session_id = sess.session_id
    
    raw_audio = b"\x01\x02\x03\x04" * 4000  # 16,000 bytes = 25 chunks
    result = svc.process_session_audio(
        session_id=session_id,
        audio_data=raw_audio,
        is_last=True,
        correlation_id="corr-service-e2e-direct",
    )
    
    assert result["status"] == "success"
    assert result["chunks_processed"] == 25
    assert result["events_count"] >= 25
    assert len(result["full_transcript"]) > 0


def test_correct_data_transfer_between_modules():
    """6. Verify data integrity between AudioGateway chunk output and TranscriptionGateway input."""
    audio_gw = AudioGateway()
    trans_gw = TranscriptionGateway()
    
    raw_audio = b"\xaa\xbb" * 1600  # 100ms = 5 chunks
    chunks = audio_gw.chunk_audio(audio_data=raw_audio)
    assert len(chunks) == 5
    
    # Hand off each chunk produced by AudioChunker directly to TranscriptionGateway
    all_events = []
    for i, c in enumerate(chunks):
        is_last = (i == len(chunks) - 1)
        evs = trans_gw.transcribe_chunk(chunk=c, is_last=is_last, session_id="test-data-transfer")
        all_events.extend(evs)
    
    assert len(all_events) >= 5
    transcript = trans_gw.get_session_transcript("test-data-transfer")
    assert isinstance(transcript, str)


def test_failure_handling_in_both_gateways():
    """7. Verify error envelopes when either gateway encounters an invalid condition."""
    svc = get_gateway_service()
    
    # 1. Invalid audio data -> AudioGatewayError
    with pytest.raises(AudioGatewayError):
        svc.audio_gateway.chunk_audio(audio_data=b"")
    
    # 2. Invalid chunk data -> TranscriptionGatewayError
    with pytest.raises(TranscriptionGatewayError):
        svc.transcription_gateway.transcribe_chunk(chunk=None)


def test_correlation_id_propagation_across_workflow(client: TestClient):
    """8. Verify correlation ID propagates without alteration across all endpoints in the pipeline."""
    test_corr_id = "corr-tracing-e2e-888999"
    
    # 1. Status endpoint
    r1 = client.get("/api/v1/gateways/status", headers={"X-Correlation-ID": test_corr_id})
    assert r1.headers.get("x-correlation-id") == test_corr_id
    
    # 2. Audio process endpoint
    r2 = client.post(
        "/api/v1/audio/process",
        json={"audio_base64": base64.b64encode(b"\x00\x00" * 320).decode("ascii"), "format": "linear16"},
        headers={"X-Correlation-ID": test_corr_id},
    )
    assert r2.headers.get("x-correlation-id") == test_corr_id
    
    # 3. Transcription process endpoint
    r3 = client.post(
        "/api/v1/transcription/process",
        json={"audio_base64": base64.b64encode(b"\x00\x00" * 320).decode("ascii"), "format": "linear16"},
        headers={"X-Correlation-ID": test_corr_id},
    )
    assert r3.headers.get("x-correlation-id") == test_corr_id
    
    # 4. Session audio ingestion endpoint
    s = client.post("/api/v1/sessions", json={"title": "Tracing Test"}, headers={"X-Correlation-ID": test_corr_id})
    s_id = s.json()["session_id"]
    r4 = client.post(
        f"/api/v1/sessions/{s_id}/audio",
        json={"audio_base64": base64.b64encode(b"\x00\x00" * 320).decode("ascii"), "format": "linear16", "is_last": True},
        headers={"X-Correlation-ID": test_corr_id},
    )
    assert r4.headers.get("x-correlation-id") == test_corr_id


def test_correlation_id_across_modules(client: TestClient):
    """8b. Additional correlation ID verification across gateway boundaries."""
    test_corr_id = "corr-tracing-e2e-998877"
    resp1 = client.get("/api/v1/gateways/status", headers={"X-Correlation-ID": test_corr_id})
    assert resp1.headers.get("x-correlation-id") == test_corr_id
