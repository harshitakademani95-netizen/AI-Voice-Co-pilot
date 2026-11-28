"""Unit and integration tests for Week 2 Day 8 Transcription Orchestrator."""

from typing import List
import pytest

from src.schemas.audio import AudioFormat
from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.adapter import STTAdapterState
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.orchestrator import TranscriptionOrchestrator
from voice_stt.schemas import (
    AudioChunk,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


class TestTranscriptionOrchestrator:
    """Verifies Day 8 TranscriptionOrchestrator coordination contract."""

    def test_default_initialization_uses_mock_transcriber(self) -> None:
        """Verify orchestrator defaults to DeterministicFakeTranscriber without API keys."""
        orch = TranscriptionOrchestrator()
        assert isinstance(orch.adapter, DeterministicFakeTranscriber)
        assert isinstance(orch.accumulator, OrderedSegmentAccumulator)
        assert orch.session_id.startswith("orch-session-")

        orch.initialize()
        assert orch.state == STTAdapterState.READY

    def test_custom_adapter_and_session_id_injection(self) -> None:
        """Verify orchestrator accepts dependency-injected adapter, accumulator, and session ID."""
        custom_adapter = DeterministicFakeTranscriber(script=["Custom injected script."])
        custom_acc = OrderedSegmentAccumulator()
        orch = TranscriptionOrchestrator(
            adapter=custom_adapter,
            accumulator=custom_acc,
            session_id="custom-session-123",
        )
        assert orch.adapter is custom_adapter
        assert orch.accumulator is custom_acc
        assert orch.session_id == "custom-session-123"

    def test_single_audio_chunk_produces_valid_transcript_events(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Test that an existing AudioChunk passes through orchestrator and yields valid TranscriptEvents."""
        orch = TranscriptionOrchestrator()
        orch.initialize(session_id="test-single-chunk")

        chunk = AudioChunk(
            sequence_id=0,
            timestamp=0.0,
            data=sample_audio_bytes,
            format=AudioFormat(sample_rate=16000),
            metadata={"duration_ms": 100.0, "is_last": False},
        )

        events = orch.process_chunk(chunk)
        assert isinstance(events, list)
        for event in events:
            assert isinstance(event, TranscriptEvent)
            assert event.session_id == "test-single-chunk"
            assert event.event_type in (
                TranscriptEventType.INTERIM,
                TranscriptEventType.FINAL,
                TranscriptEventType.STREAM_COMPLETED,
            )

    def test_multi_chunk_scripted_orchestration_flow(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Test streaming multiple chunks through orchestrator and verifying accumulator integration."""
        target_script = ["Explain technical error in terminal."]
        transcriber = DeterministicFakeTranscriber(script=target_script, seed=42)
        orch = TranscriptionOrchestrator(adapter=transcriber)

        with orch:
            all_events: List[TranscriptEvent] = []
            for i in range(5):
                chunk = AudioChunk(
                    sequence_id=i,
                    timestamp=i * 0.1,
                    data=sample_audio_bytes,
                    metadata={"duration_ms": 100.0, "is_last": (i == 4)},
                )
                events = orch.process_chunk(chunk, is_last=(i == 4))
                all_events.extend(events)

            assert len(all_events) > 0
            # Accumulator has collected the final segment
            final_segments = orch.get_final_segments()
            assert len(final_segments) == 1
            assert final_segments[0].text == "Explain technical error in terminal."
            assert orch.get_full_transcript() == "Explain technical error in terminal."

    def test_raw_audio_bytes_ingestion(self, sample_audio_bytes: bytes) -> None:
        """Verify orchestrator accepts raw audio bytes and normalizes them through adapter."""
        orch = TranscriptionOrchestrator()
        with orch:
            events = orch.process_chunk(sample_audio_bytes, is_last=True)
            assert isinstance(events, list)
            assert len(events) > 0
            assert all(isinstance(e, TranscriptEvent) for e in events)

    def test_stream_processing_generator(self, sample_audio_bytes: bytes) -> None:
        """Verify process_stream consumes an iterable of chunks and yields events sequentially."""
        transcriber = DeterministicFakeTranscriber(script=["Stream test sentence."])
        orch = TranscriptionOrchestrator(adapter=transcriber)

        chunks = [
            AudioChunk(
                sequence_id=i,
                timestamp=i * 0.1,
                data=sample_audio_bytes,
                metadata={"duration_ms": 100.0, "is_last": (i == 3)},
            )
            for i in range(4)
        ]

        yielded_events = list(orch.process_stream(chunks))
        assert len(yielded_events) > 0
        assert orch.get_full_transcript() == "Stream test sentence."

    def test_reset_clears_adapter_and_accumulator_state(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Verify reset resets both adapter and accumulator for a fresh session."""
        transcriber = DeterministicFakeTranscriber(script=["Reset."])
        orch = TranscriptionOrchestrator(adapter=transcriber)

        with orch:
            chunk = AudioChunk(
                sequence_id=0,
                timestamp=0.0,
                data=sample_audio_bytes,
                metadata={"duration_ms": 100.0, "is_last": True},
            )
            orch.process_chunk(chunk, is_last=True)
            assert orch.get_full_transcript() == "Reset."

            orch.reset()
            assert orch.get_full_transcript() == ""
            assert len(orch.get_final_segments()) == 0
            assert orch.get_interim_segment() is None

    def test_context_manager_and_closed_guard(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Verify context manager initializes on entry and closes on exit, guarding closed state."""
        orch = TranscriptionOrchestrator()
        assert orch.state == STTAdapterState.UNINITIALIZED

        with orch as active_orch:
            assert active_orch.state == STTAdapterState.READY

        assert orch.state == STTAdapterState.CLOSED

        with pytest.raises(RuntimeError, match="Cannot process audio on a closed"):
            orch.process_chunk(sample_audio_bytes)

    def test_error_event_propagation(self, sample_audio_bytes: bytes) -> None:
        """Verify adapter error injection produces an error event without crashing orchestrator."""
        failing_transcriber = DeterministicFakeTranscriber(inject_error_at_chunk=0)
        orch = TranscriptionOrchestrator(adapter=failing_transcriber)

        with orch:
            chunk = AudioChunk(
                sequence_id=0,
                timestamp=0.0,
                data=sample_audio_bytes,
                metadata={"duration_ms": 100.0, "is_last": False},
            )
            events = orch.process_chunk(chunk)
            assert len(events) == 1
            assert events[0].event_type == TranscriptEventType.ERROR
            assert events[0].error is not None
            assert orch.state == STTAdapterState.ERROR

    def test_fixture_replay_orchestration(self, sample_audio_bytes: bytes) -> None:
        """Verify orchestrator correctly replays canonical demonstration fixture A."""
        transcriber = DeterministicFakeTranscriber.from_fixture("A")
        orch = TranscriptionOrchestrator(adapter=transcriber)

        with orch:
            for i in range(len(transcriber.fixture.events) + 1):
                chunk = AudioChunk(
                    sequence_id=i,
                    timestamp=i * 0.1,
                    data=sample_audio_bytes,
                    metadata={"duration_ms": 100.0, "is_last": (i == len(transcriber.fixture.events))},
                )
                orch.process_chunk(chunk)

            final_text = orch.get_full_transcript()
            assert "why is this application showing this error" in final_text.lower()
