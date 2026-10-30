"""Unit tests verifying provider-neutral adapter and deterministic fake transcriber."""

from typing import List
import pytest

from voice_stt.adapter import (
    BaseSTTAdapter,
    STTAdapterConfig,
    STTAdapterState,
)
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.schemas import (
    AudioChunk,
    STTErrorDetail,
    TranscriptEvent,
    TranscriptEventType,
)


class TestAdapterInterfaceContract:
    """Verifies that BaseSTTAdapter interface rules are strictly respected."""

    def test_abstract_class_cannot_be_instantiated(self) -> None:
        with pytest.raises(TypeError):
            BaseSTTAdapter()  # type: ignore[abstract]

    def test_context_manager_lifecycle(self) -> None:
        adapter = DeterministicFakeTranscriber()
        assert adapter.state == STTAdapterState.UNINITIALIZED

        with adapter as active_adapter:
            assert active_adapter.state == STTAdapterState.READY
            assert active_adapter.session_id is not None

        assert adapter.state == STTAdapterState.CLOSED

    def test_transcribe_on_closed_adapter_fails(self, sample_audio_bytes: bytes) -> None:
        adapter = DeterministicFakeTranscriber()
        adapter.initialize()
        adapter.close()
        with pytest.raises(RuntimeError) as exc_info:
            adapter.transcribe_chunk(sample_audio_bytes)
        assert "closed STT adapter" in str(exc_info.value)

    def test_status_telemetry_reporting(self, sample_audio_bytes: bytes) -> None:
        adapter = DeterministicFakeTranscriber()
        adapter.initialize(session_id="test-session-001")
        assert adapter.get_status().chunks_processed == 0
        assert adapter.get_status().events_emitted == 0
        assert adapter.get_status().active_session_id == "test-session-001"

        adapter.transcribe_chunk(sample_audio_bytes)
        status = adapter.get_status()
        assert status.chunks_processed == 1
        assert status.events_emitted >= 1


