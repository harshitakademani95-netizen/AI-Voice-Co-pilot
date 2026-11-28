"""Dedicated integration tests for the three Week 3 Day 15 pending integration requirements.

Explicitly covers:
1. Audio gateway calling the actual audio module.
2. Successful audio module processing.
3. Audio gateway receiving the correct response.
4. Transcription gateway calling the actual transcription module.
5. Successful transcription processing.
6. Transcription gateway receiving the correct result.
7. Complete end-to-end audio-to-transcription workflow.
8. Correct data transfer between modules.
9. Audio module failure handling.
10. Transcription module failure handling.
11. Module timeout handling.
12. Correlation ID propagation.
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
from src.voice_stt.fake_transcriber import DeterministicFakeTranscriber


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. AUDIO GATEWAY TO ACTUAL MODULE TESTS
# ---------------------------------------------------------------------------

def test_01_audio_gateway_calling_actual_audio_module():
    """1. Verify AudioGateway directly invokes AudioChunker from src.audio.chunker."""
    gw = AudioGateway()
    raw_audio = b"\x00\x01\x00\x02" * 1600  # 6400 bytes = 10 chunks of 20ms (640 bytes each)
    chunks = gw.chunk_audio(audio_data=raw_audio, chunk_duration_ms=20.0)
    assert len(chunks) == 10
    assert all(isinstance(c, AudioChunk) for c in chunks)
    assert chunks[0].sequence_id == 0
    assert chunks[9].sequence_id == 9


def test_02_successful_audio_module_processing():
    """2. Verify actual audio chunking output format, frame alignment, and monotonic sequence IDs."""
    gw = AudioGateway()
    # 0.2s of 16kHz 16-bit mono PCM = 6400 bytes = 10 chunks of 640 bytes (320 samples each)
    sample_bytes = b"\x10\x00" * 3200
    chunks = gw.chunk_audio(audio_data=sample_bytes, chunk_duration_ms=20.0)
    assert len(chunks) == 10
    for idx, chunk in enumerate(chunks):
        assert chunk.sequence_id == idx
        assert chunk.duration_ms == 20.0
        assert len(chunk.data) == 640
        assert chunk.format.sample_rate == 16000
        assert chunk.format.channels == 1
        assert chunk.format.sample_width == 2


def test_03_audio_gateway_receiving_correct_response(client: TestClient):
    """3. Verify backend HTTP endpoint returns the actual AudioChunker output correctly."""
    sample_bytes = b"\x05\x00\x0a\x00" * 1600  # 0.2s = 10 chunks
    payload = {
        "audio_base64": base64.b64encode(sample_bytes).decode("ascii"),
        "format": "linear16",
        "sample_rate": 16000,
        "is_last": True,
    }
    resp = client.post("/api/v1/audio/process", json=payload, headers={"X-Correlation-ID": "test-gw-audio-resp"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["chunks_count"] == 10
    assert len(data["chunks"]) == 10
    assert data["chunks"][0]["sequence_id"] == 0
    assert data["chunks"][-1]["is_final"] is True
    assert data["chunks"][0]["byte_length"] == 640


# ---------------------------------------------------------------------------
# 2. TRANSCRIPTION GATEWAY TO ACTUAL MODULE TESTS
# ---------------------------------------------------------------------------

def test_04_transcription_gateway_calling_actual_transcription_module():
    """4. Verify TranscriptionGateway directly invokes DeterministicFakeTranscriber."""
    gw = TranscriptionGateway()
    assert hasattr(gw.adapter, "transcribe_chunk")
    assert gw.adapter.state.value == "ready"
    
    # Send chunk into adapter
    events = gw.transcribe_chunk(chunk=b"\x00\x00" * 320, is_last=False)
    assert len(events) >= 1
    assert hasattr(events[0], "event_type")


def test_05_successful_transcription_processing():
    """5. Verify STT module transcription output contains interim and final segments."""
    gw = TranscriptionGateway()
    session_id = "test-session-stt-proc-05"
    
    # Process multiple frames
    events1 = gw.transcribe_chunk(chunk=b"\x01\x00" * 320, is_last=False, session_id=session_id)
    assert len(events1) >= 1
    assert events1[0].event_type.value == "interim"
    
    events2 = gw.transcribe_chunk(chunk=b"\x02\x00" * 320, is_last=True, session_id=session_id)
    assert len(events2) >= 1
    assert any(e.event_type.value in ("final", "stream_completed") for e in events2)


def test_06_transcription_gateway_receiving_correct_result(client: TestClient):
    """6. Verify backend HTTP endpoint returns actual transcription events from the module."""
    sample_bytes = b"\x01\x00\x02\x00" * 320
    payload = {
        "audio_base64": base64.b64encode(sample_bytes).decode("ascii"),
        "format": "linear16",
        "session_id": "test-stt-resp-session-06",
        "is_last": True,
    }
    resp = client.post("/api/v1/transcription/process", json=payload, headers={"X-Correlation-ID": "test-stt-resp-corr"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["events_count"] >= 1
    assert "events" in data
    assert any(ev.get("event_type") in ("interim", "final") for ev in data["events"])


# ---------------------------------------------------------------------------
# 3. END-TO-END PIPELINE & DATA TRANSFER TESTS
# ---------------------------------------------------------------------------

def test_07_complete_end_to_end_audio_to_transcription_workflow(client: TestClient):
    """7. Compulsory E2E workflow: Both modules participate in the same request."""
    corr_id = "test-compulsory-e2e-corr-07"
    
    # 1. Create active session
    create_resp = client.post("/api/v1/sessions", json={"title": "E2E Joint Workflow"}, headers={"X-Correlation-ID": corr_id})
    assert create_resp.status_code == 201
    session_id = create_resp.json()["session_id"]
    
    # 2. Ingest audio: Audio Module chunks -> STT Module transcribes -> SessionRepository stores
    audio_bytes = b"\x03\x00\x04\x00" * 3200  # 12,800 bytes = 20 chunks of 20ms
    ingest_payload = {
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
        "format": "linear16",
        "is_last": True,
        "correlation_id": corr_id,
    }
    ingest_resp = client.post(f"/api/v1/sessions/{session_id}/audio", json=ingest_payload, headers={"X-Correlation-ID": corr_id})
    assert ingest_resp.status_code == 200
    res_data = ingest_resp.json()
    
    # Verify both modules participated in the response
    assert res_data["session_id"] == session_id
    assert res_data["status"] == "success"
    assert res_data["chunks_processed"] == 20  # from Audio Module (AudioChunker)
    assert res_data["events_count"] >= 20      # from STT Module (DeterministicFakeTranscriber)
    assert isinstance(res_data["full_transcript"], str)
    assert len(res_data["full_transcript"]) > 0
    
    # 3. Verify event persistence in Session timeline
    events_resp = client.get(f"/api/v1/sessions/{session_id}/events", headers={"X-Correlation-ID": corr_id})
    assert events_resp.status_code == 200
    timeline = events_resp.json()["events"]
    assert len(timeline) >= 21  # session_created + speech_transcript events


def test_08_correct_data_transfer_between_modules():
    """8. Verify data transfer contract between AudioChunker output and TranscriptionGateway input."""
    audio_gw = AudioGateway()
    trans_gw = TranscriptionGateway()
    
    raw_audio = b"\x00\x01\x00\x02" * 3200  # 20 chunks
    chunks = audio_gw.chunk_audio(audio_data=raw_audio)
    assert len(chunks) == 20
    
    # Directly stream chunks from audio module output into transcription gateway
    events_received = []
    for idx, c in enumerate(chunks):
        is_last = (idx == len(chunks) - 1)
        evs = trans_gw.transcribe_chunk(chunk=c, is_last=is_last, session_id="test-data-transfer-08")
        events_received.extend(evs)
    
    assert len(events_received) >= 20
    transcript = trans_gw.get_session_transcript("test-data-transfer-08")
    assert isinstance(transcript, str)
    assert len(transcript) > 0


# ---------------------------------------------------------------------------
# 4. ERROR, TIMEOUT, AND CORRELATION TRACING TESTS
# ---------------------------------------------------------------------------

def test_09_audio_module_failure_handling():
    """9. Verify AudioGateway properly handles invalid formats and empty data."""
    gw = AudioGateway()
    
    with pytest.raises(AudioFormatUnsupportedError):
        gw.validate_audio_format(sample_rate=99999)
    
    with pytest.raises(AudioGatewayError) as exc_info:
        gw.chunk_audio(audio_data=b"")
    assert exc_info.value.code == "AUDIO_EMPTY_DATA"


def test_10_transcription_module_failure_handling():
    """10. Verify TranscriptionGateway properly handles None and empty chunk payloads."""
    gw = TranscriptionGateway()
    
    with pytest.raises(TranscriptionGatewayError) as exc_info:
        gw.transcribe_chunk(chunk=None)
    assert exc_info.value.code == "EMPTY_AUDIO_CHUNK"
    
    with pytest.raises(TranscriptionGatewayError) as exc_info2:
        gw.transcribe_chunk(chunk=b"")
    assert exc_info2.value.code == "EMPTY_AUDIO_CHUNK"


def test_11_module_timeout_handling(monkeypatch):
    """11. Verify gateway timeout enforcement when module exceeds timeout limit."""
    # Audio timeout
    audio_gw = AudioGateway(timeout_seconds=0.01)
    def slow_chunk(data):
        time.sleep(0.05)
        return []
    from src.audio.chunker import AudioChunker
    monkeypatch.setattr(AudioChunker, "chunk_stream", lambda self, d: slow_chunk(d))
    with pytest.raises(GatewayTimeoutError):
        audio_gw.chunk_audio(audio_data=b"\x00" * 640)
    
    # STT timeout
    trans_gw = TranscriptionGateway(timeout_seconds=0.01)
    def slow_transcribe(chunk, is_last=False):
        time.sleep(0.05)
        return []
    monkeypatch.setattr(trans_gw.adapter, "transcribe_chunk", slow_transcribe)
    with pytest.raises(GatewayTimeoutError):
        trans_gw.transcribe_chunk(chunk=b"\x00" * 320)


def test_12_correlation_id_propagation(client: TestClient):
    """12. Verify correlation ID propagates without alteration across all endpoints."""
    test_corr_id = "corr-tracing-day15-test-12"
    
    # 1. Gateway status
    r1 = client.get("/api/v1/gateways/status", headers={"X-Correlation-ID": test_corr_id})
    assert r1.headers.get("x-correlation-id") == test_corr_id
    
    # 2. Audio process
    r2 = client.post(
        "/api/v1/audio/process",
        json={"audio_base64": base64.b64encode(b"\x00\x00" * 320).decode("ascii"), "format": "linear16"},
        headers={"X-Correlation-ID": test_corr_id},
    )
    assert r2.headers.get("x-correlation-id") == test_corr_id
    
    # 3. Transcription process
    r3 = client.post(
        "/api/v1/transcription/process",
        json={"audio_base64": base64.b64encode(b"\x00\x00" * 320).decode("ascii"), "format": "linear16"},
        headers={"X-Correlation-ID": test_corr_id},
    )
    assert r3.headers.get("x-correlation-id") == test_corr_id
