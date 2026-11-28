"""Week 3 Day 16: Session Association and Confidence Thresholds Tests.

Covers:
1. Valid session ID enforcement:
   - Non-empty, non-whitespace session_id string required.
   - Blank or invalid types rejected by schemas and accumulator.
2. Orchestrator session ID propagation:
   - Orchestrator session_id consistently propagated to events emitted by adapter.
   - Normalized error events carry the orchestrator session_id.
3. Accumulator session binding:
   - Accumulator binds to explicit session_id when provided.
   - Accumulator binds to first valid event session_id when initialized with session_id=None.
4. Cross-session event rejection:
   - Events from mismatched sessions rejected.
   - session_mismatches_count incremented.
   - Committed transcript state remains completely uncorrupted.
5. Independent session accumulators:
   - Multiple accumulators isolate transcripts and telemetry completely.
6. Configurable confidence threshold:
   - Default threshold is 0.50.
   - Configurable at initialization on accumulator and orchestrator.
7. High-confidence acceptance:
   - Segments with confidence > threshold committed to final segments and full transcript.
8. Low-confidence quarantine:
   - Segments with confidence < threshold preserved in get_low_confidence_segments().
   - Quarantined segments excluded from get_full_transcript().
9. Threshold update behavior:
   - Dynamically updating min_confidence_threshold applies to future segments.
   - Previously quarantined segments remain quarantined.
10. Boundary confidence handling:
    - Segments with confidence exactly equal to threshold are accepted.
    - Floating point boundary values (0.0 and 1.0) handled safely.
11. Invalid confidence values:
    - NaN, infinity, negative values, and values > 1.0 rejected.
12. Low-confidence metadata preservation:
    - Quarantined low-confidence segments retain all words, timing, confidence, and text.
"""

import math
from typing import Optional
from pydantic import ValidationError
import pytest

from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.adapter import BaseSTTAdapter, STTAdapterConfig, STTAdapterState
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.orchestrator import RetryConfig, TranscriptionOrchestrator
from voice_stt.schemas import (
    AudioChunk,
    STTValidationError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
    WordTiming,
)


def _make_segment(
    seg_id: str,
    text: str,
    start: float,
    end: float,
    confidence: float = 0.90,
    is_final: bool = True,
) -> TranscriptSegment:
    """Helper to construct a valid TranscriptSegment."""
    return TranscriptSegment(
        segment_id=seg_id,
        text=text,
        start_time=start,
        end_time=end,
        confidence=confidence,
        is_final=is_final,
    )


def _make_event(
    event_id: str,
    event_type: TranscriptEventType,
    seq: int,
    session_id: str = "sess-default",
    segment: Optional[TranscriptSegment] = None,
) -> TranscriptEvent:
    """Helper to construct a valid TranscriptEvent."""
    return TranscriptEvent(
        event_id=event_id,
        event_type=event_type,
        sequence_number=seq,
        timestamp=float(seq),
        session_id=session_id,
        segment=segment,
    )


class _FaultyAdapter(BaseSTTAdapter):
    """Adapter that raises an exception for testing error normalization and session propagation."""

    def transcribe_chunk(self, chunk, is_last=False):
        raise ConnectionError("Simulated remote disconnection.")

    def reset(self):
        super().reset()


