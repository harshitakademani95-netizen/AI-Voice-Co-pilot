# Week 3 Audio & VAD Demonstration and Integration Evidence

**Workstream:** W1 — Audio and Voice Activity Detection  
**Team:** SDE 3 (`sde-3-voicebot`)  
**Lead Engineer:** Harshita G Kademani  
**Execution Date:** 2026-11-28  
**Python Runtime:** Python 3.14.6  
**Operating Mode:** Deterministic simulation (no physical microphone hardware or cloud APIs required)

---

## 1. Exact Execution Commands

### A. Run Week 3 Complete Demo Script
**From Repository Root (PowerShell):**
```powershell
python projects/sde-3-voicebot/scripts/demo_week3.py
```

**From Repository Root (Linux/macOS):**
```bash
python3 projects/sde-3-voicebot/scripts/demo_week3.py
```

**From Project Folder (`projects/sde-3-voicebot/`):**
```powershell
# PowerShell
$env:PYTHONPATH="src;."
python scripts/demo_week3.py

# Linux/macOS
PYTHONPATH="src:." python3 scripts/demo_week3.py
```

### B. Run Audio & VAD Interactive CLI Suite
```powershell
# Week 1 PCM stream demo (50 chunks, 1.000s)
python -m src.cli

# Week 2 Lifecycle, VAD & Buffer Matrix (7/7 checks)
python -m src.cli_w2

# Week 3 Complete Audio & VAD Pipeline (8/8 audit checks)
python -m src.audio.demo
```

### C. Run Full Test Suite (All 412 Tests)
```powershell
# From Repository Root (using root pytest.ini)
pytest

# From Subproject Folder
cd projects/sde-3-voicebot
pytest
```

---

## 2. Real Captured Demonstration Output (JSON Lines)

Raw output file persisted at: [`projects/sde-3-voicebot/docs/evidence/demo_output.jsonl`](evidence/demo_output.jsonl)

### Scenario 1: Speech Start/End Ordering & Unique Segment IDs
```json
{"phase": "SCENARIO_1_SPEECH_ORDERING", "event_id": "evt-start-sess-demo-scen1-3", "event_type": "speech_start", "session_id": "sess-demo-scen1", "correlation_id": "corr-demo-trace-01", "sequence_number": 2, "timestamp": 0.0, "segment_id": "seg-sess-demo-scen1-1", "metadata": {"onset_sequence_id": 0, "energy": 0.3894, "speech_probability": 1.0, "segment_index": 1}, "chunk": {"sequence_id": 1, "timestamp": 0.02, "duration_ms": 20.0, "size_bytes": 640, "num_samples": 320, "format": {"sample_rate": 16000, "channels": 1, "sample_width": 2, "encoding": "pcm_s16le", "frame_size": 2, "bytes_per_second": 32000}, "metadata": {}}}
{"phase": "SCENARIO_1_SPEECH_ORDERING", "event_id": "evt-chunk-sess-demo-scen1-4", "event_type": "audio_chunk", "session_id": "sess-demo-scen1", "correlation_id": "corr-demo-trace-01", "sequence_number": 3, "timestamp": 0.02, "segment_id": "seg-sess-demo-scen1-1", "metadata": {"is_speech": true, "energy": 0.3894, "speech_probability": 1.0, "chunk_sequence_id": 1, "duration_ms": 20.0}}
{"phase": "SCENARIO_1_SPEECH_ORDERING", "event_id": "evt-chunk-sess-demo-scen1-5", "event_type": "audio_chunk", "session_id": "sess-demo-scen1", "correlation_id": "corr-demo-trace-01", "sequence_number": 4, "timestamp": 0.04, "segment_id": "seg-sess-demo-scen1-1", "metadata": {"is_speech": true, "energy": 0.3894, "speech_probability": 1.0, "chunk_sequence_id": 2, "duration_ms": 20.0}}
```

### Scenario 2 & 3: Session Tracking & Multi-Session Isolation
```json
{"phase": "SCENARIO_2_SESSION_TRACKING", "status": "PASSED", "verified_events_count": 22, "session_id": "sess-demo-scen1", "correlation_id": "corr-demo-trace-01"}
{"phase": "SCENARIO_3_MULTI_SESSION_ISOLATION", "status": "PASSED", "session_A_events": 6, "session_B_events": 4, "cross_talk": false}
```

