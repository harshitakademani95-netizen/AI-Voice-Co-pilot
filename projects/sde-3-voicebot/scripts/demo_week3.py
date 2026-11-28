#!/usr/bin/env python3
"""
Week 3 Audio & VAD Complete Demonstration Script.

Workstream: W1 - Audio and VAD
Author: Harshita G Kademani | SDE 3

Executes all 9 Week 3 lifecycle, VAD, resilience, STT bridge, and safety gate scenarios:
1. Speech start/end ordering with unique segment IDs & no duplicate start during continuous speech.
2. Strict session_id and correlation_id propagation on every event.
3. Multi-session isolation with zero event cross-talk.
4. Device loss mid-stream -> successful reconnection -> resumed capture.
5. Failed device reconnection handling.
6. Healthy device reconnection check (no false event emitted).
7. Cancellation: capture stopped, buffer flushed, reconnect blocked.
8. STT bridge handoff: Speech-to-Text transcription with finalized segment.
9. HITL approval gate: Approve, Reject, and Cancel workflows.

Outputs structured JSON lines for machine verification and human telemetry.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

# Ensure project src is on PYTHONPATH
_current_dir = Path(__file__).resolve().parent
_project_dir = _current_dir.parent
_src_dir = _project_dir / "src"
for p in [str(_src_dir), str(_project_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from src.audio.backend_integration import AudioBackendSessionManager
from src.audio.device import AudioPermissionState, MockAudioDevice
from src.audio.lifecycle import AudioLifecycleState
from src.audio.pipeline import (
    AudioPipeline,
    create_deterministic_chunk,
    generate_noise_burst_fixture,
    generate_silence_fixture,
    generate_speech_fixture,
)
from src.audio.transcription_integration import AudioTranscriptionBridge
from src.audio.vad import VADConfig
from src.context.schemas import RiskCategory
from src.models.session import SessionState
from src.repositories.session_repository import session_repository
from src.schemas.audio import AudioChunk, AudioError, AudioEvent, AudioEventType, AudioFormat

# Agentic Workflow
from agentic_workflow import (
    ApprovalStatus,
    WorkflowState,
    reset_mock_tools_state,
)
from agentic_workflow.tools import _MOCK_GENERATED_REPORTS


def emit_event(phase: str, event_data: Dict[str, Any]) -> None:
    """Format and print an event as a structured JSON line."""
    record = {"phase": phase, **event_data}
    print(json.dumps(record, default=str))


def run_all_scenarios() -> int:
    print(json.dumps({"info": "STARTING_WEEK_3_COMPLETE_DEMONSTRATION", "version": "Week 3", "student": "Harshita G Kademani"}))

    vad_config = VADConfig(
        energy_threshold=0.015,
        speech_probability_threshold=0.4,
        min_speech_duration_ms=40.0,
        min_silence_duration_ms=60.0,
    )

    # =========================================================================
    # SCENARIO 1: Speech Start/End Ordering & No Duplicate Start
    # =========================================================================
    session_1 = "sess-demo-scen1"
    corr_1 = "corr-demo-trace-01"
    pipe1 = AudioPipeline(session_id=session_1, correlation_id=corr_1, vad_config=vad_config)
    pipe1.start()

    # Utterance 1 (4 speech chunks)
    for c in generate_speech_fixture(num_chunks=4, amplitude=0.55):
        pipe1.process_chunk_direct(c)
    # Hangover silence (4 chunks to trigger SPEECH_END)
    for c in generate_silence_fixture(num_chunks=4):
        pipe1.process_chunk_direct(c)

    # Utterance 2 (distinct segment)
    for c in generate_speech_fixture(num_chunks=3, amplitude=0.55):
        pipe1.process_chunk_direct(c)
    for c in generate_silence_fixture(num_chunks=4):
        pipe1.process_chunk_direct(c)

    pipe1.stop()
    events_1 = pipe1.get_events()
    start_events = [e for e in events_1 if e.event_type == AudioEventType.SPEECH_START]
    end_events = [e for e in events_1 if e.event_type == AudioEventType.SPEECH_END]

    for e in events_1:
        emit_event("SCENARIO_1_SPEECH_ORDERING", e.to_dict(include_base64_data=False))

    assert len(start_events) == 2, f"Expected 2 starts, got {len(start_events)}"
    assert len(end_events) == 2, f"Expected 2 ends, got {len(end_events)}"
    assert start_events[0].segment_id != start_events[1].segment_id, "Segments must have distinct IDs"

    # =========================================================================
    # SCENARIO 2: Session ID and Correlation ID Propagation
    # =========================================================================
    for e in events_1:
        assert e.session_id == session_1, f"Mismatch session_id in event {e.event_id}"
        assert e.correlation_id == corr_1, f"Mismatch correlation_id in event {e.event_id}"
    emit_event("SCENARIO_2_SESSION_TRACKING", {
        "status": "PASSED",
        "verified_events_count": len(events_1),
        "session_id": session_1,
        "correlation_id": corr_1,
    })

    # =========================================================================
    # SCENARIO 3: Multi-Session Isolation
    # =========================================================================
    pipe_a = AudioPipeline(session_id="sess-iso-A", correlation_id="corr-iso-A", vad_config=vad_config)
    pipe_b = AudioPipeline(session_id="sess-iso-B", correlation_id="corr-iso-B", vad_config=vad_config)
    pipe_a.start()
    pipe_b.start()

    for c in generate_speech_fixture(num_chunks=3):
        pipe_a.process_chunk_direct(c)
    for c in generate_silence_fixture(num_chunks=3):
        pipe_b.process_chunk_direct(c)

    pipe_a.stop()
    pipe_b.stop()

    evts_a = pipe_a.get_events()
    evts_b = pipe_b.get_events()
    assert all(e.session_id == "sess-iso-A" for e in evts_a)
    assert all(e.session_id == "sess-iso-B" for e in evts_b)
    emit_event("SCENARIO_3_MULTI_SESSION_ISOLATION", {
        "status": "PASSED",
        "session_A_events": len(evts_a),
        "session_B_events": len(evts_b),
        "cross_talk": False,
    })

    # =========================================================================
    # SCENARIO 4: Device Loss Mid-Speech -> Reconnect -> Resume Capture
    # =========================================================================
    dev4 = MockAudioDevice(initial_permission=AudioPermissionState.GRANTED)
    pipe4 = AudioPipeline(device=dev4, session_id="sess-dev-loss", correlation_id="corr-dev-loss", vad_config=vad_config)
    pipe4.start()

    for c in generate_speech_fixture(num_chunks=3):
        pipe4.process_chunk_direct(c)
    assert pipe4.active_segment_id is not None

    # Mid-speech loss
    loss_evt = pipe4.handle_device_loss()
    emit_event("SCENARIO_4_DEVICE_LOSS", loss_evt.to_dict(include_base64_data=False))
    assert pipe4.state == AudioLifecycleState.ERROR
    assert pipe4.active_segment_id is None

    # Healthy reconnection
    reconn_ok = pipe4.reconnect_device(resume_capture=True)
    reconn_evts = pipe4.get_events_by_type(AudioEventType.DEVICE_RECONNECTED)
    assert reconn_ok and len(reconn_evts) == 1
    assert pipe4.state == AudioLifecycleState.RUNNING
    emit_event("SCENARIO_4_DEVICE_RECONNECTED", reconn_evts[0].to_dict(include_base64_data=False))

    # New speech after reconnection is processed cleanly
    for c in generate_speech_fixture(num_chunks=3):
        pipe4.process_chunk_direct(c)
    for c in generate_silence_fixture(num_chunks=4):
        pipe4.process_chunk_direct(c)
    pipe4.stop()

    # =========================================================================
    # SCENARIO 5: Failed Device Reconnection Handled
    # =========================================================================
    dev5 = MockAudioDevice(
        initial_permission=AudioPermissionState.GRANTED,
        simulate_reconnect_failure=True,
    )
    pipe5 = AudioPipeline(device=dev5, session_id="sess-fail-reconn", correlation_id="corr-fail-reconn")
    pipe5.start()
    dev5.disconnect(reason="hardware_bus_fault")
    pipe5.handle_device_loss()

    fail_reconn = pipe5.reconnect_device(resume_capture=True)
    assert fail_reconn is False
    assert pipe5.state == AudioLifecycleState.ERROR
    emit_event("SCENARIO_5_FAILED_RECONNECT_HANDLED", {
        "status": "PASSED",
        "reconnect_result": False,
        "state": pipe5.state.value,
        "last_error": str(pipe5.last_error),
    })

    # =========================================================================
    # SCENARIO 6: No False "Reconnected" on Healthy Device
    # =========================================================================
    dev6 = MockAudioDevice(initial_permission=AudioPermissionState.GRANTED)
    pipe6 = AudioPipeline(device=dev6, session_id="sess-healthy", correlation_id="corr-healthy")
    pipe6.start()
    no_false_reconn = pipe6.reconnect_device(resume_capture=True)
    assert no_false_reconn is True
    assert len(pipe6.get_events_by_type(AudioEventType.DEVICE_RECONNECTED)) == 0
    pipe6.stop()
    emit_event("SCENARIO_6_NO_FALSE_RECONNECTED_EVENT", {"status": "PASSED", "false_events_count": 0})

    # =========================================================================
    # SCENARIO 7: Cancellation Flushes Buffer & Blocks Reconnection
    # =========================================================================
    pipe7 = AudioPipeline(session_id="sess-cancel-guard", correlation_id="corr-cancel-guard")
    pipe7.start()
    for c in generate_speech_fixture(num_chunks=3):
        pipe7.buffer.push(c)
    assert pipe7.buffer.current_size > 0

    cancel_evt = pipe7.cancel(reason="user_request_cancelled")
    emit_event("SCENARIO_7_CANCELLATION", cancel_evt.to_dict(include_base64_data=False))
    assert pipe7.state == AudioLifecycleState.STOPPED
    assert pipe7.buffer.is_empty  # Buffer purged

    revive_attempt = pipe7.reconnect_device(resume_capture=True)
    assert revive_attempt is False  # Cannot revive cancelled session
    emit_event("SCENARIO_7_CANCEL_BLOCKED_REVIVAL", {"status": "PASSED", "revive_attempt": False})

    # =========================================================================
    # SCENARIO 8: Speech-to-Text Bridge Handoff & Segment Finalization
    # =========================================================================
    bridge_pipe = AudioPipeline(session_id="sess-stt-bridge", correlation_id="corr-stt-bridge", vad_config=vad_config)
    bridge = AudioTranscriptionBridge(pipeline=bridge_pipe, auto_feed=True)
    bridge_pipe.start()

    for c in generate_speech_fixture(num_chunks=5, amplitude=0.55):
        bridge_pipe.process_chunk_direct(c)
    for c in generate_silence_fixture(num_chunks=4):
        bridge_pipe.process_chunk_direct(c)
    bridge_pipe.stop()

    full_transcript = bridge.get_full_transcript()
    final_segments = bridge.get_final_segments()
    assert len(final_segments) > 0
    assert len(full_transcript) > 0
    emit_event("SCENARIO_8_STT_BRIDGE_HANDOFF", {
        "status": "PASSED",
        "final_segments_count": len(final_segments),
        "full_transcript": full_transcript,
        "average_confidence": bridge.accumulator.get_average_confidence(),
    })

    # =========================================================================
    # SCENARIO 9: Human-in-the-Loop Approval Gate (Approve, Reject, Cancel)
    # =========================================================================
    reset_mock_tools_state()
    session_repository.clear()
    mgr = AudioBackendSessionManager(repository=session_repository)

    # Case A: Approve
    sid_a = "sess-hitl-approve"
    mgr.create_integrated_session(session_id=sid_a, target_script=["delete old files from server"])
    mgr.process_audio_stream(session_id=sid_a, speech_chunks=4, silence_chunks=4)
    reasoning_a, plan_a, _ = mgr.execute_reasoning_and_plan(session_id=sid_a)
    assert plan_a.state == WorkflowState.AWAITING_APPROVAL
    assert len(_MOCK_GENERATED_REPORTS) == 0  # Not executed yet
    res_a = mgr.approve_and_complete_workflow(session_id=sid_a, approver="admin@academia.ai")
    assert plan_a.state == WorkflowState.SUCCEEDED
    emit_event("SCENARIO_9_HITL_APPROVE", {"case": "A_APPROVE", "final_state": plan_a.state.value})

    # Case B: Reject
    reset_mock_tools_state()
    sid_b = "sess-hitl-reject"
    mgr.create_integrated_session(session_id=sid_b, target_script=["delete old files from server"])
    mgr.process_audio_stream(session_id=sid_b, speech_chunks=4, silence_chunks=4)
    _, plan_b, _ = mgr.execute_reasoning_and_plan(session_id=sid_b)
    assert plan_b.state == WorkflowState.AWAITING_APPROVAL
    res_b = mgr.reject_and_cancel_workflow(session_id=sid_b, rejector="admin@academia.ai", comment="Unauthorized action")
    assert plan_b.state == WorkflowState.CANCELLED
    assert len(_MOCK_GENERATED_REPORTS) == 0  # Protected action never executed
    emit_event("SCENARIO_9_HITL_REJECT", {"case": "B_REJECT", "final_state": plan_b.state.value})

    # Case C: Cancel
    reset_mock_tools_state()
    sid_c = "sess-hitl-cancel"
    mgr.create_integrated_session(session_id=sid_c, target_script=["delete old files from server"])
    mgr.process_audio_stream(session_id=sid_c, speech_chunks=4, silence_chunks=4)
    _, plan_c, _ = mgr.execute_reasoning_and_plan(session_id=sid_c)
    assert plan_c.state == WorkflowState.AWAITING_APPROVAL
    res_c = mgr.cancel_workflow(session_id=sid_c, reason="User clicked cancel")
    assert plan_c.state == WorkflowState.CANCELLED
    assert len(_MOCK_GENERATED_REPORTS) == 0  # Protected action never executed
    emit_event("SCENARIO_9_HITL_CANCEL", {"case": "C_CANCEL", "final_plan_state": plan_c.state.value})

    print(json.dumps({"info": "ALL_9_WEEK_3_SCENARIOS_SUCCESSFUL", "status": "VERIFIED_PASS"}))
    return 0


if __name__ == "__main__":
    sys.exit(run_all_scenarios())
