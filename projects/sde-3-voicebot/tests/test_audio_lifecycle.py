"""
Unit tests for Audio Lifecycle Controller (Week 2, D10-D11).
"""

import unittest

from src.audio.device import (
    AudioDeviceInfo,
    AudioPermissionState,
    MockAudioDevice,
)
from src.audio.lifecycle import AudioLifecycleController, AudioLifecycleState
from src.schemas.audio import AudioChunk, AudioError, AudioFormat


class TestLifecycleController(unittest.TestCase):
    """Test suite covering lifecycle states, legal/illegal transitions, and errors."""

    def setUp(self) -> None:
        self.fmt = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.device = MockAudioDevice(
            audio_format=self.fmt,
            initial_permission=AudioPermissionState.GRANTED,
        )
        self.controller = AudioLifecycleController(device=self.device)

    def test_initial_state_idle(self) -> None:
        """Verify initial state is IDLE."""
        self.assertEqual(self.controller.state, AudioLifecycleState.IDLE)
        self.assertFalse(self.controller.is_running)
        self.assertFalse(self.controller.is_paused)

    def test_normal_start_and_run(self) -> None:
        """Verify normal transition: IDLE -> STARTING -> RUNNING."""
        self.controller.start()
        self.assertEqual(self.controller.state, AudioLifecycleState.RUNNING)
        self.assertTrue(self.controller.is_running)
        self.assertTrue(self.device.is_open)
        self.assertEqual(
            self.controller.state_history,
            [AudioLifecycleState.IDLE, AudioLifecycleState.STARTING, AudioLifecycleState.RUNNING],
        )

    def test_pause_and_resume(self) -> None:
        """Verify transition: RUNNING -> PAUSED -> RUNNING."""
        self.controller.start()
        self.controller.pause()
        self.assertEqual(self.controller.state, AudioLifecycleState.PAUSED)
        self.assertTrue(self.controller.is_paused)
        self.assertFalse(self.controller.is_running)

        # Chunks cannot be read while paused (returns None)
        chunk = self.controller.read_chunk()
        self.assertIsNone(chunk)

        # Resume
        self.controller.resume()
        self.assertEqual(self.controller.state, AudioLifecycleState.RUNNING)
        self.assertTrue(self.controller.is_running)

    def test_stop_from_running(self) -> None:
        """Verify transition: RUNNING -> STOPPING -> STOPPED."""
        self.controller.start()
        self.controller.stop()
        self.assertEqual(self.controller.state, AudioLifecycleState.STOPPED)
        self.assertFalse(self.device.is_open)
        self.assertIn(AudioLifecycleState.STOPPING, self.controller.state_history)
        self.assertIn(AudioLifecycleState.STOPPED, self.controller.state_history)

    def test_stop_from_paused(self) -> None:
        """Verify transition: PAUSED -> STOPPING -> STOPPED."""
        self.controller.start()
        self.controller.pause()
        self.controller.stop()
        self.assertEqual(self.controller.state, AudioLifecycleState.STOPPED)
        self.assertFalse(self.device.is_open)

    def test_stop_is_idempotent(self) -> None:
        """Verify calling stop() multiple times is safe and maintains STOPPED state."""
        self.controller.start()
        self.controller.stop()
        self.assertEqual(self.controller.state, AudioLifecycleState.STOPPED)
        # Second stop
        self.controller.stop()
        self.assertEqual(self.controller.state, AudioLifecycleState.STOPPED)

    def test_illegal_pause_before_start(self) -> None:
        """Verify pausing from IDLE raises AudioError."""
        with self.assertRaises(AudioError) as ctx:
            self.controller.pause()
        self.assertEqual(ctx.exception.code, "ILLEGAL_LIFECYCLE_TRANSITION")

    def test_illegal_resume_when_not_paused(self) -> None:
        """Verify resuming from RUNNING or IDLE raises AudioError."""
        with self.assertRaises(AudioError) as ctx:
            self.controller.resume()
        self.assertEqual(ctx.exception.code, "ILLEGAL_LIFECYCLE_TRANSITION")

        self.controller.start()
        with self.assertRaises(AudioError) as ctx2:
            self.controller.resume()
        self.assertEqual(ctx2.exception.code, "ILLEGAL_LIFECYCLE_TRANSITION")

    def test_illegal_start_while_already_running(self) -> None:
        """Verify starting while already running raises AudioError."""
        self.controller.start()
        with self.assertRaises(AudioError) as ctx:
            self.controller.start()
        self.assertEqual(ctx.exception.code, "ILLEGAL_LIFECYCLE_TRANSITION")

    def test_illegal_resume_after_stop(self) -> None:
        """Verify resuming after stop raises AudioError."""
        self.controller.start()
        self.controller.stop()
        with self.assertRaises(AudioError) as ctx:
            self.controller.resume()
        self.assertEqual(ctx.exception.code, "ILLEGAL_LIFECYCLE_TRANSITION")

    def test_start_fails_when_permission_not_granted(self) -> None:
        """Verify starting transitions to ERROR if permission is not GRANTED."""
        denied_device = MockAudioDevice(
            audio_format=self.fmt,
            initial_permission=AudioPermissionState.DENIED,
        )
        ctrl = AudioLifecycleController(device=denied_device)
        with self.assertRaises(AudioError) as ctx:
            ctrl.start()
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")
        self.assertEqual(ctrl.state, AudioLifecycleState.ERROR)
        self.assertIsNotNone(ctrl.last_error)

    def test_mid_stream_device_disconnect_transitions_to_error(self) -> None:
        """Verify hardware error mid-stream transitions controller to ERROR."""
        flaky_device = MockAudioDevice(
            audio_format=self.fmt,
            initial_permission=AudioPermissionState.GRANTED,
            simulate_disconnect_after_chunks=1,
        )
        ctrl = AudioLifecycleController(device=flaky_device)
        ctrl.start()
        c1 = ctrl.read_chunk()
        self.assertIsNotNone(c1)

        # 2nd chunk encounters disconnect
        with self.assertRaises(AudioError) as ctx:
            ctrl.read_chunk()
        self.assertEqual(ctrl.state, AudioLifecycleState.ERROR)
        self.assertEqual(ctx.exception.code, "DEVICE_UNAVAILABLE")

    def test_monotonic_sequence_tracking(self) -> None:
        """Verify sequence IDs monotonically advance."""
        self.controller.start()
        c0 = self.controller.read_chunk()
        c1 = self.controller.read_chunk()
        c2 = self.controller.read_chunk()
        self.assertIsNotNone(c0)
        self.assertIsNotNone(c1)
        self.assertIsNotNone(c2)
        self.assertEqual(c0.sequence_id, 0)
        self.assertEqual(c1.sequence_id, 1)
        self.assertEqual(c2.sequence_id, 2)
        self.assertLess(c0.timestamp, c1.timestamp)
        self.assertLess(c1.timestamp, c2.timestamp)
        self.assertEqual(self.controller.chunks_captured, 3)

    def test_restart_from_stopped_resets_sequence(self) -> None:
        """Verify restart after stop resets sequence tracking and reads chunk 0 cleanly."""
        self.controller.start()
        for i in range(3):
            c = self.controller.read_chunk()
            self.assertIsNotNone(c)
            self.assertEqual(c.sequence_id, i)
        self.controller.stop()
        self.assertEqual(self.controller.state, AudioLifecycleState.STOPPED)

        # Restart session
        self.controller.start()
        self.assertEqual(self.controller.state, AudioLifecycleState.RUNNING)
        c0 = self.controller.read_chunk()
        self.assertIsNotNone(c0)
        self.assertEqual(c0.sequence_id, 0)
        self.assertEqual(self.controller.chunks_captured, 1)

    def test_restart_disabled_raises_illegal_transition(self) -> None:
        """Verify restart raises ILLEGAL_LIFECYCLE_TRANSITION when allow_restart_from_stopped is False."""
        ctrl = AudioLifecycleController(
            device=self.device,
            allow_restart_from_stopped=False,
        )
        ctrl.start()
        ctrl.stop()
        with self.assertRaises(AudioError) as ctx:
            ctrl.start()
        self.assertEqual(ctx.exception.code, "ILLEGAL_LIFECYCLE_TRANSITION")

    def test_out_of_order_chunk_transitions_to_error(self) -> None:
        """Verify out of order chunk causes controller to enter ERROR state and close device."""
        class GlitchDevice(MockAudioDevice):
            def read_chunk(self):
                # Return sequence 5 then sequence 2
                if not hasattr(self, "_step"):
                    self._step = 0
                self._step += 1
                if self._step == 1:
                    return AudioChunk(
                        sequence_id=5,
                        timestamp=0.1,
                        data=b"\x00" * 640,
                        format=self._audio_format,
                    )
                return AudioChunk(
                    sequence_id=2,
                    timestamp=0.04,
                    data=b"\x00" * 640,
                    format=self._audio_format,
                )

        glitch_dev = GlitchDevice(audio_format=self.fmt, initial_permission=AudioPermissionState.GRANTED)
        ctrl = AudioLifecycleController(device=glitch_dev)
        ctrl.start()
        c1 = ctrl.read_chunk()
        self.assertEqual(c1.sequence_id, 5)

        with self.assertRaises(AudioError) as ctx:
            ctrl.read_chunk()
        self.assertEqual(ctx.exception.code, "OUT_OF_ORDER_CHUNK")
        self.assertEqual(ctrl.state, AudioLifecycleState.ERROR)
        self.assertIsNotNone(ctrl.last_error)
        self.assertFalse(glitch_dev.is_open)

    def test_end_of_stream_flag(self) -> None:
        """Verify is_end_of_stream flag is False during capture and True after stream ends."""
        finite_device = MockAudioDevice(
            audio_format=self.fmt,
            initial_permission=AudioPermissionState.GRANTED,
            total_duration_sec=0.04,  # Exactly 2 chunks of 20ms
            chunk_duration_ms=20.0,
        )
        ctrl = AudioLifecycleController(device=finite_device)
        ctrl.start()
        self.assertFalse(ctrl.is_end_of_stream)

        c1 = ctrl.read_chunk()
        self.assertIsNotNone(c1)
        self.assertFalse(ctrl.is_end_of_stream)

        c2 = ctrl.read_chunk()
        self.assertIsNotNone(c2)

        c3 = ctrl.read_chunk()
        self.assertIsNone(c3)
        self.assertTrue(ctrl.is_end_of_stream)


if __name__ == "__main__":
    unittest.main()

