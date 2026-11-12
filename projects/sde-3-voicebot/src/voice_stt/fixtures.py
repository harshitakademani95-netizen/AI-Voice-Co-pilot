"""Named Deterministic Fixtures for AI Voice Co-Pilot (W2 - STT).

This module defines the canonical named demonstration and diagnostic fixtures:
- Fixture A: Normal Transcript (Student Developer split across chronological final segments)
- Fixture B: Interim-to-Final Lifecycle (evolution of partial hypotheses into committed final segment)
- Fixture C: Out-of-Order Delivery (segments emitted out-of-order, sorted chronologically by accumulator)
- Fixture D: Duplicate Delivery (repeated delivery of the exact same event, deduplicated by accumulator)
- Fixture E: Invalid Payload (malformed payload rejected with clean error; accumulator remains uncorrupted)
- Fixture F: Simulated Adapter Failure & Recovery (controlled failure event, error status, clean recovery)
"""

from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional
from voice_stt.schemas import (
    STTErrorDetail,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
    WordTiming,
)


class STTFixture(NamedTuple):
    fixture_id: str
    name: str
    description: str
    persona: str
    expected_transcript: str
    events: List[TranscriptEvent]
    is_failure_scenario: bool = False
    raw_invalid_payload: Optional[Dict[str, Any]] = None


def get_fixture_a_normal() -> STTFixture:
    """Fixture A: Normal Multi-Segment Transcript (Student Developer).

    Scenario: "Why is this application showing this error?"
    Split across two valid final segments:
    - Segment 1: "Why is this application" (0.0s -> 0.8s, conf: 0.96)
    - Segment 2: "showing this error?" (0.8s -> 1.5s, conf: 0.97)
    """
    seg1 = TranscriptSegment(
        segment_id="fix-a-seg-001",
        text="Why is this application",
        start_time=0.0,
        end_time=0.8,
        confidence=0.96,
        is_final=True,
        language="en",
        words=[
            WordTiming(word="Why", start_time=0.0, end_time=0.2, confidence=0.97),
            WordTiming(word="is", start_time=0.2, end_time=0.35, confidence=0.96),
            WordTiming(word="this", start_time=0.35, end_time=0.5, confidence=0.95),
            WordTiming(word="application", start_time=0.5, end_time=0.8, confidence=0.98),
        ],
    )
    seg2 = TranscriptSegment(
        segment_id="fix-a-seg-002",
        text="showing this error?",
        start_time=0.8,
        end_time=1.5,
        confidence=0.97,
        is_final=True,
        language="en",
        words=[
            WordTiming(word="showing", start_time=0.8, end_time=1.05, confidence=0.96),
            WordTiming(word="this", start_time=1.05, end_time=1.2, confidence=0.97),
            WordTiming(word="error?", start_time=1.2, end_time=1.5, confidence=0.98),
        ],
    )

    evt1 = TranscriptEvent(
        event_id="fix-a-evt-001",
        event_type=TranscriptEventType.FINAL,
        sequence_number=1,
        timestamp=1000.8,
        segment=seg1,
    )
    evt2 = TranscriptEvent(
        event_id="fix-a-evt-002",
        event_type=TranscriptEventType.FINAL,
        sequence_number=2,
        timestamp=1001.5,
        segment=seg2,
    )

    return STTFixture(
        fixture_id="A",
        name="Fixture A: Normal Multi-Segment Transcript",
        description="Standard student developer utterance correctly split into two chronological final segments.",
        persona="Student Developer",
        expected_transcript="Why is this application showing this error?",
        events=[evt1, evt2],
    )


