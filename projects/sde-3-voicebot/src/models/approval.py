"""Pydantic schemas and domain models for Human-in-the-Loop File Actions and Approvals."""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalRequestCreate(BaseModel):
    session_id: str = Field(..., description="Active session identifier")
    action_type: str = Field(..., description="Target operation, e.g. 'move_files' or 'controlled_file_ops'")
    risk_level: str = Field(default="C", description="PRD Risk Category: A, B, C, or D")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Parameters for the proposed tool action")
    ttl_seconds: int = Field(default=300, ge=10, le=3600, description="Approval validity in seconds (default 5m)")


class ApprovalRecord(BaseModel):
    approval_id: str = Field(..., description="Unique approval identifier")
    session_id: str = Field(..., description="Session identifier")
    action_type: str = Field(..., description="Proposed tool action")
    risk_level: str = Field(..., description="PRD Risk Category")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    status: ApprovalStatus = Field(default=ApprovalStatus.PENDING)
    created_at: str = Field(...)
    expires_at: str = Field(...)
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    rejection_reason: Optional[str] = None


class ApprovalDecisionRequest(BaseModel):
    user_id: str = Field(default="user_local", description="Authorizing user identifier")
    reason: Optional[str] = Field(None, description="Optional decision notes")


class ToolExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(..., description="Active session identifier")
    tool_name: str = Field(..., description="Target tool name")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Tool-specific arguments")
    approval_id: Optional[str] = Field(None, description="Approval token for Category C or D actions")


class ToolExecuteResponse(BaseModel):
    execution_id: str = Field(...)
    tool_name: str = Field(...)
    status: str = Field(..., description="'completed', 'failed', or 'approval_required'")
    result: Dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = Field(False)

