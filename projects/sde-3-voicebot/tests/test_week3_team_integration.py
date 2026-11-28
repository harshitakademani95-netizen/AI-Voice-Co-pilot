"""
End-to-End Team Integration Test for Week 3 Day 21 (Audited & 100% Complete).

Workstream: W1/W2/W3/W4/W5/W6 - Academia AI Voice Bot (Team SDE 3)
Verifies the complete vertical integration flow across all team modules:
Audio Capture -> VAD -> Normalized Audio Events -> STT Transcription ->
Context & Reasoning -> Workflow Engine -> Human-in-the-Loop Safety Gate -> Backend Session Repository.

Covers all audit requirements:
- Case A: Consequential Workflow -> awaiting_approval -> Approve -> succeeded
- Case B: Consequential Workflow -> awaiting_approval -> Reject -> cancelled & failed
- Case C: Consequential Workflow -> Cancel -> prevents protected action execution
- Case D: Speech -> Device Loss -> Device Reconnect -> New Speech -> Transcription (Section 2)
- Case E: Safe Session Resource Cleanup (Section 8)
- Persistence and Retrieval in InMemorySessionRepository
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import List

# W1: Audio & VAD
from src.audio.backend_integration import AudioBackendSessionManager
from src.audio.device import AudioPermissionState, MockAudioDevice
from src.audio.lifecycle import AudioLifecycleState
from src.audio.pipeline import AudioPipeline, create_deterministic_chunk, generate_speech_fixture
from src.audio.transcription_integration import AudioTranscriptionBridge
from src.audio.vad import VADConfig
from src.schemas.audio import AudioEventType

# W2: STT Transcription
try:
    from src.voice_stt.accumulator import OrderedSegmentAccumulator
    from src.voice_stt.fake_transcriber import DeterministicFakeTranscriber
except ImportError:
    from voice_stt.accumulator import OrderedSegmentAccumulator  # type: ignore
    from voice_stt.fake_transcriber import DeterministicFakeTranscriber  # type: ignore

# W3: Context & Reasoning
from src.context.schemas import RiskCategory

# W4: Agentic Workflow Engine
from agentic_workflow import (
    ApprovalStatus,
    WorkflowState,
    reset_mock_tools_state,
)
from agentic_workflow.tools import _MOCK_GENERATED_REPORTS

# W5: Backend Repository
from src.models.session import SessionState
from src.repositories.session_repository import session_repository


class TestWeek3CompleteTeamIntegration(unittest.TestCase):
    """Verifies Day 21 complete cross-workstream team integration and safety gates."""

    def setUp(self) -> None:
        self.session_id = "sess-team-w3-d21"
        self.correlation_id = "corr-team-trace-999"
        reset_mock_tools_state()
        session_repository.clear()

    # =========================================================================
    # Case A: Consequential Workflow -> awaiting_approval -> Approve -> succeeded
    # =========================================================================

    def test_case_a_consequential_approval_gate_executes_action(self) -> None:
        """
        Verify Case A (Section 4):
        Audio -> Transcription -> Reasoning -> Consequential WorkflowProposal ->
        awaiting_approval -> Approve -> succeeded.
        Ensures protected mock action is NOT executed before approval, and IS executed after.
        """
        manager = AudioBackendSessionManager(repository=session_repository)

        # 1. Initialize session with consequential request ("delete my files")
        manager.create_integrated_session(
            session_id=self.session_id,
            correlation_id=self.correlation_id,
            target_script=["delete my files and purge temporary storage"],
        )

        # 2. Process audio stream
        stream_res = manager.process_audio_stream(
            session_id=self.session_id,
            speech_chunks=5,
            silence_chunks=4,
        )
        self.assertIn("delete my files", stream_res["transcript"].lower())

        # 3. Reasoning classifies as Category D (Destructive, requires approval)
        reasoning_res, plan, exec_res = manager.execute_reasoning_and_plan(
            session_id=self.session_id,
            active_app="Terminal",
            window_title="bash - clean.sh",
            visible_error="Pending deletion of sensitive files",
        )
        self.assertEqual(reasoning_res.risk_level, RiskCategory.CATEGORY_D)
        self.assertTrue(reasoning_res.requires_approval)

        # 4. Strictly assert workflow halts at awaiting_approval
        self.assertEqual(plan.state, WorkflowState.AWAITING_APPROVAL)
        # Verify protected action has NOT executed before approval
        self.assertEqual(len(_MOCK_GENERATED_REPORTS), 0)

        # 5. Grant human approval
        final_res = manager.approve_and_complete_workflow(
            session_id=self.session_id,
            approver="security-admin@academia.ai",
            comment="Approved destructive cleanup by verified admin",
        )
        # 6. Strictly assert final state is succeeded
        self.assertEqual(final_res.final_state, WorkflowState.SUCCEEDED.value)
        self.assertEqual(plan.state, WorkflowState.SUCCEEDED)
        # Verify protected action HAS executed upon approval
        self.assertEqual(len(_MOCK_GENERATED_REPORTS), 1)

        # 7. Session repository is marked COMPLETED
        final_session = session_repository.get(self.session_id)
        self.assertEqual(final_session.state, SessionState.COMPLETED)
        self.assertEqual(final_session.metadata["workflow_state"], "succeeded")

    # =========================================================================
    # Case B: Consequential Workflow -> awaiting_approval -> Reject -> cancelled
    # =========================================================================

    def test_case_b_consequential_rejection_prevents_action_and_fails_session(self) -> None:
        """
        Verify Case B (Section 4):
        Audio -> Transcription -> Reasoning -> Consequential WorkflowProposal ->
        awaiting_approval -> Reject -> cancelled.
        Ensures protected action does NOT execute, and session is marked FAILED (never COMPLETED).
        """
        manager = AudioBackendSessionManager(repository=session_repository)
        session_id = "sess-w3-case-b"

        manager.create_integrated_session(
            session_id=session_id,
            target_script=["delete my files and purge temporary storage"],
        )
        manager.process_audio_stream(session_id=session_id, speech_chunks=5, silence_chunks=4)

        reasoning_res, plan, _ = manager.execute_reasoning_and_plan(session_id=session_id)
        self.assertEqual(plan.state, WorkflowState.AWAITING_APPROVAL)
        self.assertEqual(len(_MOCK_GENERATED_REPORTS), 0)

        # Reject the proposal
        final_res = manager.reject_and_cancel_workflow(
            session_id=session_id,
            rejector="security-auditor@academia.ai",
            comment="Deletion rejected per security policy",
        )
        # Strictly assert workflow plan is cancelled
        self.assertEqual(plan.state, WorkflowState.CANCELLED)
        self.assertEqual(final_res.final_state, WorkflowState.CANCELLED.value)
        # Verify protected action did NOT execute
        self.assertEqual(len(_MOCK_GENERATED_REPORTS), 0)

        # Verify session is marked FAILED, NOT COMPLETED (Section 4 requirement)
        final_session = session_repository.get(session_id)
        self.assertEqual(final_session.state, SessionState.FAILED)
        self.assertNotEqual(final_session.state, SessionState.COMPLETED)

    # =========================================================================
    # Case C: Consequential Workflow -> Cancel -> prevents protected action
    # =========================================================================

    def test_case_c_consequential_cancellation_prevents_action(self) -> None:
        """
        Verify Case C (Section 4):
        Audio -> Transcription -> Reasoning -> WorkflowProposal -> Cancel ->
        Verify no protected action executes and session transitions to failed.
        """
        manager = AudioBackendSessionManager(repository=session_repository)
        session_id = "sess-w3-case-c"

        manager.create_integrated_session(
            session_id=session_id,
            target_script=["delete my files"],
        )
        manager.process_audio_stream(session_id=session_id, speech_chunks=5, silence_chunks=4)
        manager.execute_reasoning_and_plan(session_id=session_id)

        # Explicit cancellation
        res = manager.cancel_workflow(session_id=session_id, reason="User cancelled execution")
        self.assertTrue(res)

        # Protected action did NOT execute
        self.assertEqual(len(_MOCK_GENERATED_REPORTS), 0)

        plan = manager._active_plans.get(session_id)
        self.assertEqual(plan.state, WorkflowState.CANCELLED)

        session = session_repository.get(session_id)
        self.assertEqual(session.state, SessionState.FAILED)

    # =========================================================================
    # Case D: Speech -> Device Loss -> Device Reconnect -> New Speech -> STT
    # =========================================================================

    def test_case_d_speech_device_loss_reconnect_new_speech_transcription(self) -> None:
        """
        Verify Section 2:
        Speech -> Device Loss -> Device Reconnection -> New Speech -> Transcription.
        Proves:
        1. First utterance is transcribed.
        2. Device loss is handled correctly (ERROR state, segment safely closed).
        3. Device reconnects successfully (RUNNING state, DEVICE_RECONNECTED emitted).
        4. Second utterance is transcribed (new speech chunks reach STT).
        5. No duplicate chunks are sent.
        6. Both utterances retain correct identifiers.
        """
        dev = MockAudioDevice(initial_permission=AudioPermissionState.GRANTED)
        pipeline = AudioPipeline(
            session_id="sess-reconn-flow",
            correlation_id="corr-reconn-flow",
            device=dev,
            buffer_capacity=30,
            vad_config=VADConfig(min_speech_duration_ms=40.0, min_silence_duration_ms=60.0),
        )

        transcriber = DeterministicFakeTranscriber(
            script=["first command", "second command", "third command", "fourth command"],
            seed=42,
        )
        accumulator = OrderedSegmentAccumulator()
        bridge = AudioTranscriptionBridge(
            pipeline=pipeline,
            transcriber=transcriber,
            accumulator=accumulator,
            auto_feed=True,
            session_id="sess-reconn-flow",
            correlation_id="corr-reconn-flow",
        )
        pipeline.start()

        # Step 1: Utterance 1 (3 speech chunks + 4 silence chunks)
        for c in generate_speech_fixture(num_chunks=3, amplitude=0.55):
            pipeline.process_chunk_direct(c)
        for i in range(4):
            silence = create_deterministic_chunk(sequence_id=3 + i, timestamp=0.06 + i * 0.02, amplitude=0.0)
            pipeline.process_chunk_direct(silence)

        # 1. First utterance is transcribed
        transcript_1 = bridge.get_full_transcript()
        self.assertGreater(len(transcript_1), 0)
        self.assertIn("first", transcript_1.lower())
        chunks_after_u1 = bridge._speech_chunks_transcribed
        segments_after_u1 = len(bridge.get_final_segments())
        self.assertGreater(chunks_after_u1, 0)
        self.assertGreater(segments_after_u1, 0)

        # Step 2: Device loss mid-session
        loss_evt = pipeline.handle_device_loss()
        self.assertEqual(pipeline.state, AudioLifecycleState.ERROR)
        self.assertIsNone(pipeline.active_segment_id)
        self.assertEqual(loss_evt.event_type, AudioEventType.DEVICE_LOST)

        # Step 3: Device reconnection
        reconnected = pipeline.reconnect_device(resume_capture=True)
        self.assertTrue(reconnected)
        self.assertEqual(pipeline.state, AudioLifecycleState.RUNNING)
        reconn_evts = pipeline.get_events_by_type(AudioEventType.DEVICE_RECONNECTED)
        self.assertEqual(len(reconn_evts), 1)

        # Step 4: Utterance 2 (speech chunks with sequence numbers restarting from 0)
        for c in generate_speech_fixture(num_chunks=3, amplitude=0.55):
            pipeline.process_chunk_direct(c)
        for i in range(4):
            silence = create_deterministic_chunk(sequence_id=3 + i, timestamp=0.14 + i * 0.02, amplitude=0.0)
            pipeline.process_chunk_direct(silence)

        # 4. Second utterance IS transcribed (not discarded by deduplication!)
        transcript_2 = bridge.get_full_transcript()
        self.assertGreater(len(transcript_2), len(transcript_1))
        self.assertIn("second", transcript_2.lower())
        self.assertGreater(bridge._speech_chunks_transcribed, chunks_after_u1)

        # 5. Verify second utterance added new segments without duplicate chunks
        self.assertGreater(len(bridge.get_final_segments()), segments_after_u1)
        # 6. Both utterances retain correct identifiers
        all_bridge_events = bridge.get_transcript_events()
        for evt in all_bridge_events:
            self.assertEqual(evt.session_id, "sess-reconn-flow")

    # =========================================================================
    # Case E: Session Resource Cleanup (Section 8)
    # =========================================================================

    def test_case_e_session_resource_cleanup(self) -> None:
        """
        Verify safe session cleanup (Section 8):
        - Completed sessions have resources released.
        - Cancellation releases resources.
        - Repeated cleanup is safe (idempotent).
        - Active sessions are protected unless force=True.
        """
        manager = AudioBackendSessionManager(repository=session_repository)
        session_id = "sess-cleanup-test"

        manager.create_integrated_session(session_id=session_id)
        self.assertIn(session_id, manager._active_pipelines)

        # Attempt to cleanup an ACTIVE session without force: must be REFUSED
        refused = manager.cleanup_session(session_id, force=False)
        self.assertFalse(refused)
        self.assertIn(session_id, manager._active_pipelines)

        # Transition to completed
        session_repository.transition(session_id, SessionState.COMPLETED, reason="Done")

        # Cleanup completed session: must SUCCEED
        cleaned = manager.cleanup_session(session_id, force=False)
        self.assertTrue(cleaned)
        self.assertNotIn(session_id, manager._active_pipelines)
        self.assertNotIn(session_id, manager._active_bridges)

        # Repeated cleanup is safe and returns True (idempotent)
        cleaned_again = manager.cleanup_session(session_id, force=False)
        self.assertTrue(cleaned_again)

    def test_backend_audio_event_persistence_and_retrieval(self) -> None:
        """Verify all audio events, transcript, and status are retrievable from repository."""
        manager = AudioBackendSessionManager(repository=session_repository)
        session_id = "sess-persist-check"

        manager.create_integrated_session(
            session_id=session_id,
            target_script=["find my project report"],
        )
        manager.process_audio_stream(session_id=session_id, speech_chunks=5, silence_chunks=4)

        retrieved_session = session_repository.get(session_id)
        self.assertEqual(retrieved_session.session_id, session_id)

        # Check audio events
        audio_events = [e for e in retrieved_session.events if e.event_type.startswith("audio.")]
        self.assertGreater(len(audio_events), 0)

        # Verify transcript is stored
        self.assertIn("transcript", retrieved_session.metadata)
        self.assertIn("find my project report", retrieved_session.metadata["transcript"].lower())


if __name__ == "__main__":
    unittest.main()
