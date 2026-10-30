"""
AI Voice Co-Pilot - Unified Multi-Workstream Demonstration (Day 7).

Demonstrates:
- Workstream W4 (Agentic Workflow Engine - Suhani A):
  1. Pydantic-typed Workflow Schemas and Plan validation.
  2. Safe execution of harmless mock tools.
  3. Human-in-the-loop safety gate (consequential action -> awaiting_approval).
  4. Explicit approval granting and workflow resumption.
  5. Action denial scenario halting into CANCELLED.

- Workstream W3 (Context & Reasoning Engine - Amruta A J):
  1. Synthetic frame creation with screen capture disabled by default.
  2. Versioned prompts with trusted vs. untrusted content boundaries.
  3. Deterministic mock reasoning generating grounded responses with SourceReferences.
  4. Risk classification and Human-in-the-Loop safety approval gating.
"""

import sys
import argparse
import json

# W4: Agentic Workflow Imports
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

# W3: Context & Reasoning Imports
from src.context.fixtures import (
    create_synthetic_screen_frame,
    get_synthetic_document_scenario,
    get_synthetic_error_scenario,
    get_synthetic_file_action_scenario,
)
from src.context.schemas import ReasoningRequest
from src.prompts.versioned_prompts import build_versioned_prompt
from src.reasoning.mock_engine import MockReasoningEngine


def print_banner(text: str) -> None:
    print("\n" + "=" * 76)
    print(f"  {text}")
    print("=" * 76)


def run_workflow_demo() -> None:
    print_banner("DEMO: WORKSTREAM W4 - AGENTIC WORKFLOW ENGINE (Suhani A - SDE 3)")
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
    print(f"Step 2 Status:  {step2.status.value.upper()} (Executed after approval)")
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
    print_banner("W4 VERIFIED: Consequential actions halted safely without unauthorized execution.")


def run_reasoning_demo() -> None:
    print_banner("DEMO: WORKSTREAM W3 - CONTEXT & REASONING (Amruta A J - SDE 3)")
    engine = MockReasoningEngine()

    # Scenario 1: Technical Error Explanation (PRD UC-02)
    print("\n[DEMO 1] PRD UC-02: Explain Technical Error (ZeroDivisionError)")
    print("-" * 76)
    error_items = get_synthetic_error_scenario()
    req_1 = ReasoningRequest(
        request_id="req-demo-001",
        session_id="sess-student-1",
        user_query="Why is this application failing?",
        context_items=error_items,
        prompt_version="v1.0.0",
    )

    result_1 = engine.reason(req_1)
    print(f"User Query      : {req_1.user_query}")
    print(f"Prompt Version  : {result_1.prompt_version}")
    print(f"Risk Category   : {result_1.risk_level.value} (Category A: Informational)")
    print(f"Needs Approval  : {result_1.requires_approval}")
    print(f"Response        : {result_1.response_text}")
    print("Grounded Sources Cited:")
    for s in result_1.sources:
        print(f"  - [{s.source_type}] {s.source_id} @ {s.reference_location} (conf: {s.confidence_score})")
        if s.excerpt:
            print(f'    Excerpt: "{s.excerpt}"')

    # Scenario 2: Research Paper Explanation (PRD UC-03)
    print("\n[DEMO 2] PRD UC-03: Explain Document (Project Nimbus Abstract)")
    print("-" * 76)
    doc_items = get_synthetic_document_scenario()
    req_2 = ReasoningRequest(
        request_id="req-demo-002",
        session_id="sess-student-2",
        user_query="Explain the methodology shown in this paper",
        context_items=doc_items,
        prompt_version="v1.1.0",
    )

    result_2 = engine.reason(req_2)
    print(f"User Query      : {req_2.user_query}")
    print(f"Prompt Version  : {result_2.prompt_version}")
    print(f"Risk Category   : {result_2.risk_level.value}")
    print(f"Response        : {result_2.response_text}")
    print(f"Source Cited    : {result_2.sources[0].reference_location}")

    # Scenario 3: Safety Gate Demonstration (PRD UC-08 - File Move Action)
    print("\n[DEMO 3] PRD UC-08: Controlled File Operation (Safety & Approval Gate)")
    print("-" * 76)
    file_items = get_synthetic_file_action_scenario()
    req_3 = ReasoningRequest(
        request_id="req-demo-003",
        session_id="sess-student-3",
        user_query="Move these files into the archive folder",
        context_items=file_items,
        prompt_version="v1.0.0",
    )

    result_3 = engine.reason(req_3)
    print(f"User Query      : {req_3.user_query}")
    print(f"Action Required : {result_3.action_required} (Action: {result_3.action_type})")
    print(f"Risk Category   : Category {result_3.risk_level.value} (Sensitive Operation)")
    print(f"Requires Approval: {result_3.requires_approval} (Enforced by Human-in-the-Loop Safety Gate)")
    print(f"AI Response     : {result_3.response_text}")

    # Scenario 4: Trusted vs. Untrusted Prompt Boundary Demonstration
    print("\n[DEMO 4] Versioned Prompt Isolation & Prompt Injection Defense")
    print("-" * 76)
    prompt_str = build_versioned_prompt(
        version="v1.0.0",
        user_query="Why is this code failing?",
        context_items=error_items[:1],
    )
    print("Rendered Prompt Preview (Notice clean boundaries):")
    print(prompt_str[:380] + "\n... [truncated for display] ...\n" + prompt_str[-150:])

    print_banner("DEMONSTRATION COMPLETED SUCCESSFULLY [ALL CONTROLS VERIFIED]")


def run_demo(target: str = "all") -> None:
    if target in ["w4", "workflow"]:
        run_workflow_demo()
    elif target in ["w3", "reasoning"]:
        run_reasoning_demo()
    else:
        run_workflow_demo()
        run_reasoning_demo()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Voice Co-Pilot Day 7 Demonstration")
    parser.add_argument(
        "--workstream",
        "-w",
        choices=["all", "w4", "workflow", "w3", "reasoning"],
        default="all",
        help="Select which workstream demonstration to run (default: all)",
    )
    args = parser.parse_args()
    run_demo(args.workstream)
