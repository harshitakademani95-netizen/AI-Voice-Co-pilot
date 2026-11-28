"""Week 3 Day 19: Audio-to-STT Pipeline Integration Tests.

Covers:
1. Audio chunk successfully reaches STT orchestrator.
2. Session ID is preserved from audio input to transcript output.
3. Correct chronological ordering of audio chunks and timestamps.
4. Out-of-order audio chunks handling.
5. Missing audio chunks handling without corrupting order.
6. Duplicate audio event suppression.
7. Stream completion / End-of-stream behavior.
8. Cancellation during audio processing stops audio pipeline and orchestrator.
9. Late audio chunks rejected after cancellation.
10. Mock-mode end-to-end integration with zero external dependencies.
"""

from typing import List
import pytest

from src.audio.device import MockAudioDevice, AudioPermissionState
from src.audio.pipeline import AudioPipeline, create_deterministic_chunk, generate_speech_fixture
from src.audio.vad import VADConfig, VADEvent, VADEventType
from src.schemas.audio import AudioChunk, AudioFormat
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.integration import AudioSTTBridge
from voice_stt.orchestrator import TranscriptionOrchestrator
from voice_stt.schemas import TranscriptEvent, TranscriptEventType


class TestDay19AudioSTTIntegration:
    """Test suite for Day 19 Audio-to-STT integration."""

    def test_01_audio_chunk_successfully_reaches_stt(self) -> None:
        transcriber = DeterministicFakeTranscriber()
        orch = TranscriptionOrchestrator(adapter=transcriber, session_id="audio-stt-test-1")
        pipeline = AudioPipeline()
        bridge = AudioSTTBridge(orchestrator=orch, pipeline=pipeline, session_id="audio-stt-test-1")

        chunk = create_deterministic_chunk(sequence_id=0, timestamp=0.0, amplitude=0.5, duration_ms=20.0)
        events = bridge.process_chunk(chunk, is_last=True)

        assert len(events) >= 1
        assert bridge.chunks_processed == 1
        assert orch.get_full_transcript() != ""

    def test_02_session_id_preserved_from_audio_to_transcript(self) -> None:
        custom_sid = "custom-audio-session-987"
        transcriber = DeterministicFakeTranscriber()
        orch = TranscriptionOrchestrator(adapter=transcriber, session_id=custom_sid)
        bridge = AudioSTTBridge(orchestrator=orch, session_id=custom_sid)

        chunk = create_deterministic_chunk(sequence_id=0, timestamp=0.0, amplitude=0.5)
        chunk.metadata["session_id"] = custom_sid

        events = bridge.process_chunk(chunk, is_last=True)
        assert len(events) > 0
        for event in events:
            assert event.session_id == custom_sid
        assert orch.session_id == custom_sid

    def test_03_correct_ordering_of_audio_chunks(self) -> None:
        orch = TranscriptionOrchestrator(session_id="order-test")
        bridge = AudioSTTBridge(orchestrator=orch, session_id="order-test")

        chunks = [
            create_deterministic_chunk(sequence_id=i, timestamp=i * 0.02, amplitude=0.5)
            for i in range(5)
        ]

        all_events = list(bridge.process_stream(chunks))
        assert len(all_events) > 0
        final_segments = orch.get_final_segments()
        assert len(final_segments) > 0
        for i in range(len(final_segments) - 1):
            assert final_segments[i].start_time <= final_segments[i + 1].start_time

    def test_04_out_of_order_audio_chunks_handled_safely(self) -> None:
        orch = TranscriptionOrchestrator(session_id="ooo-test")
        bridge = AudioSTTBridge(orchestrator=orch, session_id="ooo-test")

        chunks = [
            create_deterministic_chunk(sequence_id=0, timestamp=0.0, amplitude=0.5),
            create_deterministic_chunk(sequence_id=2, timestamp=0.04, amplitude=0.5),
            create_deterministic_chunk(sequence_id=1, timestamp=0.02, amplitude=0.5),
        ]

        for i, chk in enumerate(chunks):
            is_last = (i == len(chunks) - 1)
            bridge.process_chunk(chk, is_last=is_last)

        # Transcripts must remain chronologically ordered in accumulator
        final_segments = orch.get_final_segments()
        for i in range(len(final_segments) - 1):
            assert final_segments[i].start_time <= final_segments[i + 1].start_time

    def test_05_missing_chunks_handled_without_corrupting_order(self) -> None:
        orch = TranscriptionOrchestrator(session_id="missing-chunks-test")
        bridge = AudioSTTBridge(orchestrator=orch, session_id="missing-chunks-test")

        # Gap between seq 0 and seq 5
        chunk_0 = create_deterministic_chunk(sequence_id=0, timestamp=0.0, amplitude=0.5)
        chunk_5 = create_deterministic_chunk(sequence_id=5, timestamp=0.10, amplitude=0.5)

        bridge.process_chunk(chunk_0)
        bridge.process_chunk(chunk_5, is_last=True)

        assert bridge.chunks_processed == 2
        assert len(orch.get_final_segments()) > 0

    def test_06_duplicate_audio_chunk_suppression(self) -> None:
        orch = TranscriptionOrchestrator(session_id="dup-audio-test")
        bridge = AudioSTTBridge(orchestrator=orch, session_id="dup-audio-test")

        chunk = create_deterministic_chunk(sequence_id=42, timestamp=0.84, amplitude=0.5)

        events_first = bridge.process_chunk(chunk)
        events_second = bridge.process_chunk(chunk)

        assert len(events_first) > 0
        assert len(events_second) == 0  # Duplicate suppressed
        assert bridge.chunks_processed == 1

    def test_07_stream_completion_and_vad_speech_end(self) -> None:
        orch = TranscriptionOrchestrator(session_id="vad-completion-test")
        bridge = AudioSTTBridge(orchestrator=orch, session_id="vad-completion-test")

        chunk = create_deterministic_chunk(sequence_id=0, timestamp=0.0, amplitude=0.5)
        vad_end = VADEvent(
            event_type=VADEventType.SPEECH_END,
            timestamp=0.02,
            duration_ms=20.0,
            energy=0.05,
            speech_probability=0.2,
            is_speech=False,
            chunk_sequence_id=0,
        )

        events = bridge.process_chunk(chunk, vad_event=vad_end)
        assert len(events) > 0
        assert any(e.event_type in (TranscriptEventType.FINAL, TranscriptEventType.FINALIZATION) for e in events)

    def test_08_cancellation_during_audio_processing(self) -> None:
        pipeline = AudioPipeline()
        orch = TranscriptionOrchestrator(session_id="cancel-audio-test")
        bridge = AudioSTTBridge(orchestrator=orch, pipeline=pipeline, session_id="cancel-audio-test")

        bridge.start()
        assert bridge.is_cancelled is False

        bridge.cancel()
        assert bridge.is_cancelled is True
        assert orch.is_cancelled is True

        chunk = create_deterministic_chunk(sequence_id=1, timestamp=0.02)
        events = bridge.process_chunk(chunk)
        assert len(events) == 0

    def test_09_late_audio_events_rejected_after_cancellation(self) -> None:
        orch = TranscriptionOrchestrator(session_id="late-audio-cancel")
        bridge = AudioSTTBridge(orchestrator=orch, session_id="late-audio-cancel")

        bridge.cancel()

        chunks = [create_deterministic_chunk(sequence_id=i, timestamp=i * 0.02) for i in range(3)]
        stream_events = list(bridge.process_stream(chunks))
        assert len(stream_events) == 0
        assert orch.get_full_transcript() == ""

    def test_10_mock_mode_audio_pipeline_to_stt_end_to_end(self) -> None:
        """Verify authentic AudioPipeline feeds directly through AudioSTTBridge without external hardware."""
        pipeline = AudioPipeline()
        orch = TranscriptionOrchestrator(session_id="e2e-pipeline-test")
        bridge = AudioSTTBridge(orchestrator=orch, pipeline=pipeline, session_id="e2e-pipeline-test")

        bridge.start()
        # Step through 5 pipeline iterations
        all_events: List[TranscriptEvent] = []
        for _ in range(5):
            res = bridge.process_step()
            if res is not None:
                _, evts = res
                all_events.extend(evts)

        summary = bridge.get_summary()
        assert summary["bridge_chunks_processed"] >= 1
        assert "pipeline_status" in summary
        bridge.stop()
