"""Unit, integration, and API acceptance tests for Week 3 Day 15 Backend Gateways.

Covers:
1. Audio Gateway: validation, chunking, format checks, timeouts, synthetic generation, error envelopes.
2. Transcription Gateway: heterogeneous normalization, transcription, accumulation, adapter errors.
3. Backend Gateway Service: coordination between audio, STT, and SessionRepository with live SSE event recording.
4. HTTP Gateway Endpoints: status, audio processing, transcription processing, and session audio ingestion.
"""
import base64
import time
from typing import Any, Dict
import pytest
from fastapi.testclient import TestClient

try:
    from src.app import app
    from src.core.errors import (
        AudioFormatUnsupportedError,
        AudioGatewayError,
        AudioModuleUnavailableError,
        GatewayTimeoutError,
        InvalidStateTransitionError,
        SessionNotFoundError,
        TranscriptionGatewayError,
        TranscriptionModuleUnavailableError,
    )
    from src.gateways.audio_gateway import AudioGateway, get_audio_gateway
    from src.gateways.service import BackendGatewayService, get_gateway_service
    from src.gateways.transcription_gateway import TranscriptionGateway, get_transcription_gateway
    from src.models.session import SessionState
    from src.repositories.session_repository import session_repository
except ImportError:
    from app import app
    from core.errors import (
        AudioFormatUnsupportedError,
        AudioGatewayError,
        AudioModuleUnavailableError,
        GatewayTimeoutError,
        InvalidStateTransitionError,
        SessionNotFoundError,
        TranscriptionGatewayError,
        TranscriptionModuleUnavailableError,
    )
    from gateways.audio_gateway import AudioGateway, get_audio_gateway
    from gateways.service import BackendGatewayService, get_gateway_service
    from gateways.transcription_gateway import TranscriptionGateway, get_transcription_gateway
    from models.session import SessionState
    from repositories.session_repository import session_repository
try:
    from src.schemas.audio import AudioChunk as Week1AudioChunk, AudioFormat
except ImportError:
    from schemas.audio import AudioChunk as Week1AudioChunk, AudioFormat

try:
    from src.voice_stt.adapter import STTAdapterConfig
    from src.voice_stt.schemas import AudioChunk as STTAudioChunk
except ImportError:
    from voice_stt.adapter import STTAdapterConfig
    from voice_stt.schemas import AudioChunk as STTAudioChunk


@pytest.fixture
def client():
    """TestClient fixture with fresh session repository."""
    session_repository.clear()
    with TestClient(app) as test_client:
        yield test_client
    session_repository.clear()


@pytest.fixture
def audio_gw():
    return AudioGateway()


@pytest.fixture
def trans_gw():
    return TranscriptionGateway()


@pytest.fixture
def gateway_svc(audio_gw, trans_gw):
    return BackendGatewayService(
        audio_gateway=audio_gw,
        transcription_gateway=trans_gw,
        session_repo=session_repository,
    )


# ===========================================================================
# 1. AUDIO GATEWAY TESTS
# ===========================================================================


