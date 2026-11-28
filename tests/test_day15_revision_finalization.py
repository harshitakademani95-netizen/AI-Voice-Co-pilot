"""Week 3 Day 15: Transcript Revision and Finalization Tests.

Covers:
1. Interim-to-revision progression:
   - Valid transition from an INTERIM hypothesis to a REVISION update.
   - REVISION updates active interim state and increments revision telemetry.
2. Revision schema validation:
   - REVISION events must have a valid non-null segment.
   - REVISION events require segment.is_final == False.
   - Rejection of invalid payloads.
3. Duplicate revision suppression:
   - Identical revision event_id delivery is suppressed.
   - Identical segment content & boundary revision is deduplicated.
4. Regressive revision rejection:
   - Older revision with lower sequence number is discarded.
   - Revision with shorter end_time than current hypothesis is discarded.
5. Finalization and interim-state clearing:
   - FINALIZATION event commits segment to final segments.
   - FINALIZATION event clears active interim segment.
   - FINALIZATION requires segment.is_final == True.
6. Duplicate finalization suppression:
   - Repeated delivery of same finalization event is suppressed.
   - Repeated delivery of identical final segment payload is suppressed.
7. Late revision rejection:
   - Revision arriving for an audio window already committed by finalization is discarded.
8. Orchestrator revision and finalization event flow:
   - End-to-end processing through TranscriptionOrchestrator with INTERIM -> REVISION -> FINALIZATION lifecycle.
"""

from typing import List, Optional
from pydantic import ValidationError
import pytest

