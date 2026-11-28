"""
CLI Demonstration for AI Voice Copilot Week 2 (D8-D14) Audio Pipeline.

Student: Harshita G Kademani | Team: SDE 3 | Workstream: W1/W2 - Audio and VAD
Project: AI Voice Copilot

Demonstrates:
1. Audio Device Selection & Permission Handling (D8-D9)
2. Lifecycle Controller State Progression (IDLE -> STARTING -> RUNNING) (D10-D11)
3. Streaming Audio Chunk Generation & Monotonic Sequence Tracking (D10-D11)
4. Bounded Buffer Enqueue & FIFO Dequeue (D12-D13)
5. Voice Activity Detection (VAD) Speech/Silence Classification (D10-D11)
6. Stream Pause & Resume Lifecycle (D10-D11)
7. Buffer Overflow & Explicit Dropped Chunk Counter / Backpressure (D12-D13)
8. Sequence Gap, Late, & Duplicate Chunk Detection (D12-D13)
9. Session Termination, Buffer Purge, & Safe Resource Cleanup (D14)

Usage:
    python -m src.cli_w2
"""

from __future__ import annotations

import sys
from typing import List, Tuple

from src.audio.buffer import BufferPushStatus
from src.audio.device import AudioPermissionState, MockAudioDevice
from src.audio.lifecycle import AudioLifecycleState
from src.audio.pipeline import AudioPipeline, create_deterministic_chunk
from src.audio.vad import VADConfig, VADEventType
from src.schemas.audio import AudioFormat


