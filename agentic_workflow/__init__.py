"""
Agentic Workflow Engine Package (Workstream W4).

Foundation of the agentic workflow engine:
- Typed workflow schemas (WorkflowPlan, WorkflowStep, ToolSpec, ApprovalRequest, WorkflowResult)
- State machine with documented transitions
- Exactly two harmless mock tools (mock_task_checker, mock_report_generator)
- Workflow executor with default-to-awaiting-approval safety gate
"""

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
from agentic_workflow.state_machine import (
    InvalidStateTransitionError,
    StateTransitionRecord,
    WorkflowStateMachine,
)
from agentic_workflow.tools import (
    REPORT_GENERATOR_SPEC,
    TASK_CHECKER_SPEC,
    ToolExecutionError,
    ToolRegistry,
    mock_report_generator,
    mock_task_checker,
    reset_mock_tools_state,
)
from agentic_workflow.executor import WorkflowExecutor

__all__ = [
    "WorkflowPlan",
    "WorkflowStep",
    "ToolSpec",
    "ApprovalRequest",
    "WorkflowResult",
    "WorkflowState",
    "StepStatus",
    "RiskLevel",
    "ApprovalStatus",
    "InvalidPlanError",
    "WorkflowStateMachine",
    "InvalidStateTransitionError",
    "StateTransitionRecord",
    "ToolRegistry",
    "TASK_CHECKER_SPEC",
    "REPORT_GENERATOR_SPEC",
    "mock_task_checker",
    "mock_report_generator",
    "ToolExecutionError",
    "reset_mock_tools_state",
    "WorkflowExecutor",
]
