"""Tests for typed error envelope and sensitive data redaction."""
from starlette.testclient import TestClient

from src.core.security import redact_sensitive_data


def test_typed_error_envelope_structure(client: TestClient):
    """Verifies that error response conforms to the typed error envelope contract."""
    response = client.get(
        "/api/v1/sessions/session-does-not-exist",
        headers={"X-Correlation-ID": "test-corr-404"},
    )
    assert response.status_code == 404
    data = response.json()

    assert "error" in data
    error = data["error"]
    assert "code" in error
    assert "message_safe_for_user" in error
    assert "retryable" in error
    assert "correlation_id" in error
    assert "details_redacted" in error
    assert error["code"] == "SESSION_NOT_FOUND"
    assert error["retryable"] is False
    assert error["correlation_id"] == "test-corr-404"


def test_validation_error_envelope(client: TestClient):
    """Verifies that Pydantic validation errors return the typed error envelope with 422."""
    # Attempt to transition session with an invalid state string
    # First create a valid session
    create_res = client.post("/api/v1/sessions")
    sid = create_res.json()["session_id"]

    # Post invalid body
    response = client.post(
        f"/api/v1/sessions/{sid}/transition",
        json={"to_state": "INVALID_STATE_NAME"},
    )
    assert response.status_code == 422
    data = response.json()
    assert "error" in data
    error = data["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert "details_redacted" in error
    assert isinstance(error["details_redacted"], list)


def test_redact_sensitive_data_keys():
    """Verifies that dictionary keys containing sensitive terms are redacted."""
    raw_payload = {
        "session_id": "session-1",
        "api_key": "sk-1234567890abcdef1234567890",
        "access_token": "secret-jwt-token-value",
        "user_password": "PlainPassword123!",
        "safe_field": "public_information",
    }
    redacted = redact_sensitive_data(raw_payload)

    assert redacted["session_id"] == "session-1"
    assert redacted["safe_field"] == "public_information"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["access_token"] == "[REDACTED]"
    assert redacted["user_password"] == "[REDACTED]"


def test_redact_sensitive_data_strings():
    """Verifies that string contents matching sensitive patterns are redacted."""
    msg = "Authentication failed with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    redacted = redact_sensitive_data(msg)
    assert "Bearer [REDACTED]" in redacted
    assert "eyJhbGciOiJI" not in redacted


def test_unhandled_exception_does_not_leak_internals():
    """Verifies that an unhandled 500 error does not leak tracebacks to the client."""
    from src.app import create_app
    app = create_app()

    @app.get("/test-internal-crash")
    def crash():
        raise RuntimeError("Database connection string: postgres://root:supersecretpass@db:5432/db")

    with TestClient(app, raise_server_exceptions=False) as custom_client:
        response = custom_client.get("/test-internal-crash")
        assert response.status_code == 500
        data = response.json()
        assert "error" in data
        error = data["error"]
        assert error["code"] == "INTERNAL_SERVER_ERROR"
        assert "supersecretpass" not in str(data)
        assert "RuntimeError" not in str(data)
        assert error["retryable"] is True
