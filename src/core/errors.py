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


class AudioGatewayError(AppError):
    """Raised when the audio gateway fails to process audio requests."""

    def __init__(self, message: str, details: Optional[Any] = None, status_code: int = 400, code: str = "AUDIO_GATEWAY_ERROR"):
        super().__init__(
            status_code=status_code,
            code=code,
            message_safe_for_user=message,
            retryable=False,
            details=details,
        )


class AudioFormatUnsupportedError(AppError):
    """Raised when an unsupported audio format (sample rate, channels, encoding) is submitted."""

    def __init__(
        self,
        message: Optional[str] = None,
        details: Optional[Any] = None,
        code: str = "UNSUPPORTED_AUDIO_FORMAT",
        **kwargs: Any,
    ):
        fmt = kwargs.get("format_name", "")
        supp = kwargs.get("supported_formats", [])
        if not message:
            message = f"Audio format '{fmt}' is unsupported. Supported formats: {supp}"
        det = details or {}
        if fmt and isinstance(det, dict):
            det["format"] = fmt
        if supp and isinstance(det, dict):
            det["supported_formats"] = supp
        super().__init__(
            status_code=400,
            code=code,
            message_safe_for_user=message,
            retryable=False,
            details=det,
        )


class AudioModuleUnavailableError(AppError):
    """Raised when the audio processing module is uninitialized or unavailable."""

    def __init__(self, message: str = "Audio processing module is currently unavailable.", details: Optional[Any] = None):
        super().__init__(
            status_code=503,
            code="AUDIO_MODULE_UNAVAILABLE",
            message_safe_for_user=message,
            retryable=True,
            details=details,
        )


class TranscriptionGatewayError(AppError):
    """Raised when the transcription gateway fails to process a transcription request."""

    def __init__(self, message: str, details: Optional[Any] = None, status_code: int = 400, code: str = "TRANSCRIPTION_GATEWAY_ERROR"):
        super().__init__(
            status_code=status_code,
            code=code,
            message_safe_for_user=message,
            retryable=False,
            details=details,
        )


class TranscriptionModuleUnavailableError(AppError):
    """Raised when the transcription engine/adapter is unavailable."""

    def __init__(self, message: str = "Transcription module is currently unavailable.", details: Optional[Any] = None):
        super().__init__(
            status_code=503,
            code="TRANSCRIPTION_MODULE_UNAVAILABLE",
            message_safe_for_user=message,
            retryable=True,
            details=details,
        )


class GatewayTimeoutError(AppError):
    """Raised when an audio or transcription gateway operation exceeds timeout."""

    def __init__(self, message: str = "Gateway operation timed out.", details: Optional[Any] = None):
        super().__init__(
            status_code=504,
            code="GATEWAY_TIMEOUT",
            message_safe_for_user=message,
            retryable=True,
            details=details,
        )


class PayloadTooLargeError(AppError):
    """Raised when an audio payload exceeds permitted size or chunk limits."""

    def __init__(self, message: str = "Audio payload exceeds maximum permitted size.", details: Optional[Any] = None):
        super().__init__(
            status_code=413,
            code="PAYLOAD_TOO_LARGE",
            message_safe_for_user=message,
            retryable=False,
            details=details,
        )


class AudioPayloadTooLargeError(PayloadTooLargeError):
    """Alias for PayloadTooLargeError specific to audio gateway."""
    pass


class CircuitBreakerOpenError(AppError):
    """Raised when an operation is rejected by an open circuit breaker."""

    def __init__(self, message: str = "Circuit breaker is OPEN. Service unavailable.", details: Optional[Any] = None):
        super().__init__(
            status_code=503,
            code="CIRCUIT_BREAKER_OPEN",
            message_safe_for_user=message,
            retryable=True,
            details=details,
        )


class ReasoningGatewayError(AppError):
    """Raised when the reasoning gateway fails to process a reasoning request."""

    def __init__(self, message: str, details: Optional[Any] = None, status_code: int = 400, code: str = "REASONING_GATEWAY_ERROR"):
        super().__init__(
            status_code=status_code,
            code=code,
            message_safe_for_user=message,
            retryable=False,
            details=details,
        )


class ReasoningModuleUnavailableError(AppError):
    """Raised when the reasoning module is unavailable."""

    def __init__(self, message: str = "Reasoning module is currently unavailable.", details: Optional[Any] = None):
        super().__init__(
            status_code=503,
            code="REASONING_MODULE_UNAVAILABLE",
            message_safe_for_user=message,
            retryable=True,
            details=details,
        )


class WorkflowGatewayError(AppError):
    """Raised when the workflow gateway fails to evaluate policy or tool execution."""

    def __init__(self, message: str, details: Optional[Any] = None, status_code: int = 400, code: str = "WORKFLOW_GATEWAY_ERROR"):
        super().__init__(
            status_code=status_code,
            code=code,
            message_safe_for_user=message,
            retryable=False,
            details=details,
        )


class WorkflowModuleUnavailableError(AppError):
    """Raised when the workflow/approval policy module is unavailable."""

    def __init__(self, message: str = "Workflow module is currently unavailable.", details: Optional[Any] = None):
        super().__init__(
            status_code=503,
            code="WORKFLOW_MODULE_UNAVAILABLE",
            message_safe_for_user=message,
            retryable=True,
            details=details,
        )


class RateLimitExceededError(AppError):
    """Raised when request rate limit is exceeded."""

    def __init__(self, message: str = "Rate limit exceeded. Please retry after the cooldown period.", details: Optional[Any] = None):
        super().__init__(
            status_code=429,
            code="RATE_LIMIT_EXCEEDED",
            message_safe_for_user=message,
            retryable=True,
            details=details,
        )


class UnauthorizedError(AppError):
    """Raised when request lacks valid authentication outside the local boundary."""

    def __init__(self, message: str = "Unauthorized: Invalid or missing authentication credentials.", details: Optional[Any] = None):
        super().__init__(
            status_code=401,
            code="UNAUTHORIZED",
            message_safe_for_user=message,
            retryable=False,
            details=details,
        )


class ForbiddenError(AppError):
    """Raised when request is forbidden by authorization policy or approval gate."""

    def __init__(self, message: str = "Forbidden: Operation not permitted by authorization or policy gate.", details: Optional[Any] = None):
        super().__init__(
            status_code=403,
            code="FORBIDDEN",
            message_safe_for_user=message,
            retryable=False,
            details=details,
        )