class TestDeterministicFakeTranscriber:
    """Tests guaranteeing strict determinism and behavior of the fake transcriber."""

    def test_determinism_scripted_mode(self, sample_audio_chunks: List[AudioChunk]) -> None:
        """Crucial Acceptance Criteria: Identical input -> Identical transcript events."""
        script = ["Explain this technical error in code."]
        seed = 101

        # Run 1
        t1 = DeterministicFakeTranscriber(script=script, seed=seed)
        t1.initialize()
        events_run_1: List[TranscriptEvent] = []
        for chunk in sample_audio_chunks:
            events_run_1.extend(t1.transcribe_chunk(chunk))

        # Run 2
        t2 = DeterministicFakeTranscriber(script=script, seed=seed)
        t2.initialize()
        events_run_2: List[TranscriptEvent] = []
        for chunk in sample_audio_chunks:
            events_run_2.extend(t2.transcribe_chunk(chunk))

        # Compare length
        assert len(events_run_1) == len(events_run_2)
        assert len(events_run_1) > 0

        # Compare field-by-field equality
        for e1, e2 in zip(events_run_1, events_run_2):
            assert e1.event_id == e2.event_id
            assert e1.event_type == e2.event_type
            assert e1.sequence_number == e2.sequence_number
            assert e1.timestamp == pytest.approx(e2.timestamp)
            if e1.event_type == TranscriptEventType.STREAM_COMPLETED:
                assert e1.segment is None and e2.segment is None
            else:
                assert e1.segment is not None and e2.segment is not None
                assert e1.segment.segment_id == e2.segment.segment_id
                assert e1.segment.text == e2.segment.text
                assert e1.segment.confidence == pytest.approx(e2.segment.confidence)
                assert e1.segment.is_final == e2.segment.is_final
                assert e1.segment.start_time == pytest.approx(e2.segment.start_time)
                assert e1.segment.end_time == pytest.approx(e2.segment.end_time)

    def test_determinism_hash_mode(self, sample_audio_chunks: List[AudioChunk]) -> None:
        """Verify hash-generative mode produces identical events across runs with same chunks."""
        seed = 42

        # Run 1
        t1 = DeterministicFakeTranscriber(seed=seed)
        t1.initialize()
        events_1 = list(t1.transcribe_stream(sample_audio_chunks))

        # Run 2
        t2 = DeterministicFakeTranscriber(seed=seed)
        t2.initialize()
        events_2 = list(t2.transcribe_stream(sample_audio_chunks))

        assert len(events_1) == len(events_2)
        assert [e.model_dump() for e in events_1] == [e.model_dump() for e in events_2]

    def test_reset_yields_identical_subsequent_sequence(
        self, sample_audio_chunks: List[AudioChunk]
    ) -> None:
        """Resetting the same transcriber instance reproduces identical events."""
        transcriber = DeterministicFakeTranscriber(script=["Why is this failing?"], seed=777)
        transcriber.initialize()

        first_pass = [e.model_dump() for e in transcriber.transcribe_stream(sample_audio_chunks)]
        transcriber.reset()
        second_pass = [e.model_dump() for e in transcriber.transcribe_stream(sample_audio_chunks)]

        assert first_pass == second_pass

    def test_simulated_error_injection(self, sample_audio_chunks: List[AudioChunk]) -> None:
        """Verify that simulated error injection produces standardized STT error event."""
        custom_error = STTErrorDetail(
            code="NETWORK_TIMEOUT_MOCK",
            message="Mock network timeout for testing recovery.",
            retryable=True,
        )
        transcriber = DeterministicFakeTranscriber(
            inject_error_at_chunk=2,
            error_detail=custom_error,
        )
        transcriber.initialize()

        # Chunk 0: normal
        evts_0 = transcriber.transcribe_chunk(sample_audio_chunks[0])
        assert len(evts_0) >= 0

        # Chunk 1: normal
        evts_1 = transcriber.transcribe_chunk(sample_audio_chunks[1])
        assert len(evts_1) >= 0

        # Chunk 2: triggered error
        evts_2 = transcriber.transcribe_chunk(sample_audio_chunks[2])
        assert len(evts_2) == 1
        err_evt = evts_2[0]
        assert err_evt.event_type == TranscriptEventType.ERROR
        assert err_evt.error is not None
        assert err_evt.error.code == "NETWORK_TIMEOUT_MOCK"
        assert transcriber.state == STTAdapterState.ERROR

    def test_interim_flag_configuration_disabled(
        self, sample_audio_chunks: List[AudioChunk]
    ) -> None:
        """When interim_results=False, only final events should be emitted."""
        config = STTAdapterConfig(interim_results=False)
        transcriber = DeterministicFakeTranscriber(
            config=config, script=["Check PDF and summarize."]
        )
        transcriber.initialize()

        all_events = list(transcriber.transcribe_stream(sample_audio_chunks))
        for evt in all_events:
            assert evt.event_type != TranscriptEventType.INTERIM
            if evt.segment:
                assert evt.segment.is_final is True

    def test_is_last_argument_honoured_for_audio_chunk(self) -> None:
        """Verify _coerce_audio_chunk honours is_last=True even when AudioChunk.is_last is False."""
        transcriber = DeterministicFakeTranscriber(script=["Final word here."])
        transcriber.initialize()
        chunk = AudioChunk(
            data=b"\x00\x01" * 800,
            sequence_number=0,
            is_last=False,
        )
        events = transcriber.transcribe_chunk(chunk, is_last=True)
        event_types = [e.event_type for e in events]
        assert TranscriptEventType.FINAL in event_types
        assert TranscriptEventType.STREAM_COMPLETED in event_types

    def test_stream_without_is_last_flushes(self) -> None:
        """Verify transcribe_stream one-item lookahead flushes pending words when stream ends without is_last."""
        transcriber = DeterministicFakeTranscriber(script=["Stream lookahead flush test."])
        transcriber.initialize()
        # All chunks have is_last=False
        chunks = [
            AudioChunk(data=b"\x00\x01" * 800, sequence_number=i, is_last=False)
            for i in range(4)
        ]
        events = list(transcriber.transcribe_stream(chunks))
        assert len(events) > 0
        assert events[-1].event_type == TranscriptEventType.STREAM_COMPLETED
        final_events = [e for e in events if e.event_type == TranscriptEventType.FINAL]
        assert len(final_events) >= 1
        assert "Stream lookahead flush test." in final_events[-1].segment.text

    def test_empty_stream_yields_nothing_and_does_not_raise(self) -> None:
        """Consuming an empty stream yields 0 events and does not raise StopIteration or error."""
        transcriber = DeterministicFakeTranscriber(script=["Never spoken."])
        transcriber.initialize()
        events = list(transcriber.transcribe_stream([]))
        assert events == []

    def test_stream_completed_emitted_exactly_once_and_last(
        self, sample_audio_chunks: List[AudioChunk]
    ) -> None:
        """STREAM_COMPLETED is emitted exactly once, at the very end, with segment=None and error=None."""
        transcriber = DeterministicFakeTranscriber(script=["One short sentence."])
        transcriber.initialize()
        events = list(transcriber.transcribe_stream(sample_audio_chunks))
        completed_events = [e for e in events if e.event_type == TranscriptEventType.STREAM_COMPLETED]
        assert len(completed_events) == 1
        last_event = events[-1]
        assert last_event.event_type == TranscriptEventType.STREAM_COMPLETED
        assert last_event.segment is None
        assert last_event.error is None
        assert last_event.sequence_number == len(events) - 1

    def test_stream_completed_not_emitted_after_injected_error(
        self, sample_audio_chunks: List[AudioChunk]
    ) -> None:
        """When an error is injected, STREAM_COMPLETED is never emitted."""
        transcriber = DeterministicFakeTranscriber(
            script=["Error injection sentence."],
            inject_error_at_chunk=1,
        )
        transcriber.initialize()
        events = []
        for chunk in sample_audio_chunks:
            chunk_events = transcriber.transcribe_chunk(chunk)
            events.extend(chunk_events)
            if transcriber.state == STTAdapterState.ERROR:
                break
        event_types = [e.event_type for e in events]
        assert TranscriptEventType.ERROR in event_types
        assert TranscriptEventType.STREAM_COMPLETED not in event_types


