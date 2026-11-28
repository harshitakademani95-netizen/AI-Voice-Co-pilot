"""Unit tests for OrderedSegmentAccumulator covering ordering, interim/final and edge cases."""

from typing import List
import pytest

from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.schemas import (
    STTErrorDetail,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


class TestOrderedSegmentAccumulator:
    """Tests covering accumulation, ordering, deduplication, and interim lifecycle."""

    def test_in_order_accumulation(self) -> None:
        accumulator = OrderedSegmentAccumulator()
        seg1 = TranscriptSegment(
            segment_id="s1",
            text="Hello world.",
            start_time=0.0,
            end_time=1.0,
            confidence=0.95,
            is_final=True,
        )
        seg2 = TranscriptSegment(
            segment_id="s2",
            text="How can I help you?",
            start_time=1.0,
            end_time=2.5,
            confidence=0.98,
            is_final=True,
        )

        assert accumulator.ingest_segment(seg1) is True
        assert accumulator.ingest_segment(seg2) is True

        finals = accumulator.get_final_segments()
        assert len(finals) == 2
        assert finals[0].text == "Hello world."
        assert finals[1].text == "How can I help you?"
        assert accumulator.get_full_transcript() == "Hello world. How can I help you?"

    def test_out_of_order_arrival_reordered_chronologically(
        self, out_of_order_segments: List[TranscriptSegment]
    ) -> None:
        """Crucial Acceptance Criteria: Out-of-order chunks must be sorted by start_time."""
        accumulator = OrderedSegmentAccumulator()

        # Ingest segments that arrived out of order: [seg2, seg3, seg1]
        for seg in out_of_order_segments:
            accumulator.ingest_segment(seg)

        finals = accumulator.get_final_segments()
        assert len(finals) == 3
        # Must be strictly ordered: seg_1 (0.0), seg_2 (1.0), seg_3 (2.0)
        assert finals[0].segment_id == "seg-part-1"
        assert finals[1].segment_id == "seg-part-2"
        assert finals[2].segment_id == "seg-part-3"
        assert finals[0].start_time == 0.0
        assert finals[1].start_time == 1.0
        assert finals[2].start_time == 2.0
        assert accumulator.get_full_transcript() == "First sentence. Second sentence. Third sentence."

    def test_interim_lifecycle_replacement_and_finalization(self) -> None:
        accumulator = OrderedSegmentAccumulator()

        # Interim step 1: "Why"
        int1 = TranscriptSegment(
            segment_id="int-1",
            text="Why",
            start_time=0.0,
            end_time=0.3,
            confidence=0.75,
            is_final=False,
        )
        accumulator.ingest_segment(int1)
        assert accumulator.final_count == 0
        assert accumulator.get_interim_segment() is not None
        assert accumulator.get_interim_segment().text == "Why"
        assert accumulator.get_full_transcript(include_interim=True) == "Why"
        assert accumulator.get_full_transcript(include_interim=False) == ""

        # Interim step 2: "Why is this"
        int2 = TranscriptSegment(
            segment_id="int-2",
            text="Why is this",
            start_time=0.0,
            end_time=0.8,
            confidence=0.82,
            is_final=False,
        )
        accumulator.ingest_segment(int2)
        assert accumulator.final_count == 0
        assert accumulator.get_interim_segment().text == "Why is this"
        assert accumulator.get_full_transcript(include_interim=True) == "Why is this"

        # Final commitment: "Why is this failing?"
        final_seg = TranscriptSegment(
            segment_id="fin-1",
            text="Why is this failing?",
            start_time=0.0,
            end_time=1.2,
            confidence=0.96,
            is_final=True,
        )
        accumulator.ingest_segment(final_seg)
        assert accumulator.final_count == 1
        # Interim should now be cleared
        assert accumulator.get_interim_segment() is None
        assert accumulator.get_full_transcript(include_interim=True) == "Why is this failing?"
        assert accumulator.get_full_transcript(include_interim=False) == "Why is this failing?"

    def test_duplicate_segment_rejection(self, valid_final_segment: TranscriptSegment) -> None:
        accumulator = OrderedSegmentAccumulator()
        # Ingest first time -> accepted
        assert accumulator.ingest_segment(valid_final_segment) is True
        assert accumulator.final_count == 1

        # Ingest exact same segment again -> rejected as duplicate
        assert accumulator.ingest_segment(valid_final_segment) is False
        assert accumulator.final_count == 1

        # Ingest different segment_id but identical timestamps and content -> rejected
        twin_segment = valid_final_segment.model_copy(update={"segment_id": "seg-final-002"})
        assert accumulator.ingest_segment(twin_segment) is False
        assert accumulator.final_count == 1

    def test_error_event_does_not_corrupt_final_segments(
        self, valid_final_segment: TranscriptSegment, sample_error_event: TranscriptEvent
    ) -> None:
        accumulator = OrderedSegmentAccumulator()
        accumulator.ingest_segment(valid_final_segment)
        assert accumulator.final_count == 1

        # Ingest error event
        accumulator.ingest_event(sample_error_event)

        # Committed final segments must remain untouched!
        assert accumulator.final_count == 1
        assert accumulator.get_final_segments()[0].text == valid_final_segment.text
        assert accumulator.last_error is not None
        assert accumulator.last_error.code == "MICROPHONE_DROPOUT"

    def test_metrics_and_summary(self) -> None:
        accumulator = OrderedSegmentAccumulator()
        seg1 = TranscriptSegment(
            segment_id="s1",
            text="Part one.",
            start_time=0.0,
            end_time=2.0,
            confidence=0.90,
            is_final=True,
        )
        seg2 = TranscriptSegment(
            segment_id="s2",
            text="Part two.",
            start_time=2.0,
            end_time=5.0,
            confidence=1.00,
            is_final=True,
        )
        accumulator.ingest_segment(seg1)
        accumulator.ingest_segment(seg2)

        assert accumulator.get_total_duration() == pytest.approx(5.0)
        assert accumulator.get_average_confidence() == pytest.approx(0.95)

        summary = accumulator.get_summary()
        assert summary["final_segments_count"] == 2
        assert summary["total_duration_seconds"] == 5.0
        assert summary["average_confidence"] == 0.95
        assert summary["full_transcript"] == "Part one. Part two."

    def test_reset_clears_all_state(self, valid_final_segment: TranscriptSegment) -> None:
        accumulator = OrderedSegmentAccumulator()
        accumulator.ingest_segment(valid_final_segment)
        assert accumulator.final_count == 1

        accumulator.reset()
        assert accumulator.final_count == 0
        assert accumulator.get_interim_segment() is None
        assert accumulator.get_full_transcript() == ""
        assert accumulator.get_total_duration() == 0.0
        assert accumulator.get_average_confidence() == 0.0

    def test_summary_has_no_stale_chunks_processed_counter(self) -> None:
        """The accumulator consumes events, not chunks; verify chunks_processed is absent."""
        accumulator = OrderedSegmentAccumulator()
        summary = accumulator.get_summary()
        assert "chunks_processed" not in summary
        assert not hasattr(accumulator, "_chunks_processed")

    def test_stream_completed_event_ingestion_preserves_final_segments(
        self, valid_final_segment: TranscriptSegment
    ) -> None:
        """Lifecycle STREAM_COMPLETED event is ingested safely without altering committed segments."""
        accumulator = OrderedSegmentAccumulator()
        accumulator.ingest_segment(valid_final_segment)
        assert accumulator.final_count == 1

        completed_event = TranscriptEvent(
            event_id="evt-completed-001",
            event_type=TranscriptEventType.STREAM_COMPLETED,
            sequence_number=99,
            timestamp=2.5,
            segment=None,
            error=None,
        )
        # Should ingest successfully
        processed = accumulator.ingest_event(completed_event)
        assert processed is True
        assert accumulator.final_count == 1
        assert accumulator.get_final_segments()[0].text == valid_final_segment.text
        assert accumulator.get_full_transcript() == valid_final_segment.text

