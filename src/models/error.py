"""Typed Error Envelope model definitions."""
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


class ErrorResponse(BaseModel):
    """Top-level error response envelope."""
    error: ErrorPayload
