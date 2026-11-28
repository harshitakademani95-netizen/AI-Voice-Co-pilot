"""Result Verification and Safety Gate for Week 3 Agentic Integration."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from src.orchestration.planner import StepState, TaskPlan, TaskStep

logger = logging.getLogger("backend.orchestration.verifier")


class StepVerificationResult(BaseModel):
    step_id: str
    is_valid: bool
    status: str
    issues: List[str] = Field(default_factory=list)


class PlanVerificationReport(BaseModel):
    plan_id: str
    is_verified: bool
    total_steps: int
    completed_steps: int
    failed_steps: int
    step_reports: List[StepVerificationResult] = Field(default_factory=list)
    summary: str


class ResultVerifier:
    """Verifies that all workflow steps executed properly and produced valid, non-empty outputs."""

    def verify_step_output(self, step: TaskStep) -> StepVerificationResult:
        """Validates that a completed step output conforms to expectations and contains no error markers."""
        issues: List[str] = []

        if step.status != StepState.COMPLETED:
            if step.status == StepState.AWAITING_APPROVAL:
                return StepVerificationResult(
                    step_id=step.step_id,
                    is_valid=True,
                    status="awaiting_approval",
                    issues=[],
                )
            issues.append(f"Step is not completed (current status: '{step.status.value}')")
            return StepVerificationResult(
                step_id=step.step_id,
                is_valid=False,
                status="failed",
                issues=issues,
            )

        if step.output is None:
            issues.append("Step output is empty (None)")
        elif isinstance(step.output, dict):
            # Check for error indicators
            if step.output.get("error") or step.output.get("is_error"):
                issues.append(f"Output indicates an execution error: {step.output.get('error')}")
            # Ensure mock tools return expected structure
            if step.tool_name == "mock_task_checker" and "task_status" not in step.output and "status" not in step.output:
                issues.append("mock_task_checker output missing 'task_status' or 'status' field")
            elif step.tool_name == "mock_report_generator" and "report_id" not in step.output and "status" not in step.output:
                issues.append("mock_report_generator output missing 'report_id' or 'status' field")
        elif isinstance(step.output, str) and not step.output.strip():
            issues.append("Step output is an empty string")

        is_valid = len(issues) == 0
        return StepVerificationResult(
            step_id=step.step_id,
            is_valid=is_valid,
            status="verified" if is_valid else "invalid_output",
            issues=issues,
        )

    def verify_plan_completion(self, plan: TaskPlan) -> PlanVerificationReport:
        """Verifies full plan execution integrity, preventing false success reporting."""
        step_reports: List[StepVerificationResult] = []
        completed = 0
        failed = 0

        for step in plan.steps:
            rep = self.verify_step_output(step)
            step_reports.append(rep)
            if step.status == StepState.COMPLETED and rep.is_valid:
                completed += 1
            elif step.status in (StepState.FAILED, StepState.BLOCKED) or not rep.is_valid:
                failed += 1

        is_verified = (failed == 0) and (completed == len(plan.steps) or any(s.status == StepState.AWAITING_APPROVAL for s in plan.steps))
        
        if is_verified and any(s.status == StepState.AWAITING_APPROVAL for s in plan.steps):
            summary = "Plan halted safely awaiting human-in-the-loop approval."
        elif is_verified:
            summary = f"All {completed}/{len(plan.steps)} steps verified successfully."
        else:
            summary = f"Verification failed: {failed} step(s) failed or generated invalid output."

        return PlanVerificationReport(
            plan_id=plan.plan_id,
            is_verified=is_verified,
            total_steps=len(plan.steps),
            completed_steps=completed,
            failed_steps=failed,
            step_reports=step_reports,
            summary=summary,
        )


result_verifier = ResultVerifier()