def get_fixture_b_interim_to_final() -> STTFixture:
    """Fixture B: Interim-to-Final Lifecycle Visibility (Research Student).

    Scenario: "Explain the methodology shown on this page."
    Demonstrates 4 progressive interim updates followed by 1 committed final segment.
    """
    int1 = TranscriptSegment(
        segment_id="fix-b-seg-int1",
        text="Explain",
        start_time=0.0,
        end_time=0.3,
        confidence=0.82,
        is_final=False,
    )
    int2 = TranscriptSegment(
        segment_id="fix-b-seg-int2",
        text="Explain the methodology",
        start_time=0.0,
        end_time=0.7,
        confidence=0.86,
        is_final=False,
    )
    int3 = TranscriptSegment(
        segment_id="fix-b-seg-int3",
        text="Explain the methodology shown on",
        start_time=0.0,
        end_time=1.1,
        confidence=0.89,
        is_final=False,
    )
    final_seg = TranscriptSegment(
        segment_id="fix-b-seg-final",
        text="Explain the methodology shown on this page.",
        start_time=0.0,
        end_time=1.4,
        confidence=0.96,
        is_final=True,
    )

    events = [
        TranscriptEvent(event_id="fix-b-evt-1", event_type=TranscriptEventType.INTERIM, sequence_number=1, timestamp=1000.3, segment=int1),
        TranscriptEvent(event_id="fix-b-evt-2", event_type=TranscriptEventType.INTERIM, sequence_number=2, timestamp=1000.7, segment=int2),
        TranscriptEvent(event_id="fix-b-evt-3", event_type=TranscriptEventType.INTERIM, sequence_number=3, timestamp=1001.1, segment=int3),
        TranscriptEvent(event_id="fix-b-evt-4", event_type=TranscriptEventType.FINAL, sequence_number=4, timestamp=1001.4, segment=final_seg),
    ]

    return STTFixture(
        fixture_id="B",
        name="Fixture B: Interim-to-Final Lifecycle",
        description="Four in-flight interim hypotheses culminating in one immutable final segment.",
        persona="Research Student",
        expected_transcript="Explain the methodology shown on this page.",
        events=events,
    )


def get_fixture_c_out_of_order() -> STTFixture:
    """Fixture C: Out-of-Order Delivery (General User).

    Three segments arriving in arrival order: [Segment 2, Segment 3, Segment 1].
    The accumulator must insert them in audio chronological order: [Seg 1, Seg 2, Seg 3].
    """
    seg1 = TranscriptSegment(segment_id="fix-c-seg-1", text="Find my project", start_time=0.0, end_time=0.9, confidence=0.95, is_final=True)
    seg2 = TranscriptSegment(segment_id="fix-c-seg-2", text="report I downloaded", start_time=0.9, end_time=1.8, confidence=0.94, is_final=True)
    seg3 = TranscriptSegment(segment_id="fix-c-seg-3", text="yesterday afternoon.", start_time=1.8, end_time=2.6, confidence=0.96, is_final=True)

    # Dispatched out of order: Seg 2 -> Seg 3 -> Seg 1
    events = [
        TranscriptEvent(event_id="fix-c-evt-2", event_type=TranscriptEventType.FINAL, sequence_number=1, timestamp=1001.0, segment=seg2),
        TranscriptEvent(event_id="fix-c-evt-3", event_type=TranscriptEventType.FINAL, sequence_number=2, timestamp=1001.2, segment=seg3),
        TranscriptEvent(event_id="fix-c-evt-1", event_type=TranscriptEventType.FINAL, sequence_number=3, timestamp=1001.5, segment=seg1),
    ]

    return STTFixture(
        fixture_id="C",
        name="Fixture C: Out-of-Order Delivery",
        description="Deliberately disordered arrival order (2, 3, 1) to verify chronological audio-time sorting.",
        persona="General User",
        expected_transcript="Find my project report I downloaded yesterday afternoon.",
        events=events,
    )


def get_fixture_d_duplicate_delivery() -> STTFixture:
    """Fixture D: Duplicate Delivery.

    Emits Segment 1, then duplicates Segment 1 with identical segment_id and event_id,
    followed by Segment 2. The duplicate must be suppressed without duplicating text.
    """
    seg1 = TranscriptSegment(segment_id="fix-d-seg-1", text="Check service status.", start_time=0.0, end_time=1.0, confidence=0.97, is_final=True)
    seg2 = TranscriptSegment(segment_id="fix-d-seg-2", text="All systems operational.", start_time=1.0, end_time=2.2, confidence=0.98, is_final=True)

    evt1 = TranscriptEvent(event_id="fix-d-evt-1", event_type=TranscriptEventType.FINAL, sequence_number=1, timestamp=1000.5, segment=seg1)
    evt1_dup = TranscriptEvent(event_id="fix-d-evt-1", event_type=TranscriptEventType.FINAL, sequence_number=2, timestamp=1000.8, segment=seg1)
    evt2 = TranscriptEvent(event_id="fix-d-evt-2", event_type=TranscriptEventType.FINAL, sequence_number=3, timestamp=1001.5, segment=seg2)

    return STTFixture(
        fixture_id="D",
        name="Fixture D: Duplicate Delivery",
        description="Duplicate delivery of segment 1 to verify deduplication without text duplication.",
        persona="System Monitor",
        expected_transcript="Check service status. All systems operational.",
        events=[evt1, evt1_dup, evt2],
    )


