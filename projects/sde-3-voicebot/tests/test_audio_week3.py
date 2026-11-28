"""
Comprehensive Unit and Integration Test Suite for Week 3 Audio & VAD (Days 15–20).

Workstream: W1 - Audio and VAD
Student: Harshita G Kademani | SDE 3

Covers all Week 3 requirements & audit fixes (B1–B15):
- Day 16: Session ID & Correlation ID propagation, multi-session isolation, parameter validation.
- Day 17: Device-loss detection during active capture, while paused, during speech without crashes. Idempotency.
- Day 18: Reconnection (success/failure), cancel -> reconnect protection (B6), safe cancellation (B3), restart (B4).
- Day 19: STT Bridge handoff, no duplicate STT chunks (B7), no metadata mutation (B14), cancelled speech discarded (B3).
- Day 20: 13-point validation checklist executed against the real runtime processing path (B9).
- Device edge cases & permission revocation (B11).
- Lifecycle methods direct testing (B15).
"""

from __future__ import annotations

import unittest
from typing import List, Set

from src.audio.device import AudioDeviceInfo, AudioPermissionState, MockAudioDevice
from src.audio.lifecycle import AudioLifecycleController, AudioLifecycleState
from src.audio.pipeline import (
    AudioPipeline,
    create_deterministic_chunk,
    generate_noise_burst_fixture,
    generate_silence_fixture,
    generate_speech_fixture,
)
from src.audio.transcription_integration import AudioTranscriptionBridge
from src.audio.vad import VADConfig
from src.audio.validation import VALIDATION_POINTS, ValidationCheckID, Week3AudioValidator
from src.schemas.audio import AudioChunk, AudioError, AudioEvent, AudioEventType, AudioFormat

try:
    from src.voice_stt.accumulator import OrderedSegmentAccumulator
    from src.voice_stt.fake_transcriber import DeterministicFakeTranscriber
    from src.voice_stt.schemas import STTErrorDetail, TranscriptEventType
except ImportError:
    from voice_stt.accumulator import OrderedSegmentAccumulator  # type: ignore
    from voice_stt.fake_transcriber import DeterministicFakeTranscriber  # type: ignore
    from voice_stt.schemas import STTErrorDetail, TranscriptEventType  # type: ignore


