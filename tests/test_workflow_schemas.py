"""
Tests for Workflow Schemas and Plan Validation using Pytest.

Covers:
- Valid workflow creation.
- Missing or invalid schema fields.
- Duplicate step IDs.
- Empty or malformed plans.
- Cycle and dependency validation.
- Schema serialization and Pydantic validation.
"""

import pytest
from pydantic import ValidationError

from agentic_workflow.schemas import (
    ApprovalRequest,
    ApprovalStatus,
    InvalidPlanError,
    RiskLevel,
    StepStatus,
    ToolSpec,
    WorkflowPlan,
    WorkflowResult,
    WorkflowState,
    WorkflowStep,
)


class TestWorkflowSchemas:
    """Test suite for typed workflow schemas."""

    def test_valid_toolspec_creation(self):
        spec = ToolSpec(
            name="mock_task_checker",
            description="Checks task status",
            input_requirements={"task_id": {"type": "string"}},
            is_consequential=False,
            risk_level=RiskLevel.INFORMATIONAL,
        )
        assert spec.name == "mock_task_checker"
        assert not spec.is_consequential
        assert spec.risk_level == RiskLevel.INFORMATIONAL
        assert "task_id" in spec.parameters

    def test_invalid_toolspec_missing_name(self):
        with pytest.raises(ValidationError):
            ToolSpec(name="", description="desc")

    def test_valid_workflow_step_creation(self):
        step = WorkflowStep(
            step_id="step-01",
            name="Inspect Task Status",
            tool_name="mock_task_checker",
            inputs={"task_id": "task-audit-101"},
            is_consequential=False,
        )
        assert step.step_id == "step-01"
        assert step.tool_name == "mock_task_checker"
        assert step.status == StepStatus.PENDING
        assert step.output is None

    def test_invalid_step_missing_or_empty_fields(self):
        with pytest.raises(ValidationError):
            WorkflowStep(step_id="", name="Valid", tool_name="mock_task_checker")

        with pytest.raises(ValidationError):
            WorkflowStep(step_id="s1", name="", tool_name="mock_task_checker")

        with pytest.raises(ValidationError):
            WorkflowStep(step_id="s1", name="Valid", tool_name="")

    def test_valid_workflow_plan_creation(self):
        step1 = WorkflowStep(
            step_id="step-01",
            name="Check Task",
            tool_name="mock_task_checker",
            inputs={"task_id": "task-audit-101"},
        )
        step2 = WorkflowStep(
            step_id="step-02",
            name="Generate Report",
            tool_name="mock_report_generator",
            inputs={"title": "Audit Summary"},
            dependencies=["step-01"],
            is_consequential=True,
        )
        plan = WorkflowPlan(
            workflow_id="plan-valid-01",
            description="Standard two-step workflow",
            steps=[step1, step2],
        )
        assert plan.workflow_id == "plan-valid-01"
        assert plan.state == WorkflowState.DRAFT
        assert len(plan.steps) == 2
        d = plan.to_dict()
        assert d["workflow_id"] == "plan-valid-01"
        assert len(d["steps"]) == 2

    def test_empty_plan_rejected(self):
        with pytest.raises(ValidationError):
            WorkflowPlan(workflow_id="plan-empty", description="No steps", steps=[])

    def test_plan_with_duplicate_step_ids_rejected(self):
        step1 = WorkflowStep(
            step_id="step-dup",
            name="Check Task",
            tool_name="mock_task_checker",
            inputs={"task_id": "1"},
        )
        step2 = WorkflowStep(
            step_id="step-dup",
            name="Check Task Again",
            tool_name="mock_task_checker",
            inputs={"task_id": "2"},
        )
        with pytest.raises(InvalidPlanError) as exc_info:
            WorkflowPlan(
                workflow_id="plan-dup",
                description="Duplicate step ids",
                steps=[step1, step2],
            )
        assert "Duplicate step_id found" in str(exc_info.value)

    def test_plan_with_unknown_dependency_rejected(self):
        step1 = WorkflowStep(
            step_id="step-01",
            name="Step 1",
            tool_name="mock_task_checker",
            dependencies=["nonexistent-step-id"],
        )
        with pytest.raises(InvalidPlanError) as exc_info:
            WorkflowPlan(
                workflow_id="plan-bad-dep",
                description="Invalid dep",
                steps=[step1],
            )
        assert "unknown dependency" in str(exc_info.value)

    def test_plan_with_self_dependency_rejected(self):
        step1 = WorkflowStep(
            step_id="step-self",
            name="Self dependent step",
            tool_name="mock_task_checker",
            dependencies=["step-self"],
        )
        with pytest.raises(InvalidPlanError) as exc_info:
            WorkflowPlan(
                workflow_id="plan-self-dep",
                description="Self dep",
                steps=[step1],
            )
        assert "cannot depend on itself" in str(exc_info.value)

    def test_plan_with_cyclic_dependency_rejected(self):
        step1 = WorkflowStep(
            step_id="step-a",
            name="Step A",
            tool_name="mock_task_checker",
            dependencies=["step-b"],
        )
        step2 = WorkflowStep(
            step_id="step-b",
            name="Step B",
            tool_name="mock_task_checker",
            dependencies=["step-a"],
        )
        with pytest.raises(InvalidPlanError) as exc_info:
            WorkflowPlan(
                workflow_id="plan-cycle",
                description="Cyclic plan",
                steps=[step1, step2],
            )
        assert (
            "Cyclic dependency detected" in str(exc_info.value)
            or "dependencies must appear earlier in the step list" in str(exc_info.value)
        )

    def test_dependency_must_appear_earlier_in_step_list(self):
        """Requirement: dependencies must appear earlier in the step list."""
        step1 = WorkflowStep(
            step_id="step-01",
            name="First Step",
            tool_name="mock_task_checker",
            dependencies=["step-02"],  # step-02 is defined later!
        )
        step2 = WorkflowStep(
            step_id="step-02",
            name="Second Step",
            tool_name="mock_task_checker",
        )
        with pytest.raises(InvalidPlanError) as exc_info:
            WorkflowPlan(
                workflow_id="plan-forward-dep",
                description="Forward dependency rejected",
                steps=[step1, step2],
            )
        assert "dependencies must appear earlier in the step list" in str(exc_info.value)

    def test_extra_fields_forbidden_on_all_schemas(self):
        """Requirement: model_config extra='forbid' on all five schemas."""
        with pytest.raises(ValidationError):
            ToolSpec(name="tool", description="desc", forbidden_extra="not_allowed")

        with pytest.raises(ValidationError):
            WorkflowStep(step_id="s1", name="step", tool_name="tool", forbidden_field=123)

        with pytest.raises(ValidationError):
            ApprovalRequest(
                workflow_id="wf-1",
                step_id="s1",
                tool_name="tool",
                reason="test",
                extra_param="forbidden"
            )

        with pytest.raises(ValidationError):
            WorkflowPlan(
                workflow_id="p1",
                steps=[WorkflowStep(step_id="s1", name="step", tool_name="tool")],
                illegal_extra=True
            )

        with pytest.raises(ValidationError):
            WorkflowResult(
                workflow_id="wf-1",
                final_state=WorkflowState.SUCCEEDED,
                unexpected_extra_key="forbidden"
            )

    def test_missing_required_fields_raise_validation_error(self):
        """Requirement: Missing required fields on WorkflowPlan, WorkflowStep, ApprovalRequest raise ValidationError."""
        # Missing tool_name on WorkflowStep
        with pytest.raises(ValidationError):
            WorkflowStep(step_id="s1", name="name")  # type: ignore

        # Missing workflow_id on WorkflowPlan
        with pytest.raises(ValidationError):
            WorkflowPlan(steps=[WorkflowStep(step_id="s1", name="name", tool_name="tool")])  # type: ignore

        # Missing reason on ApprovalRequest
        with pytest.raises(ValidationError):
            ApprovalRequest(workflow_id="wf-1", step_id="s1", tool_name="tool")  # type: ignore

    def test_approval_request_lifecycle(self):
        req = ApprovalRequest(
            approval_id="appr-101",
            workflow_id="wf-1",
            step_id="step-02",
            tool_name="mock_report_generator",
            inputs={"title": "Report Title"},
            reason="Sensitive report generation",
            risk_level=RiskLevel.SENSITIVE,
        )
        assert req.status == ApprovalStatus.PENDING
        assert req.resolved_at is None
        assert not req.is_consumed

        req.approve(by="Suhani A (SDE 3)", comment="Approved by Lead")
        assert req.status == ApprovalStatus.APPROVED
        assert req.decided_by == "Suhani A (SDE 3)"
        assert req.approved_by == "Suhani A (SDE 3)"
        assert req.decision_details == "Approved by Lead"
        assert req.resolved_at is not None

        req.consume()
        assert req.is_consumed

        req_reject = ApprovalRequest(
            approval_id="appr-102",
            workflow_id="wf-1",
            step_id="step-03",
            tool_name="mock_report_generator",
            reason="High risk",
        )
        req_reject.reject(by="Security Auditor", comment="Security risk")
        assert req_reject.status == ApprovalStatus.REJECTED
        assert req_reject.decided_by == "Security Auditor"
        assert req_reject.decision_details == "Security risk"

    def test_workflow_result_structure(self):
        res = WorkflowResult(
            workflow_id="wf-001",
            final_state=WorkflowState.SUCCEEDED,
            executed_step_ids=["step-01"],
            step_outputs={"step-01": {"status": "success"}},
            summary="Completed successfully.",
        )
        d = res.to_dict()
        assert d["workflow_id"] == "wf-001"
        assert d["final_state"] == "succeeded"
        assert d["executed_step_ids"] == ["step-01"]
        assert d["step_outputs"]["step-01"]["status"] == "success"
