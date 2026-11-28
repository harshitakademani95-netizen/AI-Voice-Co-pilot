"""
FastAPI Route Integration Tests for Audio & VAD routes (Section 3).

Verifies actual API endpoint behavior and HTTP response models:
- Successful audio initialization on existing session
- Idempotent repeated audio initialization
- Missing session returns 404 (SessionNotFoundError)
- Audio chunk processing through route handler
- Reason-and-plan route with consequential workflow
- Human-in-the-Loop approval route
- Rejection route with terminal state verification (FAILED, not COMPLETED)
- Cancellation route
- Resource cleanup route
"""

from __future__ import annotations

import unittest
from typing import Any, Coroutine

from agentic_workflow import reset_mock_tools_state
from agentic_workflow.tools import _MOCK_GENERATED_REPORTS
from src.audio.backend_integration import audio_backend_manager
from src.core.errors import SessionNotFoundError
from src.models.session import SessionCreateRequest, SessionState
from src.repositories.session_repository import session_repository
from src.routes.sessions import (
    approve_session_workflow,
    cancel_session_audio,
    cleanup_session_audio,
    create_session,
    init_session_audio,
    process_session_audio,
    reason_and_plan_session,
    reject_session_workflow,
)


def run_sync(coro: Coroutine[Any, Any, Any]) -> Any:
    """Execute coroutine synchronously without relying on Python 3.14 Windows threadpool event loop."""
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise RuntimeError("Coroutine did not complete synchronously")


