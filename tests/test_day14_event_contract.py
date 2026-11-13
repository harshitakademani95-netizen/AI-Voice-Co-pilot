"""Contract tests for TranscriptEvent schemas and accumulation rules.

Week 2 – Day 14: Contract Tests & End-to-End Demo.

Verifies:
1. TranscriptEvent objects strictly conform to Pydantic schemas.
2. Interim and final events enforce correct typing and segment constraints.
3. Required fields and data contracts are present and validated.
4. Segment IDs and event IDs are handled consistently.
5. Timestamps and sequence metadata remain mathematically valid.
6. Duplicate events and duplicate segments are suppressed cleanly.
7. Out-of-order events are reordered chronologically.
8. Interim hypotheses are cleanly replaced by corresponding finalized segments.
9. Legitimate repeated words at distinct timestamps are preserved.
10. Malformed or invalid events are rejected safely.
"""

from __future__ import annotations

import math
import pytest
from pydantic import ValidationError

from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.orchestrator import sanitize_error_message
from voice_stt.schemas import (
    STTErrorDetail,
    STTValidationError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
    WordTiming,
)


class TestDay14EventContract:
    """Rigorous contract test suite for Transcript Events and Accumulation."""

    # 1. TranscriptEvent schema structure and required fields
    def test_01_event_schema_structure_and_forbid_extra(self) -> None:
        """TranscriptEvent validates required fields and forbids unexpected extra attributes."""
        event = TranscriptEvent(
            event_id="evt-contract-001",
            event_type=TranscriptEventType.INTERIM,
            sequence_number=0,
            timestamp=0.02,
            session_id="session-event-01",
            segment=TranscriptSegment(
                segment_id="seg-contract-001",
                text="hello",
                start_time=0.0,
                end_time=0.5,
                confidence=0.92,
                is_final=False,
            ),
        )
        assert event.event_id == "evt-contract-001"
        assert event.event_type == TranscriptEventType.INTERIM
        assert event.sequence_number == 0
        assert event.timestamp == 0.02
        assert event.session_id == "session-event-01"
        assert event.segment is not None
        assert event.segment.text == "hello"

        # Forbid extra fields
        with pytest.raises(ValidationError):
            TranscriptEvent(
                event_id="evt-002",
                event_type=TranscriptEventType.STREAM_COMPLETED,
                sequence_number=1,
                timestamp=0.1,
                session_id="session-01",
                unexpected_field="disallowed",  # type: ignore[call-arg]
            )

    # 2. Interim event type enforcement
    def test_02_interim_event_contract(self) -> None:
        """TranscriptEventType.INTERIM requires segment with is_final=False."""
        # Valid interim event
        seg_interim = TranscriptSegment(
            segment_id="seg-int-01",
            text="interim text",
            start_time=0.0,
            end_time=0.8,
            confidence=0.88,
            is_final=False,
        )
        event = TranscriptEvent(
            event_id="evt-int-01",
            event_type=TranscriptEventType.INTERIM,
            sequence_number=0,
            timestamp=0.8,
            session_id="session-01",
            segment=seg_interim,
        )
        assert event.event_type == TranscriptEventType.INTERIM
        assert event.segment.is_final is False

        # Reject interim event without segment
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptEvent(
                event_id="evt-int-invalid",
                event_type=TranscriptEventType.INTERIM,
                sequence_number=1,
                timestamp=0.8,
                session_id="session-01",
                segment=None,
            )

        # Reject interim event with a finalized segment
        seg_final = TranscriptSegment(
            segment_id="seg-fin-01",
            text="final text",
            start_time=0.0,
            end_time=0.8,
            confidence=0.95,
            is_final=True,
        )
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptEvent(
                event_id="evt-int-mismatch",
                event_type=TranscriptEventType.INTERIM,
                sequence_number=2,
                timestamp=0.8,
                session_id="session-01",
                segment=seg_final,
            )

    # 3. Final event type enforcement
    def test_03_final_event_contract(self) -> None:
        """TranscriptEventType.FINAL requires segment with is_final=True."""
        seg_final = TranscriptSegment(
            segment_id="seg-fin-02",
            text="committed speech sentence",
            start_time=0.0,
            end_time=1.5,
            confidence=0.99,
            is_final=True,
        )
        event = TranscriptEvent(
            event_id="evt-fin-02",
            event_type=TranscriptEventType.FINAL,
            sequence_number=3,
            timestamp=1.5,
            session_id="session-01",
            segment=seg_final,
        )
        assert event.event_type == TranscriptEventType.FINAL
        assert event.segment.is_final is True

        # Reject final event without segment
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptEvent(
                event_id="evt-fin-invalid",
                event_type=TranscriptEventType.FINAL,
                sequence_number=4,
                timestamp=1.5,
                session_id="session-01",
                segment=None,
            )

        # Reject final event with an interim segment
        seg_interim = TranscriptSegment(
            segment_id="seg-int-02",
            text="tentative hypothesis",
            start_time=0.0,
            end_time=1.5,
            confidence=0.80,
            is_final=False,
        )
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptEvent(
                event_id="evt-fin-mismatch",
                event_type=TranscriptEventType.FINAL,
                sequence_number=5,
                timestamp=1.5,
                session_id="session-01",
                segment=seg_interim,
            )

    # 4. Error event contract and secrets masking
    def test_04_error_event_contract_and_secrets_masking(self) -> None:
        """TranscriptEventType.ERROR requires an STTErrorDetail with masked sensitive tokens."""
        raw_msg = "Invalid auth token: Bearer sk-abcdefghijklmnopqrstuvwxyz123456"

        # Direct construction with raw unmasked credential raises ValidationError
        with pytest.raises(ValidationError):
            STTErrorDetail(
                code="AUTHENTICATION_FAILED",
                message=raw_msg,
                retryable=False,
            )

        # Sanitized error message is masked and accepted cleanly
        sanitized_msg = sanitize_error_message(raw_msg)
        assert "[REDACTED" in sanitized_msg

        error = STTErrorDetail(
            code="AUTHENTICATION_FAILED",
            message=sanitized_msg,
            retryable=False,
            details={"endpoint": "/v1/audio/transcriptions"},
        )
        assert "[REDACTED_API_KEY]" in error.message

        event = TranscriptEvent(
            event_id="evt-err-01",
            event_type=TranscriptEventType.ERROR,
            sequence_number=1,
            timestamp=0.5,
            session_id="session-01",
            error=error,
        )
        assert event.event_type == TranscriptEventType.ERROR
        assert event.error is not None
        assert event.error.code == "AUTHENTICATION_FAILED"

        # Reject error event missing error field
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptEvent(
                event_id="evt-err-invalid",
                event_type=TranscriptEventType.ERROR,
                sequence_number=2,
                timestamp=0.5,
                session_id="session-01",
                error=None,
            )

    # 5. Out-of-order segment reconciliation
    def test_05_out_of_order_segment_reconciliation(self) -> None:
        """Segments arriving in reversed order are accumulated into strict chronological order."""
        accumulator = OrderedSegmentAccumulator()

        seg1 = TranscriptSegment(segment_id="s1", text="first", start_time=0.0, end_time=1.0, is_final=True, confidence=0.9)
        seg2 = TranscriptSegment(segment_id="s2", text="second", start_time=1.2, end_time=2.0, is_final=True, confidence=0.9)
        seg3 = TranscriptSegment(segment_id="s3", text="third", start_time=2.2, end_time=3.0, is_final=True, confidence=0.9)

        # Ingest out of order: 3, 1, 2
        accumulator.ingest_segment(seg3)
        accumulator.ingest_segment(seg1)
        accumulator.ingest_segment(seg2)

        final_segments = accumulator.get_final_segments()
        assert len(final_segments) == 3
        assert [s.segment_id for s in final_segments] == ["s1", "s2", "s3"]
        assert accumulator.get_full_transcript() == "first second third"
        assert accumulator.out_of_order_count >= 1

    # 6. Duplicate suppression contract
    def test_06_duplicate_suppression_contract(self) -> None:
        """Duplicate event IDs, segment IDs, and identical text boundaries are suppressed."""
        accumulator = OrderedSegmentAccumulator()

        seg = TranscriptSegment(segment_id="s_dup", text="hello duplicate", start_time=0.0, end_time=1.0, is_final=True, confidence=0.9)
        evt1 = TranscriptEvent(
            event_id="e_dup_1",
            event_type=TranscriptEventType.FINAL,
            sequence_number=0,
            timestamp=1.0,
            session_id="sess-1",
            segment=seg,
        )

        # First ingestion accepted
        assert accumulator.ingest_event(evt1) is True
        assert len(accumulator.get_final_segments()) == 1

        # Duplicate event ID rejected
        assert accumulator.ingest_event(evt1) is False

        # Different event ID, but duplicate segment ID rejected
        evt2 = TranscriptEvent(
            event_id="e_dup_2",
            event_type=TranscriptEventType.FINAL,
            sequence_number=1,
            timestamp=1.1,
            session_id="sess-1",
            segment=seg,
        )
        assert accumulator.ingest_event(evt2) is False

        # Different event ID and segment ID, but identical text and audio window rejected
        seg_same_content = TranscriptSegment(
            segment_id="s_dup_diff_id",
            text="hello duplicate",
            start_time=0.0,
            end_time=1.0,
            is_final=True,
            confidence=0.9,
        )
        evt3 = TranscriptEvent(
            event_id="e_dup_3",
            event_type=TranscriptEventType.FINAL,
            sequence_number=2,
            timestamp=1.2,
            session_id="sess-1",
            segment=seg_same_content,
        )
        assert accumulator.ingest_event(evt3) is False

        # Verify only one segment remains and telemetry counts 3 suppressions
        assert len(accumulator.get_final_segments()) == 1
        assert accumulator.duplicates_suppressed == 3

    # 7. Interim hypothesis replacement by final segment
    def test_07_interim_hypothesis_replaced_by_final_segment(self) -> None:
        """Finalized segment clears and replaces the active interim hypothesis."""
        accumulator = OrderedSegmentAccumulator()

        # Ingest interim event
        interim_seg = TranscriptSegment(
            segment_id="seg_stream_1",
            text="voice co",
            start_time=0.0,
            end_time=0.5,
            is_final=False,
            confidence=0.75,
        )
        evt_interim = TranscriptEvent(
            event_id="evt_stream_1",
            event_type=TranscriptEventType.INTERIM,
            sequence_number=0,
            timestamp=0.5,
            session_id="sess-stream",
            segment=interim_seg,
        )
        accumulator.ingest_event(evt_interim)
        assert accumulator.get_interim_segment() is not None
        assert accumulator.get_interim_segment().text == "voice co"
        assert accumulator.get_full_transcript(include_interim=True) == "voice co"

        # Ingest final event for the same span
        final_seg = TranscriptSegment(
            segment_id="seg_stream_final",
            text="voice copilot",
            start_time=0.0,
            end_time=1.0,
            is_final=True,
            confidence=0.98,
        )
        evt_final = TranscriptEvent(
            event_id="evt_stream_final",
            event_type=TranscriptEventType.FINAL,
            sequence_number=1,
            timestamp=1.0,
            session_id="sess-stream",
            segment=final_seg,
        )
        accumulator.ingest_event(evt_final)

        # Interim hypothesis must be cleared, finalized segment committed
        assert accumulator.get_interim_segment() is None
        assert len(accumulator.get_final_segments()) == 1
        assert accumulator.get_full_transcript(include_interim=True) == "voice copilot"
        assert accumulator.get_full_transcript(include_interim=False) == "voice copilot"

    # 8. Late interim after finalization is discarded
    def test_08_late_interim_after_finalization_discarded(self) -> None:
        """An interim event arriving with end_time <= max_finalized_end is safely discarded."""
        accumulator = OrderedSegmentAccumulator()

        # Commit final segment for [0.0, 2.0]
        final_seg = TranscriptSegment(
            segment_id="final_span",
            text="speech already finalized",
            start_time=0.0,
            end_time=2.0,
            is_final=True,
            confidence=0.95,
        )
        accumulator.ingest_segment(final_seg)
        assert len(accumulator.get_final_segments()) == 1

        # Late interim arrives for [0.5, 1.8]
        late_interim = TranscriptSegment(
            segment_id="late_int",
            text="stale partial",
            start_time=0.5,
            end_time=1.8,
            is_final=False,
            confidence=0.70,
        )
        result = accumulator.ingest_segment(late_interim)
        assert result is False
        assert accumulator.get_interim_segment() is None
        assert accumulator.get_full_transcript() == "speech already finalized"

    # 9. Legitimate repeated words at distinct timestamps preserved
    def test_09_repeated_words_at_distinct_timestamps_preserved(self) -> None:
        """Consecutive repeated words in different segments/timestamps are not falsely deduplicated."""
        accumulator = OrderedSegmentAccumulator()

        seg_yes_1 = TranscriptSegment(
            segment_id="yes_1",
            text="yes",
            start_time=1.0,
            end_time=1.4,
            is_final=True,
            confidence=0.95,
        )
        seg_yes_2 = TranscriptSegment(
            segment_id="yes_2",
            text="yes",
            start_time=2.0,
            end_time=2.4,
            is_final=True,
            confidence=0.95,
        )

        assert accumulator.ingest_segment(seg_yes_1) is True
        assert accumulator.ingest_segment(seg_yes_2) is True
        assert len(accumulator.get_final_segments()) == 2
        assert accumulator.get_full_transcript() == "yes yes"

    # 10. Word-level timing validation
    def test_10_word_timing_validation(self) -> None:
        """WordTiming models validate boundaries against segment span."""
        word1 = WordTiming(word="speech", start_time=0.0, end_time=0.4, confidence=0.96)
        word2 = WordTiming(word="to", start_time=0.4, end_time=0.6, confidence=0.95)
        word3 = WordTiming(word="text", start_time=0.6, end_time=1.0, confidence=0.97)

        seg = TranscriptSegment(
            segment_id="seg-words",
            text="speech to text",
            start_time=0.0,
            end_time=1.0,
            confidence=0.96,
            is_final=True,
            words=[word1, word2, word3],
        )
        assert len(seg.words) == 3
        assert seg.words[0].word == "speech"

        # Word timing exceeding segment boundary is rejected
        word_overflow = WordTiming(word="overflow", start_time=0.0, end_time=2.5, confidence=0.9)
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptSegment(
                segment_id="seg-invalid-words",
                text="overflow",
                start_time=0.0,
                end_time=1.0,
                confidence=0.9,
                is_final=True,
                words=[word_overflow],
            )
