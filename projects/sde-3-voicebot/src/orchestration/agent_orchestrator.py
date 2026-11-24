"""Central Agent Orchestration Service for Week 3 Agentic Integration."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from agentic_workflow.tools import ToolRegistry
from src.context.schemas import ContextItem
from src.gateways.reasoning_gateway import ReasoningGateway, get_reasoning_gateway
from src.gateways.workflow_gateway import WorkflowGateway, get_workflow_gateway
from src.models.approval import ToolExecuteRequest
from src.orchestration.planner import StepState, TaskPlan, TaskPlanner, TaskStep, task_planner
from src.orchestration.retrieval import ContextRetrievalService, retrieval_service
from src.orchestration.verifier import PlanVerificationReport, ResultVerifier, result_verifier
from src.repositories.session_repository import InMemorySessionRepository, session_repository

logger = logging.getLogger("backend.orchestration.agent")


class AgentOrchestrationResult:
    """Encapsulates the complete result of an agentic workflow execution."""

    def __init__(
        self,
        session_id: str,
        user_query: str,
        plan: TaskPlan,
        verification: PlanVerificationReport,
        final_response: str,
        status: str,
        approval_id: Optional[str] = None,
    ) -> None:
        self.session_id = session_id
        self.user_query = user_query
        self.plan = plan
        self.verification = verification
        self.final_response = final_response
        self.status = status
        self.approval_id = approval_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_query": self.user_query,
            "status": self.status,
            "approval_id": self.approval_id,
            "final_response": self.final_response,
            "plan": self.plan.model_dump(),
            "verification": self.verification.model_dump(),
        }


class AgentOrchestrationService:
    """Central Agent Orchestration coordinating Context Retrieval, Planning, Tool Execution,

    Workflow Policy, and Output Verification.
    """

    def __init__(
        self,
        planner: Optional[TaskPlanner] = None,
        retriever: Optional[ContextRetrievalService] = None,
        verifier: Optional[ResultVerifier] = None,
        tool_registry: Optional[ToolRegistry] = None,
        workflow_gw: Optional[WorkflowGateway] = None,
        session_repo: Optional[InMemorySessionRepository] = None,
    ) -> None:
        self.planner = planner or task_planner
        self.retriever = retriever or retrieval_service
        self.verifier = verifier or result_verifier
        self.tool_registry = tool_registry or ToolRegistry()
        self.workflow_gw = workflow_gw or get_workflow_gateway()
        self.session_repo = session_repo or session_repository

    def orchestrate(
        self,
        session_id: str,
        user_query: str,
        intent: Optional[str] = None,
        action_type: Optional[str] = None,
        correlation_id: Optional[str] = None,
        context_items: Optional[List[ContextItem]] = None,
    ) -> AgentOrchestrationResult:
        """Executes the full agentic loop: Retrieval -> Planning -> Execution -> Verification -> Event Recording."""
        corr_id = correlation_id or f"corr-{uuid.uuid4().hex[:8]}"

        # Ensure session exists (auto-create if missing for ad-hoc queries)
        try:
            self.session_repo.get(session_id)
        except Exception:
            try:
                self.session_repo.create(session_id=session_id)
            except Exception:
                pass

        # 1. Retrieve & sanitize relevant context
        retrieved_items = self.retriever.retrieve(session_id=session_id, query=user_query)
        all_context = list(context_items or []) + retrieved_items

        # 2. Construct multi-step execution plan
        plan: TaskPlan = self.planner.create_plan(
            session_id=session_id,
            user_query=user_query,
            intent=intent,
            action_type=action_type,
            context_items=all_context,
        )

        self.session_repo.add_event(
            session_id=session_id,
            event_type="agent_plan_created",
            payload={"plan_id": plan.plan_id, "steps_count": len(plan.steps)},
            correlation_id=corr_id,
        )

        completed_outputs: Dict[str, Any] = {}
        plan_status = "completed"
        approval_id: Optional[str] = None

        # 3. Sequential Execution with Dependency Resolution and Safety Gates
        for step in plan.steps:
            # Check prerequisite dependencies
            deps_failed = any(
                completed_outputs.get(d, {}).get("is_error", False)
                for d in step.depends_on
            )
            if deps_failed:
                step.status = StepState.BLOCKED
                step.error = f"Prerequisite dependency failed in: {step.depends_on}"
                plan_status = "failed"
                break

            # Check Approval Gate on Category C/D actions
            if step.requires_approval:
                step.status = StepState.AWAITING_APPROVAL
                policy_res = self.workflow_gw.evaluate_policy(
                    action_type=step.tool_name,
                    parameters=step.inputs,
                    session_id=session_id,
                )
                approval_id = policy_res.get("approval_id")
                plan_status = "requires_approval"
                step.output = {"status": "awaiting_approval", "approval_id": approval_id}

                self.session_repo.add_event(
                    session_id=session_id,
                    event_type="approval_requested",
                    payload={"step_id": step.step_id, "tool_name": step.tool_name, "approval_id": approval_id},
                    correlation_id=corr_id,
                )
                break

            # Resolve dynamic inputs from previous steps
            step.status = StepState.RUNNING
            resolved_inputs = self.planner.resolve_inputs(step, completed_outputs)

            try:
                # Execute registered tool
                if self.tool_registry.is_registered(step.tool_name):
                    tool_res = self.tool_registry.execute(step.tool_name, resolved_inputs)
                    step.output = tool_res
                    step.status = StepState.COMPLETED
                    completed_outputs[step.step_id] = tool_res
                else:
                    # Execute via Workflow Gateway
                    exec_req = ToolExecuteRequest(
                        tool_name=step.tool_name,
                        session_id=session_id,
                        parameters=resolved_inputs,
                    )
                    gw_res = self.workflow_gw.execute_tool(exec_req, correlation_id=corr_id)
                    step.output = gw_res.result
                    step.status = StepState.COMPLETED
                    completed_outputs[step.step_id] = gw_res.result

                self.session_repo.add_event(
                    session_id=session_id,
                    event_type="agent_step_completed",
                    payload={"step_id": step.step_id, "tool_name": step.tool_name, "status": "completed"},
                    correlation_id=corr_id,
                )
            except Exception as exc:
                logger.error("Step %s failed during tool execution: %s", step.step_id, exc)
                step.status = StepState.FAILED
                step.error = str(exc)
                completed_outputs[step.step_id] = {"is_error": True, "error": str(exc)}
                plan_status = "failed"
                self.session_repo.add_event(
                    session_id=session_id,
                    event_type="agent_step_failed",
                    payload={"step_id": step.step_id, "tool_name": step.tool_name, "error": str(exc)},
                    correlation_id=corr_id,
                )
                break

        plan.status = plan_status
        plan.completed_at = datetime.now(timezone.utc).isoformat()

        # 4. Result Verification Phase
        verification: PlanVerificationReport = self.verifier.verify_plan_completion(plan)

        # 5. Formulate UI Response
        if plan_status == "requires_approval":
            final_resp = f"Operation '{user_query}' requires human approval before proceeding. Approval Ticket ID: {approval_id}."
        elif verification.is_verified and plan_status == "completed":
            final_resp = f"Task completed successfully. {verification.summary}"
        else:
            final_resp = f"Task execution incomplete. Reason: {verification.summary}"

        return AgentOrchestrationResult(
            session_id=session_id,
            user_query=user_query,
            plan=plan,
            verification=verification,
            final_response=final_resp,
            status=plan_status,
            approval_id=approval_id,
        )


# Singleton
agent_orchestrator = AgentOrchestrationService()
