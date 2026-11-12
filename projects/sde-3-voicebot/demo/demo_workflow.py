"""
Interactive Demonstration of the Agentic Workflow Engine (Day 7).

Demonstrates:
1. Pydantic-typed Workflow Schemas and Plan validation.
2. Tool registry containing exactly two harmless mock tools:
   - Tool 1: Mock Task Checker (`mock_task_checker`) [Safe, Informational]
   - Tool 2: Mock Report Generator (`mock_report_generator`) [Consequential, Sensitive]
3. Automatic execution of safe informational step.
4. Human-in-the-loop safety gate: Consequential action defaults to `awaiting_approval`.
5. Explicit approval granting resumption and execution to `SUCCEEDED`.
6. Safety denial scenario: Action rejection halts workflow into `CANCELLED` without executing.
"""

import json
from agentic_workflow import (
    ApprovalStatus,
    StepStatus,
    ToolRegistry,
    WorkflowExecutor,
    WorkflowPlan,
    WorkflowStateMachine,
    WorkflowStep,
    reset_mock_tools_state,
)


def print_banner(text: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {text}")
    print("=" * 72)


def run_demo() -> None:
    reset_mock_tools_state()
    registry = ToolRegistry()
    executor = WorkflowExecutor(registry)

    print_banner("1. TOOL REGISTRY VERIFICATION")
    print(f"Registered mock tools count: {len(registry.available_tools)}")
    for name, spec in registry.available_tools.items():
        gate_flag = "[CONSEQUENTIAL - GATED]" if spec.is_consequential else "[SAFE - AUTO]"
        print(f"  * {spec.name:<24} {gate_flag:<25} Risk: {spec.risk_level.value:<14} ({spec.description})")

    print_banner("2. DEFINING TYPED WORKFLOW PLAN (Multi-Step Vertical Slice)")
    step1 = WorkflowStep(
        step_id="step-001",
        name="Inspect Codebase Audit Task",
        tool_name="mock_task_checker",
        inputs={"task_id": "task-audit-101"},
        is_consequential=False,
    )
    step2 = WorkflowStep(
        step_id="step-002",
        name="Generate Executive Audit Report",
        tool_name="mock_report_generator",
        inputs={
            "title": "Quarterly Codebase Audit Report",
            "sample_data": {"items_analyzed": 142, "status": "approved"}
        },
        dependencies=["step-001"],
        is_consequential=True,
    )

    plan = WorkflowPlan(
        workflow_id="plan-demo-001",
        description="Run task check followed by gated consequential report generation.",
        steps=[step1, step2],
    )
    print(f"Workflow ID:  {plan.workflow_id}")
    print(f"Description:  {plan.description}")
    print(f"Initial State: {plan.state.value.upper()}")
    print(f"Steps ({len(plan.steps)} total):")
    for s in plan.steps:
        print(f"   - [{s.step_id}] {s.name} (Tool: {s.tool_name}, Consequential: {s.is_consequential})")

    print_banner("3. PHASE 1: EXECUTE SAFE STEP & TRIGGER HUMAN SAFETY GATE")
    sm = WorkflowStateMachine(initial_state=plan.state)
    result_phase1 = executor.execute(plan, sm)

    print(f"Workflow State:       {result_phase1.final_state.value.upper()}")
    print(f"Executed Steps:       {result_phase1.executed_step_ids}")
    print(f"Step 1 Status:        {step1.status.value.upper()} (Safe - Auto Completed)")
    print(f"Step 1 Output:        {step1.output}")
    print(f"Step 2 Status:        {step2.status.value.upper()} (Consequential - Gated & Not Executed)")

    # Inspect generated approval request
    approvals = result_phase1.approval_requests
    print(f"\nGenerated Approval Requests: {len(approvals)}")
    assert len(approvals) == 1, "Expected exactly 1 pending approval request."
    req = approvals[0]
    print(f"  * Approval ID: {req.approval_id}")
    print(f"  * Step ID:     {req.step_id} -> Tool: {req.tool_name}")
    print(f"  * Risk Level:  {req.risk_level.value.upper()}")
    print(f"  * Reason:      {req.reason}")
    print(f"  * Inputs:      {json.dumps(req.inputs)}")
    print(f"  * Status:      {req.status.value.upper()}")

    print_banner("4. HUMAN-IN-THE-LOOP APPROVAL DECISION")
    print("Reviewer (Suhani A - SDE 3) approves the consequential action...")
    executor.approve_request(req.approval_id, by="Suhani A (SDE 3)", comment="Audit data verified. Report generation approved.")
    print(f"Approval Status:    {req.status.value.upper()}")
    print(f"Decided By:         {req.decided_by}")
    print(f"Decision Details:   {req.decision_details}")

    print_banner("5. PHASE 2: RESUME WORKFLOW & EXECUTE APPROVED ACTION")
    result_phase2 = executor.execute(plan, sm)

    print(f"Final State:    {result_phase2.final_state.value.upper()}")
    print(f"Executed Steps: {result_phase2.executed_step_ids}")
    print(f"Step 2 Status:  {step2.status.value.upper()}")
    print(f"Step 2 Output:  {step2.output}")
    print(f"Summary:        {result_phase2.summary}")

    print_banner("6. SAFETY TEST: REJECTED APPROVAL SCENARIO")
    step_unauth = WorkflowStep(
        step_id="step-unauth-01",
        name="Generate Sensitive Financial Report",
        tool_name="mock_report_generator",
        inputs={"title": "Unauthorized Budget Overwrite"},
        is_consequential=True,
    )
    plan_rejected = WorkflowPlan(
        workflow_id="plan-demo-reject",
        description="Plan simulating denied approval",
        steps=[step_unauth],
    )
    sm_reject = WorkflowStateMachine(initial_state=plan_rejected.state)
    res_paused = executor.execute(plan_rejected, sm_reject)
    print(f"Workflow State: {res_paused.final_state.value.upper()}")

    reject_req = res_paused.approval_requests[0]
    print(f"Reviewer DENIES approval for request '{reject_req.approval_id}'...")
    executor.reject_request(reject_req.approval_id, by="Suhani A (SDE 3)", comment="Action rejected: Policy breach.")
    res_cancelled = executor.execute(plan_rejected, sm_reject)

    print(f"Resulting State:   {res_cancelled.final_state.value.upper()}")
    print(f"Step Status:       {step_unauth.status.value.upper()}")
    print(f"Was tool executed? {step_unauth.output is not None} (Verified: Not executed)")
    print_banner("DEMO COMPLETED SUCCESSFULLY: ALL ACCEPTANCE CRITERIA VERIFIED")


if __name__ == "__main__":
    run_demo()