class TestAudioGateway:
    def test_audio_gateway_initialization(self, audio_gw):
        assert audio_gw.is_available is True
        status = audio_gw.get_status()
        assert status["gateway"] == "AudioGateway"
        assert status["is_available"] is True
        assert status["total_chunks_produced"] == 0
        assert audio_gw.health_check() is True

    def test_chunk_valid_audio(self, audio_gw):
        # 16000 Hz, 16-bit mono = 32000 bytes/sec = 640 bytes per 20ms
        pcm_bytes = b"\x01\x00" * 320 * 5  # 100ms = 3200 bytes
        chunks = audio_gw.chunk_audio(raw_audio=pcm_bytes, chunk_duration_ms=20.0)

        assert len(chunks) == 5
        assert all(isinstance(c, Week1AudioChunk) for c in chunks)
        assert chunks[0].sequence_id == 0
        assert chunks[-1].sequence_id == 4
        assert audio_gw.get_status()["total_chunks_produced"] == 5

    def test_chunk_empty_audio_raises(self, audio_gw):
        with pytest.raises(AudioGatewayError) as exc_info:
            audio_gw.chunk_audio(b"")
        assert exc_info.value.code in ("AUDIO_EMPTY_DATA", "AUDIO_GATEWAY_ERROR")

    def test_validate_unsupported_format_raises(self, audio_gw):
        with pytest.raises(AudioFormatUnsupportedError) as exc_info:
            audio_gw.validate_audio_format("unsupported_ogg_vorbis")
        assert exc_info.value.code in ("UNSUPPORTED_AUDIO_FORMAT", "AUDIO_FORMAT_UNSUPPORTED")
        assert "unsupported_ogg_vorbis" in str(exc_info.value)

    def test_synthetic_audio_stream_generation(self, audio_gw):
        chunks = audio_gw.generate_synthetic_stream(
            duration_sec=0.1,  # 100ms
            chunk_duration_ms=20.0,
        )
        assert len(chunks) == 5
        assert chunks[0].duration_ms == 20.0

    def test_audio_gateway_timeout_enforcement(self, monkeypatch, audio_gw):
        # Simulate hang by having time.time jump beyond deadline
        call_count = 0

        def fake_monotonic():
            nonlocal call_count
            call_count += 1
            return 100.0 if call_count > 2 else 0.0

        monkeypatch.setattr(time, "monotonic", fake_monotonic)
        pcm_bytes = b"\x00" * 6400
        with pytest.raises(GatewayTimeoutError) as exc_info:
            audio_gw.chunk_audio(pcm_bytes, timeout_sec=0.001)
        assert exc_info.value.code == "GATEWAY_TIMEOUT"

    def test_audio_processing_unaligned_bytes_error(self, audio_gw):
        # 641 bytes is not an integer multiple of frame_size (2 bytes)
        with pytest.raises(AudioGatewayError) as exc_info:
            audio_gw.chunk_audio(b"\x00" * 641)
        assert exc_info.value.status_code == 400

    def test_audio_gateway_unavailable_raises(self, audio_gw):
        audio_gw.close()
        assert audio_gw.is_available is False
        assert audio_gw.health_check() is False
        with pytest.raises(AudioModuleUnavailableError) as exc_info:
            audio_gw.chunk_audio(b"\x00" * 640)
        assert exc_info.value.code == "AUDIO_MODULE_UNAVAILABLE"


# ===========================================================================
# 2. TRANSCRIPTION GATEWAY TESTS
# ===========================================================================


class TestTranscriptionGateway:
    def test_transcription_gateway_initialization(self, trans_gw):
        assert trans_gw.is_available is True
        assert trans_gw.health_check() is True
        status = trans_gw.get_status()
        assert status["gateway"] == "TranscriptionGateway"
        assert status["is_available"] is True
        assert status["total_chunks_transcribed"] == 0

    def test_transcribe_raw_bytes(self, trans_gw):
        pcm_data = b"\x00\x01" * 320
        events = trans_gw.transcribe_chunk(pcm_data, is_last=True, session_id="test-sid-1")
        assert len(events) >= 1
        assert events[0].segment is not None
        assert events[0].segment.text is not None
        assert trans_gw.get_status()["total_chunks_transcribed"] == 1

    def test_transcribe_week1_audio_chunk(self, trans_gw):
        fmt = AudioFormat(sample_rate=16000, channels=1, sample_width=2, encoding="pcm_s16le")
        w1_chunk = Week1AudioChunk(
            sequence_id=1,
            timestamp=0.0,
            data=b"\x00\x02" * 320,
            format=fmt,
        )
        events = trans_gw.transcribe_chunk(w1_chunk, session_id="test-sid-2")
        assert isinstance(events, list)

    def test_transcribe_empty_chunk_raises(self, trans_gw):
        with pytest.raises(TranscriptionGatewayError) as exc_info:
            trans_gw.transcribe_chunk(b"")
        assert exc_info.value.code in ("EMPTY_AUDIO_CHUNK", "TRANSCRIPTION_GATEWAY_ERROR")

    def test_transcribe_stt_audio_chunk(self, trans_gw):
        stt_chunk = STTAudioChunk(
            data=b"\x00\x03" * 320,
            sequence_id=1,
            timestamp=0.0,
        )
        events = trans_gw.transcribe_chunk(stt_chunk, session_id="test-sid-3")
        assert len(events) >= 1

    def test_transcription_gateway_timeout_enforcement(self, monkeypatch, trans_gw):
        call_count = 0

        def fake_monotonic():
            nonlocal call_count
            call_count += 1
            return 100.0 if call_count > 2 else 0.0

        monkeypatch.setattr(time, "monotonic", fake_monotonic)
        with pytest.raises(GatewayTimeoutError) as exc_info:
            trans_gw.transcribe_chunk(b"\x00\x01" * 320, timeout=0.001)
        assert exc_info.value.code == "GATEWAY_TIMEOUT"

    def test_transcription_adapter_simulated_error_propagation(self):
        from src.voice_stt.fake_transcriber import DeterministicFakeTranscriber
        error_transcriber = DeterministicFakeTranscriber(inject_error_at_chunk=0)
        custom_gw = TranscriptionGateway(adapter=error_transcriber)
        events = custom_gw.transcribe_chunk(b"\x00\x01" * 320)
        assert len(events) == 1
        assert events[0].error is not None
        assert events[0].event_type.value == "error"

    def test_transcribe_stream_and_accumulation(self, trans_gw):
        chunks = [b"\x00\x01" * 320 for _ in range(4)]
        all_events = trans_gw.transcribe_stream(chunks, session_id="acc-session-1")
        assert len(all_events) >= 1

        full_text = trans_gw.get_session_transcript("acc-session-1")
        assert isinstance(full_text, str)
        assert len(full_text) > 0

    def test_transcription_gateway_unavailable(self, trans_gw):
        trans_gw.close()
        assert trans_gw.is_available is False
        assert trans_gw.health_check() is False
        with pytest.raises(TranscriptionModuleUnavailableError) as exc_info:
            trans_gw.transcribe_chunk(b"\x00\x01" * 320)
        assert exc_info.value.code == "TRANSCRIPTION_MODULE_UNAVAILABLE"