class TestSentenceTimestampSpanRegression:
    """Regression tests verifying multi-chunk sentence time spans and word timing distribution."""

    def test_scripted_multi_chunk_sentence_uses_first_chunk_start_time(self) -> None:
        """A scripted sentence spanning multiple chunks must use the first chunk's start time and last chunk's end time."""
        transcriber = DeterministicFakeTranscriber(
            script=["Why is this application showing this error?"],  # 7 words -> 7 chunks
            seed=42,
        )
        transcriber.initialize()
        chunks = [
            AudioChunk(
                data=b"\x00\x01" * 800,
                sequence_number=i,
                timestamp=i * 0.1,
                duration_ms=100.0,
                is_last=(i == 6),
            )
            for i in range(7)
        ]
        events = list(transcriber.transcribe_stream(chunks))
        final_events = [e for e in events if e.event_type == TranscriptEventType.FINAL]
        assert len(final_events) == 1
        final_seg = final_events[0].segment
        assert final_seg is not None

        # Start time must be 0.0s (first chunk start), NOT 0.6s (last chunk start)
        assert final_seg.start_time == pytest.approx(0.0)
        # End time must correspond to the 7th chunk end time (0.7s)
        assert final_seg.end_time == pytest.approx(0.7)
        assert final_seg.text == "Why is this application showing this error?"

        # Word timestamps check
        words = final_seg.words
        assert len(words) == 7
        assert words[0].word == "Why"
        assert words[0].start_time == pytest.approx(0.0)
        assert words[-1].word == "error?"
        assert words[-1].end_time == pytest.approx(0.7)

        # Word timings remain within the complete sentence interval and are chronologically ordered
        for idx, w in enumerate(words):
            assert w.start_time >= final_seg.start_time - 1e-4
            assert w.end_time <= final_seg.end_time + 1e-4
            assert w.start_time < w.end_time
            if idx > 0:
                assert w.start_time >= words[idx - 1].end_time - 1e-4

    def test_scripted_multi_sentence_fresh_start_timestamp(self) -> None:
        """Sequential sentences must each receive a fresh sentence-start timestamp."""
        transcriber = DeterministicFakeTranscriber(
            script=["Alpha beta.", "Gamma delta epsilon."],  # 2 words then 3 words
            seed=42,
        )
        transcriber.initialize()
        # 5 chunks of 200ms
        chunks = [
            AudioChunk(
                data=b"\x00\x01" * 800,
                sequence_number=i,
                timestamp=i * 0.2,
                duration_ms=200.0,
                is_last=(i == 4),
            )
            for i in range(5)
        ]
        events = list(transcriber.transcribe_stream(chunks))
        final_events = [e for e in events if e.event_type == TranscriptEventType.FINAL]
        assert len(final_events) == 2

        seg1 = final_events[0].segment
        assert seg1 is not None
        assert seg1.text == "Alpha beta."
        assert seg1.start_time == pytest.approx(0.0)
        assert seg1.end_time == pytest.approx(0.4)  # chunks 0, 1 (0.0 to 0.4)
        assert seg1.words[0].start_time == pytest.approx(0.0)
        assert seg1.words[-1].end_time == pytest.approx(0.4)

        seg2 = final_events[1].segment
        assert seg2 is not None
        assert seg2.text == "Gamma delta epsilon."
        # Second sentence must start at 0.4s (chunk 2 start), NOT 0.0s!
        assert seg2.start_time == pytest.approx(0.4)
        assert seg2.end_time == pytest.approx(1.0)  # chunks 2, 3, 4 (0.4 to 1.0)
        assert seg2.words[0].start_time == pytest.approx(0.4)
        assert seg2.words[-1].end_time == pytest.approx(1.0)

    def test_hash_mode_multi_chunk_sentence_and_word_timings(self) -> None:
        """Hash mode generates final segments spanning multiple chunks with proper start_time and word timings."""
        transcriber = DeterministicFakeTranscriber(seed=42)
        transcriber.initialize()
        # Feed 6 chunks of 150ms: creates two 3-word sentences
        chunks = [
            AudioChunk(
                data=b"\x12\x34" * (i + 1) * 200,
                sequence_number=i,
                timestamp=i * 0.15,
                duration_ms=150.0,
                is_last=(i == 5),
            )
            for i in range(6)
        ]
        events = list(transcriber.transcribe_stream(chunks))
        final_events = [e for e in events if e.event_type == TranscriptEventType.FINAL]
        assert len(final_events) == 2

        # Sentence 1: chunks 0, 1, 2 (0.0 to 0.45s)
        h_seg1 = final_events[0].segment
        assert h_seg1 is not None
        assert h_seg1.start_time == pytest.approx(0.0)
        assert h_seg1.end_time == pytest.approx(0.45)
        assert len(h_seg1.words) == 3
        assert h_seg1.words[0].start_time == pytest.approx(0.0)
        assert h_seg1.words[-1].end_time == pytest.approx(0.45)
        for idx, w in enumerate(h_seg1.words):
            assert w.start_time >= h_seg1.start_time - 1e-4
            assert w.end_time <= h_seg1.end_time + 1e-4
            assert w.start_time < w.end_time
            if idx > 0:
                assert w.start_time >= h_seg1.words[idx - 1].end_time - 1e-4

        # Sentence 2: chunks 3, 4, 5 (0.45 to 0.90s)
        h_seg2 = final_events[1].segment
        assert h_seg2 is not None
        assert h_seg2.start_time == pytest.approx(0.45)
        assert h_seg2.end_time == pytest.approx(0.90)
        assert len(h_seg2.words) == 3
        assert h_seg2.words[0].start_time == pytest.approx(0.45)
        assert h_seg2.words[-1].end_time == pytest.approx(0.90)

    def test_reset_and_flush_do_not_retain_stale_timestamps(self) -> None:
        """Resetting transcriber clears active sentence start; subsequent stream starts clean."""
        transcriber = DeterministicFakeTranscriber(
            script=["First unfinished attempt.", "Fresh start sentence."],
            seed=42,
        )
        transcriber.initialize()
        # Feed 1 chunk of 500ms
        chunk0 = AudioChunk(data=b"\x00\x01" * 800, sequence_number=0, timestamp=0.0, duration_ms=500.0, is_last=False)
        transcriber.transcribe_chunk(chunk0)
        assert transcriber._sentence_start == pytest.approx(0.0)
        assert len(transcriber._active_sentence_words) == 1

        # Reset!
        transcriber.reset()
        assert transcriber._sentence_start is None
        assert len(transcriber._active_sentence_words) == 0

        # Now start completely new stream with offset timestamps (e.g. at 10.0s)
        new_chunks = [
            AudioChunk(data=b"\x00\x01" * 800, sequence_number=0, timestamp=10.0, duration_ms=200.0, is_last=False),
            AudioChunk(data=b"\x00\x01" * 800, sequence_number=1, timestamp=10.2, duration_ms=200.0, is_last=False),
            AudioChunk(data=b"\x00\x01" * 800, sequence_number=2, timestamp=10.4, duration_ms=200.0, is_last=True),
        ]
        new_events = list(transcriber.transcribe_stream(new_chunks))
        final_events = [e for e in new_events if e.event_type == TranscriptEventType.FINAL]
        assert len(final_events) == 1
        seg = final_events[0].segment
        assert seg is not None
        assert seg.start_time == pytest.approx(0.0)
        assert seg.end_time == pytest.approx(0.6)
        assert transcriber._sentence_start is None

    def test_interim_hypotheses_track_sentence_start_timestamp(self) -> None:
        """Interim hypotheses for in-flight words maintain sentence start timestamp."""
        transcriber = DeterministicFakeTranscriber(
            script=["One two three four."],
            seed=42,
        )
        transcriber.initialize()
        chunks = [
            AudioChunk(data=b"\x00\x01" * 800, sequence_number=i, timestamp=i * 0.1, duration_ms=100.0, is_last=(i == 3))
            for i in range(4)
        ]
        events = list(transcriber.transcribe_stream(chunks))
        interims = [e for e in events if e.event_type == TranscriptEventType.INTERIM]
        assert len(interims) == 3
        for idx, interim in enumerate(interims):
            assert interim.segment is not None
            # Every interim for this sentence must anchor to sentence_start = 0.0s
            assert interim.segment.start_time == pytest.approx(0.0)
            assert interim.segment.end_time == pytest.approx((idx + 1) * 0.1)
