"""
Unit tests for audio error handling covering invalid, empty, and corrupt chunks.
"""

import unittest

from src.schemas.audio import AudioChunk, AudioError, AudioFormat


class TestAudioErrors(unittest.TestCase):
    """Test validation errors for invalid, empty, and corrupt audio inputs."""

    def test_invalid_sample_rate_negative_or_zero(self):
        """Negative and zero sample rates must raise AudioError."""
        with self.assertRaises(AudioError) as ctx:
            AudioFormat(sample_rate=-16000)
        self.assertEqual(ctx.exception.code, "INVALID_SAMPLE_RATE")

        with self.assertRaises(AudioError) as ctx:
            AudioFormat(sample_rate=0)
        self.assertEqual(ctx.exception.code, "INVALID_SAMPLE_RATE")

    def test_invalid_sample_rate_type(self):
        """Non-integer sample rate types (strings, floats, bools) must raise AudioError."""
        with self.assertRaises(AudioError) as ctx:
            AudioFormat(sample_rate="16000")  # type: ignore
        self.assertEqual(ctx.exception.code, "INVALID_SAMPLE_RATE")

        with self.assertRaises(AudioError) as ctx:
            AudioFormat(sample_rate=16000.5)  # type: ignore
        self.assertEqual(ctx.exception.code, "INVALID_SAMPLE_RATE")

        with self.assertRaises(AudioError) as ctx:
            AudioFormat(sample_rate=True)  # bool is subclass of int in Python
        self.assertEqual(ctx.exception.code, "INVALID_SAMPLE_RATE")

    def test_unsupported_sample_rate(self):
        """Unsupported sample rates (e.g. 12345 Hz) must raise AudioError."""
        with self.assertRaises(AudioError) as ctx:
            AudioFormat(sample_rate=12345)
        self.assertEqual(ctx.exception.code, "INVALID_SAMPLE_RATE")
        self.assertIn("Unsupported sample rate", ctx.exception.message)

    def test_invalid_channels_count(self):
        """Channels count outside {1, 2} must raise AudioError."""
        for invalid_ch in [0, -1, 3, 5, 8]:
            with self.assertRaises(AudioError) as ctx:
                AudioFormat(channels=invalid_ch)
            self.assertEqual(ctx.exception.code, "INVALID_CHANNELS")
            self.assertIn("Invalid channel count", ctx.exception.message)

    def test_invalid_channels_type(self):
        """Non-integer channels type must raise AudioError."""
        with self.assertRaises(AudioError) as ctx:
            AudioFormat(channels="mono")  # type: ignore
        self.assertEqual(ctx.exception.code, "INVALID_CHANNELS")

        with self.assertRaises(AudioError) as ctx:
            AudioFormat(channels=False)  # type: ignore
        self.assertEqual(ctx.exception.code, "INVALID_CHANNELS")

    def test_invalid_sample_width_and_encoding(self):
        """Invalid sample width or empty encoding must raise AudioError."""
        with self.assertRaises(AudioError) as ctx:
            AudioFormat(sample_width=3)  # Unsupported bit depth
        self.assertEqual(ctx.exception.code, "INVALID_SAMPLE_WIDTH")

        with self.assertRaises(AudioError) as ctx:
            AudioFormat(encoding="")  # Empty encoding
        self.assertEqual(ctx.exception.code, "INVALID_ENCODING")

    def test_invalid_chunk_sequence_id(self):
        """Negative or non-integer sequence IDs must raise AudioError."""
        valid_data = b"\x00\x00" * 10
        with self.assertRaises(AudioError) as ctx:
            AudioChunk(sequence_id=-1, timestamp=0.0, data=valid_data)
        self.assertEqual(ctx.exception.code, "INVALID_SEQUENCE_ID")

        with self.assertRaises(AudioError) as ctx:
            AudioChunk(sequence_id="0", timestamp=0.0, data=valid_data)  # type: ignore
        self.assertEqual(ctx.exception.code, "INVALID_SEQUENCE_ID")

    def test_invalid_chunk_timestamp(self):
        """Negative or non-numeric timestamps must raise AudioError."""
        valid_data = b"\x00\x00" * 10
        with self.assertRaises(AudioError) as ctx:
            AudioChunk(sequence_id=0, timestamp=-0.5, data=valid_data)
        self.assertEqual(ctx.exception.code, "INVALID_TIMESTAMP")

        with self.assertRaises(AudioError) as ctx:
            AudioChunk(sequence_id=0, timestamp="0.0", data=valid_data)  # type: ignore
        self.assertEqual(ctx.exception.code, "INVALID_TIMESTAMP")

    def test_invalid_chunk_data_type(self):
        """Chunk data that is not bytes or bytearray must raise AudioError."""
        with self.assertRaises(AudioError) as ctx:
            AudioChunk(sequence_id=0, timestamp=0.0, data=[0, 1, 2])  # type: ignore
        self.assertEqual(ctx.exception.code, "INVALID_CHUNK_DATA")

        with self.assertRaises(AudioError) as ctx:
            AudioChunk(sequence_id=0, timestamp=0.0, data="audio_string")  # type: ignore
        self.assertEqual(ctx.exception.code, "INVALID_CHUNK_DATA")

    def test_empty_chunk_data(self):
        """Empty audio bytes (b'') must raise AudioError with code EMPTY_CHUNK_DATA."""
        with self.assertRaises(AudioError) as ctx:
            AudioChunk(sequence_id=0, timestamp=0.0, data=b"")
        self.assertEqual(ctx.exception.code, "EMPTY_CHUNK_DATA")
        self.assertIn("cannot be empty", ctx.exception.message)

    def test_corrupt_chunk_data_unaligned_frame_size(self):
        """Audio chunk data not aligned to frame size must raise AudioError with CORRUPT_CHUNK_DATA."""
        # Default format: 1 channel, 2 bytes/sample -> frame_size = 2 bytes
        # 3 bytes is unaligned (remainder 1 byte) -> corrupt!
        corrupt_bytes_mono = b"\x01\x02\x03"
        with self.assertRaises(AudioError) as ctx:
            AudioChunk(sequence_id=0, timestamp=0.0, data=corrupt_bytes_mono)
        self.assertEqual(ctx.exception.code, "CORRUPT_CHUNK_DATA")
        self.assertIn("Corrupt audio chunk", ctx.exception.message)
        self.assertEqual(ctx.exception.details.get("remainder"), 1)

        # Stereo format: 2 channels * 2 bytes = 4 bytes/frame
        # 6 bytes is unaligned (remainder 2 bytes) -> corrupt!
        stereo_fmt = AudioFormat(channels=2)
        corrupt_bytes_stereo = b"\x01\x02\x03\x04\x05\x06"
        with self.assertRaises(AudioError) as ctx:
            AudioChunk(sequence_id=0, timestamp=0.0, data=corrupt_bytes_stereo, format=stereo_fmt)
        self.assertEqual(ctx.exception.code, "CORRUPT_CHUNK_DATA")
        self.assertIn("Corrupt audio chunk", ctx.exception.message)
        self.assertEqual(ctx.exception.details.get("remainder"), 2)

    def test_audio_error_serialization(self):
        """AudioError.to_dict() must conform to the system design error payload."""
        err = AudioError(
            message="Invalid sample rate provided",
            code="INVALID_SAMPLE_RATE",
            details={"sample_rate": 99999},
        )
        payload = err.to_dict()
        self.assertIn("error", payload)
        self.assertEqual(payload["error"]["code"], "INVALID_SAMPLE_RATE")
        self.assertEqual(payload["error"]["message"], "Invalid sample rate provided")
        self.assertEqual(payload["error"]["details"]["sample_rate"], 99999)
        self.assertIn("request_id", payload["error"])
        self.assertIsNone(payload["error"]["request_id"])

    def test_audio_error_with_request_id(self):
        """AudioError supports request_id in initialization and to_dict per Doc 04 section 5."""
        err = AudioError(
            message="Validation failed",
            code="VALIDATION_FAILED",
            details={"field": "channels"},
            request_id="req-test-uuid-999",
        )
        self.assertEqual(err.request_id, "req-test-uuid-999")
        self.assertIn("req-test-uuid-999", str(err))

        payload = err.to_dict()
        self.assertEqual(payload["error"]["request_id"], "req-test-uuid-999")

        # Can also pass or override request_id in to_dict()
        override_payload = err.to_dict(request_id="req-override-123")
        self.assertEqual(override_payload["error"]["request_id"], "req-override-123")

    def test_invalid_chunk_timestamp_nan_and_infinity(self):
        """NaN, +inf, and -inf timestamps must be rejected with AudioError."""
        valid_data = b"\x00\x00" * 10
        for invalid_ts in [float("nan"), float("inf"), float("-inf")]:
            with self.assertRaises(AudioError) as ctx:
                AudioChunk(sequence_id=0, timestamp=invalid_ts, data=valid_data)
            self.assertEqual(ctx.exception.code, "INVALID_TIMESTAMP")
            self.assertIn("finite", ctx.exception.message)

    def test_invalid_encoding_names(self):
        """Arbitrary / unsupported encoding names like 'banana' must raise AudioError."""
        with self.assertRaises(AudioError) as ctx:
            AudioFormat(sample_rate=16000, channels=1, sample_width=2, encoding="banana")
        self.assertEqual(ctx.exception.code, "INVALID_ENCODING")
        self.assertIn("Unsupported audio encoding", ctx.exception.message)

    def test_encoding_incompatible_with_sample_width(self):
        """Encoding must be compatible with sample_width (e.g. 16-bit encoding with 4-byte width fails)."""
        with self.assertRaises(AudioError) as ctx:
            AudioFormat(sample_rate=16000, channels=1, sample_width=4, encoding="pcm_s16le")
        self.assertEqual(ctx.exception.code, "INVALID_ENCODING")
        self.assertIn("incompatible with sample_width", ctx.exception.message)

        with self.assertRaises(AudioError) as ctx:
            AudioFormat(sample_rate=16000, channels=1, sample_width=1, encoding="pcm_s32le")
        self.assertEqual(ctx.exception.code, "INVALID_ENCODING")
        self.assertIn("incompatible with sample_width", ctx.exception.message)

    def test_chunk_bytearray_defensive_copy(self):
        """AudioChunk must defensively copy bytearray data to maintain immutability."""
        buf = bytearray(b"\x01\x02\x03\x04")
        chunk = AudioChunk(sequence_id=0, timestamp=0.0, data=buf)
        self.assertIsInstance(chunk.data, bytes)
        self.assertEqual(chunk.data, b"\x01\x02\x03\x04")

        # Mutate the source bytearray
        buf[0] = 0xAA
        buf[1] = 0xBB

        # chunk.data must remain unchanged!
        self.assertEqual(chunk.data, b"\x01\x02\x03\x04")

    def test_chunk_from_dict_error_handling(self):
        """AudioChunk.from_dict wraps missing keys, non-dict payloads, and bad base64 in AudioError."""
        # Non-dict payload
        with self.assertRaises(AudioError) as ctx:
            AudioChunk.from_dict("not-a-dict")  # type: ignore
        self.assertEqual(ctx.exception.code, "INVALID_PAYLOAD")

        # Missing sequence_id
        with self.assertRaises(AudioError) as ctx:
            AudioChunk.from_dict({"timestamp": 0.0, "data_b64": "AAAA"})
        self.assertEqual(ctx.exception.code, "INVALID_PAYLOAD")
        self.assertIn("sequence_id", ctx.exception.message)

        # Missing timestamp
        with self.assertRaises(AudioError) as ctx:
            AudioChunk.from_dict({"sequence_id": 0, "data_b64": "AAAA"})
        self.assertEqual(ctx.exception.code, "INVALID_PAYLOAD")
        self.assertIn("timestamp", ctx.exception.message)

        # Invalid base64 in data_b64
        with self.assertRaises(AudioError) as ctx:
            AudioChunk.from_dict({
                "sequence_id": 0,
                "timestamp": 0.0,
                "data_b64": "!!not_valid_base64!!!",
            })
        self.assertEqual(ctx.exception.code, "CORRUPT_CHUNK_DATA")
        self.assertIn("invalid base64", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
