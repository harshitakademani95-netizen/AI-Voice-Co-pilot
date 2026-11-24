"""Task Planner and Multi-Step Execution Planning for Week 3 Agentic Integration."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import logging
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

logger = logging.getLogger("backend.orchestration.planner")


class StepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    AWAITING_APPROVAL = "awaiting_approval"


class TaskStep(BaseModel):
    step_id: str
    description: str
    tool_name: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)
    status: StepState = StepState.PENDING
    output: Optional[Any] = None
    error: Optional[str] = None
    requires_approval: bool = False
    risk_level: str = "A"


class TaskPlan(BaseModel):
    plan_id: str
    session_id: str
    user_query: str
    steps: List[TaskStep]
    status: str = "pending"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None


class TaskPlanner:
    """Decomposes complex user requests into ordered, dependency-resolved task plans."""

    def create_plan(
        self,
        session_id: str,
        user_query: str,
        intent: Optional[str] = None,
        action_type: Optional[str] = None,
        context_items: Optional[List[Any]] = None,
    ) -> TaskPlan:
        """Analyzes user intent and context to construct an executable multi-step TaskPlan."""
        plan_id = f"plan-{uuid.uuid4().hex[:8]}"
        steps: List[TaskStep] = []
        query_lower = user_query.strip().lower()

        # Multi-step: Check tasks then generate report
        if "report" in query_lower and ("task" in query_lower or "check" in query_lower or "status" in query_lower):
            step1 = TaskStep(
                step_id="step-1",
                description="Query active tasks and statuses",
                tool_name="mock_task_checker",
                inputs={"task_id": "task-mock-01"},
                depends_on=[],
                requires_approval=False,
                risk_level="A",
            )
            step2 = TaskStep(
                step_id="step-2",
                description="Compile progress report from retrieved task data",
                tool_name="mock_report_generator",
                inputs={"title": "Automated Progress Report"},
                depends_on=["step-1"],
                requires_approval=False,
                risk_level="B",
            )
            steps = [step1, step2]

        # Sensitive actions requiring Human-in-the-Loop approval (Category C/D)
        elif any(kw in query_lower for kw in ["delete", "wipe", "remove", "move file", "drop"]):
            tool_name = "delete_files" if "delete" in query_lower or "remove" in query_lower else "controlled_file_ops"
            risk = "D" if "delete" in query_lower or "wipe" in query_lower else "C"
            step = TaskStep(
                step_id="step-1",
                description=f"Perform controlled file operation: {user_query}",
                tool_name=tool_name,
                inputs={"target": query_lower, "session_id": session_id},
                depends_on=[],
                requires_approval=True,
                risk_level=risk,
            )
            steps = [step]

        # General inquiry or single-tool execution
        elif "task" in query_lower:
            step = TaskStep(
                step_id="step-1",
                description="Check tasks and pending actions",
                tool_name="mock_task_checker",
                inputs={"user_id": session_id},
                depends_on=[],
                requires_approval=False,
                risk_level="A",
            )
            steps = [step]

        elif "report" in query_lower:
            step = TaskStep(
                step_id="step-1",
                description="Generate summary report",
                tool_name="mock_report_generator",
                inputs={"title": "Summary Report", "recipient": "user@example.com"},
                depends_on=[],
                requires_approval=False,
                risk_level="B",
            )
            steps = [step]

        else:
            # Informational / reasoning task
            chosen_tool = action_type or "system_query"
            step = TaskStep(
                step_id="step-1",
                description=f"Process query: {user_query}",
                tool_name=chosen_tool,
                inputs={"query": user_query, "intent": intent or "general_query"},
                depends_on=[],
                requires_approval=False,
                risk_level="A",
            )
            steps = [step]

        return TaskPlan(
            plan_id=plan_id,
            session_id=session_id,
            user_query=user_query,
            steps=steps,
            status="pending",
        )

    def resolve_inputs(self, step: TaskStep, completed_outputs: Dict[str, Any]) -> Dict[str, Any]:
        """Injects outputs of completed prerequisite steps into downstream step inputs."""
        resolved = dict(step.inputs)
        for dep_id in step.depends_on:
            if dep_id in completed_outputs:
                dep_data = completed_outputs[dep_id]
                # If dependency produced items/data, pass them into step
                if isinstance(dep_data, dict):
                    resolved["dependency_context"] = dep_data
                    if "tasks" in dep_data and "data" not in resolved:
                        resolved["data"] = dep_data["tasks"]
                else:
                    resolved["dependency_context"] = dep_data
        return resolved


task_planner = TaskPlanner()
