"""
Tests for Workflow Executor, Mock Tools, and Safety Gates using Pytest.

Covers:
- Exactly two harmless mock tools registered (mock_task_checker, mock_report_generator).
- Rejection of unknown tools and external execution.
- Successful execution of both mock tools.
- Correct execution order and dependency enforcement.
- Approval-required actions remaining blocked until approval.
- Denied approvals preventing execution.
- Handling of execution errors.
- Final WorkflowResult correctness and audit integrity.
"""

import pytest

from agentic_workflow.schemas import (
    ApprovalRequest,
    ApprovalStatus,
    InvalidPlanError,
    RiskLevel,
    StepStatus,
    WorkflowPlan,
    WorkflowState,
    WorkflowStep,
)
from agentic_workflow.state_machine import WorkflowStateMachine
from agentic_workflow.tools import (
    ToolExecutionError,
    ToolRegistry,
    _MOCK_GENERATED_REPORTS,
    reset_mock_tools_state,
)
from agentic_workflow.executor import WorkflowExecutor


class TestExecutorAndMockTools:
    """Test suite validating mock execution, tool safety, and executor logic."""

    @pytest.fixture(autouse=True)
    def setup_state(self):
        reset_mock_tools_state()
        self.registry = ToolRegistry()
        self.executor = WorkflowExecutor(self.registry)

    def test_registry_contains_exactly_two_harmless_mock_tools(self):
        """Acceptance criteria: Exactly two harmless mock tools exist."""
        available = self.registry.available_tools
        assert len(available) == 2
        assert "mock_task_checker" in available
        assert "mock_report_generator" in available

        # Tool 1: Mock Task Checker (informational, non-consequential)
        assert not available["mock_task_checker"].is_consequential
        assert available["mock_task_checker"].risk_level == RiskLevel.INFORMATIONAL

        # Tool 2: Mock Report Generator (consequential, sensitive)
        assert available["mock_report_generator"].is_consequential
        assert available["mock_report_generator"].risk_level == RiskLevel.SENSITIVE

    def test_registry_rejects_unauthorized_external_or_system_tools(self):
        """Acceptance criteria: No real external actions or unrestricted computer control."""
        for unauthorized in ["execute_shell", "send_email", "delete_file", "control_mouse", "run_bash"]:
            assert not self.registry.is_registered(unauthorized)
            with pytest.raises(ToolExecutionError) as exc_info:
                self.registry.execute(unauthorized, {})
            assert "Security violation" in str(exc_info.value)

    def test_plan_with_unknown_tool_is_rejected(self):
        """Requirement: Unknown tool rejection with clear error message."""
        step = WorkflowStep(
            step_id="step-bad",
            name="Run foreign command",
            tool_name="unknown_external_tool",
            inputs={"cmd": "ls"},
        )
        plan = WorkflowPlan(
            workflow_id="plan-bad-tool",
            description="Unauthorized plan",
            steps=[step],
        )
        with pytest.raises(InvalidPlanError) as exc_info:
            self.executor.execute(plan)
        assert "Unknown tool rejected" in str(exc_info.value)

    def test_successful_execution_of_mock_task_checker(self):
        """Requirement: Successful execution of mock task checker (harmless, no approval needed)."""
        step = WorkflowStep(
            step_id="step-task-01",
            name="Inspect Audit Task",
            tool_name="mock_task_checker",
            inputs={"task_id": "task-audit-101"},
            is_consequential=False,
        )
        plan = WorkflowPlan(
            workflow_id="plan-task-check",
            description="Inspect audit task",
            steps=[step],
        )

        sm = WorkflowStateMachine(initial_state=plan.state)
        result = self.executor.execute(plan, sm)

        assert result.final_state == WorkflowState.SUCCEEDED
        assert step.status == StepStatus.COMPLETED
        assert "step-task-01" in result.executed_step_ids
        output = result.step_outputs["step-task-01"]
        assert output["status"] == "success"
        assert output["task_id"] == "task-audit-101"
        assert output["task_status"] == "completed"
        assert output["simulated"] is True
        assert len(result.approval_requests) == 0

    def test_consequential_report_generator_defaults_to_awaiting_approval(self):
        """
        Requirement: Consequential actions must default to awaiting approval
        and remain blocked until approval.
        """
        step = WorkflowStep(
            step_id="step-report-01",
            name="Generate Executive Audit Report",
            tool_name="mock_report_generator",
            inputs={"title": "Quarterly Audit Report"},
            is_consequential=True,
        )
        plan = WorkflowPlan(
            workflow_id="plan-report",
            description="Generate simulated report",
            steps=[step],
        )

        sm = WorkflowStateMachine(initial_state=plan.state)
        result = self.executor.execute(plan, sm)

        # Must halt at AWAITING_APPROVAL
        assert result.final_state == WorkflowState.AWAITING_APPROVAL
        assert step.status == StepStatus.AWAITING_APPROVAL
        assert len(result.executed_step_ids) == 0
        assert len(result.approval_requests) == 1

        req = result.approval_requests[0]
        assert req.status == ApprovalStatus.PENDING
        assert req.step_id == "step-report-01"
        assert req.tool_name == "mock_report_generator"
        assert req.risk_level == RiskLevel.SENSITIVE

        # Invariant: report must NOT have been generated yet
        assert len(_MOCK_GENERATED_REPORTS) == 0

    def test_consequential_action_executes_after_explicit_approval(self):
        """Requirement: Explicit approval unblocks execution and completes successfully."""
        step = WorkflowStep(
            step_id="step-rep",
            name="Publish Metrics Report",
            tool_name="mock_report_generator",
            inputs={"title": "Vulnerability Scan Report"},
            is_consequential=True,
        )
        plan = WorkflowPlan(
            workflow_id="plan-approved-report",
            description="Approved report plan",
            steps=[step],
        )

        sm = WorkflowStateMachine(initial_state=plan.state)
        # Phase 1: Pauses for approval
        self.executor.execute(plan, sm)
        assert sm.current_state == WorkflowState.AWAITING_APPROVAL

        # Retrieve pending approval request
        req = self.executor.get_approval_request_for_step(plan.workflow_id, "step-rep")
        assert req is not None

        # Phase 2: Explicit human approval
        self.executor.approve_request(req.approval_id, comment="Approved by Suhani A (SDE 3)")
        assert req.status == ApprovalStatus.APPROVED

        # Phase 3: Resume execution
        resume_result = self.executor.execute(plan, sm)
        assert resume_result.final_state == WorkflowState.SUCCEEDED
        assert step.status == StepStatus.COMPLETED
        assert "step-rep" in resume_result.executed_step_ids
        assert len(_MOCK_GENERATED_REPORTS) == 1

    def test_denied_approval_prevents_execution_and_cancels_workflow(self):
        """Requirement: Denied approvals prevent execution."""
        step = WorkflowStep(
            step_id="step-deny",
            name="Generate Unauthorized Report",
            tool_name="mock_report_generator",
            inputs={"title": "Confidential Report"},
            is_consequential=True,
        )
        plan = WorkflowPlan(
            workflow_id="plan-denied-report",
            description="Denied action plan",
            steps=[step],
        )

        sm = WorkflowStateMachine(initial_state=plan.state)
        self.executor.execute(plan, sm)
        assert sm.current_state == WorkflowState.AWAITING_APPROVAL

        req = self.executor.get_approval_request_for_step(plan.workflow_id, "step-deny")
        assert req is not None

        # Deny approval
        self.executor.reject_request(req.approval_id, comment="Security policy denial")
        assert req.status == ApprovalStatus.REJECTED

        # Resume execution
        result = self.executor.execute(plan, sm)
        assert result.final_state == WorkflowState.CANCELLED
        assert step.status == StepStatus.CANCELLED
        assert len(result.executed_step_ids) == 0
        # Invariant: Action was never executed
        assert len(_MOCK_GENERATED_REPORTS) == 0

    def test_correct_execution_order_and_multi_step_flow(self):
        """
        Requirement: Correct execution order across both mock tools.
        Step 1: mock_task_checker runs first.
        Step 2: mock_report_generator pauses for approval.
        Upon approval, step 2 completes.
        """
        step1 = WorkflowStep(
            step_id="s1",
            name="Check Dependency Scan",
            tool_name="mock_task_checker",
            inputs={"task_id": "task-sync-202"},
            is_consequential=False,
        )
        step2 = WorkflowStep(
            step_id="s2",
            name="Generate Dependency Report",
            tool_name="mock_report_generator",
            inputs={"title": "Dependency Report"},
            dependencies=["s1"],
            is_consequential=True,
        )
        plan = WorkflowPlan(
            workflow_id="plan-multi-slice",
            description="End to end vertical slice",
            steps=[step1, step2],
        )

        sm = WorkflowStateMachine(initial_state=plan.state)

        # 1st run: step 1 completes, step 2 pauses
        res1 = self.executor.execute(plan, sm)
        assert res1.final_state == WorkflowState.AWAITING_APPROVAL
        assert step1.status == StepStatus.COMPLETED
        assert step2.status == StepStatus.AWAITING_APPROVAL
        assert res1.executed_step_ids == ["s1"]

        # Approve step 2
        req = self.executor.get_approval_request_for_step(plan.workflow_id, "s2")
        self.executor.approve_request(req.approval_id, comment="Approved generation")

        # 2nd run: resumes and finishes step 2
        res2 = self.executor.execute(plan, sm)
        assert res2.final_state == WorkflowState.SUCCEEDED
        assert step2.status == StepStatus.COMPLETED
        assert res2.executed_step_ids == ["s1", "s2"]
        assert "s1" in res2.step_outputs
        assert "s2" in res2.step_outputs

    def test_correct_handling_of_execution_errors(self):
        """Requirement: Correct handling of execution errors."""
        step = WorkflowStep(
            step_id="step-err",
            name="Call with Invalid Parameters",
            tool_name="mock_task_checker",
            inputs={},  # Missing required 'task_id'
            is_consequential=False,
        )
        plan = WorkflowPlan(
            workflow_id="plan-err",
            description="Plan causing execution error",
            steps=[step],
        )

        sm = WorkflowStateMachine(initial_state=plan.state)
        result = self.executor.execute(plan, sm)

        assert result.final_state == WorkflowState.FAILED
        assert step.status == StepStatus.FAILED
        assert "task_id" in (step.error or "")

    def test_final_workflow_result_correctness(self):
        """Requirement: Final WorkflowResult correctness and audit integrity."""
        step = WorkflowStep(
            step_id="step-audit",
            name="Task Check",
            tool_name="mock_task_checker",
            inputs={"task_id": "task-audit-101"},
            is_consequential=False,
        )
        plan = WorkflowPlan(
            workflow_id="plan-audit-res",
            description="Audit plan",
            steps=[step],
        )
        sm = WorkflowStateMachine(initial_state=plan.state)
        result = self.executor.execute(plan, sm)

        assert result.workflow_id == "plan-audit-res"
        assert result.final_state == WorkflowState.SUCCEEDED
        assert result.start_time is not None
        assert result.end_time is not None
        assert "step-audit" in result.step_outputs
        assert "Workflow completed successfully" in result.summary

    def test_unapproved_action_remains_blocked_on_repeated_resume(self):
        """Proves that calling execute repeatedly while approval is pending never runs the consequential tool."""
        step = WorkflowStep(
            step_id="step-repeat",
            name="Blocked Consequential Report",
            tool_name="mock_report_generator",
            inputs={"title": "Pending Report"},
            is_consequential=True,
        )
        plan = WorkflowPlan(
            workflow_id="plan-repeat-block",
            description="Repeated resume test",
            steps=[step],
        )
        sm = WorkflowStateMachine(initial_state=plan.state)

        # First run triggers gate
        res1 = self.executor.execute(plan, sm)
        assert res1.final_state == WorkflowState.AWAITING_APPROVAL
        assert len(res1.executed_step_ids) == 0
        assert len(_MOCK_GENERATED_REPORTS) == 0

        # Second attempt without approval
        res2 = self.executor.execute(plan, sm)
        assert res2.final_state == WorkflowState.AWAITING_APPROVAL
        assert len(res2.executed_step_ids) == 0
        assert len(_MOCK_GENERATED_REPORTS) == 0

        # Third attempt without approval
        res3 = self.executor.execute(plan, sm)
        assert res3.final_state == WorkflowState.AWAITING_APPROVAL
        assert len(res3.executed_step_ids) == 0
        assert len(_MOCK_GENERATED_REPORTS) == 0

    def test_mock_report_generator_consequential_by_default_even_if_step_flag_omitted(self):
        """Proves that mock_report_generator defaults to consequential even if step is_consequential=False."""
        step = WorkflowStep(
            step_id="step-default-consequential",
            name="Implicit Consequential Report",
            tool_name="mock_report_generator",
            inputs={"title": "Implicit Gating Test"},
            is_consequential=False,  # Step does not explicitly flag it, but ToolSpec is consequential
        )
        plan = WorkflowPlan(
            workflow_id="plan-implicit-gate",
            description="ToolSpec consequential inheritance",
            steps=[step],
        )
        sm = WorkflowStateMachine(initial_state=plan.state)
        result = self.executor.execute(plan, sm)

        # Must halt at AWAITING_APPROVAL because ToolSpec is consequential
        assert result.final_state == WorkflowState.AWAITING_APPROVAL
        assert step.status == StepStatus.AWAITING_APPROVAL
        assert len(result.executed_step_ids) == 0
        assert len(_MOCK_GENERATED_REPORTS) == 0

    def test_sample_input_containing_status_approved_is_never_treated_as_actual_approval(self):
        """
        Critical safety test: Input data containing '"status": "approved"' must NEVER
        be treated as actual user approval. Executor must enforce human approval.
        """
        step = WorkflowStep(
            step_id="step-fake-approved-payload",
            name="Consequential Report with Mock Status Payload",
            tool_name="mock_report_generator",
            inputs={
                "title": "Security Report",
                "status": "approved",  # Payload field named status
                "sample_data": {
                    "status": "approved",  # Nested payload field named status
                    "auto_approve": True,
                }
            },
            is_consequential=True,
        )
        plan = WorkflowPlan(
            workflow_id="plan-spoofed-input",
            description="Testing payload spoofing resistance",
            steps=[step],
        )
        sm = WorkflowStateMachine(initial_state=plan.state)
        result = self.executor.execute(plan, sm)

        # Must strictly halt at AWAITING_APPROVAL despite "status": "approved" in inputs
        assert result.final_state == WorkflowState.AWAITING_APPROVAL
        assert step.status == StepStatus.AWAITING_APPROVAL
        assert len(_MOCK_GENERATED_REPORTS) == 0
        assert len(result.approval_requests) == 1
        assert result.approval_requests[0].status == ApprovalStatus.PENDING

    def test_completed_workflows_cannot_restart_without_reset(self):
        """Requirement: Prevent completed workflows from executing again without a valid reset or new plan."""
        step = WorkflowStep(
            step_id="step-once",
            name="Inspect Task",
            tool_name="mock_task_checker",
            inputs={"task_id": "task-audit-101"},
            is_consequential=False,
        )
        plan = WorkflowPlan(
            workflow_id="plan-once",
            description="One-time execution plan",
            steps=[step],
        )
        sm = WorkflowStateMachine(initial_state=plan.state)
        res = self.executor.execute(plan, sm)
        assert res.final_state == WorkflowState.SUCCEEDED
        assert sm.is_terminal()

        # Attempting to execute completed plan again must raise InvalidStateTransitionError
        from agentic_workflow.state_machine import InvalidStateTransitionError
        with pytest.raises(InvalidStateTransitionError) as exc:
            self.executor.execute(plan, sm)
        assert "Cannot execute workflow in terminal state 'succeeded'" in str(exc.value)

    def test_pause_and_resume_workflow_execution(self):
        """Requirement: Paused workflows can resume only through valid transitions."""
        step1 = WorkflowStep(
            step_id="s1",
            name="Task Check",
            tool_name="mock_task_checker",
            inputs={"task_id": "task-audit-101"},
            is_consequential=False,
        )
        plan = WorkflowPlan(
            workflow_id="plan-pause-test",
            description="Testing pause and resume",
            steps=[step1],
        )
        sm = WorkflowStateMachine(initial_state=plan.state)
        # Transition to running then pause
        sm.transition_to(WorkflowState.RUNNING)
        plan.state = WorkflowState.RUNNING
        pause_res = self.executor.pause(plan, sm)
        assert pause_res.final_state == WorkflowState.PAUSED
        assert sm.current_state == WorkflowState.PAUSED

        # Resuming executes the step to succeeded
        resume_res = self.executor.execute(plan, sm)
        assert resume_res.final_state == WorkflowState.SUCCEEDED
        assert sm.current_state == WorkflowState.SUCCEEDED
        assert "s1" in resume_res.executed_step_ids

    def test_regression_stale_approval_reuse_prevented_across_runs(self):
        """
        Fix 1 CRITICAL Regression Test:
        Approve and complete a workflow, then re-run a NEW plan with the same
        workflow_id and step_ids on the same executor; it must return awaiting_approval
        and must NOT run the report generator without new approval.
        """
        # Run 1: Create, approve, and execute
        step1 = WorkflowStep(
            step_id="step-rep",
            name="Generate Report Run 1",
            tool_name="mock_report_generator",
            inputs={"title": "Run 1 Report"},
            is_consequential=True,
        )
        plan1 = WorkflowPlan(
            workflow_id="plan-reuse-check",
            description="Run 1 Plan",
            steps=[step1],
        )
        sm1 = WorkflowStateMachine(initial_state=plan1.state)
        res1 = self.executor.execute(plan1, sm1)
        assert res1.final_state == WorkflowState.AWAITING_APPROVAL

        # Approve and execute Run 1
        req1 = self.executor.get_approval_request_for_step(plan1.workflow_id, "step-rep", run_id=plan1.run_id)
        self.executor.approve_request(req1.approval_id, by="Auditor", comment="Approved Run 1")
        res1_final = self.executor.execute(plan1, sm1)
        assert res1_final.final_state == WorkflowState.SUCCEEDED
        assert req1.is_consumed is True
        assert len(_MOCK_GENERATED_REPORTS) == 1

        # Run 2: NEW plan with the exact same workflow_id and step_id on the SAME executor
        step2 = WorkflowStep(
            step_id="step-rep",
            name="Generate Report Run 2",
            tool_name="mock_report_generator",
            inputs={"title": "Run 2 Report"},
            is_consequential=True,
        )
        plan2 = WorkflowPlan(
            workflow_id="plan-reuse-check",
            description="Run 2 Plan with same IDs",
            steps=[step2],
        )
        sm2 = WorkflowStateMachine(initial_state=plan2.state)

        # Executing Run 2 MUST STOP at AWAITING_APPROVAL and NOT reuse Run 1's consumed approval
        res2 = self.executor.execute(plan2, sm2)
        assert res2.final_state == WorkflowState.AWAITING_APPROVAL
        assert step2.status == StepStatus.AWAITING_APPROVAL
        assert len(res2.executed_step_ids) == 0
        # Reports count must still be 1 (Run 2's report was NOT generated!)
        assert len(_MOCK_GENERATED_REPORTS) == 1

    def test_regression_rejected_workflow_then_new_plan_can_be_approved(self):
        """
        Fix 1 CRITICAL Regression Test:
        Reject a workflow, then run a new plan with the same IDs;
        approving the new request must succeed and not be blocked by the old rejection.
        """
        # Run 1: Rejected
        step1 = WorkflowStep(
            step_id="step-rep",
            name="Run 1 Report",
            tool_name="mock_report_generator",
            inputs={"title": "Report 1"},
            is_consequential=True,
        )
        plan1 = WorkflowPlan(
            workflow_id="plan-reject-reuse",
            description="Run 1 Plan",
            steps=[step1],
        )
        sm1 = WorkflowStateMachine(initial_state=plan1.state)
        self.executor.execute(plan1, sm1)
        req1 = self.executor.get_approval_request_for_step(plan1.workflow_id, "step-rep", run_id=plan1.run_id)
        self.executor.reject_request(req1.approval_id, by="Auditor", comment="Rejected Run 1")
        res1 = self.executor.execute(plan1, sm1)
        assert res1.final_state == WorkflowState.CANCELLED

        # Run 2: New plan instance with same IDs
        step2 = WorkflowStep(
            step_id="step-rep",
            name="Run 2 Report",
            tool_name="mock_report_generator",
            inputs={"title": "Report 2"},
            is_consequential=True,
        )
        plan2 = WorkflowPlan(
            workflow_id="plan-reject-reuse",
            description="Run 2 Plan",
            steps=[step2],
        )
        sm2 = WorkflowStateMachine(initial_state=plan2.state)
        res2 = self.executor.execute(plan2, sm2)
        assert res2.final_state == WorkflowState.AWAITING_APPROVAL

        # Retrieve Run 2 request (most recent, bound to plan2.run_id)
        req2 = self.executor.get_approval_request_for_step(plan2.workflow_id, "step-rep", run_id=plan2.run_id)
        assert req2.approval_id != req1.approval_id
        assert req2.status == ApprovalStatus.PENDING

        # Approve Run 2
        self.executor.approve_request(req2.approval_id, by="Lead", comment="Approved Run 2")
        res2_final = self.executor.execute(plan2, sm2)
        assert res2_final.final_state == WorkflowState.SUCCEEDED
        assert step2.status == StepStatus.COMPLETED

    def test_approval_cannot_be_used_twice(self):
        """Requirement: An approval cannot be used twice."""
        req = ApprovalRequest(
            approval_id="appr-consume-test",
            workflow_id="wf-test",
            step_id="s1",
            tool_name="mock_report_generator",
            inputs={"title": "Test"},
            reason="Test",
        )
        req.approve(by="Tester")
        assert not req.is_consumed
        req.consume()
        assert req.is_consumed

    def test_unknown_approval_id_and_double_resolving_raise_errors(self):
        """Requirement: Approving an unknown ID and double-resolving raise proper KeyError/ValueError."""
        # Unknown ID
        with pytest.raises(KeyError) as exc:
            self.executor.approve_request("unknown-id-12345")
        assert "not found" in str(exc.value)

        with pytest.raises(KeyError):
            self.executor.reject_request("unknown-id-12345")

        # Create valid request
        step = WorkflowStep(
            step_id="s1",
            name="Step",
            tool_name="mock_report_generator",
            inputs={"title": "Double Resolve"},
            is_consequential=True,
        )
        plan = WorkflowPlan(workflow_id="wf-double", steps=[step])
        req = self.executor.create_approval_request(plan, step)

        # First approval works
        self.executor.approve_request(req.approval_id, by="Lead")

        # Double resolving must raise ValueError
        with pytest.raises(ValueError) as val_exc:
            self.executor.approve_request(req.approval_id, by="Lead Again")
        assert "already been resolved" in str(val_exc.value)

        with pytest.raises(ValueError) as val_exc2:
            self.executor.reject_request(req.approval_id)
        assert "already been resolved" in str(val_exc2.value)

    def test_consequential_step_as_first_step(self):
        """Requirement: Consequential step as first step pauses in awaiting_approval immediately from draft."""
        step = WorkflowStep(
            step_id="step-first-consequential",
            name="First Step Consequential",
            tool_name="mock_report_generator",
            inputs={"title": "First Report"},
            is_consequential=True,
        )
        plan = WorkflowPlan(
            workflow_id="plan-first-gate",
            description="First step is consequential",
            steps=[step],
        )
        sm = WorkflowStateMachine(initial_state=plan.state)
        result = self.executor.execute(plan, sm)

        assert result.final_state == WorkflowState.AWAITING_APPROVAL
        assert step.status == StepStatus.AWAITING_APPROVAL
        assert len(result.executed_step_ids) == 0

    def test_mid_workflow_failure_with_earlier_steps_completed(self):
        """Requirement: Mid-workflow failure preserves earlier completed step outputs and sets FAILED."""
        step1 = WorkflowStep(
            step_id="s1",
            name="Step 1 Success",
            tool_name="mock_task_checker",
            inputs={"task_id": "task-audit-101"},
            is_consequential=False,
        )
        step2 = WorkflowStep(
            step_id="s2",
            name="Step 2 Failure",
            tool_name="mock_task_checker",
            inputs={},  # Missing task_id causes failure
            dependencies=["s1"],
            is_consequential=False,
        )
        plan = WorkflowPlan(
            workflow_id="plan-mid-fail",
            description="Failing mid-workflow",
            steps=[step1, step2],
        )
        sm = WorkflowStateMachine(initial_state=plan.state)
        result = self.executor.execute(plan, sm)

        assert result.final_state == WorkflowState.FAILED
        assert step1.status == StepStatus.COMPLETED
        assert step2.status == StepStatus.FAILED
        assert result.executed_step_ids == ["s1"]
        assert "s1" in result.step_outputs
        assert result.error is not None

    def test_dependency_failure_path(self):
        """Requirement: If dependency fails, subsequent dependent step is failed."""
        step1 = WorkflowStep(
            step_id="s1",
            name="Step 1 Failing",
            tool_name="mock_task_checker",
            inputs={},  # Missing task_id
            is_consequential=False,
        )
        step2 = WorkflowStep(
            step_id="s2",
            name="Step 2 Dependent",
            tool_name="mock_task_checker",
            inputs={"task_id": "task-audit-101"},
            dependencies=["s1"],
            is_consequential=False,
        )
        plan = WorkflowPlan(
            workflow_id="plan-dep-fail",
            description="Dependency failure test",
            steps=[step1, step2],
        )
        sm = WorkflowStateMachine(initial_state=plan.state)
        result = self.executor.execute(plan, sm)

        assert result.final_state == WorkflowState.FAILED
        assert step1.status == StepStatus.FAILED

    def test_executor_reset_clears_approvals(self):
        """Requirement: Resetting executor clears tracked approval requests."""
        step = WorkflowStep(
            step_id="step-reset",
            name="Consequential Step",
            tool_name="mock_report_generator",
            inputs={"title": "Report"},
            is_consequential=True,
        )
        plan = WorkflowPlan(
            workflow_id="plan-reset-test",
            steps=[step],
        )
        sm = WorkflowStateMachine(initial_state=plan.state)
        self.executor.execute(plan, sm)
        assert len(self.executor.approval_requests) == 1

        self.executor.reset()
        assert len(self.executor.approval_requests) == 0
