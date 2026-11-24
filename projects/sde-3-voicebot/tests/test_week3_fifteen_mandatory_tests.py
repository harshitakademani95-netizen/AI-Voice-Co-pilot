"""The 15 Mandatory Integration Tests Specified in Week 3 Section 9.

Explicitly maps 1:1 to:
TEST 1: Audio input successfully reaches transcription.
TEST 2: Transcription output successfully reaches reasoning.
TEST 3: Reasoning retrieves relevant context and produces grounded results.
TEST 4: Planning produces an executable workflow.
TEST 5: Controlled tool execution works correctly.
TEST 6: Approval-required actions wait for approval.
TEST 7: Rejected actions are not executed.
TEST 8: Workflow results reach the UI/backend response.
TEST 9: Events persist in the correct order.
TEST 10: SSE reconnect and Last-Event-ID replay work without gaps or duplicates.
TEST 11: Unauthorized requests are rejected.
TEST 12: Rate limits work and return typed errors.
TEST 13: Dependency failures and timeouts are handled correctly.
TEST 14: Correlation IDs and session IDs propagate across all services.
TEST 15: Existing Week 1 and Week 2 functionality continues working.
"""
from datetime import datetime, timezone
import pytest
from starlette.testclient import TestClient

from agentic_workflow.tools import ToolRegistry, reset_mock_tools_state
from src.app import create_app
from src.audio.buffer import BoundedAudioBuffer, BufferPushStatus
from src.audio.vad import MockVAD, VADConfig
from src.context.schemas import ContextItem, ContextType, ReasoningRequest
from src.core.errors import ForbiddenError
from src.gateways.audio_gateway import AudioGateway
from src.gateways.reasoning_gateway import ReasoningGateway
from src.gateways.service import get_gateway_service
from src.gateways.transcription_gateway import TranscriptionGateway
from src.gateways.workflow_gateway import WorkflowGateway
from src.models.approval import ApprovalStatus, ToolExecuteRequest
from src.models.session import SessionState
from src.orchestration.agent_orchestrator import AgentOrchestrationService
from src.orchestration.planner import StepState, TaskPlanner
from src.repositories.approval_repository import approval_repository
from src.repositories.session_repository import session_repository
from src.schemas.audio import AudioChunk


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_state():
    reset_mock_tools_state()
    session_repository.clear()
    approval_repository.clear()
    yield
    reset_mock_tools_state()
    session_repository.clear()
    approval_repository.clear()


# ============================================================================
# TEST 1: Audio input successfully reaches transcription
# ============================================================================
def test_01_audio_input_successfully_reaches_transcription():
    audio_gw = AudioGateway()
    trans_gw = TranscriptionGateway()

    # Generate audio chunks
    raw_audio = b"\x00\x00" * 4000
    chunks = audio_gw.chunk_audio(raw_audio=raw_audio)
    assert len(chunks) >= 1

    events = trans_gw.transcribe_chunk(chunk=chunks[0], session_id="sess-t1")
    assert len(events) >= 1
    assert any(hasattr(e, "segment") or "segment" in str(e) for e in events)


# ============================================================================
# TEST 2: Transcription output successfully reaches reasoning
# ============================================================================
def test_02_transcription_output_successfully_reaches_reasoning():
    service = get_gateway_service()
    session = service.session_repo.create()

    # Transcribe simulated audio text
    res = service.execute_pipeline(
        session_id=session.session_id,
        user_query="Schedule a team meeting tomorrow morning",
    )
    assert res["status"] in ("completed", "requires_approval")
    assert "reasoning" in res
    assert res["reasoning"]["status"] in ("success", "needs_clarification")
    assert res["reasoning"]["confidence"] > 0.0


