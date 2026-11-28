"""
Backend Session and Workflow Integration Engine (Week 3, Day 21).

Binds the real AudioPipeline, AudioTranscriptionBridge, MockReasoningEngine,
Agentic Workflow Executor, and InMemorySessionRepository into a unified runtime:
- Persists all normalized AudioEvents directly into InMemorySessionRepository.
- Automatically captures speech, transcribes, feeds into Context & Reasoning.
- Dynamically derives WorkflowPlans from reasoning outputs (not hardcoded).
- Enforces Human-in-the-Loop safety approval gates before consequential actions.
- Persists transcript, reasoning response, and workflow plans in session state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from src.audio.device import AudioPermissionState, MockAudioDevice
from src.audio.lifecycle import AudioLifecycleState
from src.audio.pipeline import AudioPipeline, create_deterministic_chunk, generate_speech_fixture
from src.audio.transcription_integration import AudioTranscriptionBridge
from src.audio.vad import VADConfig
from src.context.fixtures import create_synthetic_screen_frame
from src.context.schemas import ContextItem, ContextType, ReasoningRequest, RiskCategory
from src.models.session import Session, SessionEvent, SessionState
from src.reasoning.mock_engine import MockReasoningEngine
from src.repositories.session_repository import InMemorySessionRepository, session_repository
from src.schemas.audio import AudioChunk, AudioError, AudioEvent, AudioEventType, AudioFormat

# Agentic Workflow imports
from agentic_workflow import (
    ApprovalRequest,
    ApprovalStatus,
    RiskLevel,
    StepStatus,
    ToolRegistry,
    WorkflowExecutor,
    WorkflowPlan,
    WorkflowState,
    WorkflowStateMachine,
    WorkflowStep,
    reset_mock_tools_state,
)

import sys
from pathlib import Path

_curr_path = Path(__file__).resolve().parent
_src_path = _curr_path.parent
_proj_path = _src_path.parent
for _p in [str(_src_path), str(_proj_path)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# STT imports
try:
    from src.voice_stt.accumulator import OrderedSegmentAccumulator
    from src.voice_stt.fake_transcriber import DeterministicFakeTranscriber
except ImportError:
    try:
        from voice_stt.accumulator import OrderedSegmentAccumulator  # type: ignore
        from voice_stt.fake_transcriber import DeterministicFakeTranscriber  # type: ignore
    except ImportError as err:
        raise ImportError(
            f"AudioBackendSessionManager requires voice_stt: {err}. "
            "Please ensure pydantic is installed (`pip install 'pydantic>=2,<3'`) and that "
            "'projects/sde-3-voicebot/src' or the project root is on PYTHONPATH."
        ) from err

logger = logging.getLogger(__name__)


class AudioBackendSessionManager:
    """
    Manages live sessions connecting AudioPipeline -> STT -> Reasoning -> Workflow -> Repository.
    """

    def __init__(
        self,
        repository: Optional[InMemorySessionRepository] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ) -> None:
        self.repository = repository or session_repository
        self.tool_registry = tool_registry or ToolRegistry()
        self.workflow_executor = WorkflowExecutor(self.tool_registry)
        self.reasoning_engine = MockReasoningEngine()
        self._active_pipelines: Dict[str, AudioPipeline] = {}
        self._active_bridges: Dict[str, AudioTranscriptionBridge] = {}
        self._active_plans: Dict[str, WorkflowPlan] = {}
        self._state_machines: Dict[str, WorkflowStateMachine] = {}

    def init_audio_pipeline(
        self,
        session_id: str,
        correlation_id: Optional[str] = None,
        target_script: Optional[List[str]] = None,
    ) -> Session:
        """
        Initialize and attach AudioPipeline + STT Bridge to an EXISTING session in the repository.
        Handles repeated initialization safely without duplicate pipelines or duplicate bridges (Section 3).
        """
        session = self.repository.get(session_id)
        cid = correlation_id or session.metadata.get("correlation_id") or f"corr-{session_id}"

        # If already initialized and running, handle safely (idempotent repeated call)
        if session_id in self._active_pipelines and session_id in self._active_bridges:
            logger.info("Audio pipeline already initialized for session %s; reusing active pipeline.", session_id)
            return self.repository.get(session_id)

        # Transition from CREATED to ACTIVE if needed
        if session.state == SessionState.CREATED:
            try:
                self.repository.transition(session_id, SessionState.ACTIVE, reason="Session initialized for voice interaction")
            except Exception as exc:
                logger.warning("Could not transition session state: %s", exc)

        # Setup AudioPipeline with automatic event logging callback to repository
        def on_audio_event(evt: AudioEvent) -> None:
            try:
                self.repository.add_event(
                    session_id=session_id,
                    event_type=f"audio.{evt.event_type.value}",
                    payload=evt.to_dict(),
                )
            except Exception as exc:
                logger.warning("Failed to record audio event in session repository: %s", exc)

        pipeline = AudioPipeline(
            session_id=session_id,
            correlation_id=cid,
            buffer_capacity=30,
            vad_config=VADConfig(
                energy_threshold=0.015,
                speech_probability_threshold=0.4,
                min_speech_duration_ms=40.0,
                min_silence_duration_ms=60.0,
            ),
            on_event_callback=on_audio_event,
        )

        transcriber = DeterministicFakeTranscriber(script=target_script, seed=42)
        bridge = AudioTranscriptionBridge(
            pipeline=pipeline,
            transcriber=transcriber,
            accumulator=OrderedSegmentAccumulator(),
            auto_feed=True,
            session_id=session_id,
            correlation_id=cid,
        )

        pipeline.start()
        self._active_pipelines[session_id] = pipeline
        self._active_bridges[session_id] = bridge
        return self.repository.get(session_id)

    def create_integrated_session(
        self,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        target_script: Optional[List[str]] = None,
    ) -> Session:
        """
        Create a new session in repository (or reuse existing) and wire AudioPipeline + STT Bridge.
        """
        sid = session_id or f"sess-w3-{uuid.uuid4().hex[:8]}"
        cid = correlation_id or f"corr-w3-{uuid.uuid4().hex[:8]}"
        try:
            self.repository.create(session_id=sid, metadata={"correlation_id": cid})
        except Exception:
            logger.info("Session %s already exists in repository; attaching pipeline directly.", sid)
        return self.init_audio_pipeline(session_id=sid, correlation_id=cid, target_script=target_script)

    def process_audio_stream(
        self,
        session_id: str,
        speech_chunks: int = 5,
        silence_chunks: int = 4,
    ) -> Dict[str, Any]:
        """
        Process deterministic audio stream through the pipeline:
        Directly ingests deterministic speech chunks and silence debounce frames through
        the pipeline's bounded buffer and VAD, emitting normalized events to the STT Bridge
        and persisting them in the session repository.
        """
        pipeline = self._active_pipelines.get(session_id)
        bridge = self._active_bridges.get(session_id)
        if not pipeline or not bridge:
            raise AudioError(f"No active pipeline for session {session_id}", code="SESSION_NOT_FOUND")

        # Ingest speech chunks directly into pipeline (bounded buffer -> VAD -> events)
        for c in generate_speech_fixture(num_chunks=speech_chunks, amplitude=0.55):
            pipeline.process_chunk_direct(c)

        # Ingest debounce silence chunks to close speech segment
        start_t = speech_chunks * 0.02
        for i in range(silence_chunks):
            silence_chunk = create_deterministic_chunk(
                sequence_id=speech_chunks + i,
                timestamp=start_t + i * 0.02,
                amplitude=0.0,
            )
            pipeline.process_chunk_direct(silence_chunk)

        pipeline.stop()

        transcript = bridge.get_full_transcript()
        conf = bridge.accumulator.get_average_confidence()

        # Update session repository with transcription results
        self.repository.update_metadata(
            session_id,
            {"transcript": transcript, "transcription_confidence": conf},
        )
        self.repository.add_event(
            session_id=session_id,
            event_type="transcription.completed",
            payload={"transcript": transcript, "confidence": conf},
        )
        return {"transcript": transcript, "confidence": conf}

    def execute_reasoning_and_plan(
        self,
        session_id: str,
        active_app: str = "Visual Studio Code",
        window_title: str = "VSCode - main.py",
        visible_error: str = "TypeError: unsupported operand type(s) for +: 'int' and 'str'",
    ) -> Tuple[Any, WorkflowPlan, Any]:
        """
        Passes transcript to MockReasoningEngine, derives a real WorkflowPlan from
        the reasoning output, and initiates execution up to the Human-in-the-Loop Safety Gate.
        """
        session = self.repository.get(session_id)
        transcript = session.metadata.get("transcript", "explain this technical error in code")
        correlation_id = session.metadata.get("correlation_id", f"corr-{session_id}")

        # 1. Context Item Creation (grounds error keywords so reasoning recognizes TypeError)
        screen_frame = create_synthetic_screen_frame(
            frame_id=f"frame-{session_id[:8]}",
            active_app=active_app,
            window_title=window_title,
            visible_text=visible_error,
        )
        screen_item = ContextItem(
            item_id=f"ctx-screen-{session_id[:8]}",
            context_type=ContextType.SCREEN,
            source="Display-1",
            content=f"Error log on active app {active_app}: {visible_error}",
            screen_context=screen_frame,
            timestamp=datetime.now(timezone.utc),
        )

        # 2. Reasoning Execution
        reasoning_req = ReasoningRequest(
            request_id=f"req-{correlation_id}",
            session_id=session_id,
            user_query=transcript,
            context_items=[screen_item],
        )
        reasoning_res = self.reasoning_engine.reason(reasoning_req)

        # 3. Dynamic Workflow Plan Construction from Reasoning Output (not hardcoded)
        # Derive steps directly based on reasoning response and risk category
        is_consequential = reasoning_res.risk_level in (RiskCategory.CATEGORY_C, RiskCategory.CATEGORY_D) or reasoning_res.requires_approval

        step1 = WorkflowStep(
            step_id=f"step-inspect-{session_id[:6]}",
            name="Inspect Workspace Error Details",
            tool_name="mock_task_checker",
            inputs={"task_id": "task-audit-101", "context": screen_item.content, "query": transcript},
            is_consequential=False,
        )
        step2 = WorkflowStep(
            step_id=f"step-action-{session_id[:6]}",
            name="Execute Error Remediation",
            tool_name="mock_report_generator",
            inputs={"title": "Error Remediation Action", "details": reasoning_res.response_text},
            is_consequential=is_consequential,
            dependencies=[step1.step_id],
        )

        plan = WorkflowPlan(
            workflow_id=f"wf-{session_id}",
            run_id=f"run-{correlation_id}",
            description=f"Remediation plan grounded in: {reasoning_res.response_text[:40]}...",
            steps=[step1, step2],
        )

        sm = WorkflowStateMachine(initial_state=WorkflowState.DRAFT)
        self._active_plans[session_id] = plan
        self._state_machines[session_id] = sm

        # 4. Execute up to safety gate
        execution_result = self.workflow_executor.execute(plan, sm=sm)

        # 5. Persist reasoning and plan in session repository
        self.repository.update_metadata(
            session_id,
            {
                "reasoning_response": reasoning_res.response_text,
                "risk_level": reasoning_res.risk_level.value,
                "workflow_plan_id": plan.workflow_id,
                "workflow_state": plan.state.value,
            },
        )

        self.repository.add_event(
            session_id=session_id,
            event_type="reasoning.completed",
            payload={
                "response_text": reasoning_res.response_text,
                "risk_level": reasoning_res.risk_level.value,
                "requires_approval": reasoning_res.requires_approval,
            },
        )
        self.repository.add_event(
            session_id=session_id,
            event_type="workflow.plan_created",
            payload={
                "workflow_id": plan.workflow_id,
                "state": plan.state.value,
                "step_count": len(plan.steps),
            },
        )

        return reasoning_res, plan, execution_result

    def approve_and_complete_workflow(
        self,
        session_id: str,
        approver: str = "lead-engineer@academia.ai",
        comment: str = "Approved for execution",
    ) -> Any:
        """Approve pending consequential step and resume execution to completion."""
        plan = self._active_plans.get(session_id)
        sm = self._state_machines.get(session_id)
        if not plan or not sm:
            raise AudioError(f"No active workflow plan for session {session_id}", code="PLAN_NOT_FOUND")

        pending_requests = [
            req for req in self.workflow_executor.approval_requests.values()
            if req.workflow_id == plan.workflow_id and req.status == ApprovalStatus.PENDING
        ]
        if pending_requests:
            req = pending_requests[0]
            self.workflow_executor.approve_request(req.approval_id, by=approver, comment=comment)

        result = self.workflow_executor.execute(plan, sm=sm)
        self.repository.update_metadata(session_id, {"workflow_state": plan.state.value})
        self.repository.add_event(
            session_id=session_id,
            event_type="workflow.completed",
            payload={"final_state": plan.state.value, "executed_steps": result.executed_step_ids},
        )
        self.repository.transition(session_id, SessionState.COMPLETED, reason="Workflow executed to completion")
        return result

    def reject_and_cancel_workflow(
        self,
        session_id: str,
        rejector: str = "security-auditor@academia.ai",
        comment: str = "Disallowed operation",
    ) -> Any:
        """Reject pending consequential step and cancel workflow safely."""
        plan = self._active_plans.get(session_id)
        sm = self._state_machines.get(session_id)
        if not plan or not sm:
            raise AudioError(f"No active workflow plan for session {session_id}", code="PLAN_NOT_FOUND")

        pending_requests = [
            req for req in self.workflow_executor.approval_requests.values()
            if req.workflow_id == plan.workflow_id and req.status == ApprovalStatus.PENDING
        ]
        if pending_requests:
            req = pending_requests[0]
            self.workflow_executor.reject_request(req.approval_id, by=rejector, comment=comment)

        result = self.workflow_executor.execute(plan, sm=sm)
        self.repository.update_metadata(session_id, {"workflow_state": plan.state.value})
        self.repository.add_event(
            session_id=session_id,
            event_type="workflow.cancelled",
            payload={"final_state": plan.state.value, "reason": comment},
        )
        # On rejection, transition session to FAILED / terminal rejection state, NOT COMPLETED (Section 4)
        try:
            self.repository.transition(session_id, SessionState.FAILED, reason=f"Workflow rejected: {comment}")
        except Exception as exc:
            logger.warning("Could not transition session to FAILED: %s", exc)
        return result



    def cancel_workflow(
        self,
        session_id: str,
        reason: str = "user_cancelled",
    ) -> Any:
        """
        Cancel active workflow and pipeline safely without executing protected actions (Section 4).
        """
        pipeline = self._active_pipelines.get(session_id)
        if pipeline:
            pipeline.cancel(reason=reason)

        bridge = self._active_bridges.get(session_id)
        if bridge:
            bridge.reset()

        plan = self._active_plans.get(session_id)
        sm = self._state_machines.get(session_id)
        if plan:
            plan.state = WorkflowState.CANCELLED
            if sm and sm.can_transition_to(WorkflowState.CANCELLED):
                try:
                    sm.transition_to(WorkflowState.CANCELLED, reason=reason)
                except Exception:
                    pass
            self.repository.update_metadata(session_id, {"workflow_state": plan.state.value})

        self.repository.add_event(
            session_id=session_id,
            event_type="workflow.cancelled",
            payload={"session_id": session_id, "reason": reason},
        )
        try:
            self.repository.transition(session_id, SessionState.FAILED, reason=f"Cancelled: {reason}")
        except Exception:
            pass
        return True

    def cleanup_session(self, session_id: str, force: bool = False) -> bool:
        """
        Safely release and remove resources (pipeline, bridge, plan, state machine) for a session (Section 8).
        - Prevents accidental deletion of active/running sessions unless force=True.
        - Closes pipelines and flushes buffers to prevent memory leaks.
        - Safe and idempotent when called repeatedly.
        - Preserves persisted events and metadata in the session repository.
        """
        try:
            session = self.repository.get(session_id)
            if session.state in (SessionState.ACTIVE, SessionState.PAUSED) and not force:
                logger.warning("Refusing to cleanup active session %s without force=True", session_id)
                return False
        except Exception:
            pass

        pipeline = self._active_pipelines.pop(session_id, None)
        if pipeline is not None:
            try:
                pipeline.stop()
                pipeline.buffer.clear()
            except Exception as exc:
                logger.warning("Error stopping pipeline during cleanup of %s: %s", session_id, exc)

        bridge = self._active_bridges.pop(session_id, None)
        if bridge is not None:
            try:
                bridge.reset()
            except Exception as exc:
                logger.warning("Error resetting bridge during cleanup of %s: %s", session_id, exc)

        self._active_plans.pop(session_id, None)
        self._state_machines.pop(session_id, None)

        try:
            self.repository.add_event(
                session_id=session_id,
                event_type="audio.resources_cleaned",
                payload={"session_id": session_id, "cleaned_at": datetime.now(timezone.utc).isoformat()},
            )
        except Exception:
            pass
        return True

# Singleton manager instance
audio_backend_manager = AudioBackendSessionManager()
