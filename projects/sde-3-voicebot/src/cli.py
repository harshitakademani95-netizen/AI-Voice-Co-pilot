"""
CLI Demonstration for AI Voice Copilot W1 Audio Pipeline.

Student: Harshita G Kademani | Team: SDE 3 | Workstream: W1 - Audio and VAD
Project: AI Voice Copilot

Usage:
    python -m src.cli [OPTIONS]

Options:
    --duration FLOAT     Total stream duration in seconds (default: 1.0)
    --chunk-ms FLOAT     Chunk duration in milliseconds (default: 20.0)
    --sample-rate INT    Audio sample rate in Hz (default: 16000)
    --channels INT       Number of channels (1=mono, 2=stereo) (default: 1)
    --frequency FLOAT    Synthetic tone frequency in Hz (default: 440.0)
    --realtime           Simulate real-time hardware pacing
    --help               Show this help message and exit
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

from src.audio.mock_source import MockMicrophone
from src.schemas.audio import AudioError, AudioFormat


def create_parser() -> argparse.ArgumentParser:
    """Create command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description=(
            "AI Voice Copilot - Audio Pipeline CLI Demo\n"
            "Workstream: W1 - Audio and VAD | Foundation Vertical Slice\n"
            "(Note: Uses deterministic mock audio; does not capture from real microphone hardware)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--short",
        action="store_true",
        help="Run a quick short demo (5 chunks / 100ms) for quick inspection",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=1.0,
        help="Total duration to stream in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--chunk-ms",
        type=float,
        default=20.0,
        help="Audio chunk duration in milliseconds (default: 20.0 ms)",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=16000,
        help="Audio sample rate in Hz (e.g. 8000, 16000, 44100, 48000) (default: 16000)",
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=1,
        help="Number of channels: 1 (mono) or 2 (stereo) (default: 1)",
    )
    parser.add_argument(
        "--frequency",
        type=float,
        default=440.0,
        help="Synthetic acoustic tone frequency in Hz (default: 440.0)",
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="Simulate real-time streaming pacing using synthetic mock source",
    )
    return parser


def run_cli_demo(args: argparse.Namespace) -> int:
    """Run the audio streaming demonstration."""
    print("=" * 86)
    print("AI Voice Copilot - Audio Pipeline Demonstration (W1)")
    print("Workstream: W1 - Audio and VAD | Student: Harshita G Kademani (SDE 3)")
    print("(Simulated mock microphone source; no physical microphone hardware required)")
    print("=" * 86)

    # If --short is selected, override duration to a brief 0.1 second demo
    stream_duration = 0.1 if args.short else args.duration

    try:
        audio_format = AudioFormat(
            sample_rate=args.sample_rate,
            channels=args.channels,
            sample_width=2,
            encoding="pcm_s16le",
        )
    except AudioError as err:
        print(f"\n[ERROR] Schema Validation Failed: {err}")
        return 1

    print("\n[Configuration]")
    print(f"  * Sample Rate    : {audio_format.sample_rate} Hz")
    print(f"  * Channels       : {audio_format.channels} ({'Mono' if audio_format.channels == 1 else 'Stereo'})")
    print(f"  * Bit Depth      : {audio_format.sample_width * 8}-bit PCM ({audio_format.encoding})")
    print(f"  * Frame Size     : {audio_format.frame_size} bytes")
    print(f"  * Chunk Duration : {args.chunk_ms} ms")
    print(f"  * Stream Duration: {stream_duration} s {'(Short Demo)' if args.short else ''}")
    print(f"  * Tone Frequency : {args.frequency} Hz")
    print(f"  * Mode           : {'Real-time simulation' if args.realtime else 'Fast deterministic batch'}")
    print("\n[Streaming AudioChunks]")
    header = f"{'Seq ID':>8} | {'Timestamp':>11} | {'Chunk Size':>12} | {'Sample Rate':>13} | {'Channels':>10} | {'Duration':>10}"
    print("-" * len(header))
    print(header)
    print("-" * len(header))

    try:
        mock_mic = MockMicrophone(
            audio_format=audio_format,
            chunk_duration_ms=args.chunk_ms,
            frequency_hz=args.frequency,
            amplitude=0.6,
            total_duration_sec=stream_duration,
        )

        chunk_count = 0
        total_bytes = 0
        total_duration_ms = 0.0

        for chunk in mock_mic.stream(simulate_realtime=args.realtime):
            chunk_count += 1
            total_bytes += chunk.size_bytes
            total_duration_ms += chunk.duration_ms

            ts_str = f"{chunk.timestamp:8.3f}s"
            size_str = f"{chunk.size_bytes} B"
            dur_str = f"{chunk.duration_ms:6.1f} ms"
            rate_str = f"{chunk.format.sample_rate} Hz"
            ch_str = f"{chunk.format.channels} ({'Mono' if chunk.format.channels == 1 else 'Stereo'})"

            print(
                f"{chunk.sequence_id:8d} | {ts_str:>11} | {size_str:>12} | "
                f"{rate_str:>13} | {ch_str:>10} | {dur_str:>10}"
            )

        print("-" * len(header))
        print("\n[Stream Summary]")
        print(f"  * Total Chunks Emitted: {chunk_count}")
        print(f"  * Total Audio Duration: {total_duration_ms / 1000.0:.3f} s ({total_duration_ms:.1f} ms)")
        print(f"  * Total Bytes Streamed: {total_bytes} bytes")
        print(f"  * Stream Status       : COMPLETED SUCCESSFUL (Deterministic & Validated)")
        print("=" * 86)
        return 0

    except AudioError as err:
        print(f"\n[AUDIO PIPELINE ERROR] {err}")
        return 1
    except KeyboardInterrupt:
        print("\n[Stream interrupted by user]")
        return 0


def main() -> None:
    """Entry point for CLI demo."""
    parser = create_parser()
    args = parser.parse_args()
    exit_code = run_cli_demo(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
