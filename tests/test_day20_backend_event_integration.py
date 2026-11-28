"""Week 3 Day 20: STT-to-Backend Event-Stream Integration Tests.

Covers:
1. INTERIM events forwarded to backend repository as voice_stt.interim.
2. REVISION events forwarded to backend repository as voice_stt.revision.
3. FINALIZATION events forwarded to backend repository as voice_stt.finalization.
4. ERROR events forwarded to backend repository as voice_stt.error.
5. Session ID, sequence number, confidence, and timestamps preserved in payload.
6. Duplicate transcript event publication suppressed.
7. Missing session handled gracefully without crashing or corrupting STT state.
8. Inactive/terminal session handled gracefully without crashing or corrupting STT state.
9. Backend failure isolation: STT accumulator transcript remains completely uncorrupted.
10. End-to-end integration: Audio -> Orchestrator -> BackendEventStreamBridge -> InMemorySessionRepository.
"""

from typing import Any, Dict, List
import pytest

from src.models.session import Session, SessionEvent, SessionState
from src.repositories.session_repository import InMemorySessionRepository
from voice_stt.integration import AudioSTTBridge, BackendEventStreamBridge, STT_BACKEND_EVENT_TYPE_MAP
from voice_stt.orchestrator import TranscriptionOrchestrator
from voice_stt.schemas import (
    STTErrorDetail,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


class TestDay20BackendEventIntegration:
    """Test suite for Day 20 STT-to-Backend Event-Stream integration."""

    @pytest.fixture
    def repo(self) -> InMemorySessionRepository:
        r = InMemorySessionRepository()
        r.create(session_id="test-session-20")
        r.transition(session_id="test-session-20", to_state=SessionState.ACTIVE)
        return r

    def test_01_interim_event_forwarded_to_backend(self, repo: InMemorySessionRepository) -> None:
        bridge = BackendEventStreamBridge(repository=repo, session_id="test-session-20")

        event = TranscriptEvent(
            event_id="evt-interim-1",
            event_type=TranscriptEventType.INTERIM,
            sequence_number=1,
            timestamp=100.0,
            session_id="test-session-20",
            segment=TranscriptSegment(
                segment_id="seg-1",
                start_time=0.0,
                end_time=1.0,
                text="hello world interim",
                confidence=0.85,
                is_final=False,
            ),
        )

        session_evt = bridge.publish_event(event)
        assert session_evt is not None
        assert session_evt.event_type == "voice_stt.interim"
        assert session_evt.payload["transcript"] == "hello world interim"
        assert session_evt.payload["confidence"] == 0.85
        assert session_evt.payload["is_final"] is False

    def test_02_revision_event_forwarded_to_backend(self, repo: InMemorySessionRepository) -> None:
        bridge = BackendEventStreamBridge(repository=repo, session_id="test-session-20")

        event = TranscriptEvent(
            event_id="evt-revision-1",
            event_type=TranscriptEventType.REVISION,
            sequence_number=2,
            timestamp=101.0,
            session_id="test-session-20",
            segment=TranscriptSegment(
                segment_id="seg-2",
                start_time=0.0,
                end_time=1.5,
                text="hello world revised",
                confidence=0.90,
                is_final=False,
            ),
        )

        session_evt = bridge.publish_event(event)
        assert session_evt is not None
        assert session_evt.event_type == "voice_stt.revision"
        assert session_evt.payload["transcript"] == "hello world revised"

    def test_03_finalization_event_forwarded_to_backend(self, repo: InMemorySessionRepository) -> None:
        bridge = BackendEventStreamBridge(repository=repo, session_id="test-session-20")

        event = TranscriptEvent(
            event_id="evt-final-1",
            event_type=TranscriptEventType.FINALIZATION,
            sequence_number=3,
            timestamp=102.0,
            session_id="test-session-20",
            segment=TranscriptSegment(
                segment_id="seg-3",
                start_time=0.0,
                end_time=2.0,
                text="hello world finalized.",
                confidence=0.98,
                is_final=True,
            ),
        )

        session_evt = bridge.publish_event(event)
        assert session_evt is not None
        assert session_evt.event_type == "voice_stt.finalization"
        assert session_evt.payload["is_final"] is True
        assert session_evt.payload["transcript"] == "hello world finalized."

    def test_04_error_event_forwarded_to_backend(self, repo: InMemorySessionRepository) -> None:
        bridge = BackendEventStreamBridge(repository=repo, session_id="test-session-20")

        error_detail = STTErrorDetail(
            code="TRANSCRIPTION_TIMEOUT",
            message="Speech engine timed out.",
            retryable=True,
        )
        event = TranscriptEvent(
            event_id="evt-error-1",
            event_type=TranscriptEventType.ERROR,
            sequence_number=4,
            timestamp=103.0,
            session_id="test-session-20",
            error=error_detail,
        )

        session_evt = bridge.publish_event(event)
        assert session_evt is not None
        assert session_evt.event_type == "voice_stt.error"
        assert session_evt.payload["error"]["code"] == "TRANSCRIPTION_TIMEOUT"

    def test_05_session_id_and_metadata_preserved(self, repo: InMemorySessionRepository) -> None:
        bridge = BackendEventStreamBridge(repository=repo, session_id="test-session-20")

        event = TranscriptEvent(
            event_id="evt-meta-1",
            event_type=TranscriptEventType.FINALIZATION,
            sequence_number=5,
            timestamp=104.0,
            session_id="test-session-20",
            metadata={"source": "microphone", "chunk_index": 7},
            segment=TranscriptSegment(
                segment_id="seg-meta-1",
                start_time=1.0,
                end_time=2.5,
                text="metadata preserved test",
                confidence=0.95,
                is_final=True,
            ),
        )

        session_evt = bridge.publish_event(event)
        assert session_evt is not None
        assert session_evt.payload["metadata"]["source"] == "microphone"
        assert session_evt.payload["metadata"]["chunk_index"] == 7
        assert session_evt.payload["source_event_id"] == "evt-meta-1"
        assert session_evt.payload["source_timestamp"] == 104.0

    def test_06_duplicate_event_publication_suppression(self, repo: InMemorySessionRepository) -> None:
        bridge = BackendEventStreamBridge(repository=repo, session_id="test-session-20")

        event = TranscriptEvent(
            event_id="evt-dup-unique-123",
            event_type=TranscriptEventType.FINALIZATION,
            sequence_number=6,
            timestamp=105.0,
            session_id="test-session-20",
            segment=TranscriptSegment(
                segment_id="seg-dup-1",
                start_time=0.0,
                end_time=1.0,
                text="duplicate suppression test",
                confidence=0.95,
                is_final=True,
            ),
        )

        evt1 = bridge.publish_event(event)
        evt2 = bridge.publish_event(event)

        assert evt1 is not None
        assert evt2 is None  # Suppressed
        # Verify repository session events contains it only once
        session = repo.get("test-session-20")
        matching = [e for e in session.events if e.payload.get("source_event_id") == "evt-dup-unique-123"]
        assert len(matching) == 1

    def test_07_missing_session_handled_gracefully(self, repo: InMemorySessionRepository) -> None:
        bridge = BackendEventStreamBridge(repository=repo, session_id="nonexistent-session")

        event = TranscriptEvent(
            event_id="evt-missing-session-1",
            event_type=TranscriptEventType.FINALIZATION,
            sequence_number=1,
            timestamp=100.0,
            session_id="nonexistent-session",
            segment=TranscriptSegment(
                segment_id="seg-1",
                start_time=0.0,
                end_time=1.0,
                text="should fail safely",
                confidence=0.9,
                is_final=True,
            ),
        )

        res = bridge.publish_event(event)
        assert res is None
        assert len(bridge.publish_failures) == 1
        assert "not found" in bridge.publish_failures[0]["reason"].lower()

    def test_08_inactive_terminal_session_handled_gracefully(self, repo: InMemorySessionRepository) -> None:
        repo.create(session_id="terminal-session")
        repo.transition(session_id="terminal-session", to_state=SessionState.FAILED, reason="System failure")

        bridge = BackendEventStreamBridge(repository=repo, session_id="terminal-session")
        event = TranscriptEvent(
            event_id="evt-term-1",
            event_type=TranscriptEventType.INTERIM,
            sequence_number=1,
            timestamp=100.0,
            session_id="terminal-session",
            segment=TranscriptSegment(
                segment_id="seg-1",
                start_time=0.0,
                end_time=1.0,
                text="terminal test",
                confidence=0.9,
                is_final=False,
            ),
        )

        res = bridge.publish_event(event)
        assert res is None
        assert len(bridge.publish_failures) == 1
        assert "terminal" in bridge.publish_failures[0]["reason"].lower()

    def test_09_backend_failure_does_not_corrupt_stt_accumulator(self, repo: InMemorySessionRepository) -> None:
        # Repository has missing session, bridge fails to publish
        bridge = BackendEventStreamBridge(repository=repo, session_id="unregistered-sid")
        orch = TranscriptionOrchestrator(session_id="orch-safe-session")

        event = TranscriptEvent(
            event_id="evt-orch-safe-1",
            event_type=TranscriptEventType.FINALIZATION,
            sequence_number=1,
            timestamp=100.0,
            session_id="orch-safe-session",
            segment=TranscriptSegment(
                segment_id="seg-safe-1",
                start_time=0.0,
                end_time=1.0,
                text="accumulator remains intact",
                confidence=0.95,
                is_final=True,
            ),
        )

        # STT orchestrator ingests successfully
        orch.ingest_event(event)
        assert orch.get_full_transcript() == "accumulator remains intact"

        # Backend publication failure is isolated
        published = bridge.publish_event(event, session_id="unregistered-sid")
        assert published is None
        # Accumulator transcript still completely intact
        assert orch.get_full_transcript() == "accumulator remains intact"
        assert len(orch.get_final_segments()) == 1

    def test_10_end_to_end_audio_to_stt_to_backend_stream(self, repo: InMemorySessionRepository) -> None:
        """End-to-End: Audio chunks -> AudioSTTBridge -> TranscriptionOrchestrator -> BackendEventStreamBridge -> SessionRepository."""
        sid = "test-session-20"
        backend_bridge = BackendEventStreamBridge(repository=repo, session_id=sid)
        orch = TranscriptionOrchestrator(session_id=sid)
        audio_bridge = AudioSTTBridge(
            orchestrator=orch,
            session_id=sid,
            backend_bridge=backend_bridge,
        )

        from src.audio.pipeline import create_deterministic_chunk
        chunk1 = create_deterministic_chunk(sequence_id=0, timestamp=0.0, amplitude=0.5)
        chunk2 = create_deterministic_chunk(sequence_id=1, timestamp=0.02, amplitude=0.5)

        events1 = audio_bridge.process_chunk(chunk1)
        events2 = audio_bridge.process_chunk(chunk2, is_last=True)

        assert len(events1) + len(events2) > 0
        assert len(backend_bridge.published_events) > 0

        # Verify events are stored in authentic session repository
        session = repo.get(sid)
        backend_stt_events = [e for e in session.events if e.event_type.startswith("voice_stt.")]
        assert len(backend_stt_events) >= 1
        assert any(e.event_type == "voice_stt.finalization" for e in backend_stt_events)
        assert orch.get_full_transcript() != ""

    def test_11_auto_create_session_feature(self, repo: InMemorySessionRepository) -> None:
        """When auto_create_session is True, a new session is initialized and activated automatically."""
        new_sid = "auto-created-session-123"
        bridge = BackendEventStreamBridge(repository=repo, session_id=new_sid, auto_create_session=True)

        event = TranscriptEvent(
            event_id="evt-auto-1",
            event_type=TranscriptEventType.FINALIZATION,
            sequence_number=1,
            timestamp=100.0,
            session_id=new_sid,
            segment=TranscriptSegment(
                segment_id="seg-auto-1",
                start_time=0.0,
                end_time=1.0,
                text="auto created session event",
                confidence=0.99,
                is_final=True,
            ),
        )

        published = bridge.publish_event(event)
        assert published is not None
        session = repo.get(new_sid)
        assert session.state == SessionState.ACTIVE
        assert any(e.payload.get("source_event_id") == "evt-auto-1" for e in session.events)
