"""
Unit tests for Audio Device Adapter and Permission Handling (Week 2, D8-D9).
"""

import unittest

from src.audio.device import (
    AudioDeviceInfo,
    AudioDeviceInterface,
    AudioPermissionState,
    MockAudioDevice,
)
from src.schemas.audio import AudioChunk, AudioError, AudioFormat


class TestDeviceAdapter(unittest.TestCase):
    """Test suite covering MockAudioDevice, selection, permissions, and error safety."""

    def setUp(self) -> None:
        self.fmt = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.device = MockAudioDevice(
            audio_format=self.fmt,
            initial_permission=AudioPermissionState.UNKNOWN,
        )

    def test_device_listing(self) -> None:
        """Verify device listing returns available devices."""
        devices = self.device.list_devices()
        self.assertIsInstance(devices, list)
        self.assertGreaterEqual(len(devices), 2)
        device_ids = [d.device_id for d in devices]
        self.assertIn("mock-mic-default", device_ids)

    def test_default_device_selected(self) -> None:
        """Verify initial default device is selected."""
        selected = self.device.selected_device
        self.assertIsNotNone(selected)
        self.assertEqual(selected.device_id, "mock-mic-default")

    def test_device_selection_success(self) -> None:
        """Verify selecting a valid alternative device."""
        info = self.device.select_device("mock-mic-headset")
        self.assertEqual(info.device_id, "mock-mic-headset")
        self.assertEqual(self.device.selected_device.device_id, "mock-mic-headset")

    def test_device_selection_invalid(self) -> None:
        """Verify selecting an unknown device raises AudioError."""
        with self.assertRaises(AudioError) as ctx:
            self.device.select_device("non-existent-device-id")
        self.assertEqual(ctx.exception.code, "INVALID_DEVICE_SELECTION")

    def test_permission_lifecycle_granted(self) -> None:
        """Verify permission request transitions from UNKNOWN to GRANTED."""
        self.assertEqual(self.device.get_permission_status(), AudioPermissionState.UNKNOWN)
        new_perm = self.device.request_permission()
        self.assertEqual(new_perm, AudioPermissionState.GRANTED)
        self.assertEqual(self.device.get_permission_status(), AudioPermissionState.GRANTED)

    def test_permission_requested_state_observable(self) -> None:
        """Verify REQUESTED state is observable via pending callback and two-step resolution."""
        observed = []
        dev = MockAudioDevice(
            audio_format=self.fmt,
            initial_permission=AudioPermissionState.UNKNOWN,
            permission_response=AudioPermissionState.GRANTED,
        )

        # 1. Via pending callback
        dev.request_permission(
            auto_resolve=True,
            pending_callback=lambda s: observed.append(s),
        )
        self.assertEqual(observed, [AudioPermissionState.REQUESTED])
        self.assertEqual(dev.get_permission_status(), AudioPermissionState.GRANTED)

        # 2. Via two-step manual resolution
        dev2 = MockAudioDevice(
            audio_format=self.fmt,
            initial_permission=AudioPermissionState.UNKNOWN,
            permission_response=AudioPermissionState.GRANTED,
        )
        held_state = dev2.request_permission(auto_resolve=False)
        self.assertEqual(held_state, AudioPermissionState.REQUESTED)
        self.assertEqual(dev2.get_permission_status(), AudioPermissionState.REQUESTED)

        resolved_state = dev2.resolve_permission()
        self.assertEqual(resolved_state, AudioPermissionState.GRANTED)
        self.assertEqual(dev2.get_permission_status(), AudioPermissionState.GRANTED)

    def test_permission_denied_flow(self) -> None:
        """Verify device behaves correctly when permission is DENIED."""
        denied_device = MockAudioDevice(
            audio_format=self.fmt,
            initial_permission=AudioPermissionState.DENIED,
            permission_response=AudioPermissionState.DENIED,
        )
        self.assertEqual(denied_device.get_permission_status(), AudioPermissionState.DENIED)
        with self.assertRaises(AudioError) as ctx:
            denied_device.open()
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")

    def test_read_chunk_enforces_continuous_permission(self) -> None:
        """Verify read_chunk raises PERMISSION_DENIED and closes device if permission is revoked mid-stream."""
        dev = MockAudioDevice(audio_format=self.fmt, initial_permission=AudioPermissionState.GRANTED)
        dev.open()
        c = dev.read_chunk()
        self.assertIsNotNone(c)

        # Revoke permission mid-session
        dev.set_permission_state(AudioPermissionState.DENIED)
        with self.assertRaises(AudioError) as ctx:
            dev.read_chunk()
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")
        self.assertFalse(dev.is_open)

    def test_unsupported_device_rejection(self) -> None:
        """Verify selecting an unsupported device fails with proper error."""
        unsupported = AudioDeviceInfo(
            device_id="unsupported-hw",
            name="Unsupported Ancient Hardware",
            channels=1,
            sample_rate=16000,
            is_mock=True,
            supported=False,
        )
        dev = MockAudioDevice(
            devices=[unsupported],
            default_device_id=None,
            initial_permission=AudioPermissionState.GRANTED,
        )
        with self.assertRaises(AudioError) as ctx:
            dev.select_device("unsupported-hw")
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_DEVICE")

    def test_non_mock_device_supported_accepted(self) -> None:
        """Verify non-mock device is accepted if supported=True."""
        real_hw = AudioDeviceInfo(
            device_id="real-usb-mic",
            name="Physical Studio Condenser",
            channels=1,
            sample_rate=16000,
            is_mock=False,
            supported=True,
        )
        dev = MockAudioDevice(devices=[real_hw], default_device_id="real-usb-mic")
        selected = dev.selected_device
        self.assertEqual(selected.device_id, "real-usb-mic")
        self.assertFalse(selected.is_mock)
        self.assertTrue(selected.supported)

    def test_format_compatibility_validation_on_open(self) -> None:
        """Verify open() validates format compatibility (channels and sample rate)."""
        stereo_dev = AudioDeviceInfo(
            device_id="stereo-mic",
            name="Stereo Mic",
            channels=2,
            sample_rate=48000,
            supported=True,
        )
        # Mismatched channels
        mismatch_channels = MockAudioDevice(
            devices=[stereo_dev],
            default_device_id="stereo-mic",
            audio_format=AudioFormat(sample_rate=48000, channels=1),
            initial_permission=AudioPermissionState.GRANTED,
        )
        with self.assertRaises(AudioError) as ctx_ch:
            mismatch_channels.open()
        self.assertEqual(ctx_ch.exception.code, "INVALID_CHANNELS")

        # Mismatched sample rate
        mismatch_rate = MockAudioDevice(
            devices=[stereo_dev],
            default_device_id="stereo-mic",
            audio_format=AudioFormat(sample_rate=16000, channels=2),
            initial_permission=AudioPermissionState.GRANTED,
        )
        with self.assertRaises(AudioError) as ctx_sr:
            mismatch_rate.open()
        self.assertEqual(ctx_sr.exception.code, "INVALID_SAMPLE_RATE")

        # Matching format opens successfully
        matching = MockAudioDevice(
            devices=[stereo_dev],
            default_device_id="stereo-mic",
            audio_format=AudioFormat(sample_rate=48000, channels=2),
            initial_permission=AudioPermissionState.GRANTED,
        )
        matching.open()
        self.assertTrue(matching.is_open)
        matching.close()

    def test_refuse_switch_device_while_open(self) -> None:
        """Verify select_device refuses to switch while the device is actively open."""
        self.device.request_permission()
        self.device.open()
        self.assertTrue(self.device.is_open)

        with self.assertRaises(AudioError) as ctx:
            self.device.select_device("mock-mic-headset")
        self.assertEqual(ctx.exception.code, "DEVICE_BUSY")
        self.device.close()

    def test_open_and_close_lifecycle(self) -> None:
        """Verify device open and idempotent close."""
        self.device.request_permission()
        self.assertFalse(self.device.is_open)
        self.device.open()
        self.assertTrue(self.device.is_open)

        # Idempotent close
        self.device.close()
        self.assertFalse(self.device.is_open)
        self.device.close()  # Repeated close safe
        self.assertFalse(self.device.is_open)

    def test_read_chunk_requires_open(self) -> None:
        """Verify read_chunk fails if device is not opened."""
        with self.assertRaises(AudioError) as ctx:
            self.device.read_chunk()
        self.assertEqual(ctx.exception.code, "DEVICE_NOT_OPEN")

    def test_mock_device_determinism(self) -> None:
        """Verify two mock devices produce identical audio chunks."""
        dev1 = MockAudioDevice(audio_format=self.fmt, initial_permission=AudioPermissionState.GRANTED)
        dev2 = MockAudioDevice(audio_format=self.fmt, initial_permission=AudioPermissionState.GRANTED)
        dev1.open()
        dev2.open()

        for _ in range(5):
            c1 = dev1.read_chunk()
            c2 = dev2.read_chunk()
            self.assertIsNotNone(c1)
            self.assertIsNotNone(c2)
            self.assertEqual(c1.sequence_id, c2.sequence_id)
            self.assertEqual(c1.timestamp, c2.timestamp)
            self.assertEqual(c1.data, c2.data)

        dev1.close()
        dev2.close()

    def test_simulated_init_failure(self) -> None:
        """Verify device handles simulated initialization failure safely."""
        failing_device = MockAudioDevice(
            audio_format=self.fmt,
            initial_permission=AudioPermissionState.GRANTED,
            simulate_init_failure=True,
        )
        with self.assertRaises(AudioError) as ctx:
            failing_device.open()
        self.assertEqual(ctx.exception.code, "DEVICE_INIT_FAILURE")
        self.assertFalse(failing_device.is_open)

    def test_simulated_mid_stream_disconnect(self) -> None:
        """Verify device handles mid-stream disconnect safely."""
        flaky_device = MockAudioDevice(
            audio_format=self.fmt,
            initial_permission=AudioPermissionState.GRANTED,
            simulate_disconnect_after_chunks=2,
        )
        flaky_device.open()
        c1 = flaky_device.read_chunk()
        c2 = flaky_device.read_chunk()
        self.assertIsNotNone(c1)
        self.assertIsNotNone(c2)

        # 3rd read triggers disconnect error
        with self.assertRaises(AudioError) as ctx:
            flaky_device.read_chunk()
        self.assertEqual(ctx.exception.code, "DEVICE_UNAVAILABLE")
        self.assertFalse(flaky_device.is_open)

    def test_default_device_unsupported_not_selected(self) -> None:
        """Verify default_device_id pointing to unsupported device is not pre-selected."""
        unsupported = AudioDeviceInfo(
            device_id="unsupported-hw",
            name="Unsupported Hardware",
            channels=1,
            sample_rate=16000,
            supported=False,
        )
        dev = MockAudioDevice(devices=[unsupported], default_device_id="unsupported-hw")
        self.assertIsNone(dev.selected_device)

    def test_open_unsupported_device_fails_and_stays_closed(self) -> None:
        """Verify open() on an unsupported device raises UNSUPPORTED_DEVICE and is_open stays False."""
        unsupported = AudioDeviceInfo(
            device_id="unsupported-hw",
            name="Unsupported Hardware",
            channels=1,
            sample_rate=16000,
            supported=False,
        )
        dev = MockAudioDevice(
            devices=[unsupported],
            default_device_id=None,
            initial_permission=AudioPermissionState.GRANTED,
        )
        # Manually assign unsupported device to bypass selection
        dev._selected_device = unsupported
        with self.assertRaises(AudioError) as ctx:
            dev.open()
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_DEVICE")
        self.assertFalse(dev.is_open)


if __name__ == "__main__":
    unittest.main()
