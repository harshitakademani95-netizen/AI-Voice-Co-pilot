"""Tests for Week 3 Task 4 and Task 5: Fallback Error Classification & Error Models."""

import concurrent.futures
from typing import Any
import pytest

from src.models.error import ErrorPayload, ErrorResponse
from voice_stt.orchestrator import (
    OrchestratorCancelledError,
    OrchestratorClosedError,
    is_supported_fallback_error,
    sanitize_error_message,
)
from voice_stt.schemas import STTErrorDetail, STTValidationError


class CustomNetworkError(Exception):
    def __init__(self, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.status_code = status_code


class CustomClientError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class TestFallbackErrorClassification:
    """Targeted tests for is_supported_fallback_error()."""

    def test_quota_and_rate_limit_structured_codes(self) -> None:
        for code in ("QUOTA_EXCEEDED", "RATE_LIMITED", "RESOURCE_EXHAUSTED", "HTTP_429", "TOO_MANY_REQUESTS"):
            err_detail = STTErrorDetail(code=code, message="Provider quota exhausted.")
            assert is_supported_fallback_error(Exception("quota"), err_detail) is True

    def test_http_429_status_code_attribute(self) -> None:
        exc = CustomNetworkError("Rate limit reached", status_code=429)
        assert is_supported_fallback_error(exc) is True

    def test_network_connection_failures(self) -> None:
        for exc_cls in (ConnectionError, ConnectionResetError, ConnectionRefusedError, BrokenPipeError):
            assert is_supported_fallback_error(exc_cls("Network disconnected")) is True

        err_detail = STTErrorDetail(code="CONNECTION_REFUSED", message="Connection refused by remote host")
        assert is_supported_fallback_error(Exception("refused"), err_detail) is True

    def test_http_503_and_service_unavailable(self) -> None:
        exc = CustomNetworkError("Backend service unavailable", status_code=503)
        assert is_supported_fallback_error(exc) is True

        for code in ("SERVICE_UNAVAILABLE", "HTTP_503", "UNAVAILABLE", "BAD_GATEWAY", "GATEWAY_TIMEOUT"):
            err_detail = STTErrorDetail(code=code, message="Provider unavailable")
            assert is_supported_fallback_error(Exception("503"), err_detail) is True

    def test_timeout_failures(self) -> None:
        assert is_supported_fallback_error(TimeoutError("Operation timed out")) is True
        assert is_supported_fallback_error(concurrent.futures.TimeoutError("Future timed out")) is True

        err_detail = STTErrorDetail(code="TRANSCRIPTION_TIMEOUT", message="Timed out waiting for STT response")
        assert is_supported_fallback_error(Exception("timeout"), err_detail) is True

    def test_programming_errors_never_trigger_fallback(self) -> None:
        programming_exceptions = [
            ValueError("Invalid value"),
            TypeError("NoneType is not callable"),
            KeyError("missing_key"),
            IndexError("list index out of range"),
            AttributeError("'NoneType' object has no attribute 'process'"),
            NameError("name 'undefined_var' is not defined"),
            AssertionError("Assertion failed"),
            NotImplementedError("Not implemented"),
        ]
        for exc in programming_exceptions:
            assert is_supported_fallback_error(exc) is False

    def test_validation_and_invalid_input_never_trigger_fallback(self) -> None:
        val_exc = STTValidationError("Sample rate must be positive", field_name="sample_rate")
        assert is_supported_fallback_error(val_exc) is False

        for code in ("VALIDATION_ERROR", "INVALID_PAYLOAD", "INVALID_INPUT", "BAD_REQUEST"):
            err_detail = STTErrorDetail(code=code, message="Validation error occurred")
            assert is_supported_fallback_error(Exception("invalid"), err_detail) is False

        bad_req_exc = CustomClientError("Bad Request", status_code=400)
        assert is_supported_fallback_error(bad_req_exc) is False

    def test_authentication_and_authorization_never_trigger_fallback(self) -> None:
        auth_exc = CustomClientError("Unauthorized", status_code=401)
        assert is_supported_fallback_error(auth_exc) is False

        forbidden_exc = CustomClientError("Forbidden", status_code=403)
        assert is_supported_fallback_error(forbidden_exc) is False

        for code in ("UNAUTHENTICATED", "UNAUTHORIZED", "PERMISSION_DENIED", "FORBIDDEN"):
            err_detail = STTErrorDetail(code=code, message="Access denied")
            assert is_supported_fallback_error(Exception("auth"), err_detail) is False

    def test_cancelled_and_closed_states_never_trigger_fallback(self) -> None:
        cancelled_exc = OrchestratorCancelledError("Operation cancelled by caller")
        assert is_supported_fallback_error(cancelled_exc) is False

        closed_exc = OrchestratorClosedError("Orchestrator closed")
        assert is_supported_fallback_error(closed_exc) is False

        for code in ("OPERATION_CANCELLED", "ADAPTER_CLOSED", "CANCELLED", "CLOSED"):
            err_detail = STTErrorDetail(code=code, message="Session terminated")
            assert is_supported_fallback_error(Exception("closed"), err_detail) is False


class TestErrorModelConversionAndSanitization:
    """Targeted tests for STTErrorDetail and ErrorPayload conversion."""

    def test_stt_error_to_backend_error_payload(self) -> None:
        stt_err = STTErrorDetail(
            code="TRANSCRIPTION_TIMEOUT",
            message="Operation timed out after 3 retries",
            request_id="req-123",
            retryable=True,
            details={"attempts": 3},
        )
        payload = stt_err.to_error_payload(correlation_id="corr-999")
        assert isinstance(payload, ErrorPayload)
        assert payload.code == "TRANSCRIPTION_TIMEOUT"
        assert payload.message == "Operation timed out after 3 retries"
        assert payload.message_safe_for_user == "Operation timed out after 3 retries"
        assert payload.retryable is True
        assert payload.correlation_id == "corr-999"
        assert payload.request_id == "req-123"
        assert payload.details_redacted == {"attempts": 3}

        # Wrap in ErrorResponse
        resp = ErrorResponse(error=payload)
        assert resp.error.code == "TRANSCRIPTION_TIMEOUT"

    def test_error_payload_sanitizes_credentials(self) -> None:
        exc = Exception("Failed to connect with token Bearer secret_token_xyz_123456")
        payload = ErrorPayload.from_stt_error(exc)
        assert "Bearer [REDACTED_TOKEN]" in payload.message
        assert "secret_token_xyz" not in payload.message