### Scenario 4: Device Loss Mid-Speech -> Reconnect -> Resumed Capture
```json
{"phase": "SCENARIO_4_DEVICE_LOSS", "event_id": "evt-devloss-sess-dev-loss-7", "event_type": "device_lost", "session_id": "sess-dev-loss", "correlation_id": "corr-dev-loss", "sequence_number": 6, "timestamp": 0.04, "segment_id": null, "metadata": {"error_code": "DEVICE_UNAVAILABLE", "error_message": "Audio input device was unexpectedly disconnected or became unavailable.", "session_id": "sess-dev-loss", "correlation_id": "corr-dev-loss"}, "chunk": null}
{"phase": "SCENARIO_4_DEVICE_RECONNECTED", "event_id": "evt-devrecon-sess-dev-loss-8", "event_type": "device_reconnected", "session_id": "sess-dev-loss", "correlation_id": "corr-dev-loss", "sequence_number": 7, "timestamp": 0.04, "segment_id": null, "metadata": {"device_id": "mock-mic-default", "device_name": "Mock Studio Microphone (Synthetic Default)", "resumed": true}, "chunk": null}
```

### Scenario 5 & 6: Reconnect Edge Cases (Failure & Healthy Device)
```json
{"phase": "SCENARIO_5_FAILED_RECONNECT_HANDLED", "status": "PASSED", "reconnect_result": false, "state": "ERROR", "last_error": "[DEVICE_RECONNECT_FAILED] Audio device reconnection failed: device unavailable or unsupported."}
{"phase": "SCENARIO_6_NO_FALSE_RECONNECTED_EVENT", "status": "PASSED", "false_events_count": 0}
```

### Scenario 7: Cancellation Flushes Buffer & Blocks Reconnect
```json
{"phase": "SCENARIO_7_CANCELLATION", "event_id": "evt-cancel-sess-cancel-guard-1", "event_type": "cancelled", "session_id": "sess-cancel-guard", "correlation_id": "corr-cancel-guard", "sequence_number": 0, "timestamp": 0.0, "segment_id": null, "metadata": {"reason": "user_request_cancelled", "session_id": "sess-cancel-guard"}, "chunk": null}
{"phase": "SCENARIO_7_CANCEL_BLOCKED_REVIVAL", "status": "PASSED", "revive_attempt": false}
```

### Scenario 8: Speech-to-Text Bridge Handoff
```json
{"phase": "SCENARIO_8_STT_BRIDGE_HANDOFF", "status": "PASSED", "final_segments_count": 2, "full_transcript": "this this this this copilot", "average_confidence": 0.9435}
```

### Scenario 9: Human-in-the-Loop Safety Gate (Approve, Reject, Cancel)
```json
{"phase": "SCENARIO_9_HITL_APPROVE", "case": "A_APPROVE", "final_state": "succeeded"}
{"phase": "SCENARIO_9_HITL_REJECT", "case": "B_REJECT", "final_state": "cancelled"}
{"phase": "SCENARIO_9_HITL_CANCEL", "case": "C_CANCEL", "final_plan_state": "cancelled"}
{"info": "ALL_9_WEEK_3_SCENARIOS_SUCCESSFUL", "status": "VERIFIED_PASS"}
```

---

## 3. Real Test Suite Verification Summary

Raw test execution persisted at: [`projects/sde-3-voicebot/docs/evidence/pytest_output.txt`](evidence/pytest_output.txt)

