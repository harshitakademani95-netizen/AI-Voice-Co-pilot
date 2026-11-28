"""Comprehensive unit tests covering the 20 mandatory Week 1 requirements."""

import math
from typing import List
import pytest
from pydantic import ValidationError

from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.adapter import BaseSTTAdapter, STTAdapterState
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.fixtures import get_fixture
from voice_stt.schemas import (
    AudioChunk,
    STTErrorDetail,
    STTValidationError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
    WordTiming,
)


class TestTwentyWeek1Requirements:
    """Explicitly verifies the 20 requirements specified in the Week 1 upgrade specification."""

    # 1. Valid final segment
    def test_01_valid_final_segment(self) -> None:
        seg = TranscriptSegment(
            segment_id="seg-final-001",
            text="Valid finalized segment text.",
            start_time=0.0,
            end_time=1.2,
            confidence=0.96,
            is_final=True,
            language="en",
        )
        assert seg.is_final is True
        assert seg.text == "Valid finalized segment text."
        assert seg.start_time == 0.0
        assert seg.end_time == 1.2
        assert seg.confidence == 0.96

    # 2. Valid interim segment
    def test_02_valid_interim_segment(self) -> None:
        seg = TranscriptSegment(
            segment_id="seg-interim-001",
            text="Valid interim",
            start_time=0.0,
            end_time=0.5,
            confidence=0.85,
            is_final=False,
            language="en",
        )
        assert seg.is_final is False
        assert seg.text == "Valid interim"

    # 3. Missing required fields
    def test_03_missing_required_fields(self) -> None:
        # text is missing
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptSegment.model_validate({
                "start_time": 0.0,
                "end_time": 1.0,
                "confidence": 0.9,
            })

    # 4. Incorrect field types
    def test_04_incorrect_field_types(self) -> None:
        # start_time passed as incompatible string
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptSegment.model_validate({
                "text": "Hello",
                "start_time": "invalid_number_string",
                "end_time": 1.0,
                "confidence": 0.9,
            })

    # 5. Negative, non-finite or reversed timestamps
    def test_05_negative_nonfinite_or_reversed_timestamps(self) -> None:
        # Negative start
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptSegment(text="Test", start_time=-0.5, end_time=1.0, confidence=0.9)

        # Reversed timestamps (end < start)
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptSegment(text="Test", start_time=2.0, end_time=1.0, confidence=0.9)

        # Non-finite (NaN, Inf)
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptSegment(text="Test", start_time=float("nan"), end_time=1.0, confidence=0.9)

        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptSegment(text="Test", start_time=0.0, end_time=float("inf"), confidence=0.9)

    # 6. Invalid confidence values
    def test_06_invalid_confidence_values(self) -> None:
        # Confidence < 0.0
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptSegment(text="Low", start_time=0.0, end_time=1.0, confidence=-0.1)

        # Confidence > 1.0
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptSegment(text="High", start_time=0.0, end_time=1.0, confidence=1.05)

        # Confidence NaN / Inf
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptSegment(text="NaN", start_time=0.0, end_time=1.0, confidence=float("nan"))

    # 7. Unsupported event types
    def test_07_unsupported_event_types(self) -> None:
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptEvent.model_validate({
                "event_id": "evt-001",
                "event_type": "unsupported_magic_event",
                "sequence_number": 1,
            })

    # 8. Malformed error events
    def test_08_malformed_error_events(self) -> None:
        # Error event missing required error payload
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptEvent(
                event_type=TranscriptEventType.ERROR,
                sequence_number=1,
                error=None,
            )

    # 9. Chronological ordering of multiple final segments
    def test_09_chronological_ordering_of_multiple_final_segments(self) -> None:
        acc = OrderedSegmentAccumulator()
        s1 = TranscriptSegment(segment_id="s1", text="Part 1", start_time=0.0, end_time=1.0, confidence=0.95, is_final=True)
        s2 = TranscriptSegment(segment_id="s2", text="Part 2", start_time=1.0, end_time=2.0, confidence=0.96, is_final=True)
        acc.ingest_segment(s1)
        acc.ingest_segment(s2)
        finals = acc.get_final_segments()
        assert len(finals) == 2
        assert finals[0].start_time == 0.0
        assert finals[1].start_time == 1.0

    # 10. Out-of-order event arrival
    def test_10_out_of_order_event_arrival(self) -> None:
        acc = OrderedSegmentAccumulator()
        s_late = TranscriptSegment(segment_id="s_late", text="Late text", start_time=2.0, end_time=3.0, confidence=0.95, is_final=True)
        s_early = TranscriptSegment(segment_id="s_early", text="Early text", start_time=0.0, end_time=1.0, confidence=0.97, is_final=True)
        # Ingest out of order: late first, then early
        acc.ingest_segment(s_late)
        acc.ingest_segment(s_early)
        finals = acc.get_final_segments()
        assert finals[0].segment_id == "s_early"
        assert finals[1].segment_id == "s_late"
        assert acc.out_of_order_count == 1
        assert acc.get_full_transcript() == "Early text Late text"

    # 11. Repeated delivery of the same event
    def test_11_repeated_delivery_of_the_same_event(self) -> None:
        acc = OrderedSegmentAccumulator()
        seg = TranscriptSegment(segment_id="s1", text="Duplicate me", start_time=0.0, end_time=1.0, confidence=0.95, is_final=True)
        evt = TranscriptEvent(event_id="e1", event_type=TranscriptEventType.FINAL, sequence_number=1, segment=seg)

        assert acc.ingest_event(evt) is True
        assert acc.final_count == 1

        # Second delivery of same event
        assert acc.ingest_event(evt) is False
        assert acc.final_count == 1
        assert acc.duplicates_suppressed == 1
        assert acc.get_full_transcript() == "Duplicate me"

    # 12. Interim updates followed by a final segment
    def test_12_interim_updates_followed_by_a_final_segment(self) -> None:
        acc = OrderedSegmentAccumulator()
        int1 = TranscriptSegment(segment_id="i1", text="Hello", start_time=0.0, end_time=0.4, confidence=0.8, is_final=False)
        int2 = TranscriptSegment(segment_id="i2", text="Hello world", start_time=0.0, end_time=0.8, confidence=0.85, is_final=False)
        final_seg = TranscriptSegment(segment_id="f1", text="Hello world!", start_time=0.0, end_time=1.0, confidence=0.98, is_final=True)

        acc.ingest_segment(int1)
        assert acc.get_interim_segment().text == "Hello"
        assert acc.final_count == 0

        acc.ingest_segment(int2)
        assert acc.get_interim_segment().text == "Hello world"
        assert acc.final_count == 0

        acc.ingest_segment(final_seg)
        assert acc.final_count == 1
        assert acc.get_interim_segment() is None
        assert acc.get_full_transcript() == "Hello world!"

    # 13. Late interim updates after finalization
    def test_13_late_interim_updates_after_finalization(self) -> None:
        acc = OrderedSegmentAccumulator()
        # Finalized segment covering 0.0s to 1.5s
        final_seg = TranscriptSegment(segment_id="f1", text="Committed sentence.", start_time=0.0, end_time=1.5, confidence=0.98, is_final=True)
        acc.ingest_segment(final_seg)

        # Late interim from 0.0s to 0.8s (already finalized!)
        late_interim = TranscriptSegment(segment_id="late_int", text="Stale words", start_time=0.0, end_time=0.8, confidence=0.7, is_final=False)
        result = acc.ingest_segment(late_interim)

        assert result is False
        assert acc.get_interim_segment() is None
        assert acc.get_full_transcript() == "Committed sentence."

    # 14. Equal timestamps and overlapping segments
    def test_14_equal_timestamps_and_overlapping_segments(self) -> None:
        acc = OrderedSegmentAccumulator()
        # Two different valid segments with identical start_time (e.g. multi-word or multi-speaker)
        s1 = TranscriptSegment(segment_id="seg_a", text="Speaker A", start_time=1.0, end_time=2.0, confidence=0.92, is_final=True)
        s2 = TranscriptSegment(segment_id="seg_b", text="Speaker B", start_time=1.0, end_time=2.5, confidence=0.94, is_final=True)

        acc.ingest_segment(s1)
        acc.ingest_segment(s2)

        finals = acc.get_final_segments()
        assert len(finals) == 2
        # Both preserved stably
        assert finals[0].text == "Speaker A"
        assert finals[1].text == "Speaker B"

    # 15. Empty transcript and reset behavior
    def test_15_empty_transcript_and_reset_behavior(self) -> None:
        acc = OrderedSegmentAccumulator()
        seg = TranscriptSegment(segment_id="s1", text="Before reset", start_time=0.0, end_time=1.0, confidence=0.9, is_final=True)
        acc.ingest_segment(seg)
        assert acc.final_count == 1

        acc.reset()
        assert acc.final_count == 0
        assert acc.get_full_transcript() == ""
        assert acc.get_total_duration() == 0.0
        assert acc.get_average_confidence() == 0.0
        assert acc.get_interim_segment() is None

    # 16. Deterministic repeated mock runs
    def test_16_deterministic_repeated_mock_runs(self) -> None:
        fix = get_fixture("A")
        # Run 1
        t1 = DeterministicFakeTranscriber(fixture=fix, seed=42)
        t1.initialize()
        events1 = [t1.transcribe_chunk(b"\x00" * 3200) for _ in range(3)]

        # Run 2
        t2 = DeterministicFakeTranscriber(fixture=fix, seed=42)
        t2.initialize()
        events2 = [t2.transcribe_chunk(b"\x00" * 3200) for _ in range(3)]

        assert len(events1) == len(events2)
        assert [[e.model_dump() for e in sub] for sub in events1] == [[e.model_dump() for e in sub] for sub in events2]

    # 17. Simulated adapter failure
    def test_17_simulated_adapter_failure(self) -> None:
        t = DeterministicFakeTranscriber(inject_error_at_chunk=1)
        t.initialize()

        # Chunk 0: normal
        evts_0 = t.transcribe_chunk(b"\x00" * 3200)
        assert t.state == STTAdapterState.READY

        # Chunk 1: failure triggered
        evts_1 = t.transcribe_chunk(b"\x00" * 3200)
        assert t.state == STTAdapterState.ERROR
        assert len(evts_1) == 1
        assert evts_1[0].event_type == TranscriptEventType.ERROR
        assert evts_1[0].error is not None

    # 18. Recovery after a failed run
    def test_18_recovery_after_failed_run(self) -> None:
        t = DeterministicFakeTranscriber(inject_error_at_chunk=0)
        t.initialize()
        t.transcribe_chunk(b"\x00" * 3200)
        assert t.state == STTAdapterState.ERROR

        # Resetting restores adapter to READY
        t.reset()
        assert t.state == STTAdapterState.READY
        assert t.get_status().last_error is None

    # 19. Consistency between the final transcript and committed segments
    def test_19_consistency_between_final_transcript_and_committed_segments(self) -> None:
        acc = OrderedSegmentAccumulator()
        seg1 = TranscriptSegment(segment_id="s1", text="Why is this application", start_time=0.0, end_time=0.8, confidence=0.96, is_final=True)
        seg2 = TranscriptSegment(segment_id="s2", text="showing this error?", start_time=0.8, end_time=1.5, confidence=0.97, is_final=True)
        acc.ingest_segment(seg1)
        acc.ingest_segment(seg2)

        final_segments = acc.get_final_segments()
        expected = " ".join(s.text.strip() for s in final_segments)
        assert acc.get_full_transcript() == expected

    # 20. Correct telemetry calculations
    def test_20_correct_telemetry_calculations(self) -> None:
        acc = OrderedSegmentAccumulator()
        seg1 = TranscriptSegment(segment_id="s1", text="One", start_time=0.0, end_time=2.0, confidence=0.90, is_final=True)
        seg2 = TranscriptSegment(segment_id="s2", text="Two", start_time=2.0, end_time=5.0, confidence=1.00, is_final=True)
        acc.ingest_segment(seg1)
        acc.ingest_segment(seg2)

        summary = acc.get_summary()
        assert summary["final_segments_count"] == 2
        assert summary["total_duration_seconds"] == 5.0
        assert summary["average_confidence"] == pytest.approx(0.95)
        assert summary["is_verified"] is True

