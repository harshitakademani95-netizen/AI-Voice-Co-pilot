"""Comprehensive Automated Integration Tests for Week 3 Agentic Orchestration.

Covers:
- Phase 2: Agent Orchestration
- Phase 3: Task Planning & Multi-Step Execution
- Phase 4: Tool Registry & Tool Calling
- Phase 5: Retrieval & Context Management
- Phase 6: Result Verification (Preventing False Success)
- Phase 7: Full End-to-End Voice-to-UI Integration
- Phase 8: Approval & Permission Enforcement
"""
import pytest
from datetime import datetime, timezone

from agentic_workflow.tools import ToolRegistry, reset_mock_tools_state
from src.context.schemas import ContextItem, ContextType
from src.gateways.service import get_gateway_service
from src.orchestration.agent_orchestrator import AgentOrchestrationService
from src.orchestration.planner import StepState, TaskPlanner, TaskStep
from src.orchestration.retrieval import ContextRetrievalService
from src.orchestration.verifier import ResultVerifier
from src.repositories.approval_repository import approval_repository
from src.repositories.session_repository import session_repository


@pytest.fixture(autouse=True)
def reset_orchestration_state():
    reset_mock_tools_state()
    session_repository.clear()
    approval_repository.clear()
    yield
    reset_mock_tools_state()
    session_repository.clear()
    approval_repository.clear()


# ============================================================================
# PHASE 5: Retrieval and Context Management Tests
# ============================================================================

def test_context_retrieval_success_and_relevance():
    service = ContextRetrievalService()
    session_id = "sess-retrieval-1"

    item1 = ContextItem(
        item_id="ctx-1",
        context_type=ContextType.DOCUMENT,
        source="ide",
        content="Active file is backend/router.py with FastAPI setup.",
        timestamp=datetime.now(timezone.utc),
    )
    item2 = ContextItem(
        item_id="ctx-2",
        context_type=ContextType.CONVERSATION,
        source="chat",
        content="User previously requested status report for task backlog.",
        timestamp=datetime.now(timezone.utc),
    )
    service.add_context(session_id, item1)
    service.add_context(session_id, item2)

    # Relevant query matching item 2
    results = service.retrieve(session_id=session_id, query="status report")
    assert len(results) >= 1
    assert any("report" in str(r.content).lower() for r in results)


def test_context_retrieval_sanitizes_credentials():
    service = ContextRetrievalService()
    session_id = "sess-retrieval-secret"

    sensitive_item = ContextItem(
        item_id="ctx-secret",
        context_type=ContextType.DOCUMENT,
        source="env",
        content="Authorization header: Bearer secret_token_xyz123 and api_key=abc999",
        timestamp=datetime.now(timezone.utc),
    )
    service.add_context(session_id, sensitive_item)

    results = service.retrieve(session_id=session_id, query="Authorization header")
    assert len(results) == 1
    content_str = str(results[0].content)
    assert "secret_token_xyz123" not in content_str
    assert "[REDACTED_CREDENTIAL]" in content_str


def test_context_retrieval_empty_and_graceful_failure():
    service = ContextRetrievalService()
    empty_res = service.retrieve(session_id="non-existent", query="anything")
    assert empty_res == []


# ============================================================================
# PHASE 3: Task Planning and Multi-Step Execution Tests
# ============================================================================

def test_task_planner_multi_step_decomposition():
    planner = TaskPlanner()
    plan = planner.create_plan(
        session_id="sess-plan-1",
        user_query="Please check tasks and compile a progress report",
    )
    assert plan.plan_id.startswith("plan-")
    assert len(plan.steps) == 2
    assert plan.steps[0].tool_name == "mock_task_checker"
    assert plan.steps[1].tool_name == "mock_report_generator"
    assert "step-1" in plan.steps[1].depends_on


