"""Integration tests verifying end-to-end chunk-to-transcript pipeline."""

from typing import List
import pytest

from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.schemas import AudioChunk


class TestEndToEndPipeline:
    """Verifies end-to-end integration of AudioChunks -> FakeTranscriber -> OrderedSegmentAccumulator."""

    def test_mock_chunk_to_transcript_flow(self, sample_audio_bytes: bytes) -> None:
        target_script = [
            "Why is this application showing this error?",
            "Explain the methodology shown on this page.",
        ]
        transcriber = DeterministicFakeTranscriber(
            script=target_script,
            seed=42,
        )
        accumulator = OrderedSegmentAccumulator()

        with transcriber:
            # Simulate 20 streaming 100ms audio chunks
            for i in range(20):
                chunk = AudioChunk(
                    chunk_id=f"stream-{i:03d}",
                    data=sample_audio_bytes,
                    sequence_number=i,
                    timestamp=i * 0.1,
                    duration_ms=100.0,
                    sample_rate=16000,
                    is_last=(i == 19),
                )
                events = transcriber.transcribe_chunk(chunk)
                for event in events:
                    accumulator.ingest_event(event)

        final_segments = accumulator.get_final_segments()
        assert len(final_segments) == 2
        assert final_segments[0].text == "Why is this application showing this error?"
        assert final_segments[1].text == "Explain the methodology shown on this page."

        full_transcript = accumulator.get_full_transcript()
        expected = "Why is this application showing this error? Explain the methodology shown on this page."
        assert full_transcript == expected
        assert accumulator.get_interim_segment() is None
        assert accumulator.get_average_confidence() > 0.90

