"""Typed Error Envelope model definitions adhering to the W5 Backend specification.

Architectural Role:
This module defines the typed error payload envelope used by the W5 Backend HTTP REST API
to communicate error responses to clients. It is distinct from the internal domain error model
(`STTErrorDetail` in `src/voice_stt/schemas.py`), which models speech-to-text pipeline
events, accumulator errors, and adapter telemetry.
"""
from typing import Any, Optional
from pydantic import BaseModel, Field


class ErrorPayload(BaseModel):
    """The typed error envelope adhering to the W5 workstream specification
    and the API interface contracts.
    
    Fields required:
    - code: Machine-readable error code (e.g. INVALID_REQUEST, NOT_FOUND)
    - message_safe_for_user: Sanitized error description safe to display to users
    - message: Backward-compatible alias matching standard contract
    - retryable: Boolean flag indicating if client can retry
    - correlation_id: Distributed correlation identifier
    - request_id: Unique request identifier
    - details_redacted: Sanitized extra details exposing no secrets or internals
    """
    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="General user-facing message")
    message_safe_for_user: str = Field(..., description="Guaranteed safe message with zero internal details")
    retryable: bool = Field(default=False, description="Whether the operation is retryable")
    correlation_id: str = Field(..., description="Correlation ID for request tracing")
    request_id: Optional[str] = Field(default=None, description="Request ID associated with error")
    details_redacted: Optional[Any] = Field(default=None, description="Redacted contextual details safe for clients")

    @classmethod
    def from_stt_error(
        cls,
        stt_error: Any,
        correlation_id: Optional[str] = None,
    ) -> "ErrorPayload":
        """Construct a backend ErrorPayload from a domain STTErrorDetail.

        Ensures message sanitization and backward compatibility across W2/W3 STT and W5 Backend.
        """
        from voice_stt.orchestrator import sanitize_error_message

        code = getattr(stt_error, "code", "STT_ERROR")
        msg = getattr(stt_error, "message", str(stt_error))
        req_id = getattr(stt_error, "request_id", None)
        retryable = bool(getattr(stt_error, "retryable", False))
        details = getattr(stt_error, "details", None)

        safe_msg = sanitize_error_message(msg)
        cid = correlation_id or req_id or "corr-stt-unknown"

        return cls(
            code=code,
            message=safe_msg,
            message_safe_for_user=safe_msg,
            retryable=retryable,
            correlation_id=cid,
            request_id=req_id,
            details_redacted=details,
        )


class ErrorResponse(BaseModel):
    """Top-level error response envelope."""
    error: ErrorPayload
