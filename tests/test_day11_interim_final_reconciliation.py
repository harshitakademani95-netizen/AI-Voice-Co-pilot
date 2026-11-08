"""Week 2 Day 11: Interim-to-Final Transcript Reconciliation Tests.

Covers:
1. Single interim event followed by its final event.
2. Multiple interim updates followed by one final event.
3. Final transcript does not duplicate interim text or words.
4. Late interim event arriving after a final event is safely rejected.
5. Older interim hypothesis arriving after a newer one is discarded.
6. Multiple independent speech segments with their own interim and final stages.
7. Correct chronological ordering after reconciliation.
8. Legitimate repeated words in separate spoken segments preserved.
9. Empty or invalid transcript events follow existing validation rules.
10. End-to-end reconciliation through TranscriptionOrchestrator.
"""

from typing import List, Optional
from pydantic import ValidationError
import pytest

from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.adapter import BaseSTTAdapter, STTAdapterState
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.orchestrator import TranscriptionOrchestrator
from voice_stt.schemas import (
    AudioChunk,
    AudioFormat,
    STTErrorDetail,
    STTValidationError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


def _make_final(
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


def _make_interim(
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
    session_id: Optional[str] = "day11-session",
) -> TranscriptEvent:
    """Helper to construct a valid TranscriptEvent."""
    return TranscriptEvent(
        event_id=event_id,
        event_type=event_type,
        sequence_number=seq,
        timestamp=float(seq) * 0.1,
        session_id=session_id,
        segment=segment,
        error=error,
    )


class TestDay11InterimFinalReconciliation:
    """Test suite for Day 11 Interim-to-Final Transcript Reconciliation."""

    # 1. A single interim event followed by its final event
    def test_01_single_interim_followed_by_final(self) -> None:
        acc = OrderedSegmentAccumulator()
        int_seg = _make_interim("int-1", "Hello", 0.0, 0.8)
        evt_int = _make_event("evt-1", TranscriptEventType.INTERIM, 1, segment=int_seg)

        # Ingest interim
        assert acc.ingest_event(evt_int) is True
        assert acc.final_count == 0
        assert acc.get_interim_segment() is not None
        assert acc.get_interim_segment().text == "Hello"
        assert acc.get_full_transcript(include_interim=True) == "Hello"
        assert acc.get_full_transcript(include_interim=False) == ""

        # Ingest final
        fin_seg = _make_final("fin-1", "Hello world.", 0.0, 1.0)
        evt_fin = _make_event("evt-2", TranscriptEventType.FINAL, 2, segment=fin_seg)
        assert acc.ingest_event(evt_fin) is True

        # Reconciled: interim cleared, final committed
        assert acc.final_count == 1
        assert acc.get_interim_segment() is None
        assert acc.get_full_transcript(include_interim=True) == "Hello world."
        assert acc.get_full_transcript(include_interim=False) == "Hello world."
        assert acc.get_final_segments()[0].text == "Hello world."

    # 2. Multiple interim updates followed by one final event
    def test_02_multiple_interim_updates_followed_by_final(self) -> None:
        acc = OrderedSegmentAccumulator()

        hypotheses = [
            ("int-1", "The", 0.0, 0.3),
            ("int-2", "The quick", 0.0, 0.6),
            ("int-3", "The quick brown", 0.0, 1.0),
        ]
        for seq, (s_id, text, start, end) in enumerate(hypotheses, start=1):
            seg = _make_interim(s_id, text, start, end)
            evt = _make_event(f"evt-{seq}", TranscriptEventType.INTERIM, seq, segment=seg)
            assert acc.ingest_event(evt) is True
            assert acc.final_count == 0
            assert acc.get_interim_segment().text == text
            assert acc.get_full_transcript(include_interim=True) == text

        assert acc.interim_updates_count == 3

        # Final commitment
        final_seg = _make_final("fin-fox", "The quick brown fox.", 0.0, 1.4)
        evt_fin = _make_event("evt-4", TranscriptEventType.FINAL, 4, segment=final_seg)
        assert acc.ingest_event(evt_fin) is True

        assert acc.final_count == 1
        assert acc.get_interim_segment() is None
        assert acc.get_full_transcript() == "The quick brown fox."

    # 3. Final transcript does not duplicate interim text
    def test_03_final_transcript_does_not_duplicate_interim_text(self) -> None:
        acc = OrderedSegmentAccumulator()

        acc.ingest_segment(_make_interim("i1", "Good", 0.0, 0.4))
        acc.ingest_segment(_make_interim("i2", "Good morning", 0.0, 0.8))
        acc.ingest_segment(_make_final("f1", "Good morning everyone.", 0.0, 1.2))

        # Must NOT be "Good Good morning Good morning everyone."
        assert acc.final_count == 1
        assert acc.get_full_transcript() == "Good morning everyone."
        assert acc.get_full_transcript(include_interim=True) == "Good morning everyone."

        words = acc.get_full_transcript().split()
        assert words == ["Good", "morning", "everyone."]

    # 4. A late interim event arriving after a final event
    def test_04_late_interim_arriving_after_final_event_discarded(self) -> None:
        acc = OrderedSegmentAccumulator()

        fin_seg = _make_final("f-done", "Audio has been processed completely.", 0.0, 2.5)
        evt_fin = _make_event("evt-f", TranscriptEventType.FINAL, 10, segment=fin_seg)
        acc.ingest_event(evt_fin)
        assert acc.final_count == 1

        # Delayed/stale interim arrives for window 0.0 to 1.0 (already finalized!)
        late_int = _make_interim("i-late", "Audio has been", 0.0, 1.0)
        evt_late = _make_event("evt-late", TranscriptEventType.INTERIM, 5, segment=late_int)

        # Must be safely discarded
        assert acc.ingest_event(evt_late) is False
        assert acc.get_interim_segment() is None
        assert acc.get_full_transcript() == "Audio has been processed completely."

    # 5. An older interim hypothesis arriving after a newer one
    def test_05_older_interim_hypothesis_arriving_after_newer_discarded(self) -> None:
        acc = OrderedSegmentAccumulator()

        # Newer interim arrives first (e.g. out-of-order UDP / network delivery)
        newer_int = _make_interim("i-new", "Weather forecast for today", 0.0, 1.5)
        evt_newer = _make_event("evt-2", TranscriptEventType.INTERIM, seq=2, segment=newer_int)
        assert acc.ingest_event(evt_newer) is True
        assert acc.get_interim_segment().text == "Weather forecast for today"

        # Older interim with earlier sequence and shorter audio arrives late
        older_int = _make_interim("i-old", "Weather forecast", 0.0, 0.8)
        evt_older = _make_event("evt-1", TranscriptEventType.INTERIM, seq=1, segment=older_int)

        # Must NOT overwrite the newer hypothesis
        result = acc.ingest_event(evt_older)
        assert result is False
        assert acc.get_interim_segment().text == "Weather forecast for today"
        assert acc.get_full_transcript(include_interim=True) == "Weather forecast for today"

    # 6. Multiple independent speech segments
    def test_06_multiple_independent_speech_segments(self) -> None:
        acc = OrderedSegmentAccumulator()

        # Segment 1
        acc.ingest_segment(_make_interim("i1", "First thought", 0.0, 0.8))
        assert acc.get_full_transcript(include_interim=True) == "First thought"
        acc.ingest_segment(_make_final("f1", "First thought.", 0.0, 1.0))
        assert acc.get_full_transcript() == "First thought."

        # Segment 2
        acc.ingest_segment(_make_interim("i2", "Second thought", 2.0, 2.8))
        assert acc.get_full_transcript(include_interim=True) == "First thought. Second thought"
        assert acc.get_full_transcript(include_interim=False) == "First thought."
        acc.ingest_segment(_make_final("f2", "Second thought.", 2.0, 3.0))
        assert acc.get_full_transcript() == "First thought. Second thought."

        # Segment 3
        acc.ingest_segment(_make_interim("i3", "Third thought", 4.0, 4.8))
        assert acc.get_full_transcript(include_interim=True) == "First thought. Second thought. Third thought"
        acc.ingest_segment(_make_final("f3", "Third thought.", 4.0, 5.0))

        # Final check
        assert acc.final_count == 3
        assert acc.get_interim_segment() is None
        assert acc.get_full_transcript() == "First thought. Second thought. Third thought."
        assert acc.get_total_duration() == pytest.approx(5.0)

    # 7. Correct chronological ordering after reconciliation
    def test_07_correct_chronological_ordering_after_reconciliation(self) -> None:
        acc = OrderedSegmentAccumulator()

        # Segment B final arrives first (middle: 2.0 to 3.0)
        seg_b = _make_final("f-b", "Middle sentence.", 2.0, 3.0)
        acc.ingest_segment(seg_b)

        # Interim for Segment A arrives (early: 0.0 to 0.8)
        # Note: 0.0-0.8 does not overlap with 2.0-3.0, but ends before 3.0.
        # When segment A finalizes at 0.0-1.0:
        seg_a = _make_final("f-a", "Early sentence.", 0.0, 1.0)
        acc.ingest_segment(seg_a)

        # Segment C final arrives (late: 4.0 to 5.0)
        seg_c = _make_final("f-c", "Late sentence.", 4.0, 5.0)
        acc.ingest_segment(seg_c)

        finals = acc.get_final_segments()
        assert len(finals) == 3
        assert [f.segment_id for f in finals] == ["f-a", "f-b", "f-c"]
        assert acc.get_full_transcript() == "Early sentence. Middle sentence. Late sentence."
        assert acc.get_summary()["is_verified"] is True

    # 8. Legitimate repeated words in separate segments
    def test_08_legitimate_repeated_words_in_separate_segments(self) -> None:
        acc = OrderedSegmentAccumulator()

        # Segment 1: User says "Stop."
        acc.ingest_segment(_make_interim("i-stop-1", "Stop", 1.0, 1.4))
        acc.ingest_segment(_make_final("f-stop-1", "Stop.", 1.0, 1.5))

        # Segment 2: User says "Stop." again later
        acc.ingest_segment(_make_interim("i-stop-2", "Stop", 3.0, 3.4))
        acc.ingest_segment(_make_final("f-stop-2", "Stop.", 3.0, 3.5))

        finals = acc.get_final_segments()
        assert len(finals) == 2
        assert finals[0].text == "Stop."
        assert finals[1].text == "Stop."
        assert finals[0].start_time == 1.0
        assert finals[1].start_time == 3.0
        assert acc.get_full_transcript() == "Stop. Stop."

    # 9. Empty or invalid transcript events, following existing validation rules
    def test_09_empty_and_invalid_transcript_events_validation(self) -> None:
        acc = OrderedSegmentAccumulator()

        # Empty text is permitted for interim (e.g. speech onset trigger before text decoding)
        empty_interim = _make_interim("int-empty", "", 0.0, 0.2)
        evt_empty_int = _make_event("evt-e-int", TranscriptEventType.INTERIM, 1, segment=empty_interim)
        assert acc.ingest_event(evt_empty_int) is True
        assert acc.get_interim_segment().text == ""
        assert acc.get_full_transcript(include_interim=True) == ""

        # Empty text is strictly forbidden for final segments per schemas
        with pytest.raises((STTValidationError, ValidationError)):
            TranscriptSegment(
                segment_id="fin-bad",
                text="   ",
                start_time=0.0,
                end_time=1.0,
                confidence=0.95,
                is_final=True,
            )

        # Inverted timestamps are strictly forbidden
        with pytest.raises((STTValidationError, ValidationError)):
            TranscriptSegment(
                segment_id="fin-bad-time",
                text="Invalid timing",
                start_time=2.0,
                end_time=1.0,
                confidence=0.95,
                is_final=True,
            )

        # Ingesting non-TranscriptEvent raises STTValidationError
        with pytest.raises(STTValidationError):
            acc.ingest_event("not-a-transcript-event")  # type: ignore

        # Accumulator remains uncorrupted
        assert acc.final_count == 0
        assert acc.get_summary()["is_verified"] is True

    # 10. End-to-end reconciliation through the orchestrator
    def test_10_end_to_end_reconciliation_through_orchestrator(self) -> None:
        script = ["Interim to final reconciliation test sentence."]
        adapter = DeterministicFakeTranscriber(script=script, seed=123)
        orchestrator = TranscriptionOrchestrator(adapter=adapter)

        with orchestrator:
            raw_chunk = b"\x00" * 3200  # 100ms PCM16 mono at 16kHz
            chunk = AudioChunk(
                sequence_id=0,
                timestamp=0.0,
                data=raw_chunk,
                format=AudioFormat(sample_rate=16000),
                metadata={"is_last": False},
            )

            # Process chunk 1: emits interim hypothesis
            events1 = orchestrator.process_chunk(chunk, is_last=False)
            assert len(events1) >= 1

            interim_seg = orchestrator.get_interim_segment()
            if interim_seg is not None:
                assert interim_seg.is_final is False
                assert len(interim_seg.text) > 0
                assert orchestrator.get_transcript(include_interim=True) == interim_seg.text
                assert orchestrator.get_transcript(include_interim=False) == ""

            # Feed chunks until finalization
            for seq in range(1, 10):
                c = AudioChunk(
                    sequence_id=seq,
                    timestamp=seq * 0.1,
                    data=raw_chunk,
                    format=AudioFormat(sample_rate=16000),
                    metadata={"is_last": (seq == 9)},
                )
                orchestrator.process_chunk(c, is_last=(seq == 9))

            # Fully finalized
            assert orchestrator.get_interim_segment() is None
            final_text = orchestrator.get_transcript()
            assert final_text == "Interim to final reconciliation test sentence."
            assert len(orchestrator.get_final_segments()) == 1
            assert orchestrator.get_final_segments()[0].is_final is True

            summary = orchestrator.get_summary()
            assert summary["has_active_interim"] is False
            assert summary["final_segments_count"] == 1
            assert summary["is_verified"] is True
