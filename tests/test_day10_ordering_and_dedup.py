"""Week 2 Day 10: Transcript Ordering and Duplicate Suppression Tests.

Covers:
1. OUT-OF-ORDER EVENTS:
   - Chronological sorting of final segments regardless of event arrival order.
   - Handling reverse, interleaved, and randomized arrival permutations.
   - Equal start_time disambiguation ordered by end_time.
   - Telemetry tracking of out-of-order reordering events.

2. DUPLICATE SUPPRESSION:
   - Duplicate event_id suppression across all event types (final, interim, error, lifecycle).
   - Duplicate segment_id suppression across distinct events.
   - Exact content and audio boundary deduplication.
   - Duplicate interim hypothesis suppression.
   - Preservation of legitimate repeated phrases/utterances at distinct audio times.

3. LATE / DELAYED DELIVERY:
   - Late interim hypothesis arriving after audio window finalization discarded.
   - Delayed final segment backfilling into its proper chronological position.

4. ORCHESTRATOR INTEGRATION:
   - Ingesting out-of-order and duplicate events through TranscriptionOrchestrator.
   - End-to-end full transcript reconstruction and verification telemetry.
"""

from typing import List, Optional
import pytest

from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.adapter import BaseSTTAdapter, STTAdapterState, STTAdapterStatus
from voice_stt.orchestrator import TranscriptionOrchestrator
from voice_stt.schemas import (
    AudioChunk,
    AudioFormat,
    STTErrorDetail,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


def _make_final_seg(
    seg_id: str,
    text: str,
    start: float,
    end: float,
    confidence: float = 0.95,
) -> TranscriptSegment:
    """Helper to construct a valid final TranscriptSegment."""
    return TranscriptSegment(
        segment_id=seg_id,
        text=text,
        start_time=start,
        end_time=end,
        confidence=confidence,
        is_final=True,
    )


def _make_interim_seg(
    seg_id: str,
    text: str,
    start: float,
    end: float,
    confidence: float = 0.80,
) -> TranscriptSegment:
    """Helper to construct a valid interim TranscriptSegment."""
    return TranscriptSegment(
        segment_id=seg_id,
        text=text,
        start_time=start,
        end_time=end,
        confidence=confidence,
        is_final=False,
    )


def _make_event(
    event_id: str,
    event_type: TranscriptEventType,
    seq: int,
    segment: Optional[TranscriptSegment] = None,
    error: Optional[STTErrorDetail] = None,
) -> TranscriptEvent:
    """Helper to construct a valid TranscriptEvent."""
    return TranscriptEvent(
        event_id=event_id,
        event_type=event_type,
        sequence_number=seq,
        timestamp=float(seq),
        segment=segment,
        error=error,
    )


# ==============================================================================
# 1. OUT-OF-ORDER EVENT TESTS
# ==============================================================================


class TestDay10OutOfOrderEvents:
    """Test suite verifying robust chronological sorting on out-of-order arrivals."""

    def test_reverse_order_arrival_reordered_chronologically(self) -> None:
        """Deliver 5 final segments in reverse chronological order (5 -> 1)."""
        acc = OrderedSegmentAccumulator()

        s1 = _make_final_seg("s1", "One.", 0.0, 1.0)
        s2 = _make_final_seg("s2", "Two.", 1.0, 2.0)
        s3 = _make_final_seg("s3", "Three.", 2.0, 3.0)
        s4 = _make_final_seg("s4", "Four.", 3.0, 4.0)
        s5 = _make_final_seg("s5", "Five.", 4.0, 5.0)

        # Ingest in reverse: s5, s4, s3, s2, s1
        for s in [s5, s4, s3, s2, s1]:
            accepted = acc.ingest_segment(s)
            assert accepted is True

        finals = acc.get_final_segments()
        assert len(finals) == 5
        assert [f.segment_id for f in finals] == ["s1", "s2", "s3", "s4", "s5"]
        assert [f.start_time for f in finals] == [0.0, 1.0, 2.0, 3.0, 4.0]
        assert acc.get_full_transcript() == "One. Two. Three. Four. Five."
        # s4, s3, s2, s1 were inserted before previous items -> 4 reorderings
        assert acc.out_of_order_count == 4

        summary = acc.get_summary()
        assert summary["is_verified"] is True
        assert summary["out_of_order_reordered"] == 4

    def test_shuffled_permutations_reordered_consistently(self) -> None:
        """Deliver segments across multiple arbitrary permutations; all must sort identically."""
        expected_text = "Alpha. Beta. Gamma. Delta."

        permutations = [
            ["s3", "s1", "s4", "s2"],
            ["s4", "s2", "s1", "s3"],
            ["s2", "s4", "s3", "s1"],
            ["s4", "s3", "s2", "s1"],
            ["s1", "s4", "s2", "s3"],
        ]

        segments_map = {
            "s1": _make_final_seg("s1", "Alpha.", 0.0, 1.0),
            "s2": _make_final_seg("s2", "Beta.", 1.0, 2.0),
            "s3": _make_final_seg("s3", "Gamma.", 2.0, 3.0),
            "s4": _make_final_seg("s4", "Delta.", 3.0, 4.0),
        }

        for perm in permutations:
            acc = OrderedSegmentAccumulator()
            for key in perm:
                acc.ingest_segment(segments_map[key])

            finals = acc.get_final_segments()
            assert len(finals) == 4
            assert [f.segment_id for f in finals] == ["s1", "s2", "s3", "s4"]
            assert acc.get_full_transcript() == expected_text
            assert acc.get_summary()["is_verified"] is True

    def test_equal_start_timestamps_ordered_by_end_time(self) -> None:
        """When start_time is identical, secondary sort by end_time must be enforced."""
        acc = OrderedSegmentAccumulator()

        # Both start at 2.0, but s_short ends at 2.5, s_long ends at 3.5
        s_long = _make_final_seg("s_long", "Long utterance.", 2.0, 3.5)
        s_short = _make_final_seg("s_short", "Short utterance.", 2.0, 2.5)

        # Ingest longer first, then shorter
        acc.ingest_segment(s_long)
        acc.ingest_segment(s_short)

        finals = acc.get_final_segments()
        assert len(finals) == 2
        # Shorter duration [2.0, 2.5] must precede [2.0, 3.5]
        assert finals[0].segment_id == "s_short"
        assert finals[1].segment_id == "s_long"
        assert finals[0].end_time == 2.5
        assert finals[1].end_time == 3.5

    def test_delayed_final_segment_backfills_correctly(self) -> None:
        """Middle segment delayed: [0.0, 1.0] and [2.0, 3.0] exist; [1.0, 2.0] arrives late."""
        acc = OrderedSegmentAccumulator()

        first = _make_final_seg("first", "First sentence.", 0.0, 1.0)
        third = _make_final_seg("third", "Third sentence.", 2.0, 3.0)
        delayed_second = _make_final_seg("second", "Second sentence.", 1.0, 2.0)

        acc.ingest_segment(first)
        acc.ingest_segment(third)
        assert acc.out_of_order_count == 0

        # Now delayed middle segment arrives
        acc.ingest_segment(delayed_second)
        assert acc.out_of_order_count == 1

        finals = acc.get_final_segments()
        assert len(finals) == 3
        assert [f.segment_id for f in finals] == ["first", "second", "third"]
        assert acc.get_full_transcript() == "First sentence. Second sentence. Third sentence."


# ==============================================================================
# 2. DUPLICATE SUPPRESSION TESTS
# ==============================================================================


class TestDay10DuplicateSuppression:
    """Test suite verifying prevention of duplicate commitments."""

    def test_duplicate_event_id_suppression(self) -> None:
        """Repeated ingestion of the exact same event_id must be suppressed."""
        acc = OrderedSegmentAccumulator()
        seg = _make_final_seg("seg-001", "Hello there.", 0.0, 1.0)
        event = _make_event("evt-unique-1", TranscriptEventType.FINAL, 1, segment=seg)

        # First delivery accepted
        assert acc.ingest_event(event) is True
        assert acc.final_count == 1
        assert acc.duplicates_suppressed == 0

        # Second delivery with identical event_id rejected
        assert acc.ingest_event(event) is False
        assert acc.final_count == 1
        assert acc.duplicates_suppressed == 1

        # Third delivery with identical event_id rejected
        assert acc.ingest_event(event) is False
        assert acc.final_count == 1
        assert acc.duplicates_suppressed == 2

        assert acc.get_full_transcript() == "Hello there."

    def test_duplicate_segment_id_across_distinct_events(self) -> None:
        """Different event_ids carrying the same segment_id must be suppressed."""
        acc = OrderedSegmentAccumulator()
        seg = _make_final_seg("seg-shared-id", "Same segment payload.", 0.0, 1.5)

        event1 = _make_event("evt-stream-a", TranscriptEventType.FINAL, 1, segment=seg)
        event2 = _make_event("evt-stream-b", TranscriptEventType.FINAL, 2, segment=seg)

        assert acc.ingest_event(event1) is True
        assert acc.final_count == 1

        # Event 2 has new event_id but identical segment_id
        assert acc.ingest_event(event2) is False
        assert acc.final_count == 1
        assert acc.duplicates_suppressed == 1
        assert acc.get_full_transcript() == "Same segment payload."

    def test_duplicate_content_and_boundary_suppression(self) -> None:
        """Different event_id and segment_id, but identical audio time span and text."""
        acc = OrderedSegmentAccumulator()
        seg_orig = _make_final_seg("seg-orig", "Echo text.", 1.0, 2.5)
        seg_clone = _make_final_seg("seg-clone", "Echo text.", 1.0, 2.5)

        assert acc.ingest_segment(seg_orig) is True
        assert acc.final_count == 1

        # Ingest twin with new segment_id but identical timestamps and content
        assert acc.ingest_segment(seg_clone) is False
        assert acc.final_count == 1
        assert acc.duplicates_suppressed == 1
        assert acc.get_full_transcript() == "Echo text."

    def test_legitimate_repeated_utterances_preserved(self) -> None:
        """Speaker repeating the same word at different timestamps must NOT be suppressed."""
        acc = OrderedSegmentAccumulator()

        # Speaker says "Yes." at 1.0-1.5s, then pauses, then says "Yes." at 3.0-3.5s
        seg_first = _make_final_seg("seg-yes-1", "Yes.", 1.0, 1.5)
        seg_second = _make_final_seg("seg-yes-2", "Yes.", 3.0, 3.5)

        assert acc.ingest_segment(seg_first) is True
        assert acc.ingest_segment(seg_second) is True

        finals = acc.get_final_segments()
        assert len(finals) == 2
        assert finals[0].text == "Yes."
        assert finals[1].text == "Yes."
        assert finals[0].start_time == 1.0
        assert finals[1].start_time == 3.0
        assert acc.duplicates_suppressed == 0
        assert acc.get_full_transcript() == "Yes. Yes."

    def test_duplicate_interim_hypothesis_suppressed(self) -> None:
        """Identical interim hypothesis sent repeatedly is suppressed without incrementing churn."""
        acc = OrderedSegmentAccumulator()
        int_seg = _make_interim_seg("int-1", "Working on", 0.0, 0.5)

        assert acc.ingest_segment(int_seg) is True
        assert acc.interim_updates_count == 1

        # Ingest exact same interim again
        assert acc.ingest_segment(int_seg) is False
        assert acc.interim_updates_count == 1
        assert acc.duplicates_suppressed == 1

    def test_duplicate_error_event_suppressed(self) -> None:
        """Duplicate error event_id is rejected and doesn't pollute telemetry."""
        acc = OrderedSegmentAccumulator()
        err_detail = STTErrorDetail(code="AUDIO_TIMEOUT", message="Audio buffer timed out")
        err_event = _make_event("err-evt-1", TranscriptEventType.ERROR, 1, error=err_detail)

        assert acc.ingest_event(err_event) is True
        assert acc.last_error is not None
        assert acc.last_error.code == "AUDIO_TIMEOUT"

        # Re-send same error event
        assert acc.ingest_event(err_event) is False
        assert acc.duplicates_suppressed == 1


# ==============================================================================
# 3. LATE AND DELAYED DELIVERY TESTS
# ==============================================================================


class TestDay10LateDeliveryHandling:
    """Test suite verifying safe handling of delayed/late events."""

    def test_late_interim_discard_after_finalization(self) -> None:
        """Late interim arriving after its audio window was finalized must be rejected."""
        acc = OrderedSegmentAccumulator()

        # Final segment commits audio from 0.0s to 2.0s
        final_seg = _make_final_seg("final-1", "Full sentence complete.", 0.0, 2.0)
        acc.ingest_segment(final_seg)
        assert acc.final_count == 1

        # Delayed interim covering 0.5s to 1.5s arrives after finalization
        stale_interim = _make_interim_seg("late-int", "sentence comp", 0.5, 1.5)
        result = acc.ingest_segment(stale_interim)

        assert result is False
        assert acc.get_interim_segment() is None
        assert acc.get_full_transcript() == "Full sentence complete."

    def test_future_interim_accepted_after_finalization(self) -> None:
        """Interim extending beyond finalized audio window must be accepted."""
        acc = OrderedSegmentAccumulator()

        final_seg = _make_final_seg("final-1", "Sentence one.", 0.0, 1.5)
        acc.ingest_segment(final_seg)

        # Interim covering 1.5s to 2.2s is valid upcoming speech
        future_interim = _make_interim_seg("next-int", "Sentence two", 1.5, 2.2)
        result = acc.ingest_segment(future_interim)

        assert result is True
        assert acc.get_interim_segment() is not None
        assert acc.get_interim_segment().text == "Sentence two"
        assert acc.get_full_transcript(include_interim=True) == "Sentence one. Sentence two"


# ==============================================================================
# 4. ORCHESTRATOR INTEGRATION TESTS
# ==============================================================================


class _OutOfOrderSimulatingAdapter(BaseSTTAdapter):
    """Mock adapter that deliberately returns final events out of order for testing."""

    def __init__(self) -> None:
        super().__init__()
        self._chunks_received = 0

    def initialize(self, session_id: Optional[str] = None) -> None:
        super().initialize(session_id=session_id)
        self._state = STTAdapterState.READY

    def transcribe_chunk(
        self,
        chunk: AudioChunk | bytes,
        is_last: bool = False,
    ) -> List[TranscriptEvent]:
        self._chunks_received += 1
        # Chunk 1 emits segment 2 (delayed segment 1 arrives later)
        if self._chunks_received == 1:
            seg = _make_final_seg("seg-2", "second part.", 1.0, 2.0)
            return [_make_event("evt-2", TranscriptEventType.FINAL, 1, segment=seg)]
        elif self._chunks_received == 2:
            seg = _make_final_seg("seg-1", "First part", 0.0, 1.0)
            return [_make_event("evt-1", TranscriptEventType.FINAL, 2, segment=seg)]
        return []

    def transcribe_stream(self, stream):
        for chunk in stream:
            for evt in self.transcribe_chunk(chunk):
                yield evt

    def reset(self) -> None:
        super().reset()
        self._chunks_received = 0


class TestDay10OrchestratorOrderingAndDedupIntegration:
    """Integration test suite verifying TranscriptionOrchestrator ordering and dedup."""

    def test_orchestrator_ingest_event_direct_ordering_and_dedup(self) -> None:
        """Feed out-of-order and duplicate events into orchestrator via ingest_event."""
        orchestrator = TranscriptionOrchestrator()
        orchestrator.initialize(session_id="day10-orch-test")

        seg_a = _make_final_seg("seg-a", "Beginning.", 0.0, 1.0)
        seg_b = _make_final_seg("seg-b", "Middle.", 1.0, 2.0)
        seg_c = _make_final_seg("seg-c", "End.", 2.0, 3.0)

        evt_c = _make_event("evt-c", TranscriptEventType.FINAL, 1, segment=seg_c)
        evt_a = _make_event("evt-a", TranscriptEventType.FINAL, 2, segment=seg_a)
        evt_b = _make_event("evt-b", TranscriptEventType.FINAL, 3, segment=seg_b)

        # Ingest out of order: C, A, B
        assert orchestrator.ingest_event(evt_c) is True
        assert orchestrator.ingest_event(evt_a) is True
        assert orchestrator.ingest_event(evt_b) is True

        # Ingest duplicate of evt-a
        assert orchestrator.ingest_event(evt_a) is False

        # Ingest duplicate of evt-c
        assert orchestrator.ingest_event(evt_c) is False

        finals = orchestrator.get_final_segments()
        assert len(finals) == 3
        assert [f.segment_id for f in finals] == ["seg-a", "seg-b", "seg-c"]
        assert orchestrator.get_transcript() == "Beginning. Middle. End."

        summary = orchestrator.get_summary()
        assert summary["duplicates_suppressed"] == 2
        assert summary["out_of_order_reordered"] >= 1
        assert summary["is_verified"] is True

    def test_orchestrator_with_out_of_order_emitting_adapter(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Process chunks through an adapter emitting out-of-order events."""
        adapter = _OutOfOrderSimulatingAdapter()
        orchestrator = TranscriptionOrchestrator(adapter=adapter)

        with orchestrator:
            chunk1 = AudioChunk(
                sequence_id=0,
                timestamp=0.0,
                data=sample_audio_bytes,
                metadata={"is_last": False},
            )
            chunk2 = AudioChunk(
                sequence_id=1,
                timestamp=0.1,
                data=sample_audio_bytes,
                metadata={"is_last": True},
            )

            orchestrator.process_chunk(chunk1)
            orchestrator.process_chunk(chunk2, is_last=True)

            finals = orchestrator.get_final_segments()
            assert len(finals) == 2
            # Must be ordered: seg-1 (0.0-1.0), then seg-2 (1.0-2.0)
            assert finals[0].segment_id == "seg-1"
            assert finals[1].segment_id == "seg-2"
            assert orchestrator.get_transcript() == "First part second part."
            assert orchestrator.accumulator.out_of_order_count == 1

    def test_orchestrator_summary_reports_telemetry(self) -> None:
        """Verify orchestrator get_summary() reports all ordering and dedup diagnostics."""
        orchestrator = TranscriptionOrchestrator()
        orchestrator.initialize()

        seg = _make_final_seg("s-diag", "Telemetry test.", 0.0, 1.0)
        evt = _make_event("evt-diag", TranscriptEventType.FINAL, 1, segment=seg)

        orchestrator.ingest_event(evt)
        orchestrator.ingest_event(evt)  # duplicate

        summary = orchestrator.get_summary()
        assert "duplicates_suppressed" in summary
        assert "out_of_order_reordered" in summary
        assert "arrival_history" in summary
        assert summary["duplicates_suppressed"] == 1
        assert len(summary["arrival_history"]) == 2

