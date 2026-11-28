"""
Unit tests for deterministic MockMicrophone audio source.
"""

import unittest

from src.audio.mock_source import MockMicrophone
from src.schemas.audio import AudioError, AudioFormat


class TestMockMicrophone(unittest.TestCase):
    """Test MockMicrophone source generation, determinism, and streaming."""

    def test_mock_microphone_defaults(self):
        """MockMicrophone default initialization has a safe finite 1.0s duration limit."""
        mic = MockMicrophone()
        self.assertEqual(mic.format.sample_rate, 16000)
        self.assertEqual(mic.format.channels, 1)
        self.assertEqual(mic.chunk_duration_ms, 20.0)
        self.assertEqual(mic.current_sequence_id, 0)
        self.assertEqual(mic.current_timestamp, 0.0)
        self.assertEqual(mic.total_duration_sec, 1.0)
        self.assertTrue(mic.is_active)

        # Default streaming safely finishes without hanging, producing exactly 50 chunks (1.0s)
        chunks = list(mic.stream(simulate_realtime=False))
        self.assertEqual(len(chunks), 50)
        self.assertFalse(mic.is_active)

    def test_mock_microphone_explicit_unbounded_streaming(self):
        """MockMicrophone with total_duration_sec=None allows continuous unbounded streaming."""
        mic = MockMicrophone(total_duration_sec=None)
        self.assertIsNone(mic.total_duration_sec)
        self.assertTrue(mic.is_active)

        # Stream 10 chunks using max_chunks cap; mic remains active
        chunks = list(mic.stream(simulate_realtime=False, max_chunks=10))
        self.assertEqual(len(chunks), 10)
        self.assertTrue(mic.is_active)

    def test_mock_microphone_chunk_emission(self):
        """MockMicrophone emits valid chunks with increasing sequence IDs and timestamps."""
        mic = MockMicrophone(chunk_duration_ms=20.0)
        chunk_0 = mic.read_chunk()
        self.assertIsNotNone(chunk_0)
        self.assertEqual(chunk_0.sequence_id, 0)
        self.assertEqual(chunk_0.timestamp, 0.0)
        self.assertEqual(chunk_0.size_bytes, 640)
        self.assertAlmostEqual(chunk_0.duration_ms, 20.0, places=3)

        chunk_1 = mic.read_chunk()
        self.assertIsNotNone(chunk_1)
        self.assertEqual(chunk_1.sequence_id, 1)
        self.assertAlmostEqual(chunk_1.timestamp, 0.020, places=5)
        self.assertEqual(chunk_1.size_bytes, 640)

        chunk_2 = mic.read_chunk()
        self.assertIsNotNone(chunk_2)
        self.assertEqual(chunk_2.sequence_id, 2)
        self.assertAlmostEqual(chunk_2.timestamp, 0.040, places=5)

    def test_mock_microphone_determinism(self):
        """Two separate MockMicrophone instances with identical parameters produce 100% identical streams."""
        mic_a = MockMicrophone(
            audio_format=AudioFormat(sample_rate=16000, channels=1),
            chunk_duration_ms=25.0,
            frequency_hz=440.0,
            total_duration_sec=0.25,
        )
        mic_b = MockMicrophone(
            audio_format=AudioFormat(sample_rate=16000, channels=1),
            chunk_duration_ms=25.0,
            frequency_hz=440.0,
            total_duration_sec=0.25,
        )

        chunks_a = list(mic_a.stream(simulate_realtime=False))
        chunks_b = list(mic_b.stream(simulate_realtime=False))

        self.assertGreater(len(chunks_a), 0)
        self.assertEqual(len(chunks_a), len(chunks_b))

        for ca, cb in zip(chunks_a, chunks_b):
            self.assertEqual(ca.sequence_id, cb.sequence_id)
            self.assertEqual(ca.timestamp, cb.timestamp)
            self.assertEqual(ca.data, cb.data)
            self.assertEqual(ca.size_bytes, cb.size_bytes)
            self.assertEqual(ca.format, cb.format)

    def test_mock_microphone_reset(self):
        """Resetting a MockMicrophone produces the exact same stream again."""
        mic = MockMicrophone(
            chunk_duration_ms=20.0,
            total_duration_sec=0.1,
        )
        first_run = list(mic.stream(simulate_realtime=False))

        mic.reset()
        self.assertEqual(mic.current_sequence_id, 0)
        self.assertEqual(mic.current_timestamp, 0.0)

        second_run = list(mic.stream(simulate_realtime=False))

        self.assertEqual(len(first_run), len(second_run))
        for c1, c2 in zip(first_run, second_run):
            self.assertEqual(c1.sequence_id, c2.sequence_id)
            self.assertEqual(c1.timestamp, c2.timestamp)
            self.assertEqual(c1.data, c2.data)

    def test_mock_microphone_stereo_and_high_sample_rate(self):
        """MockMicrophone supports stereo channels and 48kHz digital rate."""
        stereo_fmt = AudioFormat(sample_rate=48000, channels=2, sample_width=2)
        mic = MockMicrophone(audio_format=stereo_fmt, chunk_duration_ms=10.0, total_duration_sec=0.05)
        chunks = list(mic.stream(simulate_realtime=False))

        # 48000 * 0.010 = 480 samples. 480 * 2 ch * 2 bytes = 1920 bytes
        self.assertEqual(len(chunks), 5)
        for chunk in chunks:
            self.assertEqual(chunk.format.channels, 2)
            self.assertEqual(chunk.format.sample_rate, 48000)
            self.assertEqual(chunk.size_bytes, 1920)
            self.assertAlmostEqual(chunk.duration_ms, 10.0, places=3)

    def test_mock_microphone_invalid_parameters(self):
        """Invalid microphone parameters raise AudioError."""
        with self.assertRaises(AudioError):
            MockMicrophone(chunk_duration_ms=-10.0)

        with self.assertRaises(AudioError):
            MockMicrophone(frequency_hz=0)

        with self.assertRaises(AudioError):
            MockMicrophone(amplitude=1.5)

        with self.assertRaises(AudioError):
            MockMicrophone(total_duration_sec=-1.0)

        # Test NaN / inf rejection
        for bad_val in [float("nan"), float("inf")]:
            with self.assertRaises(AudioError):
                MockMicrophone(chunk_duration_ms=bad_val)
            with self.assertRaises(AudioError):
                MockMicrophone(frequency_hz=bad_val)
            with self.assertRaises(AudioError):
                MockMicrophone(amplitude=bad_val)
            with self.assertRaises(AudioError):
                MockMicrophone(total_duration_sec=bad_val)

    def test_mock_microphone_sample_width_4_synthesis(self):
        """MockMicrophone synthesizes 32-bit (4-byte) samples with correct byte sizes and zero timestamp drift."""
        fmt_32 = AudioFormat(sample_rate=16000, channels=1, sample_width=4, encoding="pcm_s32le")
        mic = MockMicrophone(audio_format=fmt_32, chunk_duration_ms=20.0, total_duration_sec=0.1)

        chunks = list(mic.stream(simulate_realtime=False))
        self.assertEqual(len(chunks), 5)

        # 16000 * 0.020 = 320 samples. 320 samples * 1 ch * 4 bytes = 1280 bytes
        for idx, chunk in enumerate(chunks):
            self.assertEqual(chunk.sequence_id, idx)
            self.assertEqual(chunk.format.sample_width, 4)
            self.assertEqual(chunk.size_bytes, 1280)
            self.assertEqual(chunk.num_samples, 320)
            self.assertAlmostEqual(chunk.duration_ms, 20.0, places=3)
            self.assertAlmostEqual(chunk.timestamp, idx * 0.020, places=5)

    def test_mock_microphone_sample_width_1_synthesis(self):
        """MockMicrophone synthesizes 8-bit (1-byte) samples with correct byte sizes."""
        fmt_8 = AudioFormat(sample_rate=16000, channels=1, sample_width=1, encoding="pcm_u8")
        mic = MockMicrophone(audio_format=fmt_8, chunk_duration_ms=20.0, total_duration_sec=0.06)

        chunks = list(mic.stream(simulate_realtime=False))
        self.assertEqual(len(chunks), 3)

        # 16000 * 0.020 = 320 samples * 1 ch * 1 byte = 320 bytes
        for chunk in chunks:
            self.assertEqual(chunk.format.sample_width, 1)
            self.assertEqual(chunk.size_bytes, 320)
            self.assertAlmostEqual(chunk.duration_ms, 20.0, places=3)

    def test_mock_microphone_duration_overshoot_protection(self):
        """
        MockMicrophone does not overshoot requested total duration due to sample rounding.
        At 22050 Hz with 10 ms chunks, 220.5 samples rounds to 220.
        A 1.0 s stream should yield exactly 100 chunks (not 101 chunks ending at 1.0077 s).
        """
        fmt = AudioFormat(sample_rate=22050, channels=1, sample_width=2)
        mic = MockMicrophone(
            audio_format=fmt,
            chunk_duration_ms=10.0,
            total_duration_sec=1.0,
        )

        chunks = list(mic.stream(simulate_realtime=False))
        self.assertEqual(len(chunks), 100)
        final_chunk = chunks[-1]
        self.assertLessEqual(final_chunk.timestamp + final_chunk.duration_seconds, 1.0001)


if __name__ == "__main__":
    unittest.main()
