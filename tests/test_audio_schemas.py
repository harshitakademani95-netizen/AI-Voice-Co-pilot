"""
Unit tests for AudioChunk, AudioFormat, and AudioError schemas.
"""

import unittest

from src.schemas.audio import (
    SUPPORTED_CHANNELS,
    SUPPORTED_SAMPLE_RATES,
    AudioChunk,
    AudioError,
    AudioFormat,
)


class TestAudioSchemas(unittest.TestCase):
    """Test audio schema definitions, properties, and serialization."""

    def test_audio_format_defaults(self):
        """AudioFormat should default to 16kHz mono 16-bit PCM."""
        fmt = AudioFormat()
        self.assertEqual(fmt.sample_rate, 16000)
        self.assertEqual(fmt.channels, 1)
        self.assertEqual(fmt.sample_width, 2)
        self.assertEqual(fmt.encoding, "pcm_s16le")
        self.assertEqual(fmt.frame_size, 2)
        self.assertEqual(fmt.bytes_per_second, 32000)

    def test_audio_format_stereo(self):
        """AudioFormat should calculate stereo frame size and throughput correctly."""
        fmt = AudioFormat(sample_rate=48000, channels=2, sample_width=2)
        self.assertEqual(fmt.sample_rate, 48000)
        self.assertEqual(fmt.channels, 2)
        self.assertEqual(fmt.frame_size, 4)
        self.assertEqual(fmt.bytes_per_second, 192000)

    def test_audio_format_serialization(self):
        """AudioFormat should serialize to dict and deserialize back losslessly."""
        original = AudioFormat(sample_rate=44100, channels=2, sample_width=2, encoding="pcm_s16le")
        serialized = original.to_dict()
        self.assertIn("sample_rate", serialized)
        self.assertIn("channels", serialized)
        self.assertIn("frame_size", serialized)

        restored = AudioFormat.from_dict(serialized)
        self.assertEqual(original, restored)

    def test_audio_chunk_valid_happy_path(self):
        """AudioChunk should instantiate with valid parameters and compute metrics."""
        fmt = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        # 320 samples of 16-bit PCM = 640 bytes (20ms)
        pcm_bytes = b"\x00\x00" * 320
        chunk = AudioChunk(
            sequence_id=0,
            timestamp=0.0,
            data=pcm_bytes,
            format=fmt,
        )
        self.assertEqual(chunk.sequence_id, 0)
        self.assertEqual(chunk.timestamp, 0.0)
        self.assertEqual(chunk.size_bytes, 640)
        self.assertEqual(chunk.num_samples, 320)
        self.assertAlmostEqual(chunk.duration_ms, 20.0, places=3)
        self.assertAlmostEqual(chunk.duration_seconds, 0.020, places=4)

    def test_audio_chunk_serialization(self):
        """AudioChunk should serialize to dict with base64 and deserialize cleanly."""
        fmt = AudioFormat(sample_rate=16000, channels=1)
        raw_bytes = b"\x01\x02" * 160
        chunk = AudioChunk(
            sequence_id=42,
            timestamp=1.5,
            data=raw_bytes,
            format=fmt,
            metadata={"source": "test"},
        )
        data_dict = chunk.to_dict(include_base64_data=True)
        self.assertEqual(data_dict["sequence_id"], 42)
        self.assertEqual(data_dict["size_bytes"], len(raw_bytes))
        self.assertIn("data_b64", data_dict)

        restored = AudioChunk.from_dict(data_dict)
        self.assertEqual(restored.sequence_id, chunk.sequence_id)
        self.assertAlmostEqual(restored.timestamp, chunk.timestamp, places=5)
        self.assertEqual(restored.data, chunk.data)
        self.assertEqual(restored.format, chunk.format)
        self.assertEqual(restored.metadata, chunk.metadata)

    def test_schema_documentation(self):
        """Ensure schemas have non-empty docstrings explaining fields and constraints."""
        self.assertIsNotNone(AudioChunk.__doc__)
        self.assertIn("sequence_id", AudioChunk.__doc__)
        self.assertIn("timestamp", AudioChunk.__doc__)
        self.assertIn("data", AudioChunk.__doc__)

        self.assertIsNotNone(AudioFormat.__doc__)
        self.assertIn("sample_rate", AudioFormat.__doc__)
        self.assertIn("channels", AudioFormat.__doc__)
        self.assertIn("encoding", AudioFormat.__doc__)

        self.assertIsNotNone(AudioError.__doc__)

    def test_audio_format_from_dict_validation(self):
        """AudioFormat.from_dict validates required fields and does not silently default missing keys."""
        # Valid explicit format dictionary
        fmt = AudioFormat.from_dict({"sample_rate": 48000, "channels": 2})
        self.assertEqual(fmt.sample_rate, 48000)
        self.assertEqual(fmt.channels, 2)
        self.assertEqual(fmt.sample_width, 2)
        self.assertEqual(fmt.encoding, "pcm_s16le")

        # Missing sample_rate
        with self.assertRaises(AudioError) as ctx:
            AudioFormat.from_dict({"channels": 1})
        self.assertEqual(ctx.exception.code, "INVALID_PAYLOAD")
        self.assertIn("sample_rate", ctx.exception.message)

        # Missing channels
        with self.assertRaises(AudioError) as ctx:
            AudioFormat.from_dict({"sample_rate": 16000})
        self.assertEqual(ctx.exception.code, "INVALID_PAYLOAD")
        self.assertIn("channels", ctx.exception.message)

        # Empty dictionary
        with self.assertRaises(AudioError) as ctx:
            AudioFormat.from_dict({})
        self.assertEqual(ctx.exception.code, "INVALID_PAYLOAD")

        # Non-dictionary payload
        with self.assertRaises(AudioError) as ctx:
            AudioFormat.from_dict("not-a-dict")  # type: ignore
        self.assertEqual(ctx.exception.code, "INVALID_PAYLOAD")

    def test_audio_chunk_from_dict_with_incomplete_format(self):
        """AudioChunk.from_dict rejects malformed or incomplete nested format dictionaries."""
        raw_b64 = "AAAA"

        # Incomplete format dictionary (empty dict)
        with self.assertRaises(AudioError) as ctx:
            AudioChunk.from_dict({
                "sequence_id": 0,
                "timestamp": 0.0,
                "data_b64": raw_b64,
                "format": {},
            })
        self.assertEqual(ctx.exception.code, "INVALID_PAYLOAD")

        # Incomplete format dictionary (missing channels)
        with self.assertRaises(AudioError) as ctx:
            AudioChunk.from_dict({
                "sequence_id": 0,
                "timestamp": 0.0,
                "data_b64": raw_b64,
                "format": {"sample_rate": 16000},
            })
        self.assertEqual(ctx.exception.code, "INVALID_PAYLOAD")

        # Invalid format type (string instead of dict/AudioFormat)
        with self.assertRaises(AudioError) as ctx:
            AudioChunk.from_dict({
                "sequence_id": 0,
                "timestamp": 0.0,
                "data_b64": raw_b64,
                "format": "invalid-format-string",
            })
        self.assertEqual(ctx.exception.code, "INVALID_FORMAT")


if __name__ == "__main__":
    unittest.main()