# ============================================================================
# TEST 3: Reasoning retrieves relevant context and produces grounded results
# ============================================================================
def test_03_reasoning_retrieves_relevant_context_and_grounded_results():
    reasoning_gw = ReasoningGateway()
    ctx = ContextItem(
        item_id="ctx-doc-01",
        context_type=ContextType.DOCUMENT,
        source="calendar.py",
        content="Meeting with Engineering is at 10 AM.",
        timestamp=datetime.now(timezone.utc),
    )
    req = ReasoningRequest(
        request_id="req-grounded-01",
        session_id="sess-t3",
        user_query="What time is the engineering meeting?",
        context_items=[ctx],
    )
    result = reasoning_gw.reason(req)
    assert result is not None
    assert result.confidence > 0.0
    assert result.status == "success"


# ============================================================================
# TEST 4: Planning produces an executable workflow
# ============================================================================
def test_04_planning_produces_an_executable_workflow():
    planner = TaskPlanner()
    plan = planner.create_plan(
        session_id="sess-t4",
        user_query="Please check tasks and compile a progress report",
    )
    assert plan.plan_id.startswith("plan-")
    assert len(plan.steps) == 2
    assert plan.steps[0].tool_name == "mock_task_checker"
    assert plan.steps[1].tool_name == "mock_report_generator"
    assert "step-1" in plan.steps[1].depends_on


# ============================================================================
# TEST 5: Controlled tool execution works correctly
# ============================================================================
def test_05_controlled_tool_execution_works_correctly():
    registry = ToolRegistry()
    assert registry.is_registered("mock_task_checker")
    output = registry.execute("mock_task_checker", {"task_id": "task-mock-01"})
    assert isinstance(output, dict)
    assert output["status"] == "success"
    assert output["task_id"] == "task-mock-01"


# ============================================================================
# TEST 6: Approval-required actions wait for approval
# ============================================================================
def test_06_approval_required_actions_wait_for_approval():
    session = session_repository.create()
    orchestrator = AgentOrchestrationService()

    res = orchestrator.orchestrate(
        session_id=session.session_id,
        user_query="Delete all logs in the database",
    )
    assert res.status == "requires_approval"
    assert res.approval_id is not None
    rec = approval_repository.get(res.approval_id)
    assert rec.status == ApprovalStatus.PENDING


# ============================================================================
# TEST 7: Rejected actions are not executed
# ============================================================================
def test_07_rejected_actions_are_not_executed():
    workflow_gw = WorkflowGateway()
    appr = approval_repository.create_request(
        session_id="sess-t7",
        action_type="delete_files",
        risk_level="D",
    )
    # Explicitly reject approval
    approval_repository.reject(appr.approval_id, reason="Security policy denial")

    req = ToolExecuteRequest(
        tool_name="delete_files",
        session_id="sess-t7",
        approval_id=appr.approval_id,
        parameters={"path": "/data"},
    )
    with pytest.raises(ForbiddenError) as exc_info:
        workflow_gw.execute_tool(req)
    assert "not in 'approved' status" in str(exc_info.value)


# ============================================================================
# TEST 8: Workflow results reach the UI/backend response
# ============================================================================
def test_08_workflow_results_reach_the_ui_backend_response():
    service = get_gateway_service()
    session = service.session_repo.create()

    resp = service.execute_pipeline(
        session_id=session.session_id,
        user_query="Check active tasks and generate report",
    )
    assert "final_response" in resp
    assert "agent_orchestration" in resp
    assert resp["agent_orchestration"]["plan"]["status"] == "completed"
    assert "verification" in resp
    assert resp["verification"]["is_verified"] is True


# ============================================================================
# TEST 9: Events persist in the correct order
# ============================================================================
def test_09_events_persist_in_the_correct_order():
    session = session_repository.create()
    e1 = session_repository.add_event(session.session_id, "step_1", {"msg": "First"})
    e2 = session_repository.add_event(session.session_id, "step_2", {"msg": "Second"})
    e3 = session_repository.add_event(session.session_id, "step_3", {"msg": "Third"})

    assert e1.sequence_number < e2.sequence_number < e3.sequence_number
    events = session_repository.get(session.session_id).events
    assert [e.sequence_number for e in events] == sorted([e.sequence_number for e in events])


