"""
Workflow Executor for the Agentic Workflow Engine (W4).

Invariants & Architecture:
1. Accepts a WorkflowPlan.
2. Validates schema and semantic integrity.
3. Checks that every requested tool is registered and permitted.
4. Executes steps in the correct order respecting dependencies.
5. Tracks current workflow state in the state machine.
6. Enforces Safety Gate: Consequential actions default to `awaiting_approval`.
   Never executes unapproved actions.
7. Approvals are single-use: consumed approvals cannot authorize repeated executions.
8. get_approval_request_for_step returns the MOST RECENT matching request, bound to run_id.
9. Stops and waits when approval is pending; resumes only after explicit approval.
10. Records step outputs, errors, and returns a structured WorkflowResult.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from agentic_workflow.schemas import (
    ApprovalRequest,
    ApprovalStatus,
    InvalidPlanError,
    RiskLevel,
    StepStatus,
    WorkflowPlan,
    WorkflowResult,
    WorkflowState,
    WorkflowStep,
)
from agentic_workflow.state_machine import InvalidStateTransitionError, WorkflowStateMachine
from agentic_workflow.tools import ToolExecutionError, ToolRegistry


class WorkflowExecutor:
    """
    Executor driving workflow plans through state-checked mock execution.
    """

    def __init__(self, tool_registry: Optional[ToolRegistry] = None):
        self.tool_registry = tool_registry or ToolRegistry()
        self.approval_requests: Dict[str, ApprovalRequest] = {}

    def reset(self) -> None:
        """Clear all tracked approval requests and execution state."""
        self.approval_requests.clear()

    def _validate_plan_tools(self, plan: WorkflowPlan) -> None:
        """Verify that all referenced tools exist in the tool registry."""
        for step in plan.steps:
            if not self.tool_registry.is_registered(step.tool_name):
                raise InvalidPlanError(
                    f"Unknown tool rejected: Step '{step.step_id}' references unrecognized "
                    f"or unauthorized tool '{step.tool_name}'."
                )

    def is_step_consequential(self, step: WorkflowStep) -> bool:
        """
        Determine if step is consequential either by explicit step flag
        or tool specification risk rating.
        """
        if getattr(step, "is_consequential", False):
            return True
        spec = self.tool_registry.get_spec(step.tool_name)
        if spec and spec.is_consequential:
            return True
        return False

    def get_step_risk_level(self, step: WorkflowStep) -> RiskLevel:
        """Determine the safety risk level for a step."""
        spec = self.tool_registry.get_spec(step.tool_name)
        if spec:
            return spec.risk_level
        return RiskLevel.SENSITIVE if getattr(step, "is_consequential", False) else RiskLevel.INFORMATIONAL

    def create_approval_request(self, plan: WorkflowPlan, step: WorkflowStep) -> ApprovalRequest:
        """
        Generate and track a formal approval request for a consequential step.
        Binds to workflow_id and run_id.
        """
        wid = plan.workflow_id
        run_id = getattr(plan, "run_id", None)

        # Check if an unconsumed pending request already exists for this exact run
        for req in reversed(list(self.approval_requests.values())):
            if (req.workflow_id == wid and 
                req.step_id == step.step_id and 
                (run_id is None or req.run_id == run_id) and 
                req.status == ApprovalStatus.PENDING):
                return req

        risk = self.get_step_risk_level(step)
        request = ApprovalRequest(
            approval_id=f"appr-{uuid.uuid4().hex[:8]}",
            workflow_id=wid,
            run_id=run_id,
            step_id=step.step_id,
            tool_name=step.tool_name,
            inputs=step.inputs,
            reason=f"Action '{step.name}' using tool '{step.tool_name}' is classified as consequential ({risk.value}).",
            risk_level=risk,
            status=ApprovalStatus.PENDING,
        )
        self.approval_requests[request.approval_id] = request
        return request

    def approve_request(
        self, request_id: str, by: Optional[str] = None, comment: Optional[str] = None
    ) -> ApprovalRequest:
        """Approve a pending approval request."""
        if request_id not in self.approval_requests:
            raise KeyError(f"Approval request '{request_id}' not found.")
        req = self.approval_requests[request_id]
        if req.status != ApprovalStatus.PENDING:
            raise ValueError(f"Approval request '{request_id}' has already been resolved ({req.status.value}).")
        req.approve(by=by, comment=comment)
        return req

    def reject_request(
        self, request_id: str, by: Optional[str] = None, comment: Optional[str] = None
    ) -> ApprovalRequest:
        """Deny/reject a pending approval request."""
        if request_id not in self.approval_requests:
            raise KeyError(f"Approval request '{request_id}' not found.")
        req = self.approval_requests[request_id]
        if req.status != ApprovalStatus.PENDING:
            raise ValueError(f"Approval request '{request_id}' has already been resolved ({req.status.value}).")
        req.reject(by=by, comment=comment)
        return req

    def get_approval_request_for_step(
        self, workflow_id: str, step_id: str, run_id: Optional[str] = None
    ) -> Optional[ApprovalRequest]:
        """
        Find the MOST RECENT approval request associated with a specific workflow step.
        Optionally filter by run_id.
        """
        # Search in reverse to find the most recent matching request
        for req in reversed(list(self.approval_requests.values())):
            if req.workflow_id == workflow_id and req.step_id == step_id:
                if run_id is None or req.run_id == run_id:
                    return req
        return None

    def execute(self, plan: WorkflowPlan, sm: Optional[WorkflowStateMachine] = None) -> WorkflowResult:
        """
        Execute or resume execution of a WorkflowPlan.

        Args:
            plan: The WorkflowPlan to execute.
            sm: Optional existing WorkflowStateMachine instance.

        Returns:
            Structured WorkflowResult containing final status, outputs, and audit trail.
        """
        # Validate plan integrity and tools
        plan.validate_plan_integrity()
        self._validate_plan_tools(plan)

        state_machine = sm or WorkflowStateMachine(initial_state=plan.state)

        # Invariant: Completed workflows cannot restart or change state illegally
        if state_machine.is_terminal():
            raise InvalidStateTransitionError(
                from_state=state_machine.current_state,
                to_state=WorkflowState.RUNNING,
                reason=f"Cannot execute workflow in terminal state '{state_machine.current_state.value}'. "
                       f"Completed workflows cannot restart without a valid reset or new plan."
            )

        start_time = datetime.now(timezone.utc).isoformat()
        executed_step_ids: List[str] = []
        step_outputs: Dict[str, Any] = {}

        # Collect already executed steps if resuming
        for s in plan.steps:
            if s.status == StepStatus.COMPLETED:
                executed_step_ids.append(s.step_id)
                step_outputs[s.step_id] = s.output

        # State dispatch: Starting from DRAFT
        if state_machine.current_state == WorkflowState.DRAFT:
            # Check if first pending step is consequential
            first_pending = next((s for s in plan.steps if s.status == StepStatus.PENDING), None)
            if first_pending and self.is_step_consequential(first_pending):
                req = self.get_approval_request_for_step(plan.workflow_id, first_pending.step_id, run_id=plan.run_id)
                if not req or req.status != ApprovalStatus.APPROVED or req.is_consumed:
                    self.create_approval_request(plan, first_pending)
                    first_pending.status = StepStatus.AWAITING_APPROVAL
                    state_machine.transition_to(
                        WorkflowState.AWAITING_APPROVAL,
                        reason=f"Step '{first_pending.step_id}' is consequential and defaults to awaiting approval."
                    )
                    plan.state = state_machine.current_state
                    return self._build_result(plan, state_machine, executed_step_ids, step_outputs, start_time)

            state_machine.transition_to(WorkflowState.RUNNING, reason="Starting plan execution.")
            plan.state = state_machine.current_state

        # State dispatch: Resuming from PAUSED
        elif state_machine.current_state == WorkflowState.PAUSED:
            state_machine.transition_to(WorkflowState.RUNNING, reason="Resuming paused workflow.")
            plan.state = state_machine.current_state

        # State dispatch: Resuming from AWAITING_APPROVAL
        elif state_machine.current_state == WorkflowState.AWAITING_APPROVAL:
            pending_step = next(
                (s for s in plan.steps if s.status == StepStatus.AWAITING_APPROVAL), None
            )
            if pending_step:
                req = self.get_approval_request_for_step(plan.workflow_id, pending_step.step_id, run_id=plan.run_id)
                if not req or req.status == ApprovalStatus.PENDING:
                    # Still awaiting approval; stay blocked
                    return self._build_result(plan, state_machine, executed_step_ids, step_outputs, start_time)
                elif req.status == ApprovalStatus.REJECTED:
                    # Explicitly denied: halt workflow and cancel
                    pending_step.status = StepStatus.CANCELLED
                    state_machine.transition_to(
                        WorkflowState.CANCELLED,
                        reason=f"Approval denied for step '{pending_step.step_id}'."
                    )
                    plan.state = state_machine.current_state
                    return self._build_result(
                        plan, state_machine, executed_step_ids, step_outputs, start_time,
                        summary=f"Workflow cancelled: Approval denied for step '{pending_step.step_id}'."
                    )
                elif req.status == ApprovalStatus.APPROVED:
                    if req.is_consumed:
                        # Consumed approval cannot authorize execution
                        self.create_approval_request(plan, pending_step)
                        return self._build_result(plan, state_machine, executed_step_ids, step_outputs, start_time)
                    # Approved: resume execution
                    state_machine.transition_to(
                        WorkflowState.RUNNING,
                        reason=f"Approval granted for step '{pending_step.step_id}'."
                    )
                    plan.state = state_machine.current_state
                    pending_step.status = StepStatus.PENDING

        # Execution loop: executes while in RUNNING state
        if state_machine.current_state == WorkflowState.RUNNING:
            step_map = {s.step_id: s for s in plan.steps}

            for step in plan.steps:
                if step.status == StepStatus.COMPLETED:
                    continue

                # Verify all dependencies completed successfully
                for dep_id in step.dependencies:
                    dep_step = step_map.get(dep_id)
                    if not dep_step or dep_step.status != StepStatus.COMPLETED:
                        step.status = StepStatus.FAILED
                        step.error = f"Dependency '{dep_id}' was not completed."
                        state_machine.transition_to(
                            WorkflowState.FAILED,
                            reason=f"Dependency '{dep_id}' failed for step '{step.step_id}'."
                        )
                        plan.state = state_machine.current_state
                        return self._build_result(
                            plan, state_machine, executed_step_ids, step_outputs, start_time,
                            error=step.error
                        )

                # Consequential gating check: MUST be approved and unconsumed
                req = None
                if self.is_step_consequential(step):
                    req = self.get_approval_request_for_step(plan.workflow_id, step.step_id, run_id=plan.run_id)
                    if not req or req.status != ApprovalStatus.APPROVED or req.is_consumed:
                        # Must halt and request approval
                        self.create_approval_request(plan, step)
                        step.status = StepStatus.AWAITING_APPROVAL
                        state_machine.transition_to(
                            WorkflowState.AWAITING_APPROVAL,
                            reason=f"Step '{step.step_id}' is consequential and requires explicit approval."
                        )
                        plan.state = state_machine.current_state
                        return self._build_result(
                            plan, state_machine, executed_step_ids, step_outputs, start_time,
                            summary=f"Execution paused at step '{step.step_id}' awaiting approval."
                        )

                # Execute permitted mock tool
                step.status = StepStatus.RUNNING
                try:
                    tool_output = self.tool_registry.execute(step.tool_name, step.inputs)
                    step.output = tool_output
                    step.status = StepStatus.COMPLETED
                    if req and req.status == ApprovalStatus.APPROVED:
                        req.consume()
                    executed_step_ids.append(step.step_id)
                    step_outputs[step.step_id] = tool_output
                except (ToolExecutionError, Exception) as exc:
                    step.status = StepStatus.FAILED
                    step.error = str(exc)
                    state_machine.transition_to(
                        WorkflowState.FAILED,
                        reason=f"Step '{step.step_id}' failed with error: {exc}"
                    )
                    plan.state = state_machine.current_state
                    return self._build_result(
                        plan, state_machine, executed_step_ids, step_outputs, start_time,
                        error=f"Step '{step.step_id}' execution failed: {exc}"
                    )

            # Check if all steps completed
            if all(s.status == StepStatus.COMPLETED for s in plan.steps):
                state_machine.transition_to(
                    WorkflowState.SUCCEEDED,
                    reason="All workflow steps executed successfully."
                )
                plan.state = state_machine.current_state

        return self._build_result(
            plan, state_machine, executed_step_ids, step_outputs, start_time,
            summary="Workflow completed successfully." if state_machine.current_state == WorkflowState.SUCCEEDED else ""
        )

    def pause(self, plan: WorkflowPlan, sm: Optional[WorkflowStateMachine] = None) -> WorkflowResult:
        """Pause a currently running workflow."""
        state_machine = sm or WorkflowStateMachine(initial_state=plan.state)
        state_machine.transition_to(WorkflowState.PAUSED, reason="Workflow paused by user request.")
        plan.state = state_machine.current_state
        return self._build_result(
            plan, state_machine,
            [s.step_id for s in plan.steps if s.status == StepStatus.COMPLETED],
            {s.step_id: s.output for s in plan.steps if s.status == StepStatus.COMPLETED},
            datetime.now(timezone.utc).isoformat(),
            summary="Workflow paused."
        )

    def _build_result(
        self,
        plan: WorkflowPlan,
        state_machine: WorkflowStateMachine,
        executed_step_ids: List[str],
        step_outputs: Dict[str, Any],
        start_time: str,
        error: Optional[str] = None,
        summary: str = "",
    ) -> WorkflowResult:
        """Construct structured WorkflowResult."""
        relevant_approvals = [
            req for req in self.approval_requests.values() if req.workflow_id == plan.workflow_id
        ]
        end_time = datetime.now(timezone.utc).isoformat()
        if not summary:
            summary = f"Workflow in state '{state_machine.current_state.value}'. Executed {len(executed_step_ids)}/{len(plan.steps)} steps."

        return WorkflowResult(
            workflow_id=plan.workflow_id,
            final_state=state_machine.current_state,
            executed_step_ids=executed_step_ids,
            step_outputs=step_outputs,
            approval_requests=relevant_approvals,
            error=error,
            start_time=start_time,
            end_time=end_time,
            summary=summary,
        )
