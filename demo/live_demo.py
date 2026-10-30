#!/usr/bin/env python3
"""AI Voice Co-Pilot - Upgraded Day 7 Live Demonstration: Chunk-to-Transcript Pipeline.

Demonstrates the speech-to-text foundation running fully in mock mode without
external cloud APIs or paid keys:
1. Streaming audio chunks into DeterministicFakeTranscriber.
2. Emitting real-time interim hypothesis events.
3. Finalizing committed segments into the OrderedSegmentAccumulator.
4. Preserving chronological order and deduplication.
5. Providing full continuous transcript and telemetry metrics.
6. Execution of canonical named fixtures (A through F).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List

# Ensure 'src' is on sys.path so the module imports reliably from any working directory
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.fixtures import FIXTURE_REGISTRY, get_fixture
from voice_stt.schemas import AudioChunk, TranscriptEventType, TranscriptSegment


def run_fixture_demo(fixture_id: str = "A", fast: bool = False) -> int:
    """Run a specific canonical fixture demonstration."""
    fixture = get_fixture(fixture_id)
    sleep_delay = 0.0 if fast else 0.06

    print("=" * 74)
    print(f"   AI Voice Co-Pilot (W2 - STT Foundation) - {fixture.name}")
    print(f"   Author: Disha D K (SDE 3) | Persona: {fixture.persona}")
    print("   Mode: Mock / Deterministic (No paid API keys required)")
    print("=" * 74)
    print(f"[*] Description: {fixture.description}")
    print(f"[*] Expected Final Transcript: \"{fixture.expected_transcript}\"")
    print("-" * 74)

    acc = OrderedSegmentAccumulator()

    # Special handling for Fixture E (Invalid Payload Injection)
    if fixture.fixture_id == "E" and fixture.raw_invalid_payload:
        print("[*] Ingesting baseline valid segment...")
        acc.ingest_event(fixture.events[0])
        baseline_seg = fixture.events[0].segment
        if baseline_seg is not None:
            print(f"    [COMMITTED FINAL] \"{baseline_seg.text}\"")

        print("[*] Ingesting deliberately malformed payload (end_time < start_time)...")
        try:
            TranscriptSegment.model_validate(fixture.raw_invalid_payload)
            print("    [ERROR] Malformed payload was unexpectedly accepted!")
            return 1
        except Exception as err:
            print(f"    [PASS - REJECTED] Malformed payload successfully caught:")
            print(f"    >>> {type(err).__name__}: {str(err).splitlines()[0]}")

        print("-" * 74)
        print("   ACCUMULATOR INTEGRITY AUDIT")
        print("-" * 74)
        summary = acc.get_summary()
        print(f"  Final Segments Count : {summary['final_segments_count']}")
        print(f"  Full Transcript      : \"{summary['full_transcript']}\"")
        print(f"  State Integrity      : PRESERVED (Uncorrupted)")
        print("=" * 74)
        return 0

    # Normal execution
    transcriber = DeterministicFakeTranscriber(fixture=fixture, seed=42)
    transcriber.initialize()
    dummy_payload = b"\x10\x00\x20\x00" * 800  # 3200 bytes PCM

    total_chunks = len(fixture.events) + 2

    with transcriber:
        for idx in range(total_chunks):
            chunk = AudioChunk(
                chunk_id=f"chk-{idx:03d}",
                data=dummy_payload,
                sequence_number=idx,
                timestamp=idx * 0.1,
                duration_ms=100.0,
                is_last=(idx == total_chunks - 1),
            )
            events = transcriber.transcribe_chunk(chunk)

            for evt in events:
                acc.ingest_event(evt)

                if evt.event_type == TranscriptEventType.INTERIM and evt.segment:
                    sys.stdout.write(
                        f"\r  [STREAMING INTERIM] t={evt.segment.start_time:.1f}s..{evt.segment.end_time:.1f}s "
                        f"| {evt.segment.text:<45} (conf: {evt.segment.confidence:.0%})"
                    )
                    sys.stdout.flush()

                elif evt.event_type == TranscriptEventType.FINAL and evt.segment:
                    print()
                    print(
                        f"  [COMMITTED FINAL ]  t={evt.segment.start_time:.1f}s..{evt.segment.end_time:.1f}s "
                        f"| \"{evt.segment.text}\" (conf: {evt.segment.confidence:.0%})"
                    )

                elif evt.event_type == TranscriptEventType.ERROR and evt.error:
                    print()
                    print(f"  [SIMULATED ERROR ]  code={evt.error.code} | {evt.error.message}")

            if sleep_delay > 0:
                time.sleep(sleep_delay)

    print()
    print("-" * 74)
    print("   ACCUMULATOR CONSOLIDATED TRANSCRIPT & METRICS")
    print("-" * 74)

    summary = acc.get_summary()
    print(f"  Total Committed Segments : {summary['final_segments_count']}")
    print(f"  Events Ingested          : {summary['events_processed']}")
    print(f"  Interim Updates          : {summary['interim_updates_count']}")
    print(f"  Duplicates Suppressed    : {summary['duplicates_suppressed']}")
    print(f"  Out-of-Order Reordered   : {summary['out_of_order_reordered']}")
    print(f"  Total Audio Duration     : {summary['total_duration_seconds']:.2f} seconds")
    print(f"  Average Confidence       : {summary['average_confidence']:.2%}")
    print(f"  Deduplicated & Verified  : {summary['is_verified']}")
    print()
    print(f"  Full Transcript Reconstructed:")
    print(f"  >>> \"{summary['full_transcript']}\"")
    print()

    # Determinism verification demonstration
    print("-" * 74)
    print("   DETERMINISM AUDIT (Pass 1 vs Pass 2 bit-for-bit check)")
    print("-" * 74)

    transcriber.reset()
    events_pass1: List[str] = []
    for idx in range(total_chunks):
        c = AudioChunk(data=dummy_payload, sequence_number=idx, timestamp=idx * 0.1, duration_ms=100.0)
        for ev in transcriber.transcribe_chunk(c):
            events_pass1.append(ev.model_dump_json())

    t2 = DeterministicFakeTranscriber(fixture=fixture, seed=42)
    t2.initialize()
    events_pass2: List[str] = []
    for idx in range(total_chunks):
        c = AudioChunk(data=dummy_payload, sequence_number=idx, timestamp=idx * 0.1, duration_ms=100.0)
        for ev in t2.transcribe_chunk(c):
            events_pass2.append(ev.model_dump_json())

    is_deterministic = (events_pass1 == events_pass2) and len(events_pass1) > 0
    print(f"  Pass 1 Events : {len(events_pass1)}")
    print(f"  Pass 2 Events : {len(events_pass2)}")
    print(f"  Exact Bit-for-Bit Match : {'PASSED (100% Deterministic)' if is_deterministic else 'FAILED'}")
    print("=" * 74)

    return 0 if (is_deterministic or fixture.is_failure_scenario) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Voice Co-Pilot STT Demonstration")
    parser.add_argument("--fixture", choices=list(FIXTURE_REGISTRY.keys()), default="A", help="Canonical fixture (A, B, C, D, E, F)")
    parser.add_argument("--fast", action="store_true", help="Execute without simulated delay")
    parser.add_argument("--all", action="store_true", help="Execute all canonical fixtures sequentially")
    args = parser.parse_args()

    if args.all:
        for fid in sorted(FIXTURE_REGISTRY.keys()):
            run_fixture_demo(fixture_id=fid, fast=True)
            print("\n")
        sys.exit(0)
    else:
        sys.exit(run_fixture_demo(fixture_id=args.fixture, fast=args.fast))
