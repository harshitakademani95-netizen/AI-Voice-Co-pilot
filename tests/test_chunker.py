"""
Unit tests for deterministic AudioChunker.
"""

import unittest

from src.audio.chunker import AudioChunker
from src.schemas.audio import AudioChunk, AudioError, AudioFormat


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

    def test_chunker_invalid_start_offsets(self):
        """Chunker rejects negative or non-finite start sequence IDs and timestamps."""
        raw_audio = b"\x00\x00" * 320

        # Negative start_sequence_id
        with self.assertRaises(AudioError) as ctx:
            self.chunker.chunk_all(raw_audio, start_sequence_id=-1)
        self.assertEqual(ctx.exception.code, "INVALID_SEQUENCE_ID")

        # Invalid type start_sequence_id
        with self.assertRaises(AudioError) as ctx:
            self.chunker.chunk_all(raw_audio, start_sequence_id="0")  # type: ignore
        self.assertEqual(ctx.exception.code, "INVALID_SEQUENCE_ID")

        # Negative start_timestamp
        with self.assertRaises(AudioError) as ctx:
            self.chunker.chunk_all(raw_audio, start_timestamp=-1.0)
        self.assertEqual(ctx.exception.code, "INVALID_TIMESTAMP")

        # Non-finite start_timestamp (NaN)
        with self.assertRaises(AudioError) as ctx:
            self.chunker.chunk_all(raw_audio, start_timestamp=float("nan"))
        self.assertEqual(ctx.exception.code, "INVALID_TIMESTAMP")

    def test_validate_sequence_valid_stream(self):
        """AudioChunker.validate_sequence passes on valid strictly monotonically increasing streams."""
        raw_audio = b"\x00\x00" * 960  # 3 chunks
        chunks = self.chunker.chunk_all(raw_audio)
        validated = AudioChunker.validate_sequence(chunks)
        self.assertEqual(len(validated), 3)

    def test_validate_sequence_rejects_out_of_order_sequences(self):
        """AudioChunker.validate_sequence rejects non-increasing sequence IDs and non-advancing timestamps."""
        raw_chunk_data = b"\x00\x00" * 320

        # Repeated sequence ID (0, 0)
        c0 = AudioChunk(sequence_id=0, timestamp=0.0, data=raw_chunk_data, format=self.format)
        c0_dup = AudioChunk(sequence_id=0, timestamp=0.02, data=raw_chunk_data, format=self.format)
        with self.assertRaises(AudioError) as ctx:
            AudioChunker.validate_sequence([c0, c0_dup])
        self.assertEqual(ctx.exception.code, "INVALID_SEQUENCE_ORDER")

        # Decreasing sequence ID (1, 0)
        c1 = AudioChunk(sequence_id=1, timestamp=0.02, data=raw_chunk_data, format=self.format)
        with self.assertRaises(AudioError) as ctx:
            AudioChunker.validate_sequence([c1, c0])
        self.assertEqual(ctx.exception.code, "INVALID_SEQUENCE_ORDER")

        # Repeated timestamp (0.02, 0.02)
        c1_bad_ts = AudioChunk(sequence_id=1, timestamp=0.0, data=raw_chunk_data, format=self.format)
        with self.assertRaises(AudioError) as ctx:
            AudioChunker.validate_sequence([c0, c1_bad_ts])
        self.assertEqual(ctx.exception.code, "INVALID_TIMESTAMP_ORDER")

        # Decreasing timestamp (0.04 -> 0.02)
        c2 = AudioChunk(sequence_id=2, timestamp=0.01, data=raw_chunk_data, format=self.format)
        with self.assertRaises(AudioError) as ctx:
            AudioChunker.validate_sequence([c0, c1, c2])
        self.assertEqual(ctx.exception.code, "INVALID_TIMESTAMP_ORDER")

        # Empty chunk sequence
        with self.assertRaises(AudioError) as ctx:
            AudioChunker.validate_sequence([])
        self.assertEqual(ctx.exception.code, "EMPTY_CHUNK_DATA")

        # Invalid item type
        with self.assertRaises(AudioError) as ctx:
            AudioChunker.validate_sequence([c0, "not-a-chunk"])
        self.assertEqual(ctx.exception.code, "INVALID_CHUNK_DATA")


if __name__ == "__main__":
    unittest.main()
