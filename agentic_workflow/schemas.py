"""
Typed Workflow Schemas for the Agentic Workflow Engine (W4).

Provides five formal Pydantic schemas:
1. WorkflowPlan: Workflow ID, run ID, description, ordered steps, and relevant metadata.
2. WorkflowStep: Step ID, action/tool name, inputs, and required execution information.
3. ToolSpec: Tool name, description, input requirements, and approval/safety metadata.
4. ApprovalRequest: Approval ID, run ID, associated workflow/step, reason, status, approver, and decision details.
5. WorkflowResult: Workflow ID, final/current status, step outputs, errors, and execution summary.

Strict validation is enforced on all schemas:
- model_config extra="forbid" on all schemas
- Missing required fields raise ValidationError
- Duplicate step IDs rejected with InvalidPlanError
- Dependencies must appear earlier in the step list
- Cyclic dependencies rejected with InvalidPlanError
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class WorkflowState(str, Enum):
    """Seven lifecycle states of the workflow engine."""
    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    """Lifecycle status for an individual workflow step."""
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class RiskLevel(str, Enum):
    """Risk rating determining safety and approval requirements."""
    INFORMATIONAL = "informational"
    LOW = "low"
    SENSITIVE = "sensitive"
    CRITICAL = "critical"


class ApprovalStatus(str, Enum):
    """Status of a human-in-the-loop approval decision."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class InvalidPlanError(ValueError):
    """Raised when a workflow plan fails semantic or structural validation."""
    pass


class ToolSpec(BaseModel):
    """
    Schema 3: ToolSpec
    Formal declaration of tool capabilities, input schema, and safety metadata.
    """
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Unique identifier for the tool")
    description: str = Field(..., description="Human-readable explanation of tool functionality")
    input_requirements: Dict[str, Any] = Field(
        default_factory=dict,
        description="Schema defining expected input arguments and parameter constraints"
    )
    is_consequential: bool = Field(
        default=False,
        description="Flag indicating if actions with this tool are consequential and require approval"
    )
    risk_level: RiskLevel = Field(
        default=RiskLevel.INFORMATIONAL,
        description="Assigned safety risk category"
    )

    @property
    def parameters(self) -> Dict[str, Any]:
        """Backward-compatibility property for input_requirements."""
        return self.input_requirements


