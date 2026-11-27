"""
Workstream W3: Context & Reasoning Engine (Week 3 - Day 20)
Schema-Validated WorkflowProposal Handoff Adapter

Author: Amruta A J (Team SDE 3)
Module: src.reasoning.workflow_handoff
Description:
    Bridges the W3 Reasoning Layer (ReasoningResult, RiskCategory) to the W4 Agentic
    Workflow Engine (WorkflowPlan, WorkflowStep, ToolRegistry, WorkflowExecutor).
    
    Guarantees:
    1. Schema-validated WorkflowProposal with strict Pydantic v2 constraints.
    2. Explicit action-to-tool mapping restricted to harmless in-memory mock tools.
    3. Rejection of unsupported or dangerous actions (delete_files, format_disk, system_shell).
    4. Enforced approval and risk consistency: Category C/D and consequential tools
       mandate requires_approval=True and cannot execute without human approval.
    5. Single-use approvals and prompt-injection resistance.
    6. Mock-only, in-memory execution with zero external APIs and zero side effects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Ensure project root and 'web' directory are in sys.path so agentic_workflow is cleanly importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_WEB_DIR = _PROJECT_ROOT / "web"
for _p in (_PROJECT_ROOT, _WEB_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# pyrefly: ignore[missing-import]
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
# pyrefly: ignore[missing-import]
from agentic_workflow.state_machine import (
    InvalidStateTransitionError,
    WorkflowStateMachine,
)
# pyrefly: ignore[missing-import]
from agentic_workflow.tools import (
    ToolExecutionError,
    ToolRegistry,
    mock_report_generator,
    mock_task_checker,
    reset_mock_tools_state,
)
# pyrefly: ignore[missing-import]
from agentic_workflow.executor import WorkflowExecutor
from src.context.schemas import (
    ReasoningResult,
    RiskCategory,
    SourceReference,
)
from src.reasoning.llm_client import ACTION_POLICY


class ProposalStatus(str, Enum):
    """Lifecycle status of a generated WorkflowProposal."""
    PROPOSED = "proposed"
    VALIDATED = "validated"
    REJECTED = "rejected"


RISK_CATEGORY_TO_WORKFLOW_RISK: Dict[RiskCategory, RiskLevel] = {
    RiskCategory.CATEGORY_A: RiskLevel.INFORMATIONAL,
    RiskCategory.CATEGORY_B: RiskLevel.LOW,
    RiskCategory.CATEGORY_C: RiskLevel.SENSITIVE,
    RiskCategory.CATEGORY_D: RiskLevel.CRITICAL,
}

SUPPORTED_ACTION_MAPPING: Dict[str, str] = {
    "check_task": "mock_task_checker",
    "generate_report": "mock_report_generator",
}

UNSUPPORTED_ACTIONS: set[str] = {
    "search_workspace",
    "delete_files",
    "format_disk",
    "system_shell",
    "move_files",
    "archive_files",
    "rename_files",
    "execute_script",
}


class WorkflowProposal(BaseModel):
    """
    Schema-validated contract representing a structured workflow handoff proposal
    derived from a ReasoningResult.
    """
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(..., min_length=1, description="Traceable proposal identifier.")
    request_id: str = Field(..., min_length=1, description="Correlation ID matching ReasoningResult.")
    session_id: Optional[str] = Field(None, description="Active user session identifier.")
    plan: Optional[WorkflowPlan] = Field(None, description="Validated executable WorkflowPlan if valid.")
    risk_level: RiskCategory = Field(RiskCategory.CATEGORY_A, description="PRD Risk classification.")
    workflow_risk_level: Optional[RiskLevel] = Field(None, description="Mapped W4 workflow risk rating.")
    requires_approval: bool = Field(False, description="Whether human confirmation is required.")
    status: ProposalStatus = Field(ProposalStatus.PROPOSED, description="Current proposal lifecycle status.")
    rejection_reason: Optional[str] = Field(None, description="Reason explanation if proposal is rejected.")
    sources: List[SourceReference] = Field(
        default_factory=list,
        description="Grounding source references inherited from reasoning."
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Contextual metadata including provenance and proposal trace."
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of proposal generation."
    )

    @field_validator("created_at")
    @classmethod
    def validate_created_at_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("'created_at' must be a timezone-aware datetime.")
        return v


def build_workflow_proposal(
    result: ReasoningResult,
    session_id: Optional[str] = None,
    tool_inputs: Optional[Dict[str, Any]] = None,
    registry: Optional[ToolRegistry] = None,
    proposal_id: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> WorkflowProposal:
    """
    Construct a schema-validated WorkflowProposal from a validated ReasoningResult.

    Enforces:
    1. Rejection if action_required is False.
    2. Strict action-to-tool mapping restricted to harmless mock tools.
    3. Rejection of unsupported or dangerous actions (delete_files, format_disk, etc.).
    4. Consequential tool and Category C/D mandatory approval gating.
    """
    now = created_at or datetime.now(timezone.utc)
    prop_id = proposal_id or f"prop-{uuid.uuid4().hex[:8]}"

    # Invariant 1: No-action reasoning result cannot produce an actionable plan
    if not result.action_required or not result.action_type:
        return WorkflowProposal(
            proposal_id=prop_id,
            request_id=result.request_id,
            session_id=session_id,
            plan=None,
            risk_level=result.risk_level,
            workflow_risk_level=RISK_CATEGORY_TO_WORKFLOW_RISK.get(result.risk_level, RiskLevel.INFORMATIONAL),
            requires_approval=False,
            status=ProposalStatus.REJECTED,
            rejection_reason="No action required by reasoning result.",
            sources=list(result.sources),
            metadata={"request_id": result.request_id, "session_id": session_id},
            created_at=now,
        )

    action_type = result.action_type.strip().lower()

    # Invariant 2: Explicitly reject destructive or unsupported action types
    if (
        action_type in UNSUPPORTED_ACTIONS
        or action_type not in SUPPORTED_ACTION_MAPPING
        or action_type not in ACTION_POLICY
        or not ACTION_POLICY[action_type].get("allowed", False)
    ):
        return WorkflowProposal(
            proposal_id=prop_id,
            request_id=result.request_id,
            session_id=session_id,
            plan=None,
            risk_level=result.risk_level,
            workflow_risk_level=RISK_CATEGORY_TO_WORKFLOW_RISK.get(result.risk_level, RiskLevel.INFORMATIONAL),
            requires_approval=result.requires_approval,
            status=ProposalStatus.REJECTED,
            rejection_reason=(
                f"Action '{result.action_type}' is unsupported or semantically mismatched with available "
                "harmless mock tools."
            ),
            sources=list(result.sources),
            metadata={"request_id": result.request_id, "session_id": session_id},
            created_at=now,
        )

    tool_name = SUPPORTED_ACTION_MAPPING[action_type]
    reg = registry or ToolRegistry()
    spec = reg.get_spec(tool_name)

    if not spec:
        return WorkflowProposal(
            proposal_id=prop_id,
            request_id=result.request_id,
            session_id=session_id,
            plan=None,
            risk_level=result.risk_level,
            workflow_risk_level=RISK_CATEGORY_TO_WORKFLOW_RISK.get(result.risk_level, RiskLevel.INFORMATIONAL),
            requires_approval=result.requires_approval,
            status=ProposalStatus.REJECTED,
            rejection_reason=f"Tool '{tool_name}' is not registered in ToolRegistry.",
            sources=list(result.sources),
            metadata={"request_id": result.request_id, "session_id": session_id},
            created_at=now,
        )

    # Invariant 3: Mandatory approval rules
    # Consequentiality is enforced if the tool is consequential OR reasoning risk is Category C/D OR policy requires approval
    policy_requires_approval = ACTION_POLICY.get(action_type, {}).get("requires_approval", False)
    is_consequential = spec.is_consequential or (result.risk_level in (RiskCategory.CATEGORY_C, RiskCategory.CATEGORY_D)) or policy_requires_approval
    requires_approval = bool(
        result.requires_approval or
        is_consequential or
        policy_requires_approval or
        (result.risk_level in (RiskCategory.CATEGORY_C, RiskCategory.CATEGORY_D))
    )

    wf_risk = RISK_CATEGORY_TO_WORKFLOW_RISK.get(result.risk_level, RiskLevel.INFORMATIONAL)
    if is_consequential and wf_risk in (RiskLevel.INFORMATIONAL, RiskLevel.LOW):
        wf_risk = spec.risk_level if spec.risk_level != RiskLevel.INFORMATIONAL else RiskLevel.SENSITIVE

    # Invariant 4: Construct default harmless mock inputs
    if tool_inputs is not None:
        inputs = dict(tool_inputs)
    else:
        if tool_name == "mock_task_checker":
            inputs = {"task_id": "task-audit-101"}
        else:
            inputs = {
                "title": "Reasoning Audit Summary",
                "sample_data": {"summary": result.response_text[:200]},
            }

    # Invariant 5: Construct deterministic WorkflowStep
    step_id = f"step-{result.request_id[:12]}"
    step = WorkflowStep(
        step_id=step_id,
        name=f"Execute {tool_name}",
        tool_name=tool_name,
        inputs=inputs,
        is_consequential=is_consequential,
        dependencies=[],
        status=StepStatus.PENDING,
    )

    sources_dump = [s.model_dump() for s in result.sources]
    plan_id = f"wf-{result.request_id}"
    plan = WorkflowPlan(
        workflow_id=plan_id,
        description=f"Automated workflow for request {result.request_id} ({action_type})",
        steps=[step],
        metadata={
            "request_id": result.request_id,
            "session_id": session_id,
            "risk_category": result.risk_level.value,
            "sources": sources_dump,
        },
        state=WorkflowState.DRAFT,
    )

    return WorkflowProposal(
        proposal_id=prop_id,
        request_id=result.request_id,
        session_id=session_id,
        plan=plan,
        risk_level=result.risk_level,
        workflow_risk_level=wf_risk,
        requires_approval=requires_approval,
        status=ProposalStatus.PROPOSED,
        rejection_reason=None,
        sources=list(result.sources),
        metadata={
            "request_id": result.request_id,
            "session_id": session_id,
            "action_type": action_type,
            "tool_name": tool_name,
        },
        created_at=now,
    )


def validate_proposal(
    proposal: WorkflowProposal,
    registry: Optional[ToolRegistry] = None,
) -> bool:
    """
    Validate a WorkflowProposal for structural integrity, tool authorization,
    and security/approval policy consistency.

    Raises:
        InvalidPlanError: If plan integrity or safety validation fails.

    Returns:
        True if proposal is valid and marked VALIDATED; False if proposal was rejected.
    """
    if proposal.status == ProposalStatus.REJECTED or proposal.plan is None:
        return False

    # 1. Structural DAG validation
    proposal.plan.validate_plan_integrity()

    reg = registry or ToolRegistry()

    # 2. Tool verification against permitted registry
    for step in proposal.plan.steps:
        if not reg.is_registered(step.tool_name):
            raise InvalidPlanError(
                f"Unauthorized tool rejected: Step '{step.step_id}' references tool "
                f"'{step.tool_name}' which is not in the permitted ToolRegistry."
            )

        spec = reg.get_spec(step.tool_name)
        if spec and spec.is_consequential:
            if not step.is_consequential:
                raise InvalidPlanError(
                    f"Safety violation: Step '{step.step_id}' references consequential tool "
                    f"'{step.tool_name}', but step.is_consequential is False."
                )
            if not proposal.requires_approval:
                raise InvalidPlanError(
                    f"Safety violation: Proposal containing consequential tool '{step.tool_name}' "
                    "cannot have requires_approval=False."
                )

    # 3. Risk Category consistency
    if proposal.risk_level in (RiskCategory.CATEGORY_C, RiskCategory.CATEGORY_D):
        if not proposal.requires_approval:
            raise InvalidPlanError(
                f"Safety violation: Proposal with {proposal.risk_level.value} risk category "
                "must mandate requires_approval=True."
            )
        for step in proposal.plan.steps:
            if not step.is_consequential:
                raise InvalidPlanError(
                    f"Safety violation: Step '{step.step_id}' under {proposal.risk_level.value} "
                    "risk category must have is_consequential=True."
                )

    proposal.status = ProposalStatus.VALIDATED
    return True


def handoff_to_executor(
    proposal: WorkflowProposal,
    executor: Optional[WorkflowExecutor] = None,
    state_machine: Optional[WorkflowStateMachine] = None,
    registry: Optional[ToolRegistry] = None,
) -> WorkflowResult:
    """
    Hand off a validated WorkflowProposal to WorkflowExecutor for state-checked execution.

    Raises:
        InvalidPlanError: If proposal is rejected or invalid.
    """
    if proposal.status == ProposalStatus.REJECTED or proposal.plan is None:
        raise InvalidPlanError(
            f"Cannot execute rejected workflow proposal: {proposal.rejection_reason or 'No plan attached.'}"
        )

    # Ensure proposal is validated prior to execution
    if proposal.status != ProposalStatus.VALIDATED:
        validate_proposal(proposal, registry=registry)

    exec_instance = executor or WorkflowExecutor(tool_registry=registry or ToolRegistry())
    return exec_instance.execute(proposal.plan, sm=state_machine)

