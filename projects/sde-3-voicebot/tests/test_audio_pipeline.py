"""
Unit tests for End-to-End Integrated Audio Pipeline (Week 2, D14).
"""

import unittest

from src.audio.buffer import BufferPushStatus
from src.audio.device import (
    AudioDeviceInfo,
    AudioPermissionState,
    MockAudioDevice,
)
from src.audio.lifecycle import AudioLifecycleState
from src.audio.pipeline import (
    AudioPipeline,
    create_deterministic_chunk,
    generate_noise_burst_fixture,
    generate_silence_fixture,
    generate_speech_fixture,
)
from src.audio.vad import MockVAD, VADConfig, VADEventType
from src.schemas.audio import AudioError, AudioFormat


class TestAudioPipelineIntegration(unittest.TestCase):
    """Test suite covering end-to-end pipeline orchestration, state, and edge-case fixtures."""

    def setUp(self) -> None:
        self.fmt = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.pipeline = AudioPipeline(
            buffer_capacity=10,
            vad_config=VADConfig(
                energy_threshold=0.01,
                speech_probability_threshold=0.5,
                min_speech_duration_ms=40.0,
                min_silence_duration_ms=60.0,
            ),
        )

    def test_pipeline_happy_path_flow(self) -> None:
        """
        Verify complete happy path:
        Select device -> Request permission -> Start -> Process steps -> Pause -> Resume -> Stop.
        """
        # 1. Device selection
        info = self.pipeline.select_device("mock-mic-headset")
        self.assertEqual(info.device_id, "mock-mic-headset")

        # 2. Permission
        perm = self.pipeline.request_permission()
        self.assertEqual(perm, AudioPermissionState.GRANTED)

        # 3. Start
        self.pipeline.start()
        self.assertEqual(self.pipeline.state, AudioLifecycleState.RUNNING)

        # 4. Process steps
        step1 = self.pipeline.process_step()
        self.assertIsNotNone(step1)
        chunk, vad_event = step1
        self.assertEqual(chunk.sequence_id, 0)
        self.assertIsInstance(vad_event.event_type, VADEventType)

        # 5. Pause
        self.pipeline.pause()
        self.assertEqual(self.pipeline.state, AudioLifecycleState.PAUSED)
        self.assertIsNone(self.pipeline.process_step())

        # 6. Resume
        self.pipeline.resume()
        self.assertEqual(self.pipeline.state, AudioLifecycleState.RUNNING)
        step2 = self.pipeline.process_step()
        self.assertIsNotNone(step2)

        # 7. Stop and cleanup
        self.pipeline.stop()
        self.assertEqual(self.pipeline.state, AudioLifecycleState.STOPPED)
        self.assertTrue(self.pipeline.buffer.is_empty)

    def test_pipeline_status_reporting(self) -> None:
        """Verify pipeline status returns comprehensive telemetry."""
        self.pipeline.start()
        for _ in range(3):
            self.pipeline.process_step()

        status = self.pipeline.get_status()
        self.assertEqual(status["lifecycle_state"], "RUNNING")
        self.assertEqual(status["device"]["permission"], "GRANTED")
        self.assertTrue(status["device"]["is_open"])
        self.assertEqual(status["total_processed_steps"], 3)
        self.assertIn("buffer", status)
        self.assertIn("vad", status)
        self.assertIn("last_push_result", status)
        self.assertIsNotNone(status["last_push_result"])
        self.assertEqual(status["last_push_result"]["status"], "ACCEPTED")

        self.pipeline.stop()

    def test_simulated_buffer_overflow(self) -> None:
        """Verify pipeline backpressure simulation records exact accepted and dropped counts."""
        self.pipeline.start()
        # Burst 25 chunks into buffer with capacity 10
        drop_results = self.pipeline.simulate_overflow(burst_count=25)
        self.assertEqual(len(drop_results), 25)
        accepted = sum(1 for r in drop_results if r.status == BufferPushStatus.ACCEPTED)
        dropped = sum(1 for r in drop_results if r.status == BufferPushStatus.DROPPED)
        self.assertEqual(accepted, 10)
        self.assertEqual(dropped, 15)

        metrics = self.pipeline.buffer_metrics
        self.assertEqual(metrics.total_dropped, 15)
        self.assertEqual(metrics.max_size_reached, 10)

        self.pipeline.stop()

    def test_fixture_continuous_speech_generates_speech_events(self) -> None:
        """Verify processing synthetic speech fixture produces speech events."""
        speech_chunks = generate_speech_fixture(num_chunks=6, amplitude=0.6)
        events = [self.pipeline.vad.process_chunk(c) for c in speech_chunks]

        # Should produce SPEECH_START and SPEECH_ONGOING
        event_types = [e.event_type for e in events]
        self.assertIn(VADEventType.SPEECH_START, event_types)
        self.assertIn(VADEventType.SPEECH_ONGOING, event_types)

    def test_fixture_silence_generates_silence_events(self) -> None:
        """Verify processing synthetic silence fixture produces SILENCE events."""
        silence_chunks = generate_silence_fixture(num_chunks=5)
        events = [self.pipeline.vad.process_chunk(c) for c in silence_chunks]

        for e in events:
            self.assertEqual(e.event_type, VADEventType.SILENCE)

    def test_fixture_noise_burst_rejected_by_vad(self) -> None:
        """Verify noise bursts under min_speech_duration_ms do not trigger SPEECH_START."""
        burst_chunks = generate_noise_burst_fixture(burst_chunks=1, total_chunks=4, amplitude=0.8)
        events = [self.pipeline.vad.process_chunk(c) for c in burst_chunks]

        for e in events:
            self.assertNotEqual(e.event_type, VADEventType.SPEECH_START)

    def test_stop_during_paused_state(self) -> None:
        """Verify stopping from PAUSED state cleanly terminates and purges buffer."""
        self.pipeline.start()
        self.pipeline.pause()
        self.assertEqual(self.pipeline.state, AudioLifecycleState.PAUSED)
        self.pipeline.stop()
        self.assertEqual(self.pipeline.state, AudioLifecycleState.STOPPED)

    def test_unsupported_device_error_in_pipeline(self) -> None:
        """Verify selecting an unsupported device raises error without crashing."""
        unsupported = AudioDeviceInfo(
            device_id="unsupported-usb-card",
            name="Ancient ISA Card",
            channels=1,
            sample_rate=16000,
            is_mock=True,
            supported=False,
        )
        custom_dev = MockAudioDevice(devices=[unsupported], default_device_id=None)
        p = AudioPipeline(device=custom_dev)
        with self.assertRaises(AudioError) as ctx:
            p.select_device("unsupported-usb-card")
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_DEVICE")

    def test_pipeline_buffer_drain_during_overflow_prevents_starvation(self) -> None:
        """Verify that when buffer drops a chunk, consumer still drains and VAD receives chunks."""
        # Pipeline buffer capacity = 10
        self.pipeline.start()
        # Fill buffer to capacity
        for i in range(10):
            self.pipeline.buffer.push(create_deterministic_chunk(sequence_id=100 + i, timestamp=10.0 + i * 0.02))
        self.assertEqual(self.pipeline.buffer.current_size, 10)

        # process_step reads from device, pushes (which drops due to capacity 10), but MUST pop oldest
        initial_consumed = self.pipeline.buffer_metrics.total_consumed
        res = self.pipeline.process_step()
        self.assertIsNotNone(res)
        self.assertEqual(self.pipeline.buffer_metrics.total_consumed, initial_consumed + 1)
        self.assertEqual(self.pipeline.buffer.current_size, 9)

    def test_capture_burst_drives_real_overflow(self) -> None:
        """Verify capture_burst pushes real device chunks into buffer without consuming."""
        self.pipeline.start()
        # Burst 15 chunks into buffer with capacity 10
        push_results = self.pipeline.capture_burst(15)
        self.assertEqual(len(push_results), 15)

        accepted = [r for r in push_results if r.status == BufferPushStatus.ACCEPTED]
        dropped = [r for r in push_results if r.status == BufferPushStatus.DROPPED]
        self.assertEqual(len(accepted), 10)
        self.assertEqual(len(dropped), 5)
        self.assertEqual(self.pipeline.buffer.current_size, 10)

    def test_stop_clears_non_empty_buffer(self) -> None:
        """Verify stop() purges any unconsumed chunks from buffer."""
        self.pipeline.start()
        self.pipeline.capture_burst(5)
        self.assertEqual(self.pipeline.buffer.current_size, 5)

        self.pipeline.stop()
        self.assertEqual(self.pipeline.buffer.current_size, 0)
        self.assertTrue(self.pipeline.buffer.is_empty)

    def test_pipeline_vad_event_sequence_for_known_input(self) -> None:
        """Verify exact expected VAD event sequence for known synthetic tone stream."""
        self.pipeline.start()
        events = []
        for _ in range(5):
            res = self.pipeline.process_step()
            self.assertIsNotNone(res, "process_step returned None unexpectedly")
            events.append(res[1].event_type)

        self.assertEqual(len(events), 5)
        expected = [
            VADEventType.SILENCE,
            VADEventType.SPEECH_START,
            VADEventType.SPEECH_ONGOING,
            VADEventType.SPEECH_ONGOING,
            VADEventType.SPEECH_ONGOING,
        ]
        self.assertEqual(events, expected)

    def test_pipeline_restart_clears_metrics_and_events(self) -> None:
        """Verify restart from STOPPED resets sequence to 0, zeroes steps, buffer metrics, and VAD."""
        self.pipeline.start()
        for _ in range(5):
            self.pipeline.process_step()
        self.assertEqual(len(self.pipeline._processed_events), 5)
        self.assertEqual(self.pipeline.get_status()["total_processed_steps"], 5)
        self.pipeline.stop()

        # Restart session
        self.pipeline.start()
        self.assertEqual(self.pipeline.get_status()["total_processed_steps"], 0)
        self.assertEqual(self.pipeline.buffer_metrics.total_received, 0)
        self.assertEqual(self.pipeline.buffer_metrics.total_consumed, 0)
        self.assertEqual(self.pipeline.buffer_metrics.total_dropped, 0)
        self.assertFalse(self.pipeline.vad.is_speech_active)

        first_step = self.pipeline.process_step()
        self.assertIsNotNone(first_step)
        chunk, _ = first_step
        self.assertEqual(chunk.sequence_id, 0)
        self.assertEqual(self.pipeline.get_status()["total_processed_steps"], 1)

    def test_pipeline_capture_burst_exact_overflow_counts(self) -> None:
        """Verify overflow through capture_burst gives exact accepted and dropped counts."""
        self.pipeline.start()
        burst = self.pipeline.capture_burst(15)
        self.assertEqual(len(burst), 15)
        accepted = sum(1 for r in burst if r.status == BufferPushStatus.ACCEPTED)
        dropped = sum(1 for r in burst if r.status == BufferPushStatus.DROPPED)
        self.assertEqual(accepted, 10)
        self.assertEqual(dropped, 5)
        self.assertEqual(self.pipeline.buffer_metrics.total_dropped, 5)

    def test_pipeline_buffer_late_chunk_rejected_does_not_increment_dropped(self) -> None:
        """Verify late chunk pushed to pipeline.buffer is REJECTED_LATE and does NOT change total_dropped."""
        self.pipeline.start()
        # Push chunk 5 to advance expected sequence to 6
        c5 = create_deterministic_chunk(sequence_id=5, timestamp=0.1)
        self.pipeline.buffer.push(c5)
        initial_dropped = self.pipeline.buffer_metrics.total_dropped

        # Push an older unseen sequence ID (sequence 2 < expected 6, not duplicate)
        late_chunk = create_deterministic_chunk(sequence_id=2, timestamp=0.04)
        res = self.pipeline.buffer.push(late_chunk)
        self.assertEqual(res.status, BufferPushStatus.REJECTED_LATE)
        self.assertEqual(self.pipeline.buffer_metrics.total_dropped, initial_dropped)
        self.assertEqual(self.pipeline.buffer_metrics.late_chunks_detected, 1)

    def test_pipeline_buffer_duplicate_chunk_rejected_does_not_increment_dropped(self) -> None:
        """Verify duplicate chunk pushed to pipeline.buffer is REJECTED_DUPLICATE and does NOT change total_dropped."""
        self.pipeline.start()
        c = create_deterministic_chunk(sequence_id=50, timestamp=1.0)
        res1 = self.pipeline.buffer.push(c)
        self.assertEqual(res1.status, BufferPushStatus.ACCEPTED)
        initial_dropped = self.pipeline.buffer_metrics.total_dropped

        res2 = self.pipeline.buffer.push(c)
        self.assertEqual(res2.status, BufferPushStatus.REJECTED_DUPLICATE)
        self.assertEqual(self.pipeline.buffer_metrics.total_dropped, initial_dropped)
        self.assertEqual(self.pipeline.buffer_metrics.duplicate_chunks_detected, 1)

    def test_pipeline_buffer_sequence_gap_metrics(self) -> None:
        """Verify sequence gap increments sequence_gap_events by 1 and missing_chunks_total by exact count."""
        self.pipeline.start()
        self.pipeline.buffer.clear()
        self.pipeline.buffer.reset_metrics()

        self.pipeline.buffer.push(create_deterministic_chunk(sequence_id=10, timestamp=0.2))
        self.pipeline.buffer.push(create_deterministic_chunk(sequence_id=25, timestamp=0.5))

        m = self.pipeline.buffer_metrics
        self.assertEqual(m.sequence_gap_events, 1)
        self.assertEqual(m.missing_chunks_total, 14)
        self.assertEqual(m.sequence_gaps_detected, 1)

    def test_pipeline_denied_permission_blocks_start(self) -> None:
        """Verify denied permission blocks start (PERMISSION_DENIED, state ERROR, device closed)."""
        denied_dev = MockAudioDevice(
            audio_format=self.fmt,
            initial_permission=AudioPermissionState.DENIED,
        )
        p = AudioPipeline(device=denied_dev)
        with self.assertRaises(AudioError) as ctx:
            p.start()
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")
        self.assertEqual(p.state, AudioLifecycleState.ERROR)
        self.assertFalse(denied_dev.is_open)

    def test_pipeline_device_closed_after_stop(self) -> None:
        """Verify active audio device is safely closed after stop()."""
        self.pipeline.start()
        self.assertTrue(self.pipeline.device.is_open)
        self.pipeline.stop()
        self.assertFalse(self.pipeline.device.is_open)

    def test_restart_resets_vad_state(self) -> None:
        """Verify restarting the pipeline from STOPPED clears active speech state in VAD."""
        self.pipeline.start()
        # Feed speech chunks to trigger active speech
        speech_chunks = generate_speech_fixture(num_chunks=5)
        for sc in speech_chunks:
            self.pipeline.vad.process_chunk(sc)
        self.assertTrue(self.pipeline.vad.is_speech_active)

        self.pipeline.stop()
        self.pipeline.start()
        self.assertFalse(self.pipeline.vad.is_speech_active)


if __name__ == "__main__":
    unittest.main()

