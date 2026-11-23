"""Workflow Gateway connecting backend services to Workflow Policies and Approval Repositories."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional
import uuid

from src.core.errors import (
    ForbiddenError,
    GatewayTimeoutError,
    WorkflowGatewayError,
    WorkflowModuleUnavailableError,
)
from src.gateways.resilience import CircuitBreaker, CircuitBreakerOpenError, retry_with_backoff
from src.models.approval import (
    ApprovalRecord,
    ApprovalRequestCreate,
    ApprovalStatus,
    ToolExecuteRequest,
    ToolExecuteResponse,
)
from src.repositories.approval_repository import ApprovalRepository, approval_repository

logger = logging.getLogger("backend.gateways.workflow")

# Sensitive tools requiring Human-In-The-Loop approval (Categories C and D)
SENSITIVE_TOOLS = {"move_files", "delete_files", "controlled_file_ops", "wipe", "drop_table"}


class WorkflowGateway:
    """Backend gateway managing workflow policy enforcement and approval-gated actions."""

    def __init__(
        self,
        approval_repo: Optional[ApprovalRepository] = None,
        timeout_seconds: float = 10.0,
        max_workers: int = 4,
        circuit_breaker: Optional[CircuitBreaker] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.approval_repo = approval_repo or approval_repository
        self.timeout_seconds = timeout_seconds
        self.sleep_fn = sleep_fn
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=5,
            recovery_timeout_sec=30.0,
        )

        self._is_available: bool = True
        self._last_error: Optional[str] = None
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="workflow-gw-")

        # Telemetry
        self._lock = threading.Lock()
        self._total_calls: int = 0
        self._error_count: int = 0
        self._total_latency_ms: float = 0.0
        self._last_success_at: Optional[str] = None

    @property
    def is_available(self) -> bool:
        return self._is_available and (self.circuit_breaker.state != "OPEN")

    def set_available(self, available: bool) -> None:
        self._is_available = available

    def _record_telemetry(self, success: bool, latency_ms: float) -> None:
        with self._lock:
            self._total_calls += 1
            self._total_latency_ms += latency_ms
            if success:
                self._last_success_at = datetime.now(timezone.utc).isoformat()
            else:
                self._error_count += 1

    def evaluate_policy(
        self,
        action_type: str,
        parameters: Dict[str, Any],
        session_id: str,
    ) -> Dict[str, Any]:
        """Evaluates whether an action can proceed automatically or requires Human-in-the-Loop approval."""
        if not self._is_available:
            self._last_error = "Workflow module is currently unavailable"
            self._record_telemetry(success=False, latency_ms=0.0)
            raise WorkflowModuleUnavailableError(
                message="Workflow module is currently unavailable.",
                details={"session_id": session_id},
            )

        action_clean = action_type.strip().lower()
        requires_approval = action_clean in SENSITIVE_TOOLS

        approval_id: Optional[str] = None
        risk_level = "C" if action_clean in ("move_files", "controlled_file_ops") else ("D" if "delete" in action_clean or "wipe" in action_clean else "A")

        if requires_approval:
            approval = self.approval_repo.create_request(
                session_id=session_id,
                action_type=action_clean,
                risk_level=risk_level,
                parameters=parameters,
            )
            approval_id = approval.approval_id

        return {
            "action_type": action_type,
            "requires_approval": requires_approval,
            "risk_level": risk_level,
            "approval_id": approval_id,
        }

    def execute_tool(
        self,
        request: ToolExecuteRequest,
        correlation_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> ToolExecuteResponse:
        """Executes a tool operation under workflow policy, approval gating, and enforced timeouts."""
        start_time = time.monotonic()
        effective_timeout = timeout if timeout is not None else self.timeout_seconds

        if not self._is_available:
            self._last_error = "Workflow module is currently unavailable"
            self._record_telemetry(success=False, latency_ms=0.0)
            raise WorkflowModuleUnavailableError(
                message="Workflow module is currently unavailable.",
                details={"correlation_id": correlation_id},
            )

        tool_clean = request.tool_name.strip().lower()

        # Approval Gating
        if tool_clean in SENSITIVE_TOOLS:
            if not request.approval_id:
                self._record_telemetry(success=False, latency_ms=0.0)
                raise ForbiddenError(
                    message=f"Action '{request.tool_name}' requires human approval token (Category { 'D' if 'delete' in tool_clean else 'C' }).",
                    details={"tool_name": request.tool_name, "reason": "APPROVAL_REQUIRED", "correlation_id": correlation_id},
                )
            getter = getattr(self.approval_repo, "get", getattr(self.approval_repo, "get_request", None))
            record = getter(request.approval_id) if getter else None
            if not record or record.status != ApprovalStatus.APPROVED:
                self._record_telemetry(success=False, latency_ms=0.0)
                raise ForbiddenError(
                    message=f"Approval request '{request.approval_id}' is not in 'approved' status (status: '{record.status.value if record else 'not_found'}').",
                    details={"approval_id": request.approval_id, "status": record.status.value if record else "NOT_FOUND"},
                )

        def _perform_execution() -> ToolExecuteResponse:
            exec_id = f"exec-{uuid.uuid4().hex[:8]}"
            res_dict = {
                "message": f"Tool '{request.tool_name}' successfully executed under session '{request.session_id}'.",
                "parameters": request.parameters,
                "executed_at": datetime.now(timezone.utc).isoformat(),
            }
            return ToolExecuteResponse(
                execution_id=exec_id,
                tool_name=request.tool_name,
                status="completed",
                result=res_dict,
                requires_approval=False,
            )

        def _call_with_timeout() -> ToolExecuteResponse:
            fut = self._executor.submit(_perform_execution)
            try:
                return fut.result(timeout=effective_timeout)
            except FutureTimeoutError:
                fut.cancel()
                el = time.monotonic() - start_time
                raise GatewayTimeoutError(
                    message=f"Workflow tool execution exceeded timeout of {effective_timeout:.2f}s (elapsed: {el:.2f}s).",
                    details={"elapsed_seconds": el, "timeout_seconds": effective_timeout, "correlation_id": correlation_id},
                )
            except Exception as exc:
                if isinstance(exc, (GatewayTimeoutError, ForbiddenError, WorkflowGatewayError, WorkflowModuleUnavailableError)):
                    raise exc
                raise WorkflowGatewayError(
                    message=f"Workflow execution failed: {str(exc)}",
                    details={"error": str(exc), "correlation_id": correlation_id},
                ) from exc

        try:
            resp = self.circuit_breaker.execute(lambda: retry_with_backoff(_call_with_timeout, max_attempts=3, base_delay=0.05, sleep_fn=self.sleep_fn))
        except CircuitBreakerOpenError as exc:
            el = time.monotonic() - start_time
            self._last_error = str(exc)
            self._record_telemetry(success=False, latency_ms=el * 1000.0)
            raise WorkflowModuleUnavailableError(
                message="Workflow module is currently unavailable (circuit breaker OPEN).",
                details={"circuit_state": self.circuit_breaker.state, "correlation_id": correlation_id},
            ) from exc
        except Exception as exc:
            el = time.monotonic() - start_time
            self._last_error = str(exc)
            self._record_telemetry(success=False, latency_ms=el * 1000.0)
            raise

        total_elapsed = time.monotonic() - start_time
        self._record_telemetry(success=True, latency_ms=total_elapsed * 1000.0)
        self._last_error = None
        return resp

    def health_check(self) -> bool:
        if not self._is_available:
            return False
        try:
            return hasattr(self.approval_repo, "_approvals")
        except Exception:
            return False

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            avg_lat = (self._total_latency_ms / self._total_calls) if self._total_calls > 0 else 0.0
            return {
                "gateway": "WorkflowGateway",
                "is_available": self.is_available,
                "circuit_state": self.circuit_breaker.state,
                "total_calls": self._total_calls,
                "error_count": self._error_count,
                "avg_latency_ms": round(avg_lat, 2),
                "last_success_at": self._last_success_at,
                "last_error": self._last_error,
            }

    def close(self) -> None:
        self._is_available = False
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


_workflow_gateway_instance: Optional[WorkflowGateway] = None


def get_workflow_gateway() -> WorkflowGateway:
    global _workflow_gateway_instance
    if _workflow_gateway_instance is None:
        _workflow_gateway_instance = WorkflowGateway()
    return _workflow_gateway_instance
