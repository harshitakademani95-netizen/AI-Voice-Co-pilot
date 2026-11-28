"""Automated End-to-End Pipeline, Audio Gateway, and Transcription Tests."""
import base64
from pathlib import Path
import sys

_project_dir = Path(__file__).resolve().parent.parent
_src_dir = _project_dir / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))
if str(_project_dir) not in sys.path:
    sys.path.insert(0, str(_project_dir))

import pytest
from starlette.testclient import TestClient

from src.app import create_app
from src.repositories.session_repository import session_repository


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def _generate_synthetic_pcm_b64(samples: int = 1600) -> str:
    # 1600 samples = 3200 bytes for 16-bit mono = 100ms of 16kHz audio
    pcm = bytearray(samples * 2)
    for i in range(0, len(pcm), 2):
        pcm[i] = (i % 256)
        pcm[i + 1] = ((i * 3) % 128)
    return base64.b64encode(pcm).decode("ascii")


def test_audio_process_endpoint_valid_audio(client: TestClient):
    audio_b64 = _generate_synthetic_pcm_b64(1600)
    resp = client.post(
        "/audio/process",
        json={
            "audio_base64": audio_b64,
            "format": "linear16",
            "sample_rate": 16000,
            "chunk_duration_ms": 20.0,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["chunks_count"] > 0
    assert len(data["chunks"]) == data["chunks_count"]


def test_audio_process_unsupported_format_rejected(client: TestClient):
    audio_b64 = _generate_synthetic_pcm_b64(1600)
    resp = client.post(
        "/audio/process",
        json={"audio_base64": audio_b64, "format": "unsupported_codec_xyz", "sample_rate": 16000},
    )
    assert resp.status_code == 400
    assert "unsupported" in resp.text.lower()


def test_audio_process_empty_payload_rejected(client: TestClient):
    resp = client.post(
        "/audio/process",
        json={"audio_base64": "", "format": "linear16", "sample_rate": 16000},
    )
    assert resp.status_code == 400
    assert "empty" in resp.text.lower()


def test_transcription_process_valid_audio(client: TestClient):
    audio_b64 = _generate_synthetic_pcm_b64(1600)
    resp = client.post(
        "/transcription/process",
        json={
            "audio_base64": audio_b64,
            "format": "linear16",
            "is_last": True,
            "session_id": "sess-trans-e2e",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "events" in data
    assert data["events_count"] >= 1


def test_session_audio_ingest_and_transcript_retrieval(client: TestClient):
    # 1. Create a session
    sess_resp = client.post("/api/v1/sessions", json={"metadata": {"user": "tester"}})
    assert sess_resp.status_code == 201
    sid = sess_resp.json()["session_id"]

    # 2. Ingest audio into the session
    audio_b64 = _generate_synthetic_pcm_b64(1600)
    ingest_resp = client.post(
        f"/sessions/{sid}/audio",
        json={"audio_base64": audio_b64, "format": "linear16", "is_last": True},
    )
    assert ingest_resp.status_code == 200
    ingest_data = ingest_resp.json()
    assert ingest_data["status"] == "success"
    assert ingest_data["chunks_processed"] > 0

    # 3. Retrieve accumulated transcript
    trans_resp = client.get(f"/sessions/{sid}/transcript")
    assert trans_resp.status_code == 200
    trans_data = trans_resp.json()
    assert "full_transcript" in trans_data
    assert trans_data["session_id"] == sid


def test_full_pipeline_process_end_to_end(client: TestClient):
    """TEST: Audio Input -> Audio Processing -> STT -> Dispatcher/Reasoning -> Planner -> Tool Execution -> Verification."""
    audio_b64 = _generate_synthetic_pcm_b64(1600)
    pipeline_resp = client.post(
        "/pipeline/process",
        json={
            "session_id": "sess-pipeline-full-e2e",
            "audio_base64": audio_b64,
            "user_query": "Check tasks and compile report",
            "format": "linear16",
            "sample_rate": 16000,
            "prompt_version": "v1.0.0",
        },
    )
    assert pipeline_resp.status_code == 200
    data = pipeline_resp.json()
    assert data["session_id"] == "sess-pipeline-full-e2e"
    assert data["status"] in ("completed", "requires_approval")
    assert data["audio_chunks_processed"] > 0
    assert "reasoning" in data
    assert "agent_orchestration" in data
    assert "final_response" in data
    assert "verification" in data
    assert data["verification"]["is_verified"] is True
    assert data["events_recorded"] > 0


def test_session_pipeline_endpoint(client: TestClient):
    """TEST: Path-based /sessions/{id}/pipeline endpoint."""
    resp = client.post(
        "/sessions/sess-path-pipeline/pipeline",
        json={"user_query": "Explain what this error means"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "sess-path-pipeline"
    assert "final_response" in data
    assert "verification" in data
