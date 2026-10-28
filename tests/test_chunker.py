"""
Unit tests for deterministic AudioChunker.
"""

import unittest

from src.audio.chunker import AudioChunker
from src.schemas.audio import AudioError, AudioFormat


class TestAudioChunker(unittest.TestCase):
    """Test deterministic audio chunker behavior, timing, and error handling."""

    def setUp(self):
        self.format = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.chunker = AudioChunker(audio_format=self.format, chunk_duration_ms=20.0)

    def test_chunker_properties(self):
        """AudioChunker computes correct frame and byte counts."""
        # 16000 Hz * 0.020 s = 320 samples -> 640 bytes
        self.assertEqual(self.chunker.samples_per_chunk, 320)
        self.assertEqual(self.chunker.bytes_per_chunk, 640)

    def test_chunker_deterministic_output(self):
        """Same input data must produce byte-for-byte identical AudioChunks on repeated runs."""
        # 1000 audio samples (2000 bytes)
        raw_audio = bytes([i % 256 for i in range(2000)])

        run_1 = self.chunker.chunk_all(raw_audio)
        run_2 = self.chunker.chunk_all(raw_audio)

        self.assertEqual(len(run_1), len(run_2))
        for c1, c2 in zip(run_1, run_2):
            self.assertEqual(c1.sequence_id, c2.sequence_id)
            self.assertEqual(c1.timestamp, c2.timestamp)
            self.assertEqual(c1.data, c2.data)
            self.assertEqual(c1.size_bytes, c2.size_bytes)
            self.assertEqual(c1.duration_ms, c2.duration_ms)

    def test_chunker_monotonic_sequence_and_timestamps(self):
        """Chunker must output strictly monotonically increasing sequence IDs and timestamps."""
        # 3 full chunks: 640 * 3 = 1920 bytes
        raw_audio = b"\x00\x00" * 960
        chunks = self.chunker.chunk_all(raw_audio)

        self.assertEqual(len(chunks), 3)

        for i, chunk in enumerate(chunks):
            self.assertEqual(chunk.sequence_id, i)
            expected_timestamp = round(i * 0.020, 6)
            self.assertAlmostEqual(chunk.timestamp, expected_timestamp, places=5)
            self.assertEqual(chunk.size_bytes, 640)
            self.assertAlmostEqual(chunk.duration_ms, 20.0, places=3)

    def test_chunker_empty_input_raises_error(self):
        """Empty raw audio input must raise AudioError with EMPTY_CHUNK_DATA."""
        with self.assertRaises(AudioError) as ctx:
            self.chunker.chunk_all(b"")
        self.assertEqual(ctx.exception.code, "EMPTY_CHUNK_DATA")

    def test_chunker_corrupt_input_raises_error(self):
        """Corrupt audio data with unaligned byte length must raise AudioError."""
        # Frame size is 2 bytes, 7 bytes is unaligned
        corrupt_audio = b"\x00" * 7
        with self.assertRaises(AudioError) as ctx:
            self.chunker.chunk_all(corrupt_audio)
        self.assertEqual(ctx.exception.code, "CORRUPT_CHUNK_DATA")

    def test_chunker_custom_start_offset(self):
        """Chunker respects start_sequence_id and start_timestamp offsets."""
        raw_audio = b"\x00\x00" * 320
        chunks = self.chunker.chunk_all(raw_audio, start_sequence_id=10, start_timestamp=2.5)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].sequence_id, 10)
        self.assertAlmostEqual(chunks[0].timestamp, 2.5, places=4)


if __name__ == "__main__":
    unittest.main()