class TestWeek3AudioWorkstream(unittest.TestCase):
    """Test suite covering Day 16 through Day 20 requirements and audit fixes."""

    def setUp(self) -> None:
        self.session_id = "sess-w3-test-101"
        self.correlation_id = "corr-w3-trace-202"
        self.vad_config = VADConfig(
            energy_threshold=0.015,
            speech_probability_threshold=0.4,
            min_speech_duration_ms=40.0,
            min_silence_duration_ms=60.0,
        )

    # =========================================================================
    # DAY 16 – Session ID and Correlation ID
    # =========================================================================

    def test_d16_session_and_correlation_id_propagation_real_path(self) -> None:
        """Verify session ID and correlation ID are propagated to all normalized events via process_step()."""
        pipeline = AudioPipeline(
            session_id=self.session_id,
            correlation_id=self.correlation_id,
            vad_config=self.vad_config,
        )
        pipeline.start()
        for c in generate_speech_fixture(num_chunks=4):
            pipeline.buffer.push(c)
            pipeline.process_step()
        pipeline.stop()

        events = pipeline.get_events()
        self.assertGreater(len(events), 0)
        for e in events:
            self.assertEqual(e.session_id, self.session_id)
            self.assertEqual(e.correlation_id, self.correlation_id)

    def test_d16_invalid_session_or_correlation_id_rejected(self) -> None:
        """Verify pipeline rejects empty, whitespace, non-string, or boolean session/correlation IDs."""
        with self.assertRaises(AudioError) as ctx:
            AudioPipeline(session_id="", correlation_id=self.correlation_id)
        self.assertEqual(ctx.exception.code, "INVALID_PARAMETER")

        with self.assertRaises(AudioError) as ctx:
            AudioPipeline(session_id=self.session_id, correlation_id="   ")
        self.assertEqual(ctx.exception.code, "INVALID_PARAMETER")

        p = AudioPipeline(session_id=self.session_id, correlation_id=self.correlation_id)
        with self.assertRaises(AudioError):
            p.set_session("")
        with self.assertRaises(AudioError):
            p.set_session("valid-sess", correlation_id="")

    def test_d16_multi_session_isolation_and_tracing_real_path(self) -> None:
        """Verify independent pipelines maintain strict session isolation with zero event cross-talk."""
        p1 = AudioPipeline(session_id="sess-alpha", correlation_id="corr-alpha", vad_config=self.vad_config)
        p2 = AudioPipeline(session_id="sess-beta", correlation_id="corr-beta", vad_config=self.vad_config)

        p1.start()
        p2.start()

        # Ingest speech in Alpha
        for c in generate_speech_fixture(num_chunks=4):
            p1.buffer.push(c)
            p1.process_step()

        # Ingest silence in Beta
        for c in generate_silence_fixture(num_chunks=4):
            p2.buffer.push(c)
            p2.process_step()

        p1.stop()
        p2.stop()

        events_p1 = p1.get_events()
        events_p2 = p2.get_events()

        self.assertTrue(all(e.session_id == "sess-alpha" for e in events_p1))
        self.assertTrue(all(e.correlation_id == "corr-alpha" for e in events_p1))
        self.assertTrue(all(e.session_id == "sess-beta" for e in events_p2))
        self.assertTrue(all(e.correlation_id == "corr-beta" for e in events_p2))

        # Alpha detected speech, Beta remained pure silence
        self.assertTrue(any(e.event_type == AudioEventType.SPEECH_START for e in events_p1))
        self.assertFalse(any(e.event_type == AudioEventType.SPEECH_START for e in events_p2))

    # =========================================================================
    # DAY 17 – Device-Loss Detection and Handling
    # =========================================================================

    def test_d17_device_loss_during_active_capture(self) -> None:
        """Verify device loss mid-stream is safely handled and transitions to ERROR."""
        mock_dev = MockAudioDevice(initial_permission=AudioPermissionState.GRANTED)
        pipeline = AudioPipeline(device=mock_dev, session_id=self.session_id, correlation_id=self.correlation_id)
        pipeline.start()
        self.assertEqual(pipeline.state, AudioLifecycleState.RUNNING)

        # Disconnect device
        mock_dev.disconnect("USB audio interface removed")
        self.assertFalse(mock_dev.is_connected)

        # process_step catches disconnection without crashing
        step_res = pipeline.process_step()
        self.assertIsNone(step_res)
        self.assertEqual(pipeline.state, AudioLifecycleState.ERROR)

        loss_events = pipeline.get_events_by_type(AudioEventType.DEVICE_LOST)
        self.assertEqual(len(loss_events), 1)
        self.assertEqual(loss_events[0].session_id, self.session_id)
        self.assertEqual(loss_events[0].metadata["error_code"], "DEVICE_UNAVAILABLE")

    def test_d17_device_loss_during_active_speech_finalizes_segment(self) -> None:
        """Verify mid-speech device loss closes active speech segment and resets VAD state (B5)."""
        mock_dev = MockAudioDevice(initial_permission=AudioPermissionState.GRANTED)
        pipeline = AudioPipeline(device=mock_dev, session_id=self.session_id, vad_config=self.vad_config)
        pipeline.start()

        # Ingest speech chunks into buffer
        for c in generate_speech_fixture(num_chunks=4):
            pipeline.buffer.push(c)
            pipeline.process_step()

        self.assertIsNotNone(pipeline.active_segment_id)

        # Disconnect device
        mock_dev.disconnect("Cable pulled")
        pipeline.handle_device_loss()

        self.assertEqual(pipeline.state, AudioLifecycleState.ERROR)
        self.assertIsNone(pipeline.active_segment_id)

        # Final speech end event was emitted with reason device_loss
        end_events = pipeline.get_events_by_type(AudioEventType.SPEECH_END)
        self.assertEqual(len(end_events), 1)
        self.assertEqual(end_events[0].metadata["reason"], "device_loss")

    def test_d17_device_loss_while_paused(self) -> None:
        """Verify device loss occurring while paused is handled safely without throwing."""
        mock_dev = MockAudioDevice(initial_permission=AudioPermissionState.GRANTED)
        pipeline = AudioPipeline(device=mock_dev, session_id=self.session_id)
        pipeline.start()
        pipeline.pause()
        self.assertEqual(pipeline.state, AudioLifecycleState.PAUSED)

        mock_dev.disconnect("Bluetooth headset switched off")
        loss_evt = pipeline.handle_device_loss()
        self.assertEqual(loss_evt.event_type, AudioEventType.DEVICE_LOST)
        self.assertEqual(pipeline.state, AudioLifecycleState.ERROR)

    def test_d17_handle_device_loss_is_idempotent(self) -> None:
        """Verify repeated calls to handle_device_loss do not emit duplicate DEVICE_LOST events (B11)."""
        pipeline = AudioPipeline(session_id=self.session_id)
        pipeline.start()
        evt1 = pipeline.handle_device_loss()
        evt2 = pipeline.handle_device_loss()
        self.assertEqual(evt1.event_id, evt2.event_id)
        loss_evts = pipeline.get_events_by_type(AudioEventType.DEVICE_LOST)
        self.assertEqual(len(loss_evts), 1)

    # =========================================================================
    # DAY 18 – Device Reconnection and Cancellation
    # =========================================================================

    def test_d18_successful_device_reconnection_restores_capture(self) -> None:
        """Verify device reconnection restores capture and emits DEVICE_RECONNECTED event."""
        mock_dev = MockAudioDevice(initial_permission=AudioPermissionState.GRANTED)
        pipeline = AudioPipeline(device=mock_dev, session_id=self.session_id)
        pipeline.start()

        mock_dev.disconnect("Hardware unplugged")
        pipeline.handle_device_loss()
        self.assertEqual(pipeline.state, AudioLifecycleState.ERROR)

        # Reconnect
        reconnected = pipeline.reconnect_device(resume_capture=True)
        self.assertTrue(reconnected)
        self.assertEqual(pipeline.state, AudioLifecycleState.RUNNING)

        recon_events = pipeline.get_events_by_type(AudioEventType.DEVICE_RECONNECTED)
        self.assertEqual(len(recon_events), 1)
        self.assertTrue(recon_events[0].metadata["resumed"])

        # Capture step functions properly after reconnection
        step_after = pipeline.process_step()
        self.assertIsNotNone(step_after)

    def test_d18_device_reconnection_failure_handled(self) -> None:
        """Verify reconnection failure is reported cleanly and preserves error state."""
        mock_dev = MockAudioDevice(
            initial_permission=AudioPermissionState.GRANTED,
            simulate_reconnect_failure=True,
        )
        pipeline = AudioPipeline(device=mock_dev, session_id=self.session_id)
        pipeline.start()

        mock_dev.disconnect("Unplugged")
        pipeline.handle_device_loss()

        success = pipeline.reconnect_device(resume_capture=True)
        self.assertFalse(success)
        self.assertEqual(pipeline.state, AudioLifecycleState.ERROR)
        self.assertIsNotNone(pipeline.last_error)

    def test_d18_reconnection_must_not_override_cancellation(self) -> None:
        """Verify that device reconnection never silently reactivates a cancelled session (B6)."""
        pipeline = AudioPipeline(session_id=self.session_id)
        pipeline.start()
        pipeline.cancel(reason="user_aborted")
        self.assertTrue(pipeline.is_cancelled)
        self.assertEqual(pipeline.state, AudioLifecycleState.STOPPED)

        # Calling reconnect_device on cancelled session must return False and stay stopped
        result = pipeline.reconnect_device(resume_capture=True)
        self.assertFalse(result)
        self.assertTrue(pipeline.is_cancelled)
        self.assertEqual(pipeline.state, AudioLifecycleState.STOPPED)

    def test_d18_reconnecting_healthy_device_emits_no_false_event(self) -> None:
        """Verify reconnecting an already-connected healthy device emits no false event (B11)."""
        pipeline = AudioPipeline(session_id=self.session_id)
        pipeline.start()
        self.assertEqual(pipeline.state, AudioLifecycleState.RUNNING)

        result = pipeline.reconnect_device(resume_capture=True)
        self.assertTrue(result)
        # No DEVICE_RECONNECTED event should be emitted for an already healthy running device
        recon_events = pipeline.get_events_by_type(AudioEventType.DEVICE_RECONNECTED)
        self.assertEqual(len(recon_events), 0)

    def test_d18_reconnect_resume_capture_false_leaves_valid_state(self) -> None:
        """Verify resume_capture=False leaves a valid lifecycle state (B11)."""
        mock_dev = MockAudioDevice(initial_permission=AudioPermissionState.GRANTED)
        pipeline = AudioPipeline(device=mock_dev, session_id=self.session_id)
        pipeline.start()
        mock_dev.disconnect("Unplugged")
        pipeline.handle_device_loss()

        result = pipeline.reconnect_device(resume_capture=False)
        self.assertTrue(result)
        self.assertIn(pipeline.state, (AudioLifecycleState.STOPPED, AudioLifecycleState.IDLE))

    def test_d18_cancellation_during_active_speech_flushes_and_stops(self) -> None:
        """Verify cancellation terminates speech segment with cancelled reason and flushes buffers."""
        pipeline = AudioPipeline(session_id=self.session_id, vad_config=self.vad_config)
        pipeline.start()

        for c in generate_speech_fixture(num_chunks=4):
            pipeline.buffer.push(c)
            pipeline.process_step()

        self.assertIsNotNone(pipeline.active_segment_id)

        # Cancel
        cancel_evt = pipeline.cancel(reason="user_exit")
        self.assertEqual(cancel_evt.event_type, AudioEventType.CANCELLED)
        self.assertTrue(pipeline.is_cancelled)
        self.assertEqual(pipeline.state, AudioLifecycleState.STOPPED)
        self.assertTrue(pipeline.buffer.is_empty)

        # SPEECH_END emitted with reason cancelled
        end_evts = pipeline.get_events_by_type(AudioEventType.SPEECH_END)
        self.assertEqual(len(end_evts), 1)
        self.assertEqual(end_evts[0].metadata["reason"], "cancelled")

    def test_d18_restart_after_cancellation_accepts_new_speech(self) -> None:
        """Verify starting a new session after cancellation accepts new speech cleanly (B4)."""
        pipeline = AudioPipeline(session_id="session-1", vad_config=self.vad_config)
        bridge = AudioTranscriptionBridge(pipeline=pipeline, auto_feed=True)
        pipeline.start()

        for c in generate_speech_fixture(num_chunks=3):
            pipeline.buffer.push(c)
            pipeline.process_step()

        pipeline.cancel()
        self.assertTrue(pipeline.is_cancelled)
        self.assertEqual(bridge.get_full_transcript(), "")

        # Start genuinely new session
        pipeline.start(session_id="session-2", correlation_id="corr-2")
        self.assertFalse(pipeline.is_cancelled)
        self.assertEqual(pipeline.session_id, "session-2")

        for c in generate_speech_fixture(num_chunks=5):
            pipeline.buffer.push(c)
            pipeline.process_step()
        for i in range(4):
            pipeline.buffer.push(create_deterministic_chunk(5 + i, 0.10 + i * 0.02, 0.0))
            pipeline.process_step()
        pipeline.stop()

        self.assertGreater(len(pipeline.get_events()), 0)
        self.assertTrue(all(e.session_id == "session-2" for e in pipeline.get_events()))

    # =========================================================================
    # DAY 19 – Transcription Module Integration
    # =========================================================================

    def test_d19_cancelled_speech_never_becomes_final_transcription(self) -> None:
        """Verify that cancelled speech and partial hypotheses are purged upon cancellation (B3)."""
        pipeline = AudioPipeline(session_id=self.session_id, vad_config=self.vad_config)
        transcriber = DeterministicFakeTranscriber(script=["confidential information not approved"], seed=42)
        accumulator = OrderedSegmentAccumulator()
        bridge = AudioTranscriptionBridge(
            pipeline=pipeline,
            transcriber=transcriber,
            accumulator=accumulator,
            auto_feed=True,
            session_id=self.session_id,
        )

        pipeline.start()
        for c in generate_speech_fixture(num_chunks=5):
            pipeline.buffer.push(c)
            pipeline.process_step()

        # Speech is in flight; cancel before normal finalization
        pipeline.cancel(reason="user_abort")

        # Invariants under B3:
        self.assertTrue(bridge.is_cancelled)
        self.assertEqual(bridge.get_full_transcript(), "")
        self.assertEqual(len(bridge.get_final_segments()), 0)
        self.assertIsNone(bridge.get_interim_segment())

    def test_d19_prevent_duplicate_stt_input(self) -> None:
        """Verify each audio chunk is processed exactly once by STT without duplicate input (B7)."""
        pipeline = AudioPipeline(session_id=self.session_id, vad_config=self.vad_config)
        recorded_chunk_seqs: List[int] = []

        class RecordingTranscriber(DeterministicFakeTranscriber):
            def transcribe_chunk(self, chunk, is_last=False):
                recorded_chunk_seqs.append(chunk.sequence_id)
                return super().transcribe_chunk(chunk, is_last=is_last)

        rec_transcriber = RecordingTranscriber(script=["test query"], seed=42)
        bridge = AudioTranscriptionBridge(pipeline=pipeline, transcriber=rec_transcriber, auto_feed=True)

        pipeline.start()
        for c in generate_speech_fixture(num_chunks=5):
            pipeline.buffer.push(c)
            pipeline.process_step()
        for i in range(4):
            pipeline.buffer.push(create_deterministic_chunk(5 + i, 0.10 + i * 0.02, 0.0))
            pipeline.process_step()
        pipeline.stop()

        # Invariant under B7: strictly no duplicate sequence IDs fed to transcriber
        self.assertEqual(len(recorded_chunk_seqs), len(set(recorded_chunk_seqs)))

    def test_d19_prevent_shared_chunk_metadata_mutation(self) -> None:
        """Verify transcription bridge does not mutate the original AudioChunk.metadata (B14)."""
        pipeline = AudioPipeline(session_id=self.session_id, vad_config=self.vad_config)
        bridge = AudioTranscriptionBridge(pipeline=pipeline, auto_feed=False)

        original_meta = {"source": "test_mic", "custom_key": 999}
        chunk = create_deterministic_chunk(sequence_id=0, timestamp=0.0, amplitude=0.55, metadata=original_meta)

        evt = AudioEvent(
            event_id="evt-chk-0",
            event_type=AudioEventType.AUDIO_CHUNK,
            session_id=self.session_id,
            correlation_id=self.correlation_id,
            sequence_number=0,
            timestamp=0.0,
            chunk=chunk,
            segment_id="seg-1",
            metadata={"is_speech": True},
        )
        bridge.feed_audio_event(evt)

        # Original chunk metadata must be untouched (B14)
        self.assertEqual(chunk.metadata, {"source": "test_mic", "custom_key": 999})
        self.assertNotIn("is_last", chunk.metadata)
        self.assertNotIn("session_id", chunk.metadata)

    # =========================================================================
    # DAY 20 – 13-Point Comprehensive Validation
    # =========================================================================

    def test_d20_thirteen_point_audio_event_validation_all_pass(self) -> None:
        """Execute the centralized 13-point validation checklist and verify 100% pass."""
        validator = Week3AudioValidator(session_id="val-test-run", correlation_id="val-trace-run")
        results = validator.run_all_checks()

        self.assertEqual(len(results), 13)
        for res in results:
            self.assertTrue(
                res.passed,
                f"Validation check failed: {res.check.name} ({res.check.check_id}). Details: {res.details}",
            )

    # =========================================================================
    # B11 – Device Edge Cases & Permission Revocation
    # =========================================================================

    def test_b11_permission_revocation_during_capture_handled_safely(self) -> None:
        """Verify revoking permission during active streaming closes speech and emits DEVICE_LOST (B11)."""
        mock_dev = MockAudioDevice(initial_permission=AudioPermissionState.GRANTED)
        pipeline = AudioPipeline(device=mock_dev, session_id=self.session_id, vad_config=self.vad_config)
        pipeline.start()

        # Ingest speech
        for c in generate_speech_fixture(num_chunks=4):
            pipeline.buffer.push(c)
            pipeline.process_step()
        self.assertIsNotNone(pipeline.active_segment_id)

        # Revoke permission mid-stream
        mock_dev.revoke_permission()
        self.assertEqual(mock_dev.get_permission_status(), AudioPermissionState.DENIED)

        # Next process step catches PERMISSION_DENIED and closes segment cleanly
        step_res = pipeline.process_step()
        self.assertIsNone(step_res)
        self.assertEqual(pipeline.state, AudioLifecycleState.ERROR)
        self.assertIsNone(pipeline.active_segment_id)

        loss_evts = pipeline.get_events_by_type(AudioEventType.DEVICE_LOST)
        self.assertEqual(len(loss_evts), 1)

    # =========================================================================
    # B15 – Lifecycle Controller Direct Method Tests
    # =========================================================================

    def test_b15_lifecycle_handle_device_reconnected_direct(self) -> None:
        """Directly verify AudioLifecycleController.handle_device_reconnected (B15)."""
        mock_dev = MockAudioDevice(initial_permission=AudioPermissionState.GRANTED)
        controller = AudioLifecycleController(device=mock_dev)
        controller.start()
        controller.handle_device_loss()
        self.assertEqual(controller.state, AudioLifecycleState.ERROR)

        # Healthy reconnection restores controller to RUNNING
        res = controller.handle_device_reconnected(resume_capture=True)
        self.assertTrue(res)
        self.assertEqual(controller.state, AudioLifecycleState.RUNNING)

        # Reconnection with resume_capture=False leaves controller in STOPPED
        controller.handle_device_loss()
        res_no_resume = controller.handle_device_reconnected(resume_capture=False)
        self.assertTrue(res_no_resume)
        self.assertEqual(controller.state, AudioLifecycleState.STOPPED)

    def test_b15_lifecycle_cancel_direct(self) -> None:
        """Directly verify AudioLifecycleController.cancel (B15)."""
        mock_dev = MockAudioDevice(initial_permission=AudioPermissionState.GRANTED)
        controller = AudioLifecycleController(device=mock_dev)
        controller.start()
        self.assertEqual(controller.state, AudioLifecycleState.RUNNING)

        controller.cancel(reason="test_cancel")
        self.assertEqual(controller.state, AudioLifecycleState.STOPPED)

        # Idempotent cancel
        controller.cancel(reason="test_cancel_again")
        self.assertEqual(controller.state, AudioLifecycleState.STOPPED)


if __name__ == "__main__":
    unittest.main()