def get_fixture_e_invalid_payload() -> STTFixture:
    """Fixture E: Invalid Payload Rejection.

    Contains a valid baseline segment followed by an invalid event payload (inverted timestamps).
    Ensures that validation rejection occurs cleanly and does not corrupt existing final segments.
    """
    valid_seg = TranscriptSegment(
        segment_id="fix-e-seg-baseline",
        text="Baseline valid segment.",
        start_time=0.0,
        end_time=1.0,
        confidence=0.95,
        is_final=True,
    )
    baseline_evt = TranscriptEvent(
        event_id="fix-e-evt-1",
        event_type=TranscriptEventType.FINAL,
        sequence_number=1,
        timestamp=1000.5,
        segment=valid_seg,
    )

    invalid_payload = {
        "text": "Corrupted segment with inverted boundaries",
        "start_time": 5.0,
        "end_time": 2.0,  # INVERTED: end < start!
        "confidence": 1.25,  # OUT OF BOUNDS: > 1.0!
        "is_final": True,
    }

    return STTFixture(
        fixture_id="E",
        name="Fixture E: Invalid Payload Rejection",
        description="Malformed payload with inverted timestamps (end < start) and confidence > 1.0.",
        persona="Fault Injection",
        expected_transcript="Baseline valid segment.",
        events=[baseline_evt],
        is_failure_scenario=True,
        raw_invalid_payload=invalid_payload,
    )


def get_fixture_f_simulated_failure() -> STTFixture:
    """Fixture F: Simulated Adapter Failure & Clean Recovery.

    Emits Segment 1, followed by a simulated hardware/engine error event.
    Verifies error telemetry and tests recovery via pipeline reset.
    """
    seg1 = TranscriptSegment(
        segment_id="fix-f-seg-1",
        text="Transcription started cleanly.",
        start_time=0.0,
        end_time=1.2,
        confidence=0.95,
        is_final=True,
    )
    evt1 = TranscriptEvent(
        event_id="fix-f-evt-1",
        event_type=TranscriptEventType.FINAL,
        sequence_number=1,
        timestamp=1000.5,
        segment=seg1,
    )

    error_detail = STTErrorDetail(
        code="SIMULATED_TRANSCRIBER_ERROR",
        message="Simulated engine dropout: downstream buffer overflow detected.",
        retryable=True,
        details={"buffer_depth": 0, "simulated": True},
    )

    error_evt = TranscriptEvent(
        event_id="fix-f-evt-err",
        event_type=TranscriptEventType.ERROR,
        sequence_number=2,
        timestamp=1001.3,
        error=error_detail,
    )

    return STTFixture(
        fixture_id="F",
        name="Fixture F: Simulated Adapter Failure & Recovery",
        description="Controlled engine error to test error reporting and pipeline reset recovery.",
        persona="Resilience Tester",
        expected_transcript="Transcription started cleanly.",
        events=[evt1, error_evt],
        is_failure_scenario=True,
    )


FIXTURE_REGISTRY: Dict[str, STTFixture] = {
    "A": get_fixture_a_normal(),
    "B": get_fixture_b_interim_to_final(),
    "C": get_fixture_c_out_of_order(),
    "D": get_fixture_d_duplicate_delivery(),
    "E": get_fixture_e_invalid_payload(),
    "F": get_fixture_f_simulated_failure(),
}


def get_fixture(fixture_id: str) -> STTFixture:
    """Retrieve a fixture by its identifier ('A', 'B', 'C', 'D', 'E', 'F')."""
    key = fixture_id.upper().strip()
    if key not in FIXTURE_REGISTRY:
        raise KeyError(f"Unknown fixture ID '{fixture_id}'. Expected one of {list(FIXTURE_REGISTRY.keys())}.")
    return FIXTURE_REGISTRY[key]


def get_all_fixtures() -> List[STTFixture]:
    """Retrieve list of all canonical fixtures in order."""
    return [FIXTURE_REGISTRY[k] for k in sorted(FIXTURE_REGISTRY.keys())]

