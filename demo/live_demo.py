#!/usr/bin/env python3
"""AI Voice Co-Pilot - Day 7 Live Demonstration: Chunk-to-Transcript Pipeline.

Demonstrates the speech-to-text foundation running fully in mock mode without
external cloud APIs or paid keys:
1. Streaming audio chunks into DeterministicFakeTranscriber.
2. Emitting real-time interim hypothesis events.
3. Finalizing committed segments into the OrderedSegmentAccumulator.
4. Preserving chronological order and deduplication.
5. Providing full continuous transcript and telemetry metrics.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import List

from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.adapter import STTAdapterConfig
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.schemas import AudioChunk, TranscriptEventType


def run_mock_demo(fast: bool = False) -> int:
    """Run the live mock speech-to-text demonstration."""
    sleep_delay = 0.0 if fast else 0.08

    print("=" * 72)
    print("   AI Voice Co-Pilot (W2 - STT Foundation) - Day 7 Live Demonstration")
    print("   Author: Disha D K (SDE 3) | Workstream: Speech-to-Text Pipeline")
    print("   Mode: Mock / Deterministic (No paid API keys required)")
    print("=" * 72)
    print()

    # User utterance scenario from PRD User Personas:
    # "Why is this application showing this error? Explain the methodology."
    demo_script = [
        "Why is this application showing this error?",
        "Explain the methodology shown on this page.",
    ]

    config = STTAdapterConfig(
        language="en",
        sample_rate=16000,
        interim_results=True,
        model_name="deterministic-mock-v1",
    )

    transcriber = DeterministicFakeTranscriber(
        config=config,
        script=demo_script,
        seed=42,
    )
    accumulator = OrderedSegmentAccumulator()

    # Create 20 simulated 100ms audio chunks (each 3200 bytes PCM)
    total_chunks = 20
    chunk_payload = b"\x10\x00\x20\x00" * 800  # 3200 bytes

    print(f"[*] Initialized STT Adapter: {config.model_name}")
    print(f"[*] Target Utterance Scenario: {len(demo_script)} phrases")
    print(f"[*] Streaming {total_chunks} audio chunks (100ms each) into adapter...")
    print("-" * 72)

    with transcriber:
        for idx in range(total_chunks):
            is_last_chunk = (idx == total_chunks - 1)
            chunk = AudioChunk(
                chunk_id=f"chk-{idx:03d}",
                data=chunk_payload,
                sequence_number=idx,
                timestamp=idx * 0.1,
                duration_ms=100.0,
                sample_rate=16000,
                is_last=is_last_chunk,
            )

            events = transcriber.transcribe_chunk(chunk)

            for evt in events:
                accumulator.ingest_event(evt)

                if evt.event_type == TranscriptEventType.INTERIM and evt.segment:
                    sys.stdout.write(
                        f"\r  [STREAMING INTERIM] t={evt.segment.start_time:.1f}s..{evt.segment.end_time:.1f}s "
                        f"| {evt.segment.text:<45} (conf: {evt.segment.confidence:.2f})"
                    )
                    sys.stdout.flush()

                elif evt.event_type == TranscriptEventType.FINAL and evt.segment:
                    print()
                    print(
                        f"  [COMMITTED FINAL ]  t={evt.segment.start_time:.1f}s..{evt.segment.end_time:.1f}s "
                        f"| \"{evt.segment.text}\" (conf: {evt.segment.confidence:.2f})"
                    )

            if sleep_delay > 0:
                time.sleep(sleep_delay)

    print()
    print("-" * 72)
    print("   ACCUMULATOR CONSOLIDATED TRANSCRIPT & METRICS")
    print("-" * 72)

    summary = accumulator.get_summary()
    print(f"  Total Committed Segments : {summary['final_segments_count']}")
    print(f"  Events Ingested          : {summary['events_processed']}")
    print(f"  Total Audio Duration     : {summary['total_duration_seconds']:.2f} seconds")
    print(f"  Average Confidence       : {summary['average_confidence']:.2%}")
    print()
    print(f"  Full Transcript Reconstructed:")
    print(f"  >>> \"{summary['full_transcript']}\"")
    print()

    # Determinism verification demonstration
    print("-" * 72)
    print("   DETERMINISM AUDIT (Pass 1 vs Pass 2 bit-for-bit check)")
    print("-" * 72)

    transcriber.reset()
    events_replay: List[str] = []
    for idx in range(total_chunks):
        chunk = AudioChunk(
            chunk_id=f"chk-{idx:03d}",
            data=chunk_payload,
            sequence_number=idx,
            timestamp=idx * 0.1,
            duration_ms=100.0,
            sample_rate=16000,
            is_last=(idx == total_chunks - 1),
        )
        for ev in transcriber.transcribe_chunk(chunk):
            events_replay.append(ev.model_dump_json())

    # Rerun with identical fresh instance
    t2 = DeterministicFakeTranscriber(config=config, script=demo_script, seed=42)
    t2.initialize()
    events_fresh: List[str] = []
    for idx in range(total_chunks):
        chunk = AudioChunk(
            chunk_id=f"chk-{idx:03d}",
            data=chunk_payload,
            sequence_number=idx,
            timestamp=idx * 0.1,
            duration_ms=100.0,
            sample_rate=16000,
            is_last=(idx == total_chunks - 1),
        )
        for ev in t2.transcribe_chunk(chunk):
            events_fresh.append(ev.model_dump_json())

    is_deterministic = (events_replay == events_fresh)
    print(f"  Event Count Pass 1 : {len(events_replay)}")
    print(f"  Event Count Pass 2 : {len(events_fresh)}")
    print(f"  Exact Bit-for-Bit Match : {'PASSED (100% Deterministic)' if is_deterministic else 'FAILED'}")
    print("=" * 72)
    print("   Day 7 Live Demonstration Complete! All criteria met.")
    print("=" * 72)

    return 0 if is_deterministic else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Day 7 Live STT Demonstration")
    parser.add_argument("--fast", action="store_true", help="Execute without simulated streaming delay")
    args = parser.parse_args()
    sys.exit(run_mock_demo(fast=args.fast))