def run_week2_demo() -> int:
    """Run the comprehensive Week 2 Audio Pipeline demonstration with computed assertions."""
    print("=" * 88)
    print(" AI Voice Copilot - Week 2 Audio Pipeline Demonstration & Verification (D8-D14)")
    print(" Student: Harshita G Kademani | Workstream: W1/W2 Audio, Lifecycle & VAD")
    print(" Note: Deterministic simulation mode; no physical microphone or cloud APIs required")
    print("=" * 88)

    checks: List[Tuple[str, str, bool]] = []

    # 1. Device Selection & Permissions (D8-D9)
    print("\n[PHASE 1: Audio Device Adapter & Permissions (D8-D9)]")
    fmt = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
    device = MockAudioDevice(audio_format=fmt, initial_permission=AudioPermissionState.UNKNOWN)

    available_devices = device.list_devices()
    print(f"  * Available Audio Devices: {len(available_devices)}")
    for d in available_devices:
        default_tag = " [Default]" if d.is_default else ""
        print(f"    - ID: {d.device_id:<18} | Name: {d.name}{default_tag}")

    selected = device.select_device("mock-mic-headset")
    print(f"  * Selected Device        : {selected.name} ({selected.device_id})")
    print(f"  * Initial Permission     : {device.get_permission_status().value}")

    print("  * Requesting Permission  ...")
    perm_state = device.request_permission()
    print(f"  * Permission Status      : {perm_state.value} (Microphone access granted)")

    dev_ok = (selected.device_id == "mock-mic-headset" and perm_state == AudioPermissionState.GRANTED)
    checks.append((
        "Device Selection & Permission Flow",
        f"Device={selected.device_id}, Perm={perm_state.value}",
        dev_ok,
    ))

    # 2. Pipeline Initialization & Lifecycle Start (D10-D11)
    print("\n[PHASE 2: Lifecycle Controller & Pipeline Initialization (D10-D11)]")
    pipeline = AudioPipeline(
        device=device,
        buffer_capacity=10,
        vad_config=VADConfig(
            energy_threshold=0.015,
            speech_probability_threshold=0.35,
            min_speech_duration_ms=40.0,
            min_silence_duration_ms=60.0,
        ),
    )
    print(f"  * Initial Pipeline State : {pipeline.state.value}")
    print("  * Starting Audio Stream  ...")
    pipeline.start()
    print(f"  * Active Pipeline State  : {pipeline.state.value}")
    print(f"  * Device Open Status     : {device.is_open}")

    start_ok = (pipeline.state == AudioLifecycleState.RUNNING and device.is_open)
    checks.append((
        "Pipeline Start & Device Initialization",
        f"State={pipeline.state.value}, Open={device.is_open}",
        start_ok,
    ))

    # 3. Stream Chunk Capture, Bounded Buffer, and VAD (D12-D14)
    print("\n[PHASE 3: Audio Stream Capture -> Buffer Enqueue/Dequeue -> VAD (D10-D14)]")
    header = f"{'Seq':>4} | {'Timestamp':>10} | {'RMS Energy':>11} | {'Prob':>6} | {'VAD Event':>15} | {'Speech':>6}"
    print("-" * len(header))
    print(header)
    print("-" * len(header))

    processed_count = 0
    for step_num in range(8):
        res = pipeline.process_step()
        if res is not None:
            processed_count += 1
            chunk, vad_evt = res
            speech_tag = "YES" if vad_evt.is_speech else "NO"
            print(
                f"{chunk.sequence_id:4d} | {chunk.timestamp:9.3f}s | "
                f"{vad_evt.energy:11.4f} | {vad_evt.speech_probability:6.2f} | "
                f"{vad_evt.event_type.value:>15} | {speech_tag:>6}"
            )
    print("-" * len(header))

    stream_ok = (processed_count == 8)
    checks.append((
        "Streaming Capture & VAD Processing",
        f"Processed Steps={processed_count} / 8",
        stream_ok,
    ))

    # 4. Stream Pause and Resume (D10-D11)
    print("\n[PHASE 4: Stream Lifecycle Control: Pause & Resume (D10-D11)]")
    print("  * Executing pause() ...")
    pipeline.pause()
    print(f"  * Lifecycle State        : {pipeline.state.value}")
    paused_step = pipeline.process_step()
    print(f"  * Attempt step while paused: chunk returned = {paused_step} (Delivery suspended)")

    print("  * Executing resume() ...")
    pipeline.resume()
    print(f"  * Lifecycle State        : {pipeline.state.value} (Delivery resumed)")
    resumed_step = pipeline.process_step()
    if resumed_step:
        c, v = resumed_step
        print(f"  * Captured after resume  : Chunk {c.sequence_id} at {c.timestamp:.3f}s")

    pause_resume_ok = (
        pipeline.state == AudioLifecycleState.RUNNING
        and paused_step is None
        and resumed_step is not None
    )
    checks.append((
        "Stream Pause & Resume Lifecycle",
        f"Paused Step={paused_step}, Resumed Chunk={resumed_step[0].sequence_id if resumed_step else None}",
        pause_resume_ok,
    ))

    # 5. Buffer Overflow and Backpressure Policy via capture_burst() (D12-D13)
    print("\n[PHASE 5: Bounded Buffer Overflow & Backpressure Policy (D12-D13)]")
    print(f"  * Buffer Capacity Limit  : {pipeline.buffer.capacity} chunks")
    print(f"  * Current Buffer Size    : {pipeline.buffer.current_size}")
    print("  * Driving real overflow via pipeline.capture_burst(15) ...")

    # Burst 15 real chunks from device through lifecycle into buffer (capacity=10)
    burst_results = pipeline.capture_burst(15)
    burst_accepted = sum(1 for r in burst_results if r.status == BufferPushStatus.ACCEPTED)
    burst_dropped = sum(1 for r in burst_results if r.status == BufferPushStatus.DROPPED)

    print(f"  * Real Chunks Read       : {len(burst_results)}")
    print(f"  * Accepted into Buffer   : {burst_accepted} / {pipeline.buffer.capacity}")
    print(f"  * Explicitly Dropped     : {burst_dropped} (Capacity limit backpressure)")
    print(f"  * Current Buffer Fill    : {pipeline.buffer.current_size}/{pipeline.buffer.capacity}")
    print(f"  * Overflow Burst Drops   : {burst_dropped}")

    overflow_ok = (len(burst_results) == 15 and burst_accepted == 10 and burst_dropped == 5)
    checks.append((
        "Real Overflow via capture_burst(15)",
        f"Accepted={burst_accepted}/10, Dropped={burst_dropped}/5",
        overflow_ok,
    ))

    # 6. Sequence Anomaly Tracking: Gap, Late, Duplicate (D12-D13)
    print("\n[PHASE 6: Sequence Gap and Late Chunk Tracking (D12-D13)]")
    print("  * Simulating out-of-order sequence ID injection on full buffer ...")
    
    # 6a. Inject gap chunk (seq 2000). Because buffer is currently full (10 chunks),
    # this chunk triggers gap detection AND is dropped by capacity limit (+1 drop).
    gap_chunk = create_deterministic_chunk(sequence_id=2000, timestamp=1.5)
    res_gap = pipeline.buffer.push(gap_chunk)
    
    # 6b. Inject late chunk (seq 500). Sequence 500 < expected next (2001), never seen before,
    # so rejected as late. Late chunks do not enter queue and do not increment total_dropped.
    late_chunk = create_deterministic_chunk(sequence_id=500, timestamp=0.5)
    res_late = pipeline.buffer.push(late_chunk)
    
    # 6c. Inject duplicate chunk (seq 2000 again). Rejected as duplicate.
    # Duplicate chunks do not enter queue and do not increment total_dropped.
    res_dup = pipeline.buffer.push(gap_chunk)

    m = pipeline.buffer_metrics
    print(f"  * Sequence Gap Events    : {m.sequence_gap_events}")
    print(f"  * Missing Chunks Total   : {m.missing_chunks_total}")
    print(f"  * Late Chunks Detected   : {m.late_chunks_detected} (Status: {res_late.status.value})")
    print(f"  * Duplicate Chunks Noted : {m.duplicate_chunks_detected} (Status: {res_dup.status.value})")
    print(f"  * Total Drops Recorded   : {m.total_dropped}")
    print(
        f"  * Drop Breakdown         : {burst_dropped} from the overflow burst + "
        f"{1 if res_gap.status == BufferPushStatus.DROPPED else 0} dropped because "
        f"the buffer was still full when the gap chunk arrived = {m.total_dropped} total"
    )

    anomalies_ok = (
        m.sequence_gap_events == 1
        and m.late_chunks_detected == 1
        and m.duplicate_chunks_detected == 1
        and m.total_dropped == 6
    )
    checks.append((
        "Sequence Anomaly Handling (Gap/Late/Dup)",
        f"GapEvents={m.sequence_gap_events}, Late={m.late_chunks_detected}, Dup={m.duplicate_chunks_detected}, Drops={m.total_dropped}",
        anomalies_ok,
    ))

    # 7. Stop and Safe Resource Cleanup (D10-D14)
    print("\n[PHASE 7: Pipeline Termination and Resource Cleanup (D14)]")
    print("  * Executing stop() ...")
    pipeline.stop()
    print(f"  * Final Lifecycle State  : {pipeline.state.value}")
    print(f"  * Device Open Status     : {device.is_open} (Closed safely)")
    print(f"  * Buffer Remaining Chunks: {pipeline.buffer.current_size} (Buffer flushed)")

    cleanup_ok = (
        pipeline.state == AudioLifecycleState.STOPPED
        and not device.is_open
        and pipeline.buffer.is_empty
    )
    checks.append((
        "Pipeline Stop & Resource Cleanup",
        f"State={pipeline.state.value}, DeviceOpen={device.is_open}, BufEmpty={pipeline.buffer.is_empty}",
        cleanup_ok,
    ))

    # 8. Final Telemetry Report & Verification Matrix
    status = pipeline.get_status()
    print("\n[FINAL SYSTEM TELEMETRY SUMMARY]")
    print(f"  * Lifecycle State        : {status['lifecycle_state']}")
    print(f"  * Active Device          : {status['device']['name']}")
    print(f"  * Device Permission      : {status['device']['permission']}")
    print(f"  * Buffer Metrics:")
    print(f"    - Total Received       : {status['buffer']['total_received']}")
    print(f"    - Total Consumed       : {status['buffer']['total_consumed']}")
    print(f"    - Total Dropped        : {status['buffer']['total_dropped']}")
    print(f"    - Max Buffer High-Water: {status['buffer']['max_size_reached']}")
    print(f"    - Sequence Gap Events  : {status['buffer']['sequence_gap_events']}")
    print(f"    - Missing Chunks Total : {status['buffer']['missing_chunks_total']}")
    print(f"  * Total Steps Evaluated  : {status['total_processed_steps']}")

    print("\n" + "=" * 88)
    print(" CLI VERIFICATION SUMMARY MATRIX (COMPUTED LIVE)")
    print("=" * 88)
    col_w = [42, 34, 8]
    header_str = f"{'Check Description':<{col_w[0]}} | {'Measured Output':<{col_w[1]}} | {'Status':<{col_w[2]}}"
    print(header_str)
    print("-" * len(header_str))

    all_passed = True
    for desc, measured, passed in checks:
        if not passed:
            all_passed = False
        status_str = "PASS" if passed else "FAIL"
        m_str = (measured[:col_w[1] - 3] + "...") if len(measured) > col_w[1] else measured
        print(f"{desc:<{col_w[0]}} | {m_str:<{col_w[1]}} | {status_str:<{col_w[2]}}")

    print("-" * len(header_str))
    print(f"TOTAL CHECKS: {len(checks)} | PASSED: {sum(1 for _, _, p in checks if p)} | FAILED: {sum(1 for _, _, p in checks if not p)}")
    print("=" * 88)

    if all_passed:
        print(" DEMO COMPLETED SUCCESSFULLY: ALL WEEK 2 REQUIREMENTS SATISFIED (COMPUTED PASS)")
        print("=" * 88)
        return 0
    else:
        print(" DEMO FAILED: ONE OR MORE VERIFICATION CHECKS FAILED")
        print("=" * 88)
        return 1


def main() -> None:
    """Main entry point for Week 2 CLI demo."""
    sys.exit(run_week2_demo())


if __name__ == "__main__":
    main()
