"""Human-in-the-Loop Approval routes and Controlled Tool Execution endpoints."""
import uuid
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from src.models.approval import (
    ApprovalDecisionRequest,
    ApprovalRecord,
    ApprovalRequestCreate,
    ApprovalStatus,
    ToolExecuteRequest,
    ToolExecuteResponse,
)
from src.repositories.approval_repository import approval_repository
from src.repositories.session_repository import session_repository

router = APIRouter(tags=["Approvals & Tool Safety Gate"])

# Controlled tools requiring Category C / D Human-in-the-Loop approval
SENSITIVE_TOOLS = {"move_files", "delete_files", "controlled_file_ops", "archive_files"}


@router.post(
    "/approvals/request",
    response_model=ApprovalRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Create a pending action approval request",
)
async def create_approval_request(body: ApprovalRequestCreate) -> ApprovalRecord:
    # Verify session exists
    session_repository.get(body.session_id)
    return approval_repository.create_request(
        session_id=body.session_id,
        action_type=body.action_type,
        risk_level=body.risk_level,
        parameters=body.parameters,
        ttl_seconds=body.ttl_seconds,
    )


@router.get(
    "/approvals/{approval_id}",
    response_model=ApprovalRecord,
    summary="Get approval request status",
)
async def get_approval(approval_id: str) -> ApprovalRecord:
    rec = approval_repository.get(approval_id)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval request '{approval_id}' not found.",
        )
    return rec


@router.post(
    "/approvals/{approval_id}/approve",
    response_model=ApprovalRecord,
    summary="Approve pending tool action",
)
async def approve_action(
    approval_id: str,
    body: Optional[ApprovalDecisionRequest] = None,
) -> ApprovalRecord:
    decision = body or ApprovalDecisionRequest()
    try:
        rec = approval_repository.approve(approval_id, user_id=decision.user_id)
        # Record event in session if active
        try:
            session_repository.add_event(
                session_id=rec.session_id,
                event_type="action_approved",
                payload={"approval_id": approval_id, "action_type": rec.action_type, "user": decision.user_id},
            )
        except Exception:
            pass
        return rec
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Approval '{approval_id}' not found.")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.post(
    "/approvals/{approval_id}/reject",
    response_model=ApprovalRecord,
    summary="Reject pending tool action",
)
async def reject_action(
    approval_id: str,
    body: Optional[ApprovalDecisionRequest] = None,
) -> ApprovalRecord:
    decision = body or ApprovalDecisionRequest()
    try:
        rec = approval_repository.reject(approval_id, user_id=decision.user_id, reason=decision.reason)
        # Record event in session if active
        try:
            session_repository.add_event(
                session_id=rec.session_id,
                event_type="action_rejected",
                payload={"approval_id": approval_id, "action_type": rec.action_type, "reason": decision.reason},
            )
        except Exception:
            pass
        return rec
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Approval '{approval_id}' not found.")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get(
    "/approvals/{approval_id}/audit",
    summary="Get audit logs for approval request",
)
async def get_approval_audit(approval_id: str):
    rec = approval_repository.get(approval_id)
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Approval '{approval_id}' not found.")
    logs = approval_repository.get_audit_logs(approval_id)
    return {"approval_id": approval_id, "audit_records": logs}


@router.post(
    "/tools/execute",
    response_model=ToolExecuteResponse,
    summary="Controlled Tool Execution API",
    description="Executes a sandboxed tool operation under strict permission gating (docs/api-contracts/tools-execute.md).",
)
async def execute_tool(body: ToolExecuteRequest) -> ToolExecuteResponse:
    # 1. Verify session exists
    session_repository.get(body.session_id)

    # 2. Check if tool requires approval (Category C or D)
    is_sensitive = body.tool_name in SENSITIVE_TOOLS
    if is_sensitive:
        if not body.approval_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action '{body.tool_name}' requires explicit user approval. Missing approval_id.",
            )

        appr = approval_repository.get(body.approval_id)
        if not appr:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Invalid approval_id '{body.approval_id}'.",
            )

        if appr.status == ApprovalStatus.EXPIRED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Approval '{body.approval_id}' has expired. Re-request authorization.",
            )

        if appr.status != ApprovalStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action '{body.tool_name}' was not approved. Current status is '{appr.status.value}'.",
            )

    # 3. Perform safe mock execution (zero destructive host operations)
    exec_id = f"exec-{uuid.uuid4().hex[:8]}"
    mock_result: Dict[str, Any] = {}
    if body.tool_name == "file_search":
        mock_result = {
            "matched_files": ["Documents/report_q1.pdf", "Documents/report_q2.pdf"],
            "total_found": 2,
        }
    elif body.tool_name in ("move_files", "controlled_file_ops"):
        mock_result = {
            "files_moved": ["report_q1.pdf", "report_q2.pdf", "report_summary.docx"],
            "destination": body.parameters.get("destination", "archive/2026/"),
            "safety_mode": "mock_safe_execution",
            "files_modified_count": 3,
        }
    else:
        mock_result = {
            "status": "success",
            "operation": body.tool_name,
            "mode": "mock_deterministic",
        }

    return ToolExecuteResponse(
        execution_id=exec_id,
        tool_name=body.tool_name,
        status="completed",
        result=mock_result,
        requires_approval=is_sensitive,
    )