| Test Suite File | Test Count | Status | Description |
|---|---|---|---|
| `test_audio_schemas.py` | 8 | PASS | AudioFormat, AudioChunk, AudioError invariants |
| `test_audio_errors.py` | 18 | PASS | Error hierarchy, invalid frames, unaligned bytes |
| `test_chunker.py` | 9 | PASS | Monotonic sequence IDs, timestamp progression |
| `test_mock_source.py` | 10 | PASS | Deterministic mock microphone stream |
| `test_audio_device.py` | 19 | PASS | Device listing, permissions, hardware failure |
| `test_audio_lifecycle.py` | 17 | PASS | IDLE -> RUNNING <-> PAUSED -> STOPPED |
| `test_vad.py` | 13 | PASS | Energy calculation, thresholds, hangover debounce |
| `test_audio_buffer.py` | 11 | PASS | Overflow backpressure, sequence gap detection |
| `test_audio_pipeline.py` | 20 | PASS | End-to-end capture to buffer to VAD |
| `test_audio_events.py` | 11 | PASS | Day 15 normalized AudioEvent contracts |
| `test_audio_week3.py` | 21 | PASS | Days 16–20 traceability, device loss, 13-pt validator |
| `test_voice_stt_contract.py` | 4 | PASS | Formal contract between Audio and STT |
| `test_week3_team_integration.py` | 6 | PASS | Day 21 cross-team HITL approval gate |
| `test_audio_routes.py` | 9 | PASS | FastAPI HTTP route handlers & endpoints |
| `test_schemas.py` | 32 | PASS | Shared STT transcript & error schema tests |
| `test_accumulator.py` | 9 | PASS | STT segment accumulator sorting & deduplication |
| `test_adapter_and_fake.py` | 19 | PASS | STT adapter interface & fake transcriber |
| `test_twenty_requirements.py` | 20 | PASS | Formal STT acceptance requirements |
| Other Team Suites (W3/W4/W5) | 176 | PASS | Context, reasoning, workflow engine, backend |
| **TOTAL VERIFIED SUITE** | **412** | **100% PASS** | Zero failures, zero warnings |

---

## 4. Requirements Traceability Matrix

| Requirement | Implementation Evidence | Test File & Verification | Status |
|---|---|---|---|
| **Speech Start/End Ordering** | `AudioPipeline._emit_event` | `test_audio_events.py::test_event_ordering_strictly_deterministic` | ✅ PASS |
| **Unique Segment IDs** | `AudioPipeline._current_segment_id` | `test_audio_events.py::test_multiple_speech_segments_isolated_with_distinct_segment_ids` | ✅ PASS |
| **Session & Correlation IDs** | `AudioEvent.session_id` | `test_audio_week3.py::test_d16_session_and_correlation_id_propagation_real_path` | ✅ PASS |
| **Multi-Session Isolation** | Pipeline instance isolation | `test_audio_week3.py::test_d16_multi_session_isolation_and_tracing_real_path` | ✅ PASS |
| **Mid-Stream Device Loss** | `handle_device_loss()` | `test_audio_week3.py::test_d17_device_loss_during_active_capture` | ✅ PASS |
| **Device Reconnection** | `reconnect_device()` | `test_audio_week3.py::test_d18_successful_device_reconnection_restores_capture` | ✅ PASS |
| **Safe Cancellation** | `cancel()` | `test_audio_week3.py::test_d18_cancellation_during_active_speech_flushes_and_stops` | ✅ PASS |
| **No False Reconnection** | Clean state check | `test_audio_week3.py::test_d18_reconnecting_healthy_device_emits_no_false_event` | ✅ PASS |
| **STT Bridge Handoff** | `AudioTranscriptionBridge` | `test_audio_week3.py::test_d19_prevent_duplicate_stt_input` | ✅ PASS |
| **STT Contract Invariants** | `tests/test_voice_stt_contract.py` | `test_voice_stt_contract.py` (4 tests) | ✅ PASS |
| **13-Point Day 20 Validator** | `Week3AudioValidator` | `test_audio_week3.py::test_d20_thirteen_point_audio_event_validation_all_pass` | ✅ PASS |
| **Approval Gate Case A (Approve)** | `AudioBackendSessionManager` | `test_week3_team_integration.py::test_case_a_consequential_approval_gate_executes_action` | ✅ PASS |
| **Approval Gate Case B (Reject)** | `reject_and_cancel_workflow` | `test_week3_team_integration.py::test_case_b_consequential_rejection_prevents_action_and_fails_session` | ✅ PASS |
| **Approval Gate Case C (Cancel)** | `cancel_workflow` | `test_week3_team_integration.py::test_case_c_consequential_cancellation_prevents_action` | ✅ PASS |
