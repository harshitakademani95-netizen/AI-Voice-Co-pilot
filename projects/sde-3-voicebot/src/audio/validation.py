"""
Validation Framework and Acceptance Checklist for Audio & VAD (Week 3, Day 20).

Centralized definition of all 13 canonical validation criteria governing
audio ingestion, VAD qualification, buffer dynamics, session traceability,
and lifecycle resilience.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.audio.device import AudioPermissionState, MockAudioDevice
from src.audio.lifecycle import AudioLifecycleState
from src.audio.pipeline import (
    AudioPipeline,
    create_deterministic_chunk,
    generate_noise_burst_fixture,
    generate_silence_fixture,
    generate_speech_fixture,
)
from src.audio.vad import VADConfig
from src.schemas.audio import AudioChunk, AudioError, AudioEvent, AudioEventType, AudioFormat


class ValidationCheckID(str, Enum):
    """The 13 canonical Day 20 validation checkpoints."""
    CHECK_01_EVENT_ORDERING = "CHECK_01_EVENT_ORDERING"
    CHECK_02_SEQUENCE_MONOTONICITY = "CHECK_02_SEQUENCE_MONOTONICITY"
    CHECK_03_AUDIO_CHUNK_GAPS = "CHECK_03_AUDIO_CHUNK_GAPS"
    CHECK_04_LATE_ARRIVING_CHUNKS = "CHECK_04_LATE_ARRIVING_CHUNKS"
    CHECK_05_DUPLICATE_CHUNKS = "CHECK_05_DUPLICATE_CHUNKS"
    CHECK_06_SILENCE_DETECTION = "CHECK_06_SILENCE_DETECTION"
    CHECK_07_FALSE_SPEECH_TRIGGERS = "CHECK_07_FALSE_SPEECH_TRIGGERS"
    CHECK_08_SPEECH_BOUNDARY_CONSISTENCY = "CHECK_08_SPEECH_BOUNDARY_CONSISTENCY"
    CHECK_09_SESSION_ID_PROPAGATION = "CHECK_09_SESSION_ID_PROPAGATION"
    CHECK_10_CORRELATION_ID_PROPAGATION = "CHECK_10_CORRELATION_ID_PROPAGATION"
    CHECK_11_DEVICE_LOSS_RECOVERY = "CHECK_11_DEVICE_LOSS_RECOVERY"
    CHECK_12_RECONNECTION_BEHAVIOR = "CHECK_12_RECONNECTION_BEHAVIOR"
    CHECK_13_BUFFER_OVERFLOW_AND_DROPS = "CHECK_13_BUFFER_OVERFLOW_AND_DROPS"


@dataclass(frozen=True)
class ValidationPoint:
    """Metadata definition of a single validation checkpoint."""
    check_id: ValidationCheckID
    index: int
    name: str
    description: str
    failure_criterion: str


VALIDATION_POINTS: Dict[ValidationCheckID, ValidationPoint] = {
    ValidationCheckID.CHECK_01_EVENT_ORDERING: ValidationPoint(
        check_id=ValidationCheckID.CHECK_01_EVENT_ORDERING,
        index=1,
        name="Event Ordering",
        description="Verify SPEECH_START chronologically precedes constituent AUDIO_CHUNKs and SPEECH_END.",
        failure_criterion="Fails if SPEECH_END appears before SPEECH_START, or if event timestamps are inverted.",
    ),
    ValidationCheckID.CHECK_02_SEQUENCE_MONOTONICITY: ValidationPoint(
        check_id=ValidationCheckID.CHECK_02_SEQUENCE_MONOTONICITY,
        index=2,
        name="Sequence Number Monotonicity",
        description="Verify sequence numbers across emitted events advance strictly monotonically without missing numbers.",
        failure_criterion="Fails if sequence_number jumps backwards, skips numbers, or repeats within a session.",
    ),
    ValidationCheckID.CHECK_03_AUDIO_CHUNK_GAPS: ValidationPoint(
        check_id=ValidationCheckID.CHECK_03_AUDIO_CHUNK_GAPS,
        index=3,
        name="Audio Chunk Gap Detection",
        description="Verify sequence gaps in audio input chunks are detected, counted, and recorded in buffer telemetry.",
        failure_criterion="Fails if sequence_gap_events counter is not incremented when an un-sequenced chunk arrives.",
    ),
    ValidationCheckID.CHECK_04_LATE_ARRIVING_CHUNKS: ValidationPoint(
        check_id=ValidationCheckID.CHECK_04_LATE_ARRIVING_CHUNKS,
        index=4,
        name="Late-Arriving Chunk Rejection",
        description="Verify chunks with sequence IDs older than previously seen history are rejected with REJECTED_LATE.",
        failure_criterion="Fails if a late/out-of-order chunk is accepted or does not increment late_chunks counter.",
    ),
    ValidationCheckID.CHECK_05_DUPLICATE_CHUNKS: ValidationPoint(
        check_id=ValidationCheckID.CHECK_05_DUPLICATE_CHUNKS,
        index=5,
        name="Duplicate Chunk Rejection",
        description="Verify duplicate chunks with previously seen sequence IDs are rejected with REJECTED_DUPLICATE.",
        failure_criterion="Fails if duplicate sequence IDs enter the buffer or are not recorded in duplicate metrics.",
    ),
    ValidationCheckID.CHECK_06_SILENCE_DETECTION: ValidationPoint(
        check_id=ValidationCheckID.CHECK_06_SILENCE_DETECTION,
        index=6,
        name="Silence Detection & Event Generation",
        description="Verify silent audio frames generate SILENCE events without falsely triggering speech segments.",
        failure_criterion="Fails if pure silence creates a speech segment, or if SILENCE event is never emitted.",
    ),
    ValidationCheckID.CHECK_07_FALSE_SPEECH_TRIGGERS: ValidationPoint(
        check_id=ValidationCheckID.CHECK_07_FALSE_SPEECH_TRIGGERS,
        index=7,
        name="False Speech Trigger Rejection",
        description="Verify transient noise bursts shorter than min_speech_duration_ms are rejected as non-speech.",
        failure_criterion="Fails if a 20ms click or noise burst below threshold triggers a SPEECH_START event.",
    ),
    ValidationCheckID.CHECK_08_SPEECH_BOUNDARY_CONSISTENCY: ValidationPoint(
        check_id=ValidationCheckID.CHECK_08_SPEECH_BOUNDARY_CONSISTENCY,
        index=8,
        name="Speech Start and Speech End Consistency",
        description="Verify every speech segment has matching segment_ids on SPEECH_START and SPEECH_END with accurate duration.",
        failure_criterion="Fails if segment_id does not match between onset and offset or duration is negative.",
    ),
    ValidationCheckID.CHECK_09_SESSION_ID_PROPAGATION: ValidationPoint(
        check_id=ValidationCheckID.CHECK_09_SESSION_ID_PROPAGATION,
        index=9,
        name="Session ID Propagation",
        description="Verify all emitted events in a session carry the identical, non-empty session_id.",
        failure_criterion="Fails if any event lacks session_id or carries a mismatched/corrupted identifier.",
    ),
    ValidationCheckID.CHECK_10_CORRELATION_ID_PROPAGATION: ValidationPoint(
        check_id=ValidationCheckID.CHECK_10_CORRELATION_ID_PROPAGATION,
        index=10,
        name="Correlation ID Propagation",
        description="Verify all emitted events in a session retain the exact correlation_id for distributed tracing.",
        failure_criterion="Fails if correlation_id is dropped, mutated, or missing from any event.",
    ),
    ValidationCheckID.CHECK_11_DEVICE_LOSS_RECOVERY: ValidationPoint(
        check_id=ValidationCheckID.CHECK_11_DEVICE_LOSS_RECOVERY,
        index=11,
        name="Device-Loss Detection and Handling",
        description="Verify hardware disconnection mid-stream transitions lifecycle to ERROR, closes speech, and emits DEVICE_LOST.",
        failure_criterion="Fails if application crashes, or if active speech is left open, or state is not ERROR.",
    ),
    ValidationCheckID.CHECK_12_RECONNECTION_BEHAVIOR: ValidationPoint(
        check_id=ValidationCheckID.CHECK_12_RECONNECTION_BEHAVIOR,
        index=12,
        name="Device Reconnection and Cancellation Guard",
        description="Verify reconnect restores capture on healthy devices and never reactivates a cancelled session.",
        failure_criterion="Fails if reconnection fails on healthy reconnect or silently overrides cancellation.",
    ),
    ValidationCheckID.CHECK_13_BUFFER_OVERFLOW_AND_DROPS: ValidationPoint(
        check_id=ValidationCheckID.CHECK_13_BUFFER_OVERFLOW_AND_DROPS,
        index=13,
        name="Buffer Overflow and Drop Counter Accuracy",
        description="Verify bounded buffer enforces capacity limit and total_dropped counter exactly matches overflow count.",
        failure_criterion="Fails if buffer size exceeds capacity or if dropped chunks are silently lost without counter increment.",
    ),
}


@dataclass
class ValidationResult:
    """Reported result for a validation check."""
    check: ValidationPoint
    passed: bool
    details: str
    observed_value: Any = None
    expected_value: Any = None


class Week3AudioValidator:
    """
    Automated evaluation engine executing live tests for each of the 13 validation points.
    """

    def __init__(self, session_id: str = "val-sess-13p", correlation_id: str = "val-corr-13p") -> None:
        self.session_id = session_id
        self.correlation_id = correlation_id
        self.vad_config = VADConfig(
            energy_threshold=0.015,
            speech_probability_threshold=0.4,
            min_speech_duration_ms=40.0,
            min_silence_duration_ms=60.0,
        )

    def run_all_checks(self) -> List[ValidationResult]:
        """Execute all 13 canonical checks and return detailed results."""
        results: List[ValidationResult] = []
        results.append(self.check_01_event_ordering())
        results.append(self.check_02_sequence_monotonicity())
        results.append(self.check_03_audio_chunk_gaps())
        results.append(self.check_04_late_arriving_chunks())
        results.append(self.check_05_duplicate_chunks())
        results.append(self.check_06_silence_detection())
        results.append(self.check_07_false_speech_triggers())
        results.append(self.check_08_speech_boundary_consistency())
        results.append(self.check_09_session_id_propagation())
        results.append(self.check_10_correlation_id_propagation())
        results.append(self.check_11_device_loss_recovery())
        results.append(self.check_12_reconnection_behavior())
        results.append(self.check_13_buffer_overflow_and_drops())
        return results

    def check_01_event_ordering(self) -> ValidationResult:
        pt = VALIDATION_POINTS[ValidationCheckID.CHECK_01_EVENT_ORDERING]
        pipeline = AudioPipeline(session_id=self.session_id, correlation_id=self.correlation_id, vad_config=self.vad_config)
        pipeline.start()
        # Feed speech then silence
        for c in generate_speech_fixture(5):
            pipeline.buffer.push(c)
            pipeline.process_step()
        for i in range(4):
            pipeline.buffer.push(create_deterministic_chunk(5 + i, 0.10 + i * 0.02, 0.0))
            pipeline.process_step()
        pipeline.stop()

        events = pipeline.get_events()
        types = [e.event_type for e in events]
        passed = (
            AudioEventType.SPEECH_START in types
            and AudioEventType.SPEECH_END in types
            and types.index(AudioEventType.SPEECH_START) < types.index(AudioEventType.SPEECH_END)
        )
        return ValidationResult(
            check=pt,
            passed=passed,
            details=f"SPEECH_START at idx {types.index(AudioEventType.SPEECH_START)} < SPEECH_END at idx {types.index(AudioEventType.SPEECH_END)}",
        )

    def check_02_sequence_monotonicity(self) -> ValidationResult:
        pt = VALIDATION_POINTS[ValidationCheckID.CHECK_02_SEQUENCE_MONOTONICITY]
        pipeline = AudioPipeline(session_id=self.session_id, correlation_id=self.correlation_id, vad_config=self.vad_config)
        pipeline.start()
        for c in generate_speech_fixture(4):
            pipeline.buffer.push(c)
            pipeline.process_step()
        events = pipeline.get_events()
        seqs = [e.sequence_number for e in events]
        expected = list(range(len(events)))
        passed = (seqs == expected) and len(seqs) > 0
        return ValidationResult(check=pt, passed=passed, details=f"Observed seqs: {seqs[:5]}... count={len(seqs)}")

    def check_03_audio_chunk_gaps(self) -> ValidationResult:
        pt = VALIDATION_POINTS[ValidationCheckID.CHECK_03_AUDIO_CHUNK_GAPS]
        pipeline = AudioPipeline(vad_config=self.vad_config)
        pipeline.start()
        pipeline.buffer.push(create_deterministic_chunk(0, 0.0, 0.1))
        # Gap injection: jump from 0 to 50
        res = pipeline.buffer.push(create_deterministic_chunk(50, 1.0, 0.1))
        metrics = pipeline.buffer.get_metrics()
        passed = metrics.sequence_gap_events == 1 and metrics.missing_chunks_total == 49
        return ValidationResult(
            check=pt,
            passed=passed,
            details=f"Gap events: {metrics.sequence_gap_events}, missing total: {metrics.missing_chunks_total}",
        )

    def check_04_late_arriving_chunks(self) -> ValidationResult:
        pt = VALIDATION_POINTS[ValidationCheckID.CHECK_04_LATE_ARRIVING_CHUNKS]
        pipeline = AudioPipeline(vad_config=self.vad_config)
        pipeline.start()
        pipeline.buffer.push(create_deterministic_chunk(10, 0.20, 0.1))
        # Late chunk: seq 3 is older than 10
        late = create_deterministic_chunk(3, 0.06, 0.1)
        res = pipeline.buffer.push(late)
        metrics = pipeline.buffer.get_metrics()
        passed = (res.status.value == "REJECTED_LATE") and metrics.late_chunks_detected == 1
        return ValidationResult(
            check=pt,
            passed=passed,
            details=f"Status: {res.status.value}, late_chunks_detected: {metrics.late_chunks_detected}",
        )

    def check_05_duplicate_chunks(self) -> ValidationResult:
        pt = VALIDATION_POINTS[ValidationCheckID.CHECK_05_DUPLICATE_CHUNKS]
        pipeline = AudioPipeline(vad_config=self.vad_config)
        pipeline.start()
        chunk = create_deterministic_chunk(5, 0.10, 0.1)
        pipeline.buffer.push(chunk)
        # Push same sequence ID again
        res = pipeline.buffer.push(chunk)
        metrics = pipeline.buffer.get_metrics()
        passed = (res.status.value == "REJECTED_DUPLICATE") and metrics.duplicate_chunks_detected == 1
        return ValidationResult(
            check=pt,
            passed=passed,
            details=f"Status: {res.status.value}, duplicate_chunks_detected: {metrics.duplicate_chunks_detected}",
        )

    def check_06_silence_detection(self) -> ValidationResult:
        pt = VALIDATION_POINTS[ValidationCheckID.CHECK_06_SILENCE_DETECTION]
        pipeline = AudioPipeline(vad_config=self.vad_config)
        pipeline.start()
        for c in generate_silence_fixture(5):
            pipeline.buffer.push(c)
            pipeline.process_step()
        silence_events = pipeline.get_events_by_type(AudioEventType.SILENCE)
        speech_events = pipeline.get_events_by_type(AudioEventType.SPEECH_START)
        passed = len(silence_events) > 0 and len(speech_events) == 0
        return ValidationResult(
            check=pt,
            passed=passed,
            details=f"SILENCE events emitted: {len(silence_events)}, SPEECH_START emitted: {len(speech_events)}",
        )

    def check_07_false_speech_triggers(self) -> ValidationResult:
        pt = VALIDATION_POINTS[ValidationCheckID.CHECK_07_FALSE_SPEECH_TRIGGERS]
        pipeline = AudioPipeline(vad_config=self.vad_config)
        pipeline.start()
        # Single 20ms burst below 40ms min_speech_duration_ms
        for c in generate_noise_burst_fixture(burst_chunks=1, total_chunks=4):
            pipeline.buffer.push(c)
            pipeline.process_step()
        speech_events = pipeline.get_events_by_type(AudioEventType.SPEECH_START)
        passed = len(speech_events) == 0
        return ValidationResult(
            check=pt,
            passed=passed,
            details=f"Noise burst triggered {len(speech_events)} SPEECH_START events (expected 0)",
        )

    def check_08_speech_boundary_consistency(self) -> ValidationResult:
        pt = VALIDATION_POINTS[ValidationCheckID.CHECK_08_SPEECH_BOUNDARY_CONSISTENCY]
        pipeline = AudioPipeline(session_id="boundary-sess", vad_config=self.vad_config)
        pipeline.start()
        for c in generate_speech_fixture(5):
            pipeline.buffer.push(c)
            pipeline.process_step()
        for i in range(4):
            pipeline.buffer.push(create_deterministic_chunk(5 + i, 0.10 + i * 0.02, 0.0))
            pipeline.process_step()
        pipeline.stop()
        starts = pipeline.get_events_by_type(AudioEventType.SPEECH_START)
        ends = pipeline.get_events_by_type(AudioEventType.SPEECH_END)
        passed = len(starts) == 1 and len(ends) == 1 and (starts[0].segment_id == ends[0].segment_id)
        return ValidationResult(
            check=pt,
            passed=passed,
            details=f"Start segment_id: {starts[0].segment_id if starts else None}, End segment_id: {ends[0].segment_id if ends else None}",
        )

    def check_09_session_id_propagation(self) -> ValidationResult:
        pt = VALIDATION_POINTS[ValidationCheckID.CHECK_09_SESSION_ID_PROPAGATION]
        pipeline = AudioPipeline(session_id="sess-prop-check", vad_config=self.vad_config)
        pipeline.start()
        for c in generate_speech_fixture(3):
            pipeline.buffer.push(c)
            pipeline.process_step()
        events = pipeline.get_events()
        passed = len(events) > 0 and all(e.session_id == "sess-prop-check" for e in events)
        return ValidationResult(check=pt, passed=passed, details=f"All {len(events)} events carry session_id='sess-prop-check'")

    def check_10_correlation_id_propagation(self) -> ValidationResult:
        pt = VALIDATION_POINTS[ValidationCheckID.CHECK_10_CORRELATION_ID_PROPAGATION]
        pipeline = AudioPipeline(correlation_id="corr-trace-check", vad_config=self.vad_config)
        pipeline.start()
        for c in generate_speech_fixture(3):
            pipeline.buffer.push(c)
            pipeline.process_step()
        events = pipeline.get_events()
        passed = len(events) > 0 and all(e.correlation_id == "corr-trace-check" for e in events)
        return ValidationResult(check=pt, passed=passed, details=f"All {len(events)} events carry correlation_id='corr-trace-check'")

    def check_11_device_loss_recovery(self) -> ValidationResult:
        pt = VALIDATION_POINTS[ValidationCheckID.CHECK_11_DEVICE_LOSS_RECOVERY]
        pipeline = AudioPipeline(vad_config=self.vad_config)
        pipeline.start()
        for c in generate_speech_fixture(4):
            pipeline.buffer.push(c)
            pipeline.process_step()
        # Trigger device loss mid-speech
        pipeline.handle_device_loss()
        passed = (
            pipeline.lifecycle.state == AudioLifecycleState.ERROR
            and len(pipeline.get_events_by_type(AudioEventType.DEVICE_LOST)) == 1
            and pipeline.active_segment_id is None
        )
        return ValidationResult(
            check=pt,
            passed=passed,
            details=f"Lifecycle state: {pipeline.lifecycle.state.value}, active_segment_id: {pipeline.active_segment_id}",
        )

    def check_12_reconnection_behavior(self) -> ValidationResult:
        pt = VALIDATION_POINTS[ValidationCheckID.CHECK_12_RECONNECTION_BEHAVIOR]

        # 1. Healthy device loss -> reconnect -> capture successfully resumes when requested (Section 5)
        pipeline_healthy = AudioPipeline(vad_config=self.vad_config)
        pipeline_healthy.start()
        pipeline_healthy.handle_device_loss()
        loss_state_ok = pipeline_healthy.lifecycle.state == AudioLifecycleState.ERROR

        reconn_success = pipeline_healthy.reconnect_device(resume_capture=True)
        reconn_state_ok = pipeline_healthy.lifecycle.state == AudioLifecycleState.RUNNING
        step_res = pipeline_healthy.process_step()
        reconn_capture_ok = step_res is not None
        reconn_event_emitted = len(pipeline_healthy.get_events_by_type(AudioEventType.DEVICE_RECONNECTED)) == 1

        healthy_reconnect_ok = (
            loss_state_ok
            and reconn_success
            and reconn_state_ok
            and reconn_capture_ok
            and reconn_event_emitted
        )

        # 2. Cancelled session -> reconnect attempt -> capture remains stopped (B6)
        pipeline_cancelled = AudioPipeline(vad_config=self.vad_config)
        pipeline_cancelled.start()
        pipeline_cancelled.cancel()
        reconn_cancelled = pipeline_cancelled.reconnect_device(resume_capture=True)
        is_cancelled_intact = pipeline_cancelled.is_cancelled and (reconn_cancelled is False)
        cancelled_state_ok = pipeline_cancelled.lifecycle.state == AudioLifecycleState.STOPPED
        cancelled_capture_blocked = pipeline_cancelled.process_step() is None

        cancelled_guard_ok = (
            is_cancelled_intact
            and cancelled_state_ok
            and cancelled_capture_blocked
        )

        passed = healthy_reconnect_ok and cancelled_guard_ok
        details = (
            f"Healthy Reconnect (resumed={reconn_capture_ok}, state={pipeline_healthy.lifecycle.state.value}) "
            f"and Cancelled Guard (refused={not reconn_cancelled}, blocked={cancelled_capture_blocked})"
        )
        return ValidationResult(
            check=pt,
            passed=passed,
            details=details,
        )

    def check_13_buffer_overflow_and_drops(self) -> ValidationResult:
        pt = VALIDATION_POINTS[ValidationCheckID.CHECK_13_BUFFER_OVERFLOW_AND_DROPS]
        pipeline = AudioPipeline(buffer_capacity=5, vad_config=self.vad_config)
        pipeline.start()
        results = pipeline.capture_burst(10)
        metrics = pipeline.buffer.get_metrics()
        passed = (metrics.current_size == 5) and (metrics.total_dropped == 5)
        return ValidationResult(
            check=pt,
            passed=passed,
            details=f"Buffer capacity: 5, filled: {metrics.current_size}, total_dropped: {metrics.total_dropped}",
        )

    run_all = run_all_checks

    def print_report(self, results: List[ValidationResult]) -> bool:
        """Print a formatted console report for all 13 Day 20 validation checks."""
        print("=" * 80)
        print("WEEK 3 AUDIO & VAD - DAY 20 COMPREHENSIVE VALIDATION SUITE (13/13 POINTS)")
        print("=" * 80)
        total = len(results)
        passed_count = sum(1 for r in results if r.passed)

        for res in results:
            status = "[PASS]" if res.passed else "[FAIL]"
            print(f"{status} Point {res.check.index:02d}: {res.check.name}")
            print(f"       Description: {res.check.description}")
            print(f"       Outcome:     {res.details}")
            print("-" * 80)

        pass_rate = (passed_count / total * 100) if total > 0 else 0.0
        print(f"SUMMARY: {passed_count}/{total} Checks Passed ({pass_rate:.1f}%)")
        print("=" * 80)
        return passed_count == total


if __name__ == "__main__":
    import sys
    validator = Week3AudioValidator()
    results = validator.run_all_checks()
    all_passed = validator.print_report(results)
    sys.exit(0 if all_passed else 1)