# ===========================================================================
# 3. BACKEND GATEWAY SERVICE INTEGRATION TESTS
# ===========================================================================


class TestBackendGatewayService:
    def test_service_health_check(self, gateway_svc):
        health = gateway_svc.health_check()
        assert health["status"] == "healthy"
        assert health["audio_gateway"]["status"] == "healthy"
        assert health["transcription_gateway"]["status"] == "healthy"
        assert health["session_repository"]["status"] == "healthy"

    def test_process_session_audio_full_flow(self, gateway_svc):
        # 1. Create and activate a session
        session = session_repository.create(metadata={"user": "vaishnavi"})
        session_repository.transition(session.session_id, SessionState.ACTIVE)

        # 2. Process audio
        pcm_bytes = b"\x00\x05" * 320 * 3  # 60ms
        res = gateway_svc.process_session_audio(
            session_id=session.session_id,
            audio_data=pcm_bytes,
            is_last=True,
            correlation_id="corr-test-123",
        )

        assert res["session_id"] == session.session_id
        assert res["status"] == "success"
        assert res["chunks_processed"] == 3
        assert res["events_count"] >= 1

        # 3. Verify events were recorded in SessionRepository
        updated_session = session_repository.get(session.session_id)
        assert len(updated_session.events) >= 1
        speech_events = [e for e in updated_session.events if e.event_type == "speech_transcript"]
        assert len(speech_events) >= 1
        event = speech_events[0]
        assert event.event_type == "speech_transcript"
        assert "text" in event.payload
        assert event.correlation_id == "corr-test-123"

    def test_process_session_not_found(self, gateway_svc):
        with pytest.raises(SessionNotFoundError) as exc_info:
            gateway_svc.process_session_audio(
                session_id="non-existent-session",
                audio_data=b"\x00\x01" * 320,
            )
        assert exc_info.value.code == "SESSION_NOT_FOUND"

    def test_process_session_terminal_state_raises(self, gateway_svc):
        session = session_repository.create()
        session_repository.transition(session.session_id, SessionState.ACTIVE)
        session_repository.transition(session.session_id, SessionState.STOPPED)

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            gateway_svc.process_session_audio(
                session_id=session.session_id,
                audio_data=b"\x00\x01" * 320,
            )
        assert exc_info.value.code == "INVALID_STATE_TRANSITION"

    def test_process_session_paused_state_raises(self, gateway_svc):
        session = session_repository.create()
        session_repository.transition(session.session_id, SessionState.ACTIVE)
        session_repository.transition(session.session_id, SessionState.PAUSED)

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            gateway_svc.process_session_audio(
                session_id=session.session_id,
                audio_data=b"\x00\x01" * 320,
            )
        assert exc_info.value.code == "INVALID_STATE_TRANSITION"

    def test_backend_service_audio_unavailable_propagation(self, gateway_svc):
        session = session_repository.create()
        session_repository.transition(session.session_id, SessionState.ACTIVE)
        gateway_svc.audio_gateway.close()

        with pytest.raises(AudioModuleUnavailableError) as exc_info:
            gateway_svc.process_session_audio(
                session_id=session.session_id,
                audio_data=b"\x00\x01" * 320,
            )
        assert exc_info.value.code == "AUDIO_MODULE_UNAVAILABLE"

    def test_backend_service_transcription_unavailable_propagation(self, gateway_svc):
        session = session_repository.create()
        session_repository.transition(session.session_id, SessionState.ACTIVE)
        gateway_svc.transcription_gateway.close()

        with pytest.raises(TranscriptionModuleUnavailableError) as exc_info:
            gateway_svc.process_session_audio(
                session_id=session.session_id,
                audio_data=b"\x00\x01" * 320,
            )
        assert exc_info.value.code == "TRANSCRIPTION_MODULE_UNAVAILABLE"