class TestDay16SessionAssociationAndConfidenceThresholds:
    """Comprehensive test suite for Day 16 session association and confidence filtering."""

    def test_01_valid_session_id_enforcement(self) -> None:
        """Verify non-empty session ID requirement on TranscriptEvent and accumulator."""
        # 1. Blank session_id in TranscriptEvent rejected
        with pytest.raises((STTValidationError, ValidationError)):
            TranscriptEvent(
                event_type=TranscriptEventType.FINAL,
                sequence_number=1,
                session_id="",
                segment=_make_segment("s1", "Valid text.", 0.0, 1.0),
            )

        with pytest.raises((STTValidationError, ValidationError)):
            TranscriptEvent(
                event_type=TranscriptEventType.FINAL,
                sequence_number=1,
                session_id="   ",
                segment=_make_segment("s1", "Valid text.", 0.0, 1.0),
            )

        # 2. Blank session_id in OrderedSegmentAccumulator rejected
        with pytest.raises(STTValidationError):
            OrderedSegmentAccumulator(session_id="")

        with pytest.raises(STTValidationError):
            OrderedSegmentAccumulator(session_id="   ")

        # 3. Valid non-empty session ID accepted
        acc = OrderedSegmentAccumulator(session_id="session-user-123")
        assert acc.session_id == "session-user-123"

    def test_02_orchestrator_session_id_propagation(self, sample_audio_bytes: bytes) -> None:
        """Verify orchestrator session ID is propagated to adapter events and error events."""
        orch_session = "orchestrator-session-999"

        # 1. Successful event session propagation
        orch = TranscriptionOrchestrator(session_id=orch_session)
        with orch:
            chunk = AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes)
            events = orch.process_chunk(chunk)
            assert len(events) >= 1
            for evt in events:
                assert evt.session_id == orch_session

        # 2. Normalized error event session propagation
        faulty_orch = TranscriptionOrchestrator(
            adapter=_FaultyAdapter(),
            session_id="error-session-888",
            retry_config=RetryConfig(max_retries=0),
        )
        with faulty_orch:
            err_chunk = AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes)
            err_events = faulty_orch.process_chunk(err_chunk)
            assert len(err_events) == 1
            assert err_events[0].event_type == TranscriptEventType.ERROR
            assert err_events[0].session_id == "error-session-888"

    def test_03_accumulator_session_binding(self) -> None:
        """Verify explicit binding and first-event automatic binding of accumulator."""
        # Case A: Explicit session binding
        acc_explicit = OrderedSegmentAccumulator(session_id="session-alpha")
        assert acc_explicit.session_id == "session-alpha"

        # Case B: First-event dynamic binding
        acc_dynamic = OrderedSegmentAccumulator(session_id=None)
        assert acc_dynamic.session_id is None

        seg = _make_segment("s1", "First utterance.", 0.0, 1.0)
        evt = _make_event("e1", TranscriptEventType.FINAL, 1, session_id="bound-session-beta", segment=seg)
        accepted = acc_dynamic.ingest_event(evt)
        assert accepted is True
        # Accumulator is now securely bound to bound-session-beta
        assert acc_dynamic.session_id == "bound-session-beta"

    def test_04_cross_session_event_rejection(self) -> None:
        """Verify events with mismatched session IDs are rejected and recorded."""
        acc = OrderedSegmentAccumulator(session_id="session-primary")

        # Ingest legitimate event for session-primary
        seg1 = _make_segment("s1", "Session one committed text.", 0.0, 1.5, confidence=0.95)
        evt1 = _make_event("e1", TranscriptEventType.FINAL, 1, session_id="session-primary", segment=seg1)
        assert acc.ingest_event(evt1) is True
        assert acc.final_count == 1
        assert acc.session_mismatches_count == 0

        # Ingest intruder event from session-foreign
        seg_intruder = _make_segment("s2", "Malicious alien text.", 1.5, 3.0, confidence=0.95)
        evt_intruder = _make_event("e2", TranscriptEventType.FINAL, 2, session_id="session-foreign", segment=seg_intruder)
        assert acc.ingest_event(evt_intruder) is False

        # Invariants:
        assert acc.session_mismatches_count == 1
        assert acc.final_count == 1
        assert acc.get_full_transcript() == "Session one committed text."
        summary = acc.get_summary()
        assert summary["session_mismatches_count"] == 1
        assert summary["full_transcript"] == "Session one committed text."

    def test_05_independent_session_accumulators(self) -> None:
        """Verify multiple accumulators operate with complete session isolation."""
        acc1 = OrderedSegmentAccumulator(session_id="session-tenant-1")
        acc2 = OrderedSegmentAccumulator(session_id="session-tenant-2")

        seg1 = _make_segment("s-t1", "Tenant one notes.", 0.0, 1.0)
        evt1 = _make_event("e-t1", TranscriptEventType.FINAL, 1, session_id="session-tenant-1", segment=seg1)

        seg2 = _make_segment("s-t2", "Tenant two notes.", 0.0, 1.0)
        evt2 = _make_event("e-t2", TranscriptEventType.FINAL, 1, session_id="session-tenant-2", segment=seg2)

        acc1.ingest_event(evt1)
        acc2.ingest_event(evt2)

        # Cross-ingestion is rejected
        assert acc1.ingest_event(evt2) is False
        assert acc2.ingest_event(evt1) is False

        assert acc1.get_full_transcript() == "Tenant one notes."
        assert acc2.get_full_transcript() == "Tenant two notes."
        assert acc1.session_mismatches_count == 1
        assert acc2.session_mismatches_count == 1

    def test_06_configurable_confidence_threshold_defaults(self) -> None:
        """Verify default confidence threshold is 0.50 and configurable."""
        acc_default = OrderedSegmentAccumulator()
        assert acc_default.min_confidence_threshold == 0.50

        acc_custom = OrderedSegmentAccumulator(min_confidence_threshold=0.85)
        assert acc_custom.min_confidence_threshold == 0.85

        orch = TranscriptionOrchestrator(min_confidence_threshold=0.75)
        assert orch.min_confidence_threshold == 0.75

    def test_07_high_confidence_acceptance(self) -> None:
        """Verify segments with confidence >= threshold are committed normally."""
        acc = OrderedSegmentAccumulator(min_confidence_threshold=0.70)

        seg_high = _make_segment("s-high", "High quality transcription.", 0.0, 2.0, confidence=0.92)
        evt = _make_event("e-high", TranscriptEventType.FINAL, 1, segment=seg_high)

        assert acc.ingest_event(evt) is True
        assert acc.final_count == 1
        assert acc.low_confidence_count == 0
        assert len(acc.get_low_confidence_segments()) == 0
        assert acc.get_full_transcript() == "High quality transcription."

    def test_08_low_confidence_quarantine(self) -> None:
        """Verify segments below threshold are quarantined and excluded from full transcript."""
        acc = OrderedSegmentAccumulator(min_confidence_threshold=0.60)

        # 1. Low confidence segment (0.45 < 0.60)
        seg_low = _make_segment("s-low", "Mumbled unintelligible speech", 0.0, 1.5, confidence=0.45)
        evt_low = _make_event("e-low", TranscriptEventType.FINAL, 1, segment=seg_low)
        assert acc.ingest_event(evt_low) is True

        # 2. High confidence segment (0.88 >= 0.60)
        seg_high = _make_segment("s-high", "Clear crisp utterance.", 1.5, 3.0, confidence=0.88)
        evt_high = _make_event("e-high", TranscriptEventType.FINAL, 2, segment=seg_high)
        assert acc.ingest_event(evt_high) is True

        # Invariants:
        assert acc.final_count == 1
        assert acc.low_confidence_count == 1
        quarantined = acc.get_low_confidence_segments()
        assert len(quarantined) == 1
        assert quarantined[0].segment_id == "s-low"
        assert quarantined[0].text == "Mumbled unintelligible speech"
        assert quarantined[0].confidence == 0.45

        # get_full_transcript must ONLY contain the clear utterance
        assert acc.get_full_transcript() == "Clear crisp utterance."
        summary = acc.get_summary()
        assert summary["low_confidence_count"] == 1
        assert summary["final_segments_count"] == 1

    def test_09_threshold_update_behavior(self) -> None:
        """Verify dynamic threshold update affects future segments without reclassifying old ones."""
        acc = OrderedSegmentAccumulator(min_confidence_threshold=0.80)

        # Segment with confidence 0.70 ingested under 0.80 threshold -> quarantined
        seg1 = _make_segment("s1", "First utterance.", 0.0, 1.0, confidence=0.70)
        acc.ingest_event(_make_event("e1", TranscriptEventType.FINAL, 1, segment=seg1))
        assert acc.final_count == 0
        assert acc.low_confidence_count == 1

        # Now dynamically lower the threshold to 0.50
        acc.min_confidence_threshold = 0.50
        assert acc.min_confidence_threshold == 0.50

        # Historical quarantined segments remain quarantined
        assert acc.final_count == 0
        assert acc.low_confidence_count == 1

        # Future incoming segment with same confidence (0.70) under new threshold (0.50) -> committed
        seg2 = _make_segment("s2", "Second utterance.", 1.0, 2.0, confidence=0.70)
        acc.ingest_event(_make_event("e2", TranscriptEventType.FINAL, 2, segment=seg2))
        assert acc.final_count == 1
        assert acc.low_confidence_count == 1
        assert acc.get_full_transcript() == "Second utterance."

    def test_10_boundary_confidence_handling(self) -> None:
        """Verify boundary confidence values: equality, 0.0, and 1.0."""
        # 1. Exact equality to threshold (0.60 == 0.60) must be accepted
        acc = OrderedSegmentAccumulator(min_confidence_threshold=0.60)
        seg_exact = _make_segment("s-exact", "Exact boundary match.", 0.0, 1.0, confidence=0.60)
        acc.ingest_event(_make_event("e1", TranscriptEventType.FINAL, 1, segment=seg_exact))
        assert acc.final_count == 1
        assert acc.low_confidence_count == 0

        # 2. Extreme boundary 0.0 (all non-negative confidence accepted)
        acc_zero = OrderedSegmentAccumulator(min_confidence_threshold=0.0)
        seg_zero = _make_segment("s-zero", "Zero confidence speech.", 0.0, 1.0, confidence=0.0)
        acc_zero.ingest_event(_make_event("e2", TranscriptEventType.FINAL, 1, segment=seg_zero))
        assert acc_zero.final_count == 1
        assert acc_zero.low_confidence_count == 0

        # 3. Extreme boundary 1.0 (only perfect 1.0 confidence accepted)
        acc_perfect = OrderedSegmentAccumulator(min_confidence_threshold=1.0)
        seg_99 = _make_segment("s-99", "Near perfect.", 0.0, 1.0, confidence=0.9999)
        seg_100 = _make_segment("s-100", "Perfect.", 1.0, 2.0, confidence=1.0)
        acc_perfect.ingest_event(_make_event("e3", TranscriptEventType.FINAL, 1, segment=seg_99))
        acc_perfect.ingest_event(_make_event("e4", TranscriptEventType.FINAL, 2, segment=seg_100))
        assert acc_perfect.final_count == 1
        assert acc_perfect.low_confidence_count == 1
        assert acc_perfect.get_full_transcript() == "Perfect."

    def test_11_invalid_confidence_values(self) -> None:
        """Verify NaN, infinity, negative, and > 1.0 values are rejected."""
        # 1. Accumulator threshold rejection
        for invalid in (-0.01, 1.01, float("nan"), float("inf"), float("-inf"), "0.5"):
            with pytest.raises(STTValidationError):
                OrderedSegmentAccumulator(min_confidence_threshold=invalid)  # type: ignore

        acc = OrderedSegmentAccumulator()
        for invalid in (-0.5, 1.5, float("nan"), float("inf")):
            with pytest.raises(STTValidationError):
                acc.min_confidence_threshold = invalid

        # 2. TranscriptSegment confidence rejection
        for bad_conf in (-0.1, 1.1, float("nan"), float("inf")):
            with pytest.raises((STTValidationError, ValidationError)):
                TranscriptSegment(
                    segment_id="bad-c",
                    text="Invalid confidence",
                    start_time=0.0,
                    end_time=1.0,
                    confidence=bad_conf,
                )

    def test_12_low_confidence_metadata_preservation(self) -> None:
        """Verify quarantined low-confidence segments retain word-level timings and metadata."""
        acc = OrderedSegmentAccumulator(min_confidence_threshold=0.80)

        words = [
            WordTiming(word="Low", start_time=0.0, end_time=0.3, confidence=0.45),
            WordTiming(word="confidence", start_time=0.3, end_time=0.8, confidence=0.40),
        ]
        seg_meta = TranscriptSegment(
            segment_id="seg-preserve-meta",
            text="Low confidence",
            start_time=0.0,
            end_time=0.8,
            confidence=0.42,
            is_final=True,
            language="en-US",
            words=words,
        )
        evt = _make_event("evt-meta", TranscriptEventType.FINAL, 1, segment=seg_meta)
        acc.ingest_event(evt)

        quarantined = acc.get_low_confidence_segments()
        assert len(quarantined) == 1
        q = quarantined[0]
        assert q.segment_id == "seg-preserve-meta"
        assert q.text == "Low confidence"
        assert q.confidence == 0.42
        assert q.language == "en-US"
        assert len(q.words) == 2
        assert q.words[0].word == "Low"
        assert q.words[1].word == "confidence"

    def test_13_confidence_threshold_orchestrator_inheritance(self) -> None:
        """Verify priority resolution of min_confidence_threshold in TranscriptionOrchestrator."""
        # 1. Adapter threshold of 0.85 inherited by the orchestrator when omitted on orchestrator
        adapter_85 = DeterministicFakeTranscriber(
            config=STTAdapterConfig(min_confidence_threshold=0.85),
        )
        orch_inherited = TranscriptionOrchestrator(adapter=adapter_85)
        assert orch_inherited.min_confidence_threshold == 0.85
        assert orch_inherited.accumulator.min_confidence_threshold == 0.85

        # 2. Explicit orchestrator threshold overriding the adapter threshold
        orch_override = TranscriptionOrchestrator(
            adapter=adapter_85,
            min_confidence_threshold=0.65,
        )
        assert orch_override.min_confidence_threshold == 0.65
        assert orch_override.accumulator.min_confidence_threshold == 0.65

        # 3. Default threshold of 0.50 when neither orchestrator nor adapter threshold is configured
        orch_default = TranscriptionOrchestrator()
        assert orch_default.min_confidence_threshold == 0.50
        assert orch_default.accumulator.min_confidence_threshold == 0.50

        # Compatibility with bare adapter without a config object
        class _BareAdapter(BaseSTTAdapter):
            def __init__(self):
                super().__init__()
                self.config = None  # No config

            def transcribe_chunk(self, chunk, is_last=False):
                return []

            def reset(self):
                pass

        bare_orch = TranscriptionOrchestrator(adapter=_BareAdapter())
        assert bare_orch.min_confidence_threshold == 0.50

        # 4. Invalid threshold values being rejected on orchestrator constructor
        for bad_thresh in (-0.05, 1.05, float("nan"), float("inf"), float("-inf")):
            with pytest.raises(STTValidationError):
                TranscriptionOrchestrator(min_confidence_threshold=bad_thresh)
