"""Week 2 Day 9: End-to-End Transcription Flow Verification Tests.

Verifies:
1. AudioChunk ingestion into TranscriptionOrchestrator.
2. Provider-neutral adapter delegation and event generation.
3. Deterministic fake transcriber output validity.
4. Ingestion of every event into OrderedSegmentAccumulator.
5. Accurate retrieval of full and committed transcripts.
6. Multi-chunk sequential streaming.
7. Offline mock-mode execution with zero external dependencies.
8. Cross-workstream integration with W1 AudioChunker.
9. Canonical fixture replaying and error recovery.
"""

from typing import List
import pytest

from src.audio.chunker import AudioChunker
from src.schemas.audio import AudioChunk, AudioFormat
from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.adapter import STTAdapterState
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.orchestrator import TranscriptionOrchestrator
from voice_stt.schemas import (
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


class TestDay9EndToEndTranscriptionFlow:
    """End-to-End verification test suite for Day 9."""

    def test_e2e_single_chunk_entry_and_event_generation(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Task 1-3: Verify AudioChunk enters orchestrator, adapter transcribes, events conform."""
        orchestrator = TranscriptionOrchestrator()
        orchestrator.initialize(session_id="day9-single-test")

        chunk = AudioChunk(
            sequence_id=0,
            timestamp=0.0,
            data=sample_audio_bytes,
            format=AudioFormat(sample_rate=16000),
            metadata={"duration_ms": 100.0, "is_last": False},
        )

        events = orchestrator.process_chunk(chunk)
        assert isinstance(events, list)
        assert len(events) >= 1

        for event in events:
            assert isinstance(event, TranscriptEvent)
            assert event.session_id == "day9-single-test"
            assert event.event_id is not None
            assert event.timestamp >= 0.0
            assert event.event_type in (
                TranscriptEventType.INTERIM,
                TranscriptEventType.FINAL,
                TranscriptEventType.STREAM_COMPLETED,
            )

    def test_e2e_events_ingested_and_transcript_retrieved(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Task 4-5: Verify every event enters accumulator and final transcript is retrieved."""
        target_script = ["Single sentence completion test."]
        adapter = DeterministicFakeTranscriber(script=target_script, seed=42)
        orchestrator = TranscriptionOrchestrator(adapter=adapter)

        with orchestrator:
            # 4 words in script -> 4 chunks to finalize sentence
            for i in range(4):
                chunk = AudioChunk(
                    sequence_id=i,
                    timestamp=i * 0.1,
                    data=sample_audio_bytes,
                    metadata={"duration_ms": 100.0, "is_last": (i == 3)},
                )
                orchestrator.process_chunk(chunk, is_last=(i == 3))

            # Retrieve final transcript through orchestrator methods
            transcript = orchestrator.get_transcript()
            full_transcript = orchestrator.get_full_transcript()
            assert transcript == "Single sentence completion test."
            assert full_transcript == transcript

            # Verify committed segments
            segments = orchestrator.get_final_segments()
            assert len(segments) == 1
            assert segments[0].text == "Single sentence completion test."
            assert segments[0].is_final is True
            assert segments[0].confidence > 0.90
            assert orchestrator.get_interim_segment() is None

    def test_e2e_multiple_chunks_sequential_streaming(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Task 6: Test processing multiple audio chunks in sequence with interim evolution."""
        target_script = [
            "Why is this application failing?",
            "Explain the methodology shown here.",
        ]
        adapter = DeterministicFakeTranscriber(script=target_script, seed=42)
        orchestrator = TranscriptionOrchestrator(adapter=adapter)

        with orchestrator:
            # First sentence: 5 tokens -> 5 chunks
            # Second sentence: 5 tokens -> 5 chunks
            total_chunks = 10
            observed_interims: List[str] = []

            for i in range(total_chunks):
                is_last_chunk = (i == total_chunks - 1)
                chunk = AudioChunk(
                    sequence_id=i,
                    timestamp=i * 0.1,
                    data=sample_audio_bytes,
                    metadata={"duration_ms": 100.0, "is_last": is_last_chunk},
                )
                events = orchestrator.process_chunk(chunk, is_last=is_last_chunk)

                for ev in events:
                    if ev.event_type == TranscriptEventType.INTERIM and ev.segment:
                        observed_interims.append(ev.segment.text)

            # Reconstructed full transcript contains both sentences
            expected = "Why is this application failing? Explain the methodology shown here."
            assert orchestrator.get_full_transcript() == expected

            final_segs = orchestrator.get_final_segments()
            assert len(final_segs) == 2
            assert final_segs[0].text == "Why is this application failing?"
            assert final_segs[1].text == "Explain the methodology shown here."

            # Verify chronological audio timestamps
            assert final_segs[0].start_time < final_segs[0].end_time
            assert final_segs[0].end_time <= final_segs[1].start_time
            assert final_segs[1].start_time < final_segs[1].end_time

            # Interims were observed in-flight
            assert len(observed_interims) > 0

    def test_e2e_mock_mode_zero_external_dependencies(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Task 7: Verify mock mode works without real providers, API keys, or network."""
        # Run identical sequence across two independent orchestrator instances
        script = ["Strict reproducibility check across instances."]

        orch1 = TranscriptionOrchestrator(adapter=DeterministicFakeTranscriber(script=script, seed=123))
        orch2 = TranscriptionOrchestrator(adapter=DeterministicFakeTranscriber(script=script, seed=123))

        chunks = [
            AudioChunk(
                sequence_id=i,
                timestamp=i * 0.1,
                data=sample_audio_bytes,
                metadata={"duration_ms": 100.0, "is_last": (i == 4)},
            )
            for i in range(5)
        ]

        events1 = list(orch1.process_stream(chunks))
        events2 = list(orch2.process_stream(chunks))

        assert len(events1) == len(events2)
        for e1, e2 in zip(events1, events2):
            assert e1.event_id == e2.event_id
            assert e1.event_type == e2.event_type
            assert e1.timestamp == e2.timestamp
            if e1.segment and e2.segment:
                assert e1.segment.text == e2.segment.text
                assert e1.segment.confidence == e2.segment.confidence

        assert orch1.get_full_transcript() == orch2.get_full_transcript()
        assert orch1.get_full_transcript() == "Strict reproducibility check across instances."

    def test_e2e_integration_with_w1_audio_chunker(self) -> None:
        """Task 8: Verify cross-workstream pipeline: W1 AudioChunker -> W2 TranscriptionOrchestrator."""
        # 800ms of 16kHz mono PCM16 audio = 16000 * 2 * 0.8 = 25600 bytes
        raw_pcm_audio = b"\x00\x02\x00\x04" * 6400

        chunker = AudioChunker(audio_format=AudioFormat(sample_rate=16000), chunk_duration_ms=100.0)
        chunks_from_chunker = chunker.chunk_all(raw_pcm_audio)
        assert len(chunks_from_chunker) == 8

        # Stream chunker output directly through orchestrator
        orchestrator = TranscriptionOrchestrator()
        with orchestrator:
            all_events: List[TranscriptEvent] = []
            for idx, chk in enumerate(chunks_from_chunker):
                is_last = (idx == len(chunks_from_chunker) - 1)
                evts = orchestrator.process_chunk(chk, is_last=is_last)
                all_events.extend(evts)

            assert len(all_events) > 0
            # Final transcript was populated
            assert len(orchestrator.get_full_transcript()) > 0
            assert len(orchestrator.get_final_segments()) >= 1

    def test_e2e_fixture_replay_verification(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Task 8: Verify canonical demonstration fixtures A and B through orchestrator."""
        for fix_id in ("A", "B"):
            adapter = DeterministicFakeTranscriber.from_fixture(fix_id, seed=42)
            orch = TranscriptionOrchestrator(adapter=adapter)

            with orch:
                num_chunks = len(adapter.fixture.events) + 1
                for i in range(num_chunks):
                    chunk = AudioChunk(
                        sequence_id=i,
                        timestamp=i * 0.1,
                        data=sample_audio_bytes,
                        metadata={"duration_ms": 100.0, "is_last": (i == num_chunks - 1)},
                    )
                    orch.process_chunk(chunk)

                final_text = orch.get_full_transcript()
                if fix_id == "A":
                    assert "why is this application showing this error" in final_text.lower()
                elif fix_id == "B":
                    assert "explain the methodology shown on this page" in final_text.lower()

    def test_e2e_error_recovery_and_telemetry_diagnostics(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Task 8: Verify non-destructive error handling, telemetry summary, and session reset recovery."""
        target_script = ["First sentence committed.", "Second sentence error."]
        # Inject error at chunk 4 (during second sentence)
        transcriber = DeterministicFakeTranscriber(
            script=target_script,
            seed=42,
            inject_error_at_chunk=4,
        )
        orch = TranscriptionOrchestrator(adapter=transcriber)

        with orch:
            # Process chunks 0..3 (first sentence completes at chunk 2)
            for i in range(4):
                chunk = AudioChunk(
                    sequence_id=i,
                    timestamp=i * 0.1,
                    data=sample_audio_bytes,
                    metadata={"duration_ms": 100.0, "is_last": False},
                )
                orch.process_chunk(chunk, is_last=False)

            assert "First sentence committed." in orch.get_full_transcript()

            # Now feed chunk 4 which triggers error injection
            err_chunk = AudioChunk(
                sequence_id=4,
                timestamp=0.4,
                data=sample_audio_bytes,
                metadata={"duration_ms": 100.0, "is_last": False},
            )
            err_events = orch.process_chunk(err_chunk, is_last=False)
            assert len(err_events) == 1
            assert err_events[0].event_type == TranscriptEventType.ERROR
            assert orch.state == STTAdapterState.ERROR

            # Non-destructive check: committed segment from sentence 1 remains intact
            assert "First sentence committed." in orch.get_full_transcript()

            # Inspect combined telemetry summary
            summary = orch.get_summary()
            assert summary["adapter_state"] == "error"
            assert summary["chunks_processed"] == 5
            assert summary["events_emitted"] > 0
            assert summary["final_segments_count"] == 1

            # Recovery: reset orchestrator to ready
            orch.reset()
            assert orch.get_full_transcript() == ""
            assert len(orch.get_final_segments()) == 0

            # Fresh session operates normally
            orch.initialize(session_id="recovery-session")
            assert orch.state == STTAdapterState.READY

    def test_e2e_raw_bytes_stream_pipeline(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Task 6: Verify streaming raw bytes slices directly through orchestrator without pre-wrapping."""
        target_script = ["Raw audio stream processing."]
        adapter = DeterministicFakeTranscriber(script=target_script, seed=42)
        orch = TranscriptionOrchestrator(adapter=adapter)

        with orch:
            # Provide raw bytes iterable
            raw_slices = [sample_audio_bytes for _ in range(4)]
            events = list(orch.process_stream(raw_slices))

            assert len(events) > 0
            assert orch.get_full_transcript() == "Raw audio stream processing."
            assert len(orch.get_final_segments()) == 1

    def test_e2e_late_interim_discard_invariant(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Task 8: Verify late interim hypotheses cannot corrupt already-committed final segments."""
        target_script = ["Committed segment."]
        adapter = DeterministicFakeTranscriber(script=target_script, seed=42)
        orch = TranscriptionOrchestrator(adapter=adapter)

        with orch:
            for i in range(3):
                chunk = AudioChunk(
                    sequence_id=i,
                    timestamp=i * 0.1,
                    data=sample_audio_bytes,
                    metadata={"duration_ms": 100.0, "is_last": (i == 2)},
                )
                orch.process_chunk(chunk, is_last=(i == 2))

            assert orch.get_full_transcript() == "Committed segment."
            assert len(orch.get_final_segments()) == 1

            # Manually construct a late interim event arriving after finalization
            late_segment = TranscriptSegment(
                segment_id="late-seg-001",
                text="Stale late text",
                start_time=0.0,
                end_time=0.1,
                confidence=0.5,
                is_final=False,
            )
            late_event = TranscriptEvent(
                event_id="late-evt-001",
                event_type=TranscriptEventType.INTERIM,
                sequence_number=999,
                timestamp=0.1,
                session_id=orch.session_id,
                segment=late_segment,
            )

            # Ingest late interim into orchestrator's accumulator
            orch.accumulator.ingest_event(late_event)

            # Committed transcript is preserved without corruption
            assert orch.get_full_transcript() == "Committed segment."
            assert orch.get_interim_segment() is None

    def test_e2e_diagnostics_and_confidence_metrics(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Task 8: Verify orchestrator exposes average confidence, total duration, and complete summary."""
        target_script = ["Metric calculation test."]
        adapter = DeterministicFakeTranscriber(script=target_script, seed=42)
        orch = TranscriptionOrchestrator(adapter=adapter)

        with orch:
            for i in range(3):
                chunk = AudioChunk(
                    sequence_id=i,
                    timestamp=i * 0.1,
                    data=sample_audio_bytes,
                    metadata={"duration_ms": 100.0, "is_last": (i == 2)},
                )
                orch.process_chunk(chunk, is_last=(i == 2))

            assert orch.get_average_confidence() > 0.90
            assert orch.get_total_duration() > 0.0

            summary = orch.get_summary()
            assert summary["session_id"] == orch.session_id
            assert summary["final_segments_count"] == 1
            assert summary["is_verified"] is True
            assert summary["total_duration_seconds"] > 0.0