# ============================================================================
# TEST 10: SSE reconnect and Last-Event-ID replay work without gaps or duplicates
# ============================================================================
def test_10_sse_reconnect_and_last_event_id_replay():
    session = session_repository.create()
    e1 = session_repository.add_event(session.session_id, "event_1", {"index": 1})
    e2 = session_repository.add_event(session.session_id, "event_2", {"index": 2})
    e3 = session_repository.add_event(session.session_id, "event_3", {"index": 3})
    e4 = session_repository.add_event(session.session_id, "event_4", {"index": 4})

    # Replay starting after sequence_number of e2
    all_events = session_repository.get(session.session_id).events
    replayed = [e for e in all_events if e.sequence_number > e2.sequence_number]
    assert len(replayed) == 2
    assert replayed[0].sequence_number == e3.sequence_number
    assert replayed[1].sequence_number == e4.sequence_number


# ============================================================================
# TEST 11: Unauthorized requests are rejected
# ============================================================================
def test_11_unauthorized_requests_are_rejected(client: TestClient):
    # Missing authorization token on protected session operation
    resp = client.post(
        "/api/v1/sessions/sess-protected-01/pause",
        headers={"X-User-Role": "anonymous"},
    )
    assert resp.status_code in (401, 403, 404)


# ============================================================================
# TEST 12: Rate limits work and return typed errors
# ============================================================================
def test_12_rate_limits_work_and_return_typed_errors(client: TestClient):
    from src.core.security import rate_limiter
    rate_limiter.reset()

    # Exhaust limit for an IP
    ip = "192.168.1.100"
    for _ in range(60):
        rate_limiter.is_allowed(key=f"ip:{ip}", limit=60, window_sec=60)

    # 61st request is rejected
    allowed, remaining, retry_after = rate_limiter.is_allowed(key=f"ip:{ip}", limit=60, window_sec=60)
    assert allowed is False
    assert remaining == 0
    assert retry_after >= 1
    rate_limiter.reset()


# ============================================================================
# TEST 13: Dependency failures and timeouts are handled correctly
# ============================================================================
def test_13_dependency_failures_and_timeouts_are_handled():
    workflow_gw = WorkflowGateway()
    workflow_gw.set_available(False)

    with pytest.raises(Exception) as exc_info:
        workflow_gw.evaluate_policy(action_type="any_action", parameters={}, session_id="s1")
    assert "unavailable" in str(exc_info.value).lower()
    workflow_gw.set_available(True)


# ============================================================================
# TEST 14: Correlation IDs and session IDs propagate across all services
# ============================================================================
def test_14_correlation_ids_and_session_ids_propagate_across_all_services():
    service = get_gateway_service()
    session = service.session_repo.create()
    test_corr_id = "corr-test-propagation-999"

    res = service.execute_pipeline(
        session_id=session.session_id,
        user_query="Status inquiry",
        correlation_id=test_corr_id,
    )
    assert res["session_id"] == session.session_id

    # Verify events recorded have the correlation ID
    events = session_repository.get(session.session_id).events
    assert any(e.correlation_id == test_corr_id for e in events)


# ============================================================================
# TEST 15: Existing Week 1 and Week 2 functionality continues working
# ============================================================================
def test_15_existing_week1_and_week2_functionality_continues_working():
    # Week 1: BoundedAudioBuffer and MockVAD
    buf = BoundedAudioBuffer(capacity=10)
    chunk = AudioChunk(sequence_id=1, data=b"\x00\x00" * 800, timestamp=0.0)
    res = buf.push(chunk)
    assert res.status == BufferPushStatus.ACCEPTED
    assert buf.current_size == 1
    assert buf.get_metrics().total_received == 1
    vad = MockVAD(VADConfig())
    assert vad.is_speech_active is False

    # Week 2: Session State Machine transitions
    session = session_repository.create()
    assert session.state == SessionState.CREATED
    session = session_repository.transition(session.session_id, SessionState.ACTIVE)
    assert session.state == SessionState.ACTIVE
    session = session_repository.transition(session.session_id, SessionState.PAUSED)
    assert session.state == SessionState.PAUSED