def test_task_planner_dependency_output_passing():
    planner = TaskPlanner()
    step2 = TaskStep(
        step_id="step-2",
        description="Compile report",
        tool_name="mock_report_generator",
        inputs={"title": "Report"},
        depends_on=["step-1"],
    )
    completed_outputs = {
        "step-1": {"status": "success", "task_id": "task-mock-01", "details": {"anomalies": 0}}
    }
    resolved = planner.resolve_inputs(step2, completed_outputs)
    assert "dependency_context" in resolved
    assert resolved["dependency_context"] == completed_outputs["step-1"]


# ============================================================================
# PHASE 4 & PHASE 6: Tool Execution and Result Verification Tests
# ============================================================================

def test_tool_registry_execution_via_agent():
    registry = ToolRegistry()
    assert registry.is_registered("mock_task_checker")
    res = registry.execute("mock_task_checker", {"task_id": "task-mock-01"})
    assert isinstance(res, dict)
    assert "status" in res
    assert "task_id" in res


def test_result_verifier_detects_valid_and_invalid_outputs():
    verifier = ResultVerifier()

    # Valid step
    valid_step = TaskStep(
        step_id="s1",
        description="Task check",
        tool_name="mock_task_checker",
        status=StepState.COMPLETED,
        output={"status": "success", "task_id": "task-mock-01", "task_status": "done"},
    )
    res_valid = verifier.verify_step_output(valid_step)
    assert res_valid.is_valid is True
    assert res_valid.status == "verified"

    # Invalid step (missing fields / error flag)
    invalid_step = TaskStep(
        step_id="s2",
        description="Task check",
        tool_name="mock_task_checker",
        status=StepState.COMPLETED,
        output={"error": "Database timeout", "is_error": True},
    )
    res_invalid = verifier.verify_step_output(invalid_step)
    assert res_invalid.is_valid is False
    assert len(res_invalid.issues) > 0


# ============================================================================
# PHASE 2 & PHASE 8: Agent Orchestration & Approval Gating Tests
# ============================================================================

def test_agent_orchestrator_executes_multistep_workflow():
    session = session_repository.create()
    orchestrator = AgentOrchestrationService()

    result = orchestrator.orchestrate(
        session_id=session.session_id,
        user_query="Check active tasks and generate progress report",
    )

    assert result.status == "completed"
    assert result.plan.status == "completed"
    assert len(result.plan.steps) == 2
    assert result.verification.is_verified is True
    assert result.verification.completed_steps == 2
    assert "successfully" in result.final_response.lower()

    # Check session events were recorded
    session_obj = session_repository.get(session.session_id)
    assert session_obj is not None
    event_types = [e.event_type for e in session_obj.events]
    assert "agent_plan_created" in event_types
    assert "agent_step_completed" in event_types


def test_agent_orchestrator_approval_gate_for_sensitive_action():
    session = session_repository.create()
    orchestrator = AgentOrchestrationService()

    result = orchestrator.orchestrate(
        session_id=session.session_id,
        user_query="Delete all log files in temporary folder",
    )

    assert result.status == "requires_approval"
    assert result.approval_id is not None
    assert result.plan.status == "requires_approval"
    assert any(s.status == StepState.AWAITING_APPROVAL for s in result.plan.steps)

    # Check approval record in repository
    appr_rec = approval_repository.get(result.approval_id)
    assert appr_rec is not None
    assert appr_rec.action_type in ("delete_files", "controlled_file_ops")


# ============================================================================
# PHASE 7: Full End-to-End Pipeline Integration (Audio -> UI Response)
# ============================================================================

def test_full_pipeline_with_agent_orchestration_and_verification():
    service = get_gateway_service()
    session = service.session_repo.create()

    res = service.execute_pipeline(
        session_id=session.session_id,
        user_query="Please check tasks and compile a status report",
        correlation_id="corr-voice-agent-e2e",
    )

    assert res["status"] == "completed"
    assert "agent_orchestration" in res
    assert "verification" in res
    assert "final_response" in res
    assert res["verification"]["is_verified"] is True
    assert len(res["agent_orchestration"]["plan"]["steps"]) == 2
    assert res["agent_orchestration"]["plan"]["status"] == "completed"