# ===========================================================================
# 4. HTTP API GATEWAY ROUTE TESTS
# ===========================================================================


class TestGatewayAPIRoutes:
    def test_get_gateway_status_endpoint(self, client: TestClient):
        res = client.get("/api/v1/gateways/status")
        assert res.status_code == 200
        data = res.json()
        assert "audio_gateway" in data
        assert "transcription_gateway" in data
        assert data["health"]["status"] == "healthy"

    def test_post_audio_process_valid(self, client: TestClient):
        raw_pcm = b"\x00\x01" * 320 * 2  # 40ms = 2 chunks
        b64_audio = base64.b64encode(raw_pcm).decode("utf-8")

        res = client.post(
            "/api/v1/audio/process",
            json={"audio_base64": b64_audio, "format": "linear16", "sample_rate": 16000},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["chunks_count"] == 2
        assert len(data["chunks"]) == 2
        assert data["chunks"][0]["sequence_id"] in (0, 1)

    def test_post_audio_process_unsupported_format(self, client: TestClient):
        raw_pcm = b"\x00\x01" * 320
        b64_audio = base64.b64encode(raw_pcm).decode("utf-8")

        res = client.post(
            "/api/v1/audio/process",
            json={"audio_base64": b64_audio, "format": "invalid_audio_codec"},
        )
        assert res.status_code == 400
        data = res.json()
        assert data["error"]["code"] in ("AUDIO_FORMAT_UNSUPPORTED", "UNSUPPORTED_AUDIO_FORMAT")

    def test_post_audio_process_empty_data(self, client: TestClient):
        res = client.post(
            "/api/v1/audio/process",
            json={"audio_base64": ""},
        )
        assert res.status_code == 400
        data = res.json()
        assert data["error"]["code"] == "AUDIO_DATA_EMPTY"

    def test_post_transcription_process_valid(self, client: TestClient):
        raw_pcm = b"\x00\x01" * 320 * 2
        b64_audio = base64.b64encode(raw_pcm).decode("utf-8")

        res = client.post(
            "/api/v1/transcription/process",
            json={"audio_base64": b64_audio, "format": "linear16", "is_last": True},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["events_count"] >= 1
        assert "event_type" in data["events"][0]

    def test_post_session_audio_ingest_e2e(self, client: TestClient):
        # 1. Create session
        res_create = client.post("/api/v1/sessions")
        assert res_create.status_code == 201
        sid = res_create.json()["session_id"]

        # 2. Transition to active
        res_trans = client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "active"})
        assert res_trans.status_code == 200

        # 3. Ingest audio
        raw_pcm = b"\x00\x02" * 320 * 3
        b64_audio = base64.b64encode(raw_pcm).decode("utf-8")

        res_audio = client.post(
            f"/api/v1/sessions/{sid}/audio",
            json={"audio_base64": b64_audio, "format": "linear16", "is_last": True},
            headers={"X-Correlation-ID": "test-e2e-corr-999"},
        )
        assert res_audio.status_code == 200
        data = res_audio.json()
        assert data["status"] == "success"
        assert data["session_id"] == sid
        assert data["chunks_processed"] == 3
        assert data["events_count"] >= 1

        # 4. Verify events recorded on session
        res_events = client.get(f"/api/v1/sessions/{sid}/events")
        assert res_events.status_code == 200
        events = res_events.json()["events"]
        assert len(events) >= 1
        speech_events = [e for e in events if e["event_type"] == "speech_transcript"]
        assert len(speech_events) >= 1
        assert speech_events[0]["correlation_id"] == "test-e2e-corr-999"

    def test_post_session_audio_session_not_found(self, client: TestClient):
        raw_pcm = b"\x00\x01" * 320
        b64_audio = base64.b64encode(raw_pcm).decode("utf-8")

        res = client.post(
            "/api/v1/sessions/non-existent-sid/audio",
            json={"audio_base64": b64_audio},
        )
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "SESSION_NOT_FOUND"

    def test_post_session_audio_paused_state_409(self, client: TestClient):
        res_create = client.post("/api/v1/sessions")
        sid = res_create.json()["session_id"]
        client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "active"})
        client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "paused"})

        raw_pcm = b"\x00\x01" * 320
        b64_audio = base64.b64encode(raw_pcm).decode("utf-8")
        res = client.post(f"/api/v1/sessions/{sid}/audio", json={"audio_base64": b64_audio})
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
