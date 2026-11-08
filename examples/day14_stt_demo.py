#!/usr/bin/env python3
"""End-to-End Synthetic Audio Speech-to-Text Pipeline Demonstration (Day 14).

AI Voice Co-Pilot - Workstream W2 (Speech-to-Text).

Pipeline Flow:
    Deterministic Synthetic Audio Fixture (48kHz Stereo PCM)
    ──> AudioChunk Slicing (AudioChunker)
    ──> Audio Preprocessing & Format Standardization (AudioPreprocessor: 16kHz Mono)
    ──> Transcription Orchestration (TranscriptionOrchestrator)
    ──> Provider-Neutral Deterministic Transcriber (DeterministicFakeTranscriber)
    ──> Chronological Reconciliation & Accumulation (OrderedSegmentAccumulator)
    ──> Real-time TranscriptEvents (Interim Hypotheses & Finalized Segments)
    ──> Final Ordered Transcript Output

Guarantees:
- Zero external network dependencies, cloud keys, or paid APIs.
- No physical microphone or human voice recording required.
- Temporary audio stored strictly outside the Git repository in system temp.
- 100% deterministic and reproducible on any platform.
"""

from __future__ import annotations

import math
from pathlib import Path
import struct
import sys
import tempfile
from typing import Iterator, List

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.audio.chunker import AudioChunker
from src.audio.preprocessing import AudioPreprocessor
from src.schemas.audio import AudioChunk, AudioFormat
from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.adapter import STTAdapterConfig
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.orchestrator import TranscriptionOrchestrator
from voice_stt.schemas import TranscriptEvent, TranscriptEventType


def generate_synthetic_audio_fixture(
    output_path: Path,
    duration_sec: float = 1.0,
    sample_rate: int = 48000,
    channels: int = 2,
) -> None:
    """Generate a deterministic synthetic tone audio fixture and store it outside Git."""
    num_frames = int(sample_rate * duration_sec)
    raw_bytes = bytearray()

    # Generate harmonic dual-channel tones: 440Hz (A4) Left, 880Hz (A5) Right
    freq_left = 440.0
    freq_right = 880.0
    peak_amplitude = 12000  # Low-to-moderate amplitude to demonstrate normalization

    for i in range(num_frames):
        t = float(i) / float(sample_rate)
        left_val = int(round(peak_amplitude * math.sin(2.0 * math.pi * freq_left * t)))
        right_val = int(round(peak_amplitude * math.sin(2.0 * math.pi * freq_right * t)))
        left_clamped = max(-32768, min(32767, left_val))
        right_clamped = max(-32768, min(32767, right_val))

        if channels == 2:
            raw_bytes.extend(struct.pack("<2h", left_clamped, right_clamped))
        else:
            raw_bytes.extend(struct.pack("<h", left_clamped))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(bytes(raw_bytes))