class TestAudioRoutesAPI(unittest.TestCase):
    """Test actual FastAPI session and audio route handlers."""

    def setUp(self) -> None:
        reset_mock_tools_state()
        session_repository.clear()
        audio_backend_manager._active_pipelines.clear()
        audio_backend_manager._active_bridges.clear()
        audio_backend_manager._active_plans.clear()
        audio_backend_manager._state_machines.clear()

    def test_audio_init_existing_session_success(self) -> None:
        """POST /{id}/audio/init attaches audio pipeline to an existing session."""
        # 1. Create a session first
        create_resp = run_sync(create_session(SessionCreateRequest(session_id="sess-api-001")))
        self.assertEqual(create_resp.session_id, "sess-api-001")
        self.assertEqual(create_resp.state, SessionState.CREATED)

        # 2. Initialize audio on existing session
        init_resp = run_sync(init_session_audio("sess-api-001"))
        self.assertEqual(init_resp.session_id, "sess-api-001")
        self.assertEqual(init_resp.state, SessionState.ACTIVE)

        # Verify pipeline and bridge were registered in manager
        self.assertIn("sess-api-001", audio_backend_manager._active_pipelines)
        self.assertIn("sess-api-001", audio_backend_manager._active_bridges)

    def test_audio_init_repeated_is_idempotent(self) -> None:
        """Repeated calls to /{id}/audio/init succeed without SESSION_ALREADY_EXISTS."""
        create_resp = run_sync(create_session(SessionCreateRequest(session_id="sess-api-repeat")))
        self.assertEqual(create_resp.state, SessionState.CREATED)

        # First call
        resp1 = run_sync(init_session_audio("sess-api-repeat"))
        self.assertEqual(resp1.state, SessionState.ACTIVE)

        # Second call (repeated initialization)
        resp2 = run_sync(init_session_audio("sess-api-repeat"))
        self.assertEqual(resp2.session_id, "sess-api-repeat")
        self.assertEqual(resp2.state, SessionState.ACTIVE)

    def test_audio_init_missing_session_returns_404(self) -> None:
        """POST /{id}/audio/init on non-existent session raises SessionNotFoundError with 404."""
        with self.assertRaises(SessionNotFoundError) as ctx:
            run_sync(init_session_audio("nonexistent-session-xyz"))
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.code, "SESSION_NOT_FOUND")

    def test_audio_process_route(self) -> None:
        """POST /{id}/audio/process ingests frames and updates session repository."""
        run_sync(create_session(SessionCreateRequest(session_id="sess-api-process")))
        run_sync(init_session_audio("sess-api-process"))

        process_resp = run_sync(process_session_audio("sess-api-process", speech_chunks=5, silence_chunks=4))
        self.assertEqual(process_resp.session_id, "sess-api-process")

        # Verify events are stored in session repository
        session = session_repository.get("sess-api-process")
        audio_events = [e for e in session.events if e.event_type.startswith("audio.")]
        self.assertGreater(len(audio_events), 0)

    def test_audio_reason_and_plan_consequential_route(self) -> None:
        """POST /{id}/audio/reason-and-plan constructs plan entering awaiting_approval."""
        run_sync(create_session(SessionCreateRequest(session_id="sess-api-conseq")))
        run_sync(init_session_audio("sess-api-conseq"))
        run_sync(process_session_audio("sess-api-conseq", speech_chunks=5, silence_chunks=4))

        # Set consequential query in metadata
        session_repository.update_metadata("sess-api-conseq", {"transcript": "delete my files"})

        plan_resp = run_sync(reason_and_plan_session("sess-api-conseq"))
        self.assertEqual(plan_resp.session_id, "sess-api-conseq")

        plan = audio_backend_manager._active_plans.get("sess-api-conseq")
        self.assertIsNotNone(plan)
        self.assertEqual(plan.state.value, "awaiting_approval")
        # Ensure protected action has NOT executed before approval
        self.assertEqual(len(_MOCK_GENERATED_REPORTS), 0)

    def test_audio_approve_route(self) -> None:
        """POST /{id}/audio/approve approves gate, executes action, and completes session."""
        run_sync(create_session(SessionCreateRequest(session_id="sess-api-appr")))
        run_sync(init_session_audio("sess-api-appr"))
        run_sync(process_session_audio("sess-api-appr", speech_chunks=5, silence_chunks=4))

        session_repository.update_metadata("sess-api-appr", {"transcript": "delete my files"})
        run_sync(reason_and_plan_session("sess-api-appr"))

        approve_resp = run_sync(approve_session_workflow(
            session_id="sess-api-appr",
            approver="admin@academia.ai",
            comment="Approved",
        ))
        self.assertEqual(approve_resp.session_id, "sess-api-appr")
        self.assertEqual(approve_resp.state, SessionState.COMPLETED)
        # Ensure protected mock action executed upon approval
        self.assertGreaterEqual(len(_MOCK_GENERATED_REPORTS), 1)

    def test_audio_reject_route(self) -> None:
        """POST /{id}/audio/reject cancels workflow and transitions session to failed."""
        run_sync(create_session(SessionCreateRequest(session_id="sess-api-rej")))
        run_sync(init_session_audio("sess-api-rej"))
        run_sync(process_session_audio("sess-api-rej", speech_chunks=5, silence_chunks=4))

        session_repository.update_metadata("sess-api-rej", {"transcript": "delete my files"})
        run_sync(reason_and_plan_session("sess-api-rej"))

        reject_resp = run_sync(reject_session_workflow(
            session_id="sess-api-rej",
            rejector="auditor@academia.ai",
            comment="DestructiveActionDisallowed",
        ))
        self.assertEqual(reject_resp.session_id, "sess-api-rej")
        # Rejection transitions to FAILED, never COMPLETED (Section 4)
        self.assertEqual(reject_resp.state, SessionState.FAILED)
        # Ensure protected action did NOT execute
        self.assertEqual(len(_MOCK_GENERATED_REPORTS), 0)

    def test_audio_cancel_route(self) -> None:
        """POST /{id}/audio/cancel cancels pipeline and pending workflow."""
        run_sync(create_session(SessionCreateRequest(session_id="sess-api-cancel")))
        run_sync(init_session_audio("sess-api-cancel"))

        cancel_resp = run_sync(cancel_session_audio("sess-api-cancel", reason="user_abort"))
        self.assertEqual(cancel_resp.session_id, "sess-api-cancel")
        self.assertEqual(cancel_resp.state, SessionState.FAILED)
        # Ensure protected action did NOT execute
        self.assertEqual(len(_MOCK_GENERATED_REPORTS), 0)

    def test_audio_cleanup_route(self) -> None:
        """POST /{id}/audio/cleanup removes session resources safely."""
        run_sync(create_session(SessionCreateRequest(session_id="sess-api-cleanup")))
        run_sync(init_session_audio("sess-api-cleanup"))

        # Transition session to completed so cleanup is permitted without force
        session_repository.transition("sess-api-cleanup", SessionState.COMPLETED, reason="Done")

        cleanup_resp = run_sync(cleanup_session_audio("sess-api-cleanup", force=False))
        self.assertEqual(cleanup_resp.session_id, "sess-api-cleanup")
        self.assertNotIn("sess-api-cleanup", audio_backend_manager._active_pipelines)
        self.assertNotIn("sess-api-cleanup", audio_backend_manager._active_bridges)


if __name__ == "__main__":
    unittest.main()
