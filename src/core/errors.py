"""Domain and application exceptions with typed envelope mapping."""
from typing import Any, Optional


class AppError(Exception):
    """Base application exception supporting typed error envelope fields."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message_safe_for_user: str,
        retryable: bool = False,
        details: Optional[Any] = None,
    ):
        super().__init__(message_safe_for_user)
        self.status_code = status_code
        self.code = code
        self.message_safe_for_user = message_safe_for_user
        self.retryable = retryable
        self.details = details


class SessionNotFoundError(AppError):
    """Raised when a requested session is not found in repository."""

    def __init__(self, session_id: str):
        super().__init__(
            status_code=404,
            code="SESSION_NOT_FOUND",
            message_safe_for_user=f"Session with ID '{session_id}' was not found.",
            retryable=False,
            details={"session_id": session_id},
        )


class InvalidStateTransitionError(AppError):
    """Raised when an illegal session state transition is attempted."""

    def __init__(self, current_state: str, target_state: str, reason: Optional[str] = None):
        msg = f"Cannot transition session from '{current_state}' to '{target_state}'."
        if reason:
            msg += f" Reason: {reason}"
        super().__init__(
            status_code=409,
            code="INVALID_STATE_TRANSITION",
            message_safe_for_user=msg,
            retryable=False,
            details={
                "current_state": current_state,
                "target_state": target_state,
                "reason": reason,
            },
        )


class SessionValidationError(AppError):
    """Raised when session input validation fails."""

    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(
            status_code=400,
            code="INVALID_REQUEST",
            message_safe_for_user=message,
            retryable=False,
            details=details,
        )