def run_pipeline_demo() -> int:
    """Execute the end-to-end speech-to-text pipeline demo."""
    print("=" * 78)
    print("AI VOICE CO-PILOT - SPEECH-TO-TEXT END-TO-END DEMO (WEEK 2 - DAY 14)")
    print("=" * 78)

    # 1. Generate synthetic audio fixture outside the git repository
    temp_dir = Path(tempfile.gettempdir()) / "ai_voice_copilot_demo"
    fixture_path = temp_dir / "synthetic_voice_fixture_48k_stereo.pcm"
    print(f"\n[Step 1] Generating deterministic synthetic fixture (outside Git repo)...")
    print(f"         Location:    {fixture_path}")
    print(f"         Spec:        48000 Hz, 2 Channels (Stereo), 16-bit PCM, 0.6 seconds")
    generate_synthetic_audio_fixture(
        output_path=fixture_path,
        duration_sec=0.6,
        sample_rate=48000,
        channels=2,
    )
    raw_fixture_bytes = fixture_path.read_bytes()
    print(f"         Generated:   {len(raw_fixture_bytes)} bytes of synthetic audio.")

    # 2. Slice fixture into AudioChunks using AudioChunker
    print("\n[Step 2] Chunking continuous audio stream into discrete AudioChunks...")
    input_format = AudioFormat(sample_rate=48000, channels=2, sample_width=2)
    chunker = AudioChunker(audio_format=input_format, chunk_duration_ms=100.0)
    raw_chunks: List[AudioChunk] = list(chunker.chunk_stream(raw_fixture_bytes))
    print(f"         Emitted:     {len(raw_chunks)} discrete 100ms AudioChunks.")

    # 3. Configure AudioPreprocessor (48kHz Stereo -> 16kHz Mono + Normalization)
    print("\n[Step 3] Initializing Audio Preprocessor...")
    target_format = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
    preprocessor = AudioPreprocessor(
        target_format=target_format,
        normalize=True,
        target_peak=0.95,
    )
    print("         Target Spec: 16000 Hz, 1 Channel (Mono), 16-bit PCM, 0.95 Peak Normalized")

    # 4. Configure Provider-Neutral Transcriber and Accumulator
    print("\n[Step 4] Configuring Provider-Neutral Transcriber & Orchestrator...")
    script_phrases = ["voice copilot ready to assist workspace"]
    transcriber = DeterministicFakeTranscriber(
        script=script_phrases,
        config=STTAdapterConfig(interim_results=True),
        seed=12345,
    )
    accumulator = OrderedSegmentAccumulator()
    orchestrator = TranscriptionOrchestrator(
        adapter=transcriber,
        accumulator=accumulator,
        preprocessor=preprocessor,
        session_id="day14-demo-session",
    )
    orchestrator.initialize()
    print(f"         Orchestrator Session: {orchestrator.session_id}")
    print(f"         Transcriber:          {transcriber.__class__.__name__} (Offline Deterministic Mode)")

    # 5. Process Stream Through Pipeline
    print("\n[Step 5] Streaming AudioChunks through Preprocessor & Orchestrator:")
    print("-" * 78)
    print(f"{'Chunk':<7} | {'Time (s)':<10} | {'Input Bytes':<12} | {'Preprocessed':<14} | {'Events Emitted'}")
    print("-" * 78)

    all_emitted_events: List[TranscriptEvent] = []

    for idx, chunk in enumerate(raw_chunks):
        is_last = (idx == len(raw_chunks) - 1)
        events = orchestrator.process_chunk(chunk, is_last=is_last)
        all_emitted_events.extend(events)

        event_types = ", ".join(e.event_type.value for e in events) or "none"
        preprocessed_bytes = len(chunk.data) // 6  # 48k stereo -> 16k mono is 1/6 byte count
        print(
            f"#{chunk.sequence_id:<6} | {chunk.timestamp:<10.3f} | {len(chunk.data):<12} | "
            f"{'3200 B (16kHz)':<14} | {event_types}"
        )

    # 6. Display Event Stream Details
    print("\n[Step 6] Detailed Transcript Event Stream:")
    print("-" * 78)
    print(f"{'Seq':<4} | {'Event Type':<16} | {'Confidence':<10} | {'Transcript Payload'}")
    print("-" * 78)

    for evt in all_emitted_events:
        if evt.event_type == TranscriptEventType.INTERIM and evt.segment:
            conf_str = f"{evt.segment.confidence:.2f}"
            print(f"#{evt.sequence_number:<3} | [INTERIM]        | {conf_str:<10} | \"{evt.segment.text}\" (hypothesized)")
        elif evt.event_type == TranscriptEventType.FINAL and evt.segment:
            conf_str = f"{evt.segment.confidence:.2f}"
            print(f"#{evt.sequence_number:<3} | [FINAL]          | {conf_str:<10} | \"{evt.segment.text}\" (committed)")
        elif evt.event_type == TranscriptEventType.STREAM_COMPLETED:
            print(f"#{evt.sequence_number:<3} | [COMPLETED]      | {'N/A':<10} | Stream playback completed.")
        elif evt.event_type == TranscriptEventType.ERROR and evt.error:
            print(f"#{evt.sequence_number:<3} | [ERROR]          | {'N/A':<10} | [{evt.error.code}] {evt.error.message}")

    # 7. Final Ordered Transcript & Telemetry Summary
    print("-" * 78)
    final_text = orchestrator.get_full_transcript()
    summary = orchestrator.get_summary()

    print("\n[Step 7] Final Consolidated Output:")
    print("=" * 78)
    print(f"FINAL ORDERED TRANSCRIPT:\n  \"{final_text}\"\n")
    print(f"PIPELINE TELEMETRY:")
    print(f"  • Total Chunks Ingested:       {summary.get('chunks_processed', 0)}")
    print(f"  • Total Events Emitted:        {summary.get('events_emitted', 0)}")
    print(f"  • Finalized Segments:          {summary.get('final_segments_count', len(orchestrator.get_final_segments()))}")
    print(f"  • Interim Updates Handled:     {summary.get('interim_updates_count', 0)}")
    print(f"  • Duplicates Suppressed:       {summary.get('duplicates_suppressed', 0)}")
    print(f"  • Out-of-Order Count:          {summary.get('out_of_order_count', 0)}")
    print(f"  • Average Confidence:          {orchestrator.get_average_confidence():.4f}")
    print(f"  • Total Audio Duration:        {orchestrator.get_total_duration():.2f} s")
    print(f"  • Retries Attempted:           {orchestrator.retries_attempted}")
    print(f"  • Timeouts Encountered:        {orchestrator.timeouts_encountered}")
    print("=" * 78)

    # Clean up temporary synthetic audio fixture
    try:
        fixture_path.unlink(missing_ok=True)
        print("\nCleaned up temporary synthetic fixture outside repository.")
    except Exception:
        pass

    print("\n[SUCCESS] End-to-end pipeline demonstration executed cleanly.\n")
    return 0


if __name__ == "__main__":
    sys.exit(run_pipeline_demo())

