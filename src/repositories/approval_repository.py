"""Thread-safe in-memory approval repository and safety gate for tool executions."""
from datetime import datetime, timezone, timedelta
import threading
from typing import Any, Dict, List, Optional
import uuid

from src.models.approval import ApprovalRecord, ApprovalStatus


class ApprovalRepository:
    """Manages Human-in-the-Loop approvals for sensitive actions (Category C & D)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._approvals: Dict[str, ApprovalRecord] = {}
        self._audit_logs: List[Dict[str, Any]] = []

    def clear(self) -> None:
        with self._lock:
            self._approvals.clear()
            self._audit_logs.clear()

    def create_request(
        self,
        session_id: str,
        action_type: str,
        risk_level: str = "C",
        parameters: Optional[Dict[str, Any]] = None,
        ttl_seconds: int = 300,
    ) -> ApprovalRecord:
        with self._lock:
            approval_id = f"appr-{uuid.uuid4().hex[:10]}"
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=ttl_seconds)

            record = ApprovalRecord(
                approval_id=approval_id,
                session_id=session_id,
                action_type=action_type,
                risk_level=risk_level,
                parameters=parameters or {},
                status=ApprovalStatus.PENDING,
                created_at=now.isoformat(),
                expires_at=expires_at.isoformat(),
            )
            self._approvals[approval_id] = record
            self._audit_logs.append({
                "event": "approval_created",
                "approval_id": approval_id,
                "session_id": session_id,
                "action_type": action_type,
                "risk_level": risk_level,
                "timestamp": now.isoformat(),
            })
            return record

    def get(self, approval_id: str) -> Optional[ApprovalRecord]:
        with self._lock:
            record = self._approvals.get(approval_id)
            if not record:
                return None
            self._check_expiry_unlocked(record)
            return record

    def _check_expiry_unlocked(self, record: ApprovalRecord) -> bool:
        if record.status == ApprovalStatus.PENDING:
            exp = datetime.fromisoformat(record.expires_at)
            if datetime.now(timezone.utc) > exp:
                record.status = ApprovalStatus.EXPIRED
                self._audit_logs.append({
                    "event": "approval_expired",
                    "approval_id": record.approval_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                return True
        return False

    def approve(self, approval_id: str, user_id: str = "user_local") -> ApprovalRecord:
        with self._lock:
            record = self._approvals.get(approval_id)
            if not record:
                raise KeyError(f"Approval '{approval_id}' not found.")

            self._check_expiry_unlocked(record)
            if record.status == ApprovalStatus.EXPIRED:
                raise ValueError("Approval request has expired and cannot be approved.")

            if record.status == ApprovalStatus.APPROVED:
                raise ValueError("Approval request is already approved (duplicate decision).")

            if record.status == ApprovalStatus.REJECTED:
                raise ValueError("Cannot approve an already rejected action.")

            now = datetime.now(timezone.utc).isoformat()
            record.status = ApprovalStatus.APPROVED
            record.resolved_at = now
            record.resolved_by = user_id

            self._audit_logs.append({
                "event": "approval_granted",
                "approval_id": approval_id,
                "resolved_by": user_id,
                "timestamp": now,
            })
            return record

    def reject(self, approval_id: str, user_id: str = "user_local", reason: Optional[str] = None) -> ApprovalRecord:
        with self._lock:
            record = self._approvals.get(approval_id)
            if not record:
                raise KeyError(f"Approval '{approval_id}' not found.")

            self._check_expiry_unlocked(record)
            if record.status == ApprovalStatus.EXPIRED:
                raise ValueError("Approval request has expired and cannot be rejected.")

            if record.status == ApprovalStatus.REJECTED:
                raise ValueError("Approval request is already rejected (duplicate decision).")

            if record.status == ApprovalStatus.APPROVED:
                raise ValueError("Cannot reject an already approved action.")

            now = datetime.now(timezone.utc).isoformat()
            record.status = ApprovalStatus.REJECTED
            record.resolved_at = now
            record.resolved_by = user_id
            record.rejection_reason = reason or "User rejected action"

            self._audit_logs.append({
                "event": "approval_rejected",
                "approval_id": approval_id,
                "resolved_by": user_id,
                "reason": record.rejection_reason,
                "timestamp": now,
            })
            return record

    def get_audit_logs(self, approval_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if approval_id:
                return [log for log in self._audit_logs if log.get("approval_id") == approval_id]
            return list(self._audit_logs)


approval_repository = ApprovalRepository()

