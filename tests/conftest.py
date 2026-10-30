"""Pytest fixtures for AI Voice Co-Pilot: STT pipeline and Backend tests."""

from typing import List
import pytest
from starlette.testclient import TestClient

from src.app import create_app
from src.repositories.session_repository import session_repository

try:
    from voice_stt.schemas import (
        AudioChunk,
        STTErrorDetail,
        TranscriptEvent,
        TranscriptEventType,
        TranscriptSegment,
        WordTiming,
    )
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Backend & Sessions Workstream (W5) Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_repository():
    """Ensures a clean in-memory session repository before each test."""
    session_repository.clear()
    yield
    session_repository.clear()


@pytest.fixture
def client():
    """Provides a TestClient instance for testing backend routes."""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# STT Pipeline Workstream (W2) Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_audio_bytes() -> bytes:
    """Deterministic 16kHz 16-bit mono PCM simulated audio slice (100ms = 3200 bytes)."""
    return b"\x00\x01\x00\x02" * 800


@pytest.fixture
def sample_audio_chunks(sample_audio_bytes: bytes) -> List["AudioChunk"]:
    """Series of 5 consecutive audio chunks."""
    from voice_stt.schemas import AudioChunk
    chunks = []
    for i in range(5):
        chunks.append(
            AudioChunk(
                chunk_id=f"chunk-{i:03d}",
                data=sample_audio_bytes,
                sequence_number=i,
                timestamp=i * 0.1,
                duration_ms=100.0,
                sample_rate=16000,
                is_last=(i == 4),
            )
        )
    return chunks


@pytest.fixture
def valid_interim_segment() -> "TranscriptSegment":
    """A valid interim transcript segment."""
    from voice_stt.schemas import TranscriptSegment
    return TranscriptSegment(
        segment_id="seg-interim-001",
        text="Why is this application",
        start_time=0.0,
        end_time=0.8,
        confidence=0.85,
        is_final=False,
        language="en",
    )


@pytest.fixture
def valid_final_segment() -> "TranscriptSegment":
    """A valid finalized transcript segment with word timings."""
    from voice_stt.schemas import TranscriptSegment, WordTiming
    return TranscriptSegment(
        segment_id="seg-final-001",
        text="Why is this application showing this error?",
        start_time=0.0,
        end_time=1.5,
        confidence=0.97,
        is_final=True,
        language="en",
        words=[
            WordTiming(word="Why", start_time=0.0, end_time=0.2, confidence=0.98),
            WordTiming(word="is", start_time=0.2, end_time=0.4, confidence=0.97),
            WordTiming(word="this", start_time=0.4, end_time=0.6, confidence=0.96),
            WordTiming(word="application", start_time=0.6, end_time=0.9, confidence=0.98),
            WordTiming(word="showing", start_time=0.9, end_time=1.1, confidence=0.95),
            WordTiming(word="this", start_time=1.1, end_time=1.25, confidence=0.96),
            WordTiming(word="error?", start_time=1.25, end_time=1.5, confidence=0.99),
        ],
    )


@pytest.fixture
def out_of_order_segments() -> List["TranscriptSegment"]:
    """Three final segments emitted intentionally out of chronological order."""
    from voice_stt.schemas import TranscriptSegment
    seg_1 = TranscriptSegment(
        segment_id="seg-part-1",
        text="First sentence.",
        start_time=0.0,
        end_time=1.0,
        confidence=0.95,
        is_final=True,
        language="en",
    )
    seg_2 = TranscriptSegment(
        segment_id="seg-part-2",
        text="Second sentence.",
        start_time=1.0,
        end_time=2.0,
        confidence=0.94,
        is_final=True,
        language="en",
    )
    seg_3 = TranscriptSegment(
        segment_id="seg-part-3",
        text="Third sentence.",
        start_time=2.0,
        end_time=3.0,
        confidence=0.96,
        is_final=True,
        language="en",
    )
    return [seg_2, seg_3, seg_1]


@pytest.fixture
def sample_error_event() -> "TranscriptEvent":
    """An event representing an STT processing failure."""
    from voice_stt.schemas import TranscriptEvent, TranscriptEventType, STTErrorDetail
    return TranscriptEvent(
        event_id="err-event-001",
        event_type=TranscriptEventType.ERROR,
        sequence_number=10,
        timestamp=1.23,
        error=STTErrorDetail(
            code="MICROPHONE_DROPOUT",
            message="Audio buffer underrun detected during ingestion.",
            retryable=True,
            details={"buffer_size": 0},
        ),
    )