from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.orchestrator import TranscriptionOrchestrator
from voice_stt.schemas import (
    AudioChunk,
    STTValidationError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


def _make_segment(
    seg_id: str,
    text: str,
    start: float,
    end: float,
    confidence: float = 0.90,
    is_final: bool = False,
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
    segment: Optional[TranscriptSegment] = None,
    session_id: str = "day15-test-session",
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


class TestDay15TranscriptRevisionAndFinalization:
    """Comprehensive test suite for Day 15 revision and finalization lifecycle."""

    def test_01_interim_to_revision_progression(self) -> None:
        """Verify progression from an initial INTERIM event to subsequent REVISION updates."""
        acc = OrderedSegmentAccumulator(session_id="session-progression")

        # 1. Initial interim hypothesis
        seg1 = _make_segment("seg-int-1", "Hello", 0.0, 0.5, is_final=False)
        evt1 = _make_event("evt-int-1", TranscriptEventType.INTERIM, 1, segment=seg1, session_id="session-progression")
        assert acc.ingest_event(evt1) is True
        assert acc.get_interim_segment() is not None
        assert acc.get_interim_segment().text == "Hello"
        assert acc.final_count == 0
        assert acc.revision_count == 0
        assert acc.interim_updates_count == 1

        # 2. First revision
        seg2 = _make_segment("seg-rev-1", "Hello world", 0.0, 1.0, is_final=False)
        evt2 = _make_event("evt-rev-1", TranscriptEventType.REVISION, 2, segment=seg2, session_id="session-progression")
        assert acc.ingest_event(evt2) is True
        assert acc.get_interim_segment() is not None
        assert acc.get_interim_segment().text == "Hello world"
        assert acc.final_count == 0
        assert acc.revision_count == 1
        assert acc.interim_updates_count == 2

        # 3. Second revision
        seg3 = _make_segment("seg-rev-2", "Hello world how are", 0.0, 1.5, is_final=False)
        evt3 = _make_event("evt-rev-2", TranscriptEventType.REVISION, 3, segment=seg3, session_id="session-progression")
        assert acc.ingest_event(evt3) is True
        assert acc.get_interim_segment().text == "Hello world how are"
        assert acc.revision_count == 2
        assert acc.interim_updates_count == 3
        assert acc.get_full_transcript(include_interim=True) == "Hello world how are"
        assert acc.get_full_transcript(include_interim=False) == ""

    def test_02_revision_schema_validation(self) -> None:
        """Validate schema invariants for REVISION and FINALIZATION events."""
        # 1. REVISION must have segment
        with pytest.raises((STTValidationError, ValidationError)) as exc1:
            TranscriptEvent(
                event_id="bad-rev-1",
                event_type=TranscriptEventType.REVISION,
                sequence_number=1,
                segment=None,
            )
        assert "require a non-null 'segment' payload" in str(exc1.value)

        # 2. REVISION requires is_final == False
        final_seg = _make_segment("seg-f", "Finished text.", 0.0, 1.0, is_final=True)
        with pytest.raises((STTValidationError, ValidationError)) as exc2:
            TranscriptEvent(
                event_id="bad-rev-2",
                event_type=TranscriptEventType.REVISION,
                sequence_number=1,
                segment=final_seg,
            )
        assert "segment.is_final is True" in str(exc2.value)

        # 3. FINALIZATION requires is_final == True
        interim_seg = _make_segment("seg-i", "Tentative text", 0.0, 1.0, is_final=False)
        with pytest.raises((STTValidationError, ValidationError)) as exc3:
            TranscriptEvent(
                event_id="bad-fin-1",
                event_type=TranscriptEventType.FINALIZATION,
                sequence_number=1,
                segment=interim_seg,
            )
        assert "segment.is_final is False" in str(exc3.value)

        # 4. FINALIZATION requires non-empty text
        with pytest.raises((STTValidationError, ValidationError)) as exc4:
            TranscriptSegment(
                segment_id="seg-empty",
                text="   ",
                start_time=0.0,
                end_time=1.0,
                confidence=0.9,
                is_final=True,
            )
        assert "Final segment text must not be empty" in str(exc4.value)

    def test_03_duplicate_revision_suppression(self) -> None:
        """Verify identical revision events and identical revision hypotheses are suppressed."""
        acc = OrderedSegmentAccumulator(session_id="sess-dup")
        seg = _make_segment("seg-rev", "Searching for answers", 0.0, 1.2, is_final=False)
        evt = _make_event("evt-rev-dup", TranscriptEventType.REVISION, 1, segment=seg, session_id="sess-dup")

        # Ingest first time -> Accepted
        assert acc.ingest_event(evt) is True
        assert acc.revision_count == 1
        assert acc.duplicates_suppressed == 0

        # Ingest exact same event -> Suppressed by event_id
        assert acc.ingest_event(evt) is False
        assert acc.revision_count == 1
        assert acc.duplicates_suppressed == 1

        # Ingest new event with same segment content and boundary -> Suppressed by segment hypothesis match
        evt_twin = _make_event("evt-rev-twin", TranscriptEventType.REVISION, 2, segment=seg, session_id="sess-dup")
        assert acc.ingest_event(evt_twin) is False
        assert acc.revision_count == 1
        assert acc.duplicates_suppressed == 2

    def test_04_regressive_revision_rejection(self) -> None:
        """Verify older, out-of-order, or regressive revisions cannot overwrite newer hypotheses."""
        acc = OrderedSegmentAccumulator(session_id="sess-regr")

        # Active hypothesis: seq 5, window [0.0, 2.0], text "Advanced artificial intelligence"
        seg_newer = _make_segment("seg-newer", "Advanced artificial intelligence", 0.0, 2.0, is_final=False)
        evt_newer = _make_event("evt-5", TranscriptEventType.REVISION, 5, segment=seg_newer, session_id="sess-regr")
        assert acc.ingest_event(evt_newer) is True
        assert acc.get_interim_segment().text == "Advanced artificial intelligence"

        # 1. Regressive sequence arrival: seq 3 arrives after seq 5 (longer duration 2.1s)
        seg_older_seq = _make_segment("seg-seq-3", "Advanced artificial", 0.0, 2.1, is_final=False)
        evt_older_seq = _make_event("evt-3", TranscriptEventType.REVISION, 3, segment=seg_older_seq, session_id="sess-regr")
        assert acc.ingest_event(evt_older_seq) is False
        assert acc.get_interim_segment().text == "Advanced artificial intelligence"

        # 2. Older sequence with shorter duration: seq 2 arrives after seq 5 (1.0s < 2.0s)
        seg_older_short = _make_segment("seg-seq-2", "Advanced", 0.0, 1.0, is_final=False)
        evt_older_short = _make_event("evt-2", TranscriptEventType.REVISION, 2, segment=seg_older_short, session_id="sess-regr")
        assert acc.ingest_event(evt_older_short) is False
        assert acc.get_interim_segment().text == "Advanced artificial intelligence"

        # 3. Direct segment ingestion without sequence metadata cannot prove novelty -> rejected
        seg_unsequenced_shorter = _make_segment("seg-newer", "Advanced", 0.0, 1.0, is_final=False)
        assert acc.ingest_segment(seg_unsequenced_shorter) is False
        assert acc.get_interim_segment().text == "Advanced artificial intelligence"

    def test_05_finalization_and_interim_state_clearing(self) -> None:
        """Verify FINALIZATION commits immutable segment and clears active interim hypothesis."""
        acc = OrderedSegmentAccumulator(session_id="sess-fin")

        # Ingest interim hypothesis
        seg_int = _make_segment("seg-in-flight", "Voice co-pilot is", 0.0, 1.2, is_final=False)
        evt_int = _make_event("evt-int", TranscriptEventType.INTERIM, 1, segment=seg_int, session_id="sess-fin")
        acc.ingest_event(evt_int)
        assert acc.get_interim_segment() is not None

        # Ingest revision
        seg_rev = _make_segment("seg-in-flight", "Voice co-pilot is ready", 0.0, 1.8, is_final=False)
        evt_rev = _make_event("evt-rev", TranscriptEventType.REVISION, 2, segment=seg_rev, session_id="sess-fin")
        acc.ingest_event(evt_rev)
        assert acc.get_interim_segment().text == "Voice co-pilot is ready"

        # Finalize
        seg_fin = _make_segment(
            "seg-in-flight",
            "Voice co-pilot is ready to assist.",
            0.0,
            2.2,
            confidence=0.97,
            is_final=True,
        )
        evt_fin = _make_event(
            "evt-fin",
            TranscriptEventType.FINALIZATION,
            3,
            segment=seg_fin,
            session_id="sess-fin",
        )
        assert acc.ingest_event(evt_fin) is True

        # Invariants:
        # 1. Interim state is completely cleared
        assert acc.get_interim_segment() is None
        # 2. Final segment is committed
        assert acc.final_count == 1
        finals = acc.get_final_segments()
        assert finals[0].text == "Voice co-pilot is ready to assist."
        assert finals[0].is_final is True
        # 3. Full transcript reflects final text
        assert acc.get_full_transcript() == "Voice co-pilot is ready to assist."

    def test_06_duplicate_finalization_suppression(self) -> None:
        """Verify repeated delivery of finalization events and payloads is safely suppressed."""
        acc = OrderedSegmentAccumulator(session_id="sess-dup-fin")

        seg = _make_segment("seg-committed", "Final confirmed sentence.", 0.0, 1.5, confidence=0.96, is_final=True)
        evt = _make_event("evt-fin-1", TranscriptEventType.FINALIZATION, 1, segment=seg, session_id="sess-dup-fin")

        # First ingestion accepted
        assert acc.ingest_event(evt) is True
        assert acc.final_count == 1
        assert acc.duplicates_suppressed == 0

        # Exact same event ingested again
        assert acc.ingest_event(evt) is False
        assert acc.final_count == 1
        assert acc.duplicates_suppressed == 1

        # Different event_id but identical segment_id
        evt_diff_id = _make_event("evt-fin-2", TranscriptEventType.FINALIZATION, 2, segment=seg, session_id="sess-dup-fin")
        assert acc.ingest_event(evt_diff_id) is False
        assert acc.final_count == 1
        assert acc.duplicates_suppressed == 2

        # Different event_id and segment_id but identical content and boundary
        seg_clone = _make_segment("seg-twin", "Final confirmed sentence.", 0.0, 1.5, confidence=0.96, is_final=True)
        evt_clone = _make_event("evt-fin-3", TranscriptEventType.FINALIZATION, 3, segment=seg_clone, session_id="sess-dup-fin")
        assert acc.ingest_event(evt_clone) is False
        assert acc.final_count == 1
        assert acc.duplicates_suppressed == 3

    def test_07_late_revision_rejection_after_finalization(self) -> None:
        """Late revision arriving for an already finalized audio interval must be discarded."""
        acc = OrderedSegmentAccumulator(session_id="sess-late")

        # Commit finalization for [0.0, 2.0]
        seg_fin = _make_segment("seg-fin-1", "Committed first phrase.", 0.0, 2.0, confidence=0.95, is_final=True)
        evt_fin = _make_event("evt-fin-1", TranscriptEventType.FINALIZATION, 1, segment=seg_fin, session_id="sess-late")
        acc.ingest_event(evt_fin)
        assert acc.final_count == 1

        # Now late revision arrives whose audio interval ends at 1.8s (<= 2.0s)
        late_rev = _make_segment("seg-late", "Stale revision text", 0.0, 1.8, is_final=False)
        evt_late = _make_event("evt-late", TranscriptEventType.REVISION, 2, segment=late_rev, session_id="sess-late")

        assert acc.ingest_event(evt_late) is False
        # Active interim remains None and full transcript uncorrupted
        assert acc.get_interim_segment() is None
        assert acc.get_full_transcript() == "Committed first phrase."

        # However, a revision for future audio (e.g. [2.0, 3.5]) must be accepted
        future_rev = _make_segment("seg-future", "Next sentence in progress", 2.0, 3.5, is_final=False)
        evt_future = _make_event("evt-future", TranscriptEventType.REVISION, 3, segment=future_rev, session_id="sess-late")
        assert acc.ingest_event(evt_future) is True
        assert acc.get_interim_segment().text == "Next sentence in progress"

    def test_08_orchestrator_revision_finalization_flow(self, sample_audio_bytes: bytes) -> None:
        """Verify full end-to-end orchestration with INTERIM -> REVISION -> FINALIZATION lifecycle."""
        adapter = DeterministicFakeTranscriber(
            script=["The automated testing pipeline succeeds."],
            emit_revisions=True,
            use_finalization=True,
        )
        orch = TranscriptionOrchestrator(adapter=adapter)

        with orch:
            # Chunk 0: emits INTERIM ("The")
            chunk0 = AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes)
            events0 = orch.process_chunk(chunk0)
            assert len(events0) == 1
            assert events0[0].event_type == TranscriptEventType.INTERIM
            assert orch.get_interim_segment() is not None
            assert orch.get_interim_segment().text == "The"
            assert orch.get_final_segments() == []

            # Chunk 1: emits REVISION ("The automated")
            chunk1 = AudioChunk(sequence_id=1, timestamp=0.1, data=sample_audio_bytes)
            events1 = orch.process_chunk(chunk1)
            assert len(events1) == 1
            assert events1[0].event_type == TranscriptEventType.REVISION
            assert orch.get_interim_segment().text == "The automated"
            assert orch.get_final_segments() == []

            # Chunk 2: emits REVISION ("The automated testing")
            chunk2 = AudioChunk(sequence_id=2, timestamp=0.2, data=sample_audio_bytes)
            events2 = orch.process_chunk(chunk2)
            assert len(events2) == 1
            assert events2[0].event_type == TranscriptEventType.REVISION
            assert orch.get_interim_segment().text == "The automated testing"

            # Chunk 3: emits REVISION ("The automated testing pipeline")
            chunk3 = AudioChunk(sequence_id=3, timestamp=0.3, data=sample_audio_bytes)
            events3 = orch.process_chunk(chunk3)
            assert len(events3) == 1
            assert events3[0].event_type == TranscriptEventType.REVISION

            # Chunk 4 (final): emits FINALIZATION ("The automated testing pipeline succeeds.")
            chunk4 = AudioChunk(
                sequence_id=4,
                timestamp=0.4,
                data=sample_audio_bytes,
                metadata={"is_last": True},
            )
            events4 = orch.process_chunk(chunk4, is_last=True)
            assert any(e.event_type == TranscriptEventType.FINALIZATION for e in events4)

            # Verification of final state
            assert orch.get_interim_segment() is None
            finals = orch.get_final_segments()
            assert len(finals) == 1
            assert finals[0].text == "The automated testing pipeline succeeds."
            assert orch.get_full_transcript() == "The automated testing pipeline succeeds."
            summary = orch.get_summary()
            assert summary["revision_count"] >= 3
            assert summary["final_segments_count"] == 1

    def test_09_legitimate_shorter_duration_revision_with_newer_sequence(self) -> None:
        """Verify that a newer-sequence revision with a legitimately shorter duration is accepted."""
        acc = OrderedSegmentAccumulator(session_id="sess-contract")

        # 1. Initial interim: seq 1, [0.0, 1.8], "I think he is arriving"
        seg1 = _make_segment("seg-int-1", "I think he is arriving", 0.0, 1.8, is_final=False)
        evt1 = _make_event("evt-1", TranscriptEventType.INTERIM, 1, segment=seg1, session_id="sess-contract")
        assert acc.ingest_event(evt1) is True
        assert acc.get_interim_segment().text == "I think he is arriving"
        assert acc.get_interim_segment().end_time == 1.8

        # 2. Linguistic correction / contraction: seq 2 > 1, [0.0, 1.2], "I think he left"
        seg2 = _make_segment("seg-int-1", "I think he left", 0.0, 1.2, is_final=False)
        evt2 = _make_event("evt-2", TranscriptEventType.REVISION, 2, segment=seg2, session_id="sess-contract")
        assert acc.ingest_event(evt2) is True
        assert acc.get_interim_segment().text == "I think he left"
        assert acc.get_interim_segment().end_time == 1.2
        assert acc.revision_count == 1

        # 3. Finalization commits the contracted segment
        seg_final = _make_segment("seg-int-1", "I think he left.", 0.0, 1.2, confidence=0.97, is_final=True)
        evt_final = _make_event("evt-3", TranscriptEventType.FINALIZATION, 3, segment=seg_final, session_id="sess-contract")
        assert acc.ingest_event(evt_final) is True
        assert acc.get_interim_segment() is None
        assert acc.final_count == 1
        assert acc.get_full_transcript() == "I think he left."