class ApprovalRequest(BaseModel):
    """
    Schema 4: ApprovalRequest
    Formal human-in-the-loop approval record for consequential/sensitive actions.
    Bound to workflow_id, run_id, and step_id. Approvals are single-use.
    """
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(
        default_factory=lambda: f"appr-{uuid.uuid4().hex[:8]}",
        description="Unique approval request identifier"
    )
    workflow_id: str = Field(..., min_length=1, description="Associated workflow plan ID")
    run_id: Optional[str] = Field(default=None, description="Per-run or plan-instance identifier")
    step_id: str = Field(..., min_length=1, description="Target step awaiting approval")
    tool_name: str = Field(..., min_length=1, description="Tool to be executed if approved")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Input parameters passed to the tool")
    reason: str = Field(..., description="Justification and risk explanation for requiring approval")
    risk_level: RiskLevel = Field(default=RiskLevel.SENSITIVE, description="Safety risk rating")
    status: ApprovalStatus = Field(default=ApprovalStatus.PENDING, description="Current approval status")
    decided_by: Optional[str] = Field(default=None, description="User or reviewer who made the approval decision")
    decision_details: Optional[str] = Field(default=None, description="Approver comment or rationale")
    is_consumed: bool = Field(default=False, description="Whether this approval has been consumed by execution")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: Optional[str] = Field(default=None, description="Timestamp when decision was made")

    @property
    def request_id(self) -> str:
        return self.approval_id

    @property
    def plan_id(self) -> str:
        return self.workflow_id

    @property
    def parameters(self) -> Dict[str, Any]:
        return self.inputs

    @property
    def resolution_comment(self) -> Optional[str]:
        return self.decision_details

    @property
    def approved_by(self) -> Optional[str]:
        return self.decided_by

    def approve(self, by: Optional[str] = None, comment: Optional[str] = None) -> None:
        """Record explicit approval decision."""
        self.status = ApprovalStatus.APPROVED
        self.decided_by = by
        self.decision_details = comment
        self.resolved_at = datetime.now(timezone.utc).isoformat()

    def reject(self, by: Optional[str] = None, comment: Optional[str] = None) -> None:
        """Record explicit denial/rejection decision."""
        self.status = ApprovalStatus.REJECTED
        self.decided_by = by
        self.decision_details = comment
        self.resolved_at = datetime.now(timezone.utc).isoformat()

    def consume(self) -> None:
        """Mark this approval as consumed so it cannot authorize another execution."""
        self.is_consumed = True

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class WorkflowStep(BaseModel):
    """
    Schema 2: WorkflowStep
    Atomic step specification within a workflow plan.
    Standard Pydantic model without custom positional __init__ to ensure strict validation.
    """
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(..., min_length=1, description="Unique identifier for the step")
    name: str = Field(..., min_length=1, description="Descriptive step title")
    tool_name: str = Field(..., min_length=1, description="Registered tool to execute")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Execution parameters for the tool")
    is_consequential: bool = Field(default=False, description="Flag indicating sensitive/consequential action")
    dependencies: List[str] = Field(default_factory=list, description="IDs of steps that must complete first")
    status: StepStatus = Field(default=StepStatus.PENDING, description="Current execution state")
    output: Optional[Any] = Field(default=None, description="Output returned upon successful execution")
    error: Optional[str] = Field(default=None, description="Error message if step execution fails")

    @model_validator(mode="before")
    @classmethod
    def map_parameters_to_inputs(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "parameters" in data and "inputs" not in data:
                data = dict(data)
                data["inputs"] = data.pop("parameters")
        return data

    @property
    def parameters(self) -> Dict[str, Any]:
        return self.inputs

    @parameters.setter
    def parameters(self, value: Dict[str, Any]) -> None:
        self.inputs = value

    def validate_step(self) -> None:
        """Verify step fields validity."""
        if not self.step_id or not self.step_id.strip():
            raise InvalidPlanError("Step must have a non-empty step_id.")
        if not self.name or not self.name.strip():
            raise InvalidPlanError(f"Step '{self.step_id}' must have a non-empty name.")
        if not self.tool_name or not self.tool_name.strip():
            raise InvalidPlanError(f"Step '{self.step_id}' must specify a valid tool_name.")

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class WorkflowPlan(BaseModel):
    """
    Schema 1: WorkflowPlan
    Top-level workflow schema containing workflow_id, run_id, description, ordered steps, and metadata.
    """
    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(..., min_length=1, description="Unique workflow identifier")
    run_id: str = Field(
        default_factory=lambda: f"run-{uuid.uuid4().hex[:8]}",
        description="Unique per-plan-instance/run ID"
    )
    description: str = Field(default="", description="High-level goal or summary of the workflow")
    steps: List[WorkflowStep] = Field(..., min_length=1, description="Ordered sequence of execution steps")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Contextual workflow metadata")
    state: WorkflowState = Field(default=WorkflowState.DRAFT, description="Current workflow state")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __init__(self, **kwargs: Any):
        try:
            super().__init__(**kwargs)
        except ValidationError as e:
            for err in e.errors():
                msg = err.get("msg", "")
                if "Value error, " in msg:
                    raise InvalidPlanError(msg.replace("Value error, ", "")) from e
            raise

    @model_validator(mode="before")
    @classmethod
    def map_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "plan_id" in data and "workflow_id" not in data:
                data["workflow_id"] = data.pop("plan_id")
            if "title" in data and "description" not in data:
                data["description"] = data.pop("title")
        return data

    @property
    def plan_id(self) -> str:
        return self.workflow_id

    @property
    def title(self) -> str:
        return self.description

    @model_validator(mode="after")
    def validate_plan_integrity(self) -> "WorkflowPlan":
        """
        Validate plan structure:
        - Non-empty steps
        - Unique step IDs
        - Dependencies exist AND must appear earlier in the step list
        - No self-dependencies
        - No cyclic dependencies (topological DFS)
        """
        if not self.steps or len(self.steps) == 0:
            raise InvalidPlanError("WorkflowPlan must contain at least one step.")

        seen_step_ids = set()
        step_map = {step.step_id: step for step in self.steps}

        for idx, step in enumerate(self.steps):
            if not isinstance(step, WorkflowStep):
                raise InvalidPlanError(f"Step at index {idx} is not an instance of WorkflowStep.")
            step.validate_step()
            if step.step_id in seen_step_ids:
                raise InvalidPlanError(f"Duplicate step_id found: '{step.step_id}'. Step IDs must be unique.")

            # Validate dependencies appear EARLIER in the step list
            for dep in step.dependencies:
                if dep == step.step_id:
                    raise InvalidPlanError(f"Step '{step.step_id}' cannot depend on itself.")
                if dep not in seen_step_ids:
                    if dep in step_map:
                        raise InvalidPlanError(
                            f"Step '{step.step_id}' depends on '{dep}', but dependencies must appear earlier in the step list."
                        )
                    else:
                        raise InvalidPlanError(f"Step '{step.step_id}' references unknown dependency '{dep}'.")

            seen_step_ids.add(step.step_id)

        # Cycle detection check
        visited: Dict[str, int] = {}  # 0: visiting, 1: visited

        def check_cycle(sid: str) -> bool:
            visited[sid] = 0
            for dep_id in step_map[sid].dependencies:
                if dep_id in visited:
                    if visited[dep_id] == 0:
                        return True
                elif check_cycle(dep_id):
                    return True
            visited[sid] = 1
            return False

        for step in self.steps:
            if step.step_id not in visited:
                if check_cycle(step.step_id):
                    raise InvalidPlanError("Cyclic dependency detected in workflow steps.")

        return self

    def validate(self) -> None:
        """Direct call to validate plan integrity."""
        self.validate_plan_integrity()

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class WorkflowResult(BaseModel):
    """
    Schema 5: WorkflowResult
    Standardized execution summary and audit trace.
    """
    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(..., min_length=1, description="Associated workflow plan ID")
    final_state: WorkflowState = Field(..., description="Final or current state of the workflow")
    step_outputs: Dict[str, Any] = Field(default_factory=dict, description="Outputs produced by executed steps")
    executed_step_ids: List[str] = Field(default_factory=list, description="IDs of successfully executed steps")
    approval_requests: List[ApprovalRequest] = Field(
        default_factory=list, description="Audit log of approval requests generated"
    )
    error: Optional[str] = Field(default=None, description="Top-level error message if workflow failed")
    start_time: Optional[str] = Field(default=None, description="Execution start timestamp")
    end_time: Optional[str] = Field(default=None, description="Execution completion timestamp")
    summary: str = Field(default="", description="Human-readable summary of the execution")

    @model_validator(mode="before")
    @classmethod
    def map_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "plan_id" in data and "workflow_id" not in data:
                data["workflow_id"] = data.pop("plan_id")
        return data

    @property
    def plan_id(self) -> str:
        return self.workflow_id

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
