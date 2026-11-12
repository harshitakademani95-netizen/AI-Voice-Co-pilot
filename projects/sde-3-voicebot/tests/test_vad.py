"""
Unit tests for Voice Activity Detection (VAD) (Week 2, D10-D11).
"""

import unittest

from src.audio.pipeline import (
    create_deterministic_chunk,
    generate_noise_burst_fixture,
    generate_silence_fixture,
    generate_speech_fixture,
)
from src.audio.vad import (
    MockVAD,
    VADConfig,
    VADEvent,
    VADEventType,
)
from src.schemas.audio import AudioError


class TestVoiceActivityDetection(unittest.TestCase):
    """Test suite covering MockVAD detection, thresholds, debounce, and fixtures."""

    def setUp(self) -> None:
        self.config = VADConfig(
            energy_threshold=0.01,
            speech_probability_threshold=0.5,
            min_speech_duration_ms=60.0,
            min_silence_duration_ms=60.0,
        )
        self.vad = MockVAD(config=self.config)

    def test_silence_detection(self) -> None:
        """Verify silence input produces SILENCE events."""
        silence_chunks = generate_silence_fixture(num_chunks=5)
        for chunk in silence_chunks:
            event = self.vad.process_chunk(chunk)
            self.assertEqual(event.event_type, VADEventType.SILENCE)
            self.assertFalse(event.is_speech)
            self.assertFalse(self.vad.is_speech_active)

    def test_speech_detection_and_continuation(self) -> None:
        """Verify speech chunks trigger SPEECH_START then SPEECH_ONGOING."""
        speech_chunks = generate_speech_fixture(num_chunks=8, amplitude=0.6)
        events = [self.vad.process_chunk(c) for c in speech_chunks]

        # First 2 chunks (40ms) accumulate duration towards min_speech_duration_ms (60ms)
        # 3rd chunk (60ms reached) triggers SPEECH_START
        start_events = [e for e in events if e.event_type == VADEventType.SPEECH_START]
        self.assertEqual(len(start_events), 1)

        # Subsequent chunks trigger SPEECH_ONGOING
        ongoing_events = [e for e in events if e.event_type == VADEventType.SPEECH_ONGOING]
        self.assertGreaterEqual(len(ongoing_events), 1)
        self.assertTrue(self.vad.is_speech_active)

    def test_noise_burst_rejection(self) -> None:
        """
        Verify short noise burst below min_speech_duration_ms is rejected.
        40ms burst (2 chunks @ 20ms) with 60ms threshold should never trigger SPEECH_START.
        """
        burst_chunks = generate_noise_burst_fixture(burst_chunks=2, total_chunks=6, amplitude=0.7)
        events = [self.vad.process_chunk(c) for c in burst_chunks]

        for e in events:
            self.assertNotEqual(e.event_type, VADEventType.SPEECH_START)
            self.assertFalse(e.is_speech)

    def test_speech_to_silence_transition(self) -> None:
        """Verify transition from speech to silence emits SPEECH_END after hang-over."""
        # 4 chunks speech (80ms > 60ms) -> enters speech
        speech_chunks = generate_speech_fixture(num_chunks=4, amplitude=0.6)
        for c in speech_chunks:
            self.vad.process_chunk(c)
        self.assertTrue(self.vad.is_speech_active)

        # Then 4 chunks silence (80ms > 60ms hang-over) -> emits SPEECH_END then SILENCE
        silence_chunks = generate_silence_fixture(num_chunks=4)
        silence_events = [self.vad.process_chunk(c) for c in silence_chunks]

        end_events = [e for e in silence_events if e.event_type == VADEventType.SPEECH_END]
        self.assertEqual(len(end_events), 1)
        self.assertFalse(self.vad.is_speech_active)

    def test_reset_behavior(self) -> None:
        """Verify reset clears internal state and speech tracking."""
        speech_chunks = generate_speech_fixture(num_chunks=5, amplitude=0.6)
        for c in speech_chunks:
            self.vad.process_chunk(c)
        self.assertTrue(self.vad.is_speech_active)

        self.vad.reset()
        self.assertFalse(self.vad.is_speech_active)

    def test_deterministic_output(self) -> None:
        """Verify identical audio fixtures yield identical VAD event sequences."""
        v1 = MockVAD(config=self.config)
        v2 = MockVAD(config=self.config)

        chunks = generate_speech_fixture(num_chunks=6, amplitude=0.5)
        res1 = [v1.process_chunk(c).event_type for c in chunks]
        res2 = [v2.process_chunk(c).event_type for c in chunks]

        self.assertEqual(res1, res2)

    def test_energy_threshold_sweep(self) -> None:
        """Verify energy_threshold independently governs candidate frame detection."""
        # Amplitude 0.05 gives RMS energy ~ 0.0354
        # With energy_threshold=0.02, energy > threshold -> speech
        # With energy_threshold=0.05, energy < threshold -> silence
        chunks = generate_speech_fixture(num_chunks=4, amplitude=0.05)

        vad_low = MockVAD(config=VADConfig(energy_threshold=0.02, speech_probability_threshold=0.3, min_speech_duration_ms=40.0))
        events_low = [vad_low.process_chunk(c).event_type for c in chunks]
        self.assertIn(VADEventType.SPEECH_START, events_low)

        vad_high = MockVAD(config=VADConfig(energy_threshold=0.05, speech_probability_threshold=0.3, min_speech_duration_ms=40.0))
        events_high = [vad_high.process_chunk(c).event_type for c in chunks]
        self.assertNotIn(VADEventType.SPEECH_START, events_high)

    def test_speech_probability_threshold_sweep(self) -> None:
        """Verify speech_probability_threshold independently governs speech confirmation."""
        # With energy ~ 0.0354 and energy_threshold=0.02:
        # prob = min(1.0, (0.0354 - 0.02) / (2 * 0.02)) ~ 0.3846
        chunks = generate_speech_fixture(num_chunks=4, amplitude=0.05)

        # Threshold 0.30: prob 0.385 >= 0.30 -> speech accepted
        vad_pass = MockVAD(config=VADConfig(energy_threshold=0.02, speech_probability_threshold=0.30, min_speech_duration_ms=40.0))
        events_pass = [vad_pass.process_chunk(c).event_type for c in chunks]
        self.assertIn(VADEventType.SPEECH_START, events_pass)

        # Threshold 0.50: prob 0.385 < 0.50 -> speech rejected
        vad_fail = MockVAD(config=VADConfig(energy_threshold=0.02, speech_probability_threshold=0.50, min_speech_duration_ms=40.0))
        events_fail = [vad_fail.process_chunk(c).event_type for c in chunks]
        self.assertNotIn(VADEventType.SPEECH_START, events_fail)

    def test_true_onset_timestamp_propagation(self) -> None:
        """Verify SPEECH_START carries the timestamp of the first chunk in qualification window."""
        chunks = generate_speech_fixture(num_chunks=4, amplitude=0.6)
        # chunks have timestamps 0.00, 0.02, 0.04, 0.06

        vad = MockVAD(config=VADConfig(min_speech_duration_ms=40.0))
        start_event = None
        for c in chunks:
            e = vad.process_chunk(c)
            if e.event_type == VADEventType.SPEECH_START:
                start_event = e
                break

        self.assertIsNotNone(start_event)
        # Onset timestamp must be 0.00, not 0.04 when duration qualified
        self.assertEqual(start_event.timestamp, 0.00)
        self.assertEqual(start_event.onset_sequence_id, 0)
        self.assertEqual(start_event.chunk_sequence_id, 1)

    def test_effective_energy_threshold_semantics(self) -> None:
        """Verify signal slightly above energy_threshold obeys effective_energy = t * (1 + 2*p)."""
        # Amplitude 0.035 yields RMS ~ 0.0247
        # With energy_threshold = 0.02:
        # prob = (0.0247 - 0.02) / (2 * 0.02) = 0.1175
        # Default p=0.5 requires effective_energy = 0.04 -> classified as SILENCE
        # Sensitive p=0.10 requires effective_energy = 0.024 -> classified as SPEECH
        chunks = generate_speech_fixture(num_chunks=4, amplitude=0.035)

        vad_default = MockVAD(config=VADConfig(energy_threshold=0.02, speech_probability_threshold=0.5, min_speech_duration_ms=40.0))
        events_default = [vad_default.process_chunk(c).event_type for c in chunks]
        self.assertNotIn(VADEventType.SPEECH_START, events_default)

        vad_sensitive = MockVAD(config=VADConfig(energy_threshold=0.02, speech_probability_threshold=0.10, min_speech_duration_ms=40.0))
        events_sensitive = [vad_sensitive.process_chunk(c).event_type for c in chunks]
        self.assertIn(VADEventType.SPEECH_START, events_sensitive)

    def test_hangover_silence_debounce(self) -> None:
        """Verify short silence gaps within hangover keep speech active, while longer gaps emit SPEECH_END."""
        vad = MockVAD(config=VADConfig(min_speech_duration_ms=40.0, min_silence_duration_ms=60.0))
        speech_chunks = generate_speech_fixture(num_chunks=3, amplitude=0.6)
        for sc in speech_chunks:
            vad.process_chunk(sc)
        self.assertTrue(vad.is_speech_active)

        # 1 silence chunk = 20ms (< 60ms hangover) -> remains SPEECH_ONGOING
        silence1 = generate_silence_fixture(num_chunks=1)[0]
        e1 = vad.process_chunk(silence1)
        self.assertEqual(e1.event_type, VADEventType.SPEECH_ONGOING)
        self.assertTrue(vad.is_speech_active)

        # 2 more silence chunks (total 60ms >= min_silence_duration_ms) -> triggers SPEECH_END
        silence2 = generate_silence_fixture(num_chunks=2)
        e2 = vad.process_chunk(silence2[0])
        e3 = vad.process_chunk(silence2[1])
        self.assertIn(VADEventType.SPEECH_END, [e2.event_type, e3.event_type])
        self.assertFalse(vad.is_speech_active)

    def test_noise_margin_rejection_vs_confirmation(self) -> None:
        """Verify 20ms burst is rejected as noise, but 60ms sustained burst is confirmed as speech."""
        vad = MockVAD(config=VADConfig(min_speech_duration_ms=60.0))
        # 1 chunk (20ms) burst
        burst_short = generate_noise_burst_fixture(burst_chunks=1, total_chunks=3, amplitude=0.8)
        events_short = [vad.process_chunk(c).event_type for c in burst_short]
        self.assertNotIn(VADEventType.SPEECH_START, events_short)

        vad.reset()
        # 3 chunks (60ms) sustained
        burst_sustained = generate_speech_fixture(num_chunks=3, amplitude=0.8)
        events_sustained = [vad.process_chunk(c).event_type for c in burst_sustained]
        self.assertIn(VADEventType.SPEECH_START, events_sustained)

    def test_invalid_config_rejection(self) -> None:
        """Verify invalid configuration values raise AudioError."""
        with self.assertRaises(AudioError):
            VADConfig(energy_threshold=-0.1)

        with self.assertRaises(AudioError):
            VADConfig(speech_probability_threshold=1.5)

        with self.assertRaises(AudioError):
            VADConfig(min_speech_duration_ms=-5.0)


if __name__ == "__main__":
    unittest.main()
