r"""Week 3 Dedicated Speech-to-Text Integration Demonstration.

Project: AI Voice Co-Pilot
Workstream: W2 - Speech-to-Text (Week 3, Days 15-21)
Author: Disha D K (SDE 3)
Branch: feature/w2-speech-to-text-2

Demonstrates 10 Core Week 3 Scenarios:
1. Audio input entering the authentic audio pipeline.
2. Interim transcription hypothesis generation.
3. Transcript revision (replacing tentative text).
4. Transcript finalization (immutable committed text).
5. Session ID association & propagation across layers.
6. Low-confidence segment handling & defensive quarantine.
7. Cooperative cancellation of an active transcription session.
8. Simulated network failure & automatic fallback to mock transcriber.
9. Simulated API quota / rate-limit failure (429) & automatic fallback.
10. Transcript events streaming into the backend session repository.

Usage (PowerShell):
    python examples/week3_stt_integration_demo.py
    # or using virtual environment:
    .\.venv\Scripts\python.exe examples/week3_stt_integration_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from typing import Any, Dict, List

from src.audio.device import AudioPermissionState, MockAudioDevice
from src.audio.pipeline import AudioPipeline, create_deterministic_chunk
from src.audio.vad import MockVAD, VADConfig, VADEvent, VADEventType
from src.models.session import SessionState
from src.repositories.session_repository import InMemorySessionRepository
from src.schemas.audio import AudioFormat
from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.adapter import STTAdapterConfig
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.integration import AudioSTTBridge, BackendEventStreamBridge
from voice_stt.orchestrator import TranscriptionOrchestrator
from voice_stt.schemas import (
    STTErrorDetail,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


def print_section(title: str, scenario_num: int) -> None:
    """Print standard section banner."""
    print(f"\n{'='*78}")
    print(f" [SCENARIO {scenario_num:02d}] {title}")
    print(f"{'='*78}")


def run_week3_demo() -> int:
    """Execute complete deterministic demonstration of all 10 Week 3 scenarios."""
    print("=" * 78)
    print(" AI Voice Co-Pilot - Week 3 Full Integration & Resilience Demo")
    print(" Student: Disha D K | SDE 3 | Workstream: W2 - Speech-to-Text")
    print(" Mode: Deterministic Local Verification (Zero External API Keys)")
    print("=" * 78)

    session_id = "session-demo-w3"
    results_summary: Dict[str, bool] = {}

    # -------------------------------------------------------------------------
    # Scenario 1: Audio Input Entering the Audio Pipeline
    # -------------------------------------------------------------------------
    print_section("Audio Input Entering the Audio Pipeline", 1)
    fmt = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
    device = MockAudioDevice(
        audio_format=fmt,
        initial_permission=AudioPermissionState.GRANTED,
        chunk_duration_ms=20.0,
        frequency_hz=440.0,
        amplitude=0.5,
    )

    chunk1 = create_deterministic_chunk(sequence_id=0, timestamp=0.0, amplitude=0.5, duration_ms=20.0, sample_rate=16000)
    chunk2 = create_deterministic_chunk(sequence_id=1, timestamp=0.02, amplitude=0.5, duration_ms=20.0, sample_rate=16000)
    chunk3 = create_deterministic_chunk(sequence_id=2, timestamp=0.04, amplitude=0.5, duration_ms=20.0, sample_rate=16000)

    pipeline = AudioPipeline(device=device, vad_config=VADConfig(energy_threshold=0.01))
    pipeline.start()

    print(f" Audio Pipeline started in state: {pipeline.lifecycle.state.value}")
    step1 = pipeline.process_step()
    assert step1 is not None, "Pipeline step 1 should yield audio"
    captured_chunk, vad_evt = step1
    print(f" Captured Audio Chunk -> Seq ID: {captured_chunk.sequence_id}, Size: {len(captured_chunk.data)} bytes")
    print(f" VAD Detection Result -> Event: {vad_evt.event_type.value}, Is Speech: {vad_evt.is_speech}")
    results_summary["1. Audio Pipeline Ingestion"] = captured_chunk is not None

    # -------------------------------------------------------------------------
    # Scenario 2: Interim Transcription
    # -------------------------------------------------------------------------
    print_section("Interim Transcription (Hypothesis Generation)", 2)
    orchestrator = TranscriptionOrchestrator(
        session_id=session_id,
        min_confidence_threshold=0.50,
    )
    orchestrator.initialize(session_id=session_id)

    interim_events = orchestrator.process_chunk(chunk1, is_last=False)
    print(f" Processed Chunk 0 -> Emitted {len(interim_events)} event(s)")
    for evt in interim_events:
        print(f"   Event ID: {evt.event_id} | Type: {evt.event_type.value} | Text: '{evt.segment.text if evt.segment else ''}'")
    current_interim_text = orchestrator.get_transcript(include_interim=True)
    print(f" Live Accumulator Transcript (including interim): '{current_interim_text}'")
    results_summary["2. Interim Transcription"] = len(interim_events) > 0

    # -------------------------------------------------------------------------
    # Scenario 3: Transcript Revision
    # -------------------------------------------------------------------------
    print_section("Transcript Revision (Hypothesis Updating)", 3)
    revised_evt = TranscriptEvent(
        event_id="evt-rev-001",
        event_type=TranscriptEventType.REVISION,
        sequence_number=99,
        timestamp=0.10,
        session_id=session_id,
        segment=TranscriptSegment(
            segment_id="seg-rev-01",
            start_time=0.0,
            end_time=0.04,
            text="hello voice co-pilot",
            confidence=0.92,
            is_final=False,
        ),
    )
    orchestrator.accumulator.ingest_event(revised_evt)
    revised_text = orchestrator.get_transcript(include_interim=True)
    print(f" Ingested Revision Event: {revised_evt.event_id}")
    print(f" Updated Hypothesis Text: '{revised_text}'")
    results_summary["3. Transcript Revision"] = "hello voice co-pilot" in revised_text

    # -------------------------------------------------------------------------
    # Scenario 4: Transcript Finalization
    # -------------------------------------------------------------------------
    print_section("Transcript Finalization (Committed Immutable Text)", 4)
    final_evt = TranscriptEvent(
        event_id="evt-fin-001",
        event_type=TranscriptEventType.FINALIZATION,
        sequence_number=100,
        timestamp=0.15,
        session_id=session_id,
        segment=TranscriptSegment(
            segment_id="seg-fin-01",
            start_time=0.0,
            end_time=0.04,
            text="hello voice co-pilot",
            confidence=0.97,
            is_final=True,
        ),
    )
    orchestrator.accumulator.ingest_event(final_evt)
    final_committed_text = orchestrator.get_transcript(include_interim=False)
    print(f" Ingested Finalization Event: {final_evt.event_id} (confidence: {final_evt.segment.confidence})")
    print(f" Committed Final Transcript: '{final_committed_text}'")
    results_summary["4. Transcript Finalization"] = final_committed_text == "hello voice co-pilot"

    # -------------------------------------------------------------------------
    # Scenario 5: Session ID Association
    # -------------------------------------------------------------------------
    print_section("Session ID Association Across Layers", 5)
    print(f" Orchestrator Session ID: {orchestrator.session_id}")
    print(f" Accumulator Session ID:  {orchestrator.accumulator.session_id}")
    assert orchestrator.session_id == orchestrator.accumulator.session_id == session_id

    # Test rejection of mismatched session ID
    mismatched_evt = TranscriptEvent(
        event_id="evt-mismatch",
        event_type=TranscriptEventType.INTERIM,
        sequence_number=101,
        timestamp=0.20,
        session_id="foreign-session-999",
        segment=TranscriptSegment(
            segment_id="seg-foreign",
            start_time=0.05,
            end_time=0.10,
            text="unauthorized intrusion",
            confidence=0.90,
            is_final=False,
        ),
    )
    rejected = not orchestrator.accumulator.ingest_event(mismatched_evt)
    print(f" Foreign Session Event Rejected by Accumulator: {rejected}")
    results_summary["5. Session ID Isolation"] = rejected

    # -------------------------------------------------------------------------
    # Scenario 6: Low-Confidence Segment Handling
    # -------------------------------------------------------------------------
    print_section("Low-Confidence Segment Handling & Defensive Quarantine", 6)
    low_conf_evt = TranscriptEvent(
        event_id="evt-low-conf",
        event_type=TranscriptEventType.FINALIZATION,
        sequence_number=102,
        timestamp=0.25,
        session_id=session_id,
        segment=TranscriptSegment(
            segment_id="seg-low",
            start_time=0.05,
            end_time=0.10,
            text="unclear whisper",
            confidence=0.35,  # below 0.50 threshold
            is_final=True,
        ),
    )
    orchestrator.accumulator.ingest_event(low_conf_evt)
    quarantine_count = orchestrator.accumulator.low_confidence_count
    quarantined_segs = orchestrator.accumulator.get_low_confidence_segments()
    print(f" Min Confidence Threshold: {orchestrator.min_confidence_threshold}")
    print(f" Ingested Segment Confidence: {low_conf_evt.segment.confidence}")
    print(f" Quarantined Low-Confidence Segments Count: {quarantine_count}")
    print(f" Quarantined Segment Texts: {[s.text for s in quarantined_segs]}")
    print(f" Committed Transcript (unclear whisper excluded): '{orchestrator.get_transcript(include_interim=False)}'")
    results_summary["6. Confidence Quarantine"] = quarantine_count > 0 and "unclear whisper" not in orchestrator.get_transcript(include_interim=False)

    # -------------------------------------------------------------------------
    # Scenario 7: Cancellation of an Active Transcription Session
    # -------------------------------------------------------------------------
    print_section("In-Flight Cancellation & State Cleanup", 7)
    orch_cancel_demo = TranscriptionOrchestrator(session_id="session-cancel-demo")
    orch_cancel_demo.initialize("session-cancel-demo")

    # Ingest interim hypothesis
    orch_cancel_demo.process_chunk(chunk1, is_last=False)
    print(f" Active Interim before cancel: '{orch_cancel_demo.get_transcript(include_interim=True)}'")

    orch_cancel_demo.cancel()
    print(f" Orchestrator is_cancelled: {orch_cancel_demo.is_cancelled}")
    print(f" Interim text after cancel: '{orch_cancel_demo.get_transcript(include_interim=True)}'")
    results_summary["7. In-Flight Cancellation"] = (
        orch_cancel_demo.is_cancelled and orch_cancel_demo.get_transcript(include_interim=True) == ""
    )

    # -------------------------------------------------------------------------
    # Scenario 8: Simulated Network Failure & Mock Fallback
    # -------------------------------------------------------------------------
    print_section("Simulated Network Failure & Automatic Mock Fallback", 8)
    primary_net_fail = DeterministicFakeTranscriber(
        inject_error_at_chunk=0,
        error_detail=STTErrorDetail(
            code="CONNECTION_REFUSED",
            message="Connection refused by speech API",
            retryable=True,
        ),
    )

    fallback_adapter = DeterministicFakeTranscriber()
    orch_fallback = TranscriptionOrchestrator(
        adapter=primary_net_fail,
        fallback_adapter=fallback_adapter,
        session_id="session-fallback-net",
    )
    orch_fallback.initialize("session-fallback-net")

    print(f" Primary Adapter active: {orch_fallback.adapter is primary_net_fail}")
    print(" Processing audio chunk through failing primary adapter...")
    fb_events = orch_fallback.process_chunk(chunk1, is_last=True)

    print(f" Primary failed -> Fallback activated: {orch_fallback.is_fallback_active}")
    print(f" Total Events Emitted: {len(fb_events)}")
    for evt in fb_events:
        print(f"   Event Type: {evt.event_type.value} | Segment: {evt.segment.text if evt.segment else 'N/A'}")
    results_summary["8. Network Fallback"] = orch_fallback.is_fallback_active and len(fb_events) > 0

    # -------------------------------------------------------------------------
    # Scenario 9: Simulated Quota / Rate-Limit (429) & Fallback
    # -------------------------------------------------------------------------
    print_section("Simulated Quota / Rate-Limit Failure & Mock Fallback", 9)
    primary_quota_fail = DeterministicFakeTranscriber(
        inject_error_at_chunk=0,
        error_detail=STTErrorDetail(
            code="QUOTA_EXCEEDED",
            message="HTTP 429: API Quota Exceeded",
            retryable=False,
        ),
    )

    orch_quota = TranscriptionOrchestrator(
        adapter=primary_quota_fail,
        fallback_adapter=DeterministicFakeTranscriber(),
        session_id="session-fallback-quota",
    )
    orch_quota.initialize("session-fallback-quota")

    quota_events = orch_quota.process_chunk(chunk1, is_last=True)
    print(f" HTTP 429 Quota Exceeded detected -> Fallback activated: {orch_quota.is_fallback_active}")
    results_summary["9. Quota 429 Fallback"] = orch_quota.is_fallback_active

    # -------------------------------------------------------------------------
    # Scenario 10: Transcript Events Reaching Backend Event Repository
    # -------------------------------------------------------------------------
    print_section("Transcript Events Streaming to Backend Event Repository", 10)
    repo = InMemorySessionRepository()
    repo_session_id = "session-backend-stream-demo"
    repo.create(session_id=repo_session_id)
    repo.transition(session_id=repo_session_id, to_state=SessionState.ACTIVE)

    backend_bridge = BackendEventStreamBridge(
        repository=repo,
        session_id=repo_session_id,
    )

    orch_e2e = TranscriptionOrchestrator(session_id=repo_session_id)
    audio_bridge = AudioSTTBridge(
        orchestrator=orch_e2e,
        backend_bridge=backend_bridge,
        session_id=repo_session_id,
    )
    audio_bridge.start()

    # Stream deterministic chunks through audio-to-STT-to-backend bridge
    chunks = [chunk1, chunk2, chunk3]
    for c in chunks:
        audio_bridge.process_chunk(c, is_last=(c.sequence_id == 2))

    stored_session = repo.get(repo_session_id)
    stored_events = stored_session.events
    final_text = audio_bridge.get_transcript(include_interim=False)

    print(f" Backend Session State: {stored_session.state.value}")
    print(f" Total Events Recorded in Backend Repository: {len(stored_events)}")
    for idx, se in enumerate(stored_events):
        print(f"   [{idx+1}] Event Type: {se.event_type} | STT Type: {se.payload.get('stt_event_type')} | Text: '{se.payload.get('transcript')}'")
    print(f" Final Accumulated Transcript: '{final_text}'")
    results_summary["10. Backend Repository Stream"] = len(stored_events) >= 3 and len(final_text) > 0

    # -------------------------------------------------------------------------
    # Final Verification Matrix
    # -------------------------------------------------------------------------
    print("\n" + "=" * 78)
    print(" WEEK 3 DEMONSTRATION VERIFICATION MATRIX")
    print("=" * 78)
    all_passed = True
    for scenario_name, passed in results_summary.items():
        status_symbol = "[PASS]" if passed else "[FAIL]"
        print(f" {status_symbol} {scenario_name}")
        if not passed:
            all_passed = False

    print("=" * 78)
    if all_passed:
        print(" ALL 10 WEEK 3 SCENARIOS VERIFIED SUCCESSFULLY!")
        print(" Zero external dependencies; 100% deterministic execution.")
        print("=" * 78)
        return 0
    else:
        print(" SOME DEMO SCENARIOS FAILED!")
        print("=" * 78)
        return 1


if __name__ == "__main__":
    sys.exit(run_week3_demo())
