"""Request ID and Correlation ID middleware and error handling."""
import logging
import uuid
from typing import Any, Callable
from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.errors import AppError
from src.core.security import redact_sensitive_data
from src.models.error import ErrorPayload, ErrorResponse

logger = logging.getLogger("backend.middleware")

HEADER_REQUEST_ID = "X-Request-ID"
HEADER_CORRELATION_ID = "X-Correlation-ID"


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """Middleware ensuring every request and response carries a Request ID and Correlation ID."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Extract or generate Request ID
        request_id = request.headers.get(HEADER_REQUEST_ID) or f"req-{uuid.uuid4().hex[:12]}"
        
        # Extract or generate Correlation ID
        correlation_id = request.headers.get(HEADER_CORRELATION_ID) or f"corr-{uuid.uuid4().hex[:12]}"

        # Bind to request state
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        try:
            response = await call_next(request)
        except Exception as exc:
            # Handle unexpected exceptions during middleware execution
            return handle_unhandled_exception(request, exc)

        # Inject headers into outgoing response
        response.headers[HEADER_REQUEST_ID] = request_id
        response.headers[HEADER_CORRELATION_ID] = correlation_id
        return response


def create_error_response(
    status_code: int,
    code: str,
    message_safe_for_user: str,
    correlation_id: str,
    request_id: str,
    retryable: bool = False,
    details: Any = None,
) -> JSONResponse:
    """Helper to generate a compliant typed error envelope response."""
    redacted_details = redact_sensitive_data(details) if details is not None else None
    
    payload = ErrorPayload(
        code=code,
        message=message_safe_for_user,
        message_safe_for_user=message_safe_for_user,
        retryable=retryable,
        correlation_id=correlation_id,
        request_id=request_id,
        details_redacted=redacted_details,
    )
    envelope = ErrorResponse(error=payload)
    
    response = JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(),
    )
    response.headers[HEADER_REQUEST_ID] = request_id
    response.headers[HEADER_CORRELATION_ID] = correlation_id
    return response


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Exception handler for custom AppErrors."""
    request_id = getattr(request.state, "request_id", f"req-{uuid.uuid4().hex[:12]}")
    correlation_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:12]}")

    return create_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message_safe_for_user=exc.message_safe_for_user,
        correlation_id=correlation_id,
        request_id=request_id,
        retryable=exc.retryable,
        details=exc.details,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Exception handler for standard HTTPExceptions."""
    request_id = getattr(request.state, "request_id", f"req-{uuid.uuid4().hex[:12]}")
    correlation_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:12]}")

    code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        429: "TOO_MANY_REQUESTS",
        500: "INTERNAL_SERVER_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }
    code = code_map.get(exc.status_code, f"HTTP_{exc.status_code}")
    message = str(exc.detail) if exc.detail else "An HTTP error occurred."
    retryable = exc.status_code in (429, 503, 504)

    return create_error_response(
        status_code=exc.status_code,
        code=code,
        message_safe_for_user=message,
        correlation_id=correlation_id,
        request_id=request_id,
        retryable=retryable,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Exception handler for Pydantic/FastAPI input validation errors."""
    request_id = getattr(request.state, "request_id", f"req-{uuid.uuid4().hex[:12]}")
    correlation_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:12]}")

    # Redact sensitive parameters from validation error reports
    sanitized_errors = []
    for error in exc.errors():
        loc = [str(x) for x in error.get("loc", [])]
        sanitized_errors.append({
            "field": ".".join(loc),
            "message": error.get("msg", "Invalid value"),
            "type": error.get("type", "value_error"),
        })

    return create_error_response(
        status_code=422,
        code="VALIDATION_ERROR",
        message_safe_for_user="The request body or parameters failed validation.",
        correlation_id=correlation_id,
        request_id=request_id,
        retryable=False,
        details=sanitized_errors,
    )


def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Safe fallback for unexpected 500 exceptions, concealing stack traces."""
    request_id = getattr(request.state, "request_id", f"req-{uuid.uuid4().hex[:12]}")
    correlation_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4().hex[:12]}")

    logger.error(
        f"Unhandled server exception [req_id={request_id}, corr_id={correlation_id}]: {exc}",
        exc_info=True,
    )

    return create_error_response(
        status_code=500,
        code="INTERNAL_SERVER_ERROR",
        message_safe_for_user="An unexpected internal server error occurred. Please try again later.",
        correlation_id=correlation_id,
        request_id=request_id,
        retryable=True,
        details=None,
    )
