"""Tests for Request ID and Correlation ID middleware."""
from starlette.testclient import TestClient


def test_middleware_generates_request_and_correlation_ids(client: TestClient):
    """Verifies that headers are automatically created when not passed in the request."""
    response = client.get("/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert "X-Correlation-ID" in response.headers
    assert response.headers["X-Request-ID"].startswith("req-")
    assert response.headers["X-Correlation-ID"].startswith("corr-")


def test_middleware_preserves_client_provided_ids(client: TestClient):
    """Verifies that client-provided IDs are echoed back in the response headers."""
    req_id = "custom-req-12345"
    corr_id = "custom-corr-67890"

    response = client.get(
        "/health",
        headers={
            "X-Request-ID": req_id,
            "X-Correlation-ID": corr_id,
        },
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == req_id
    assert response.headers["X-Correlation-ID"] == corr_id


def test_middleware_preserves_ids_on_error_responses(client: TestClient):
    """Verifies that error responses also carry both tracking headers."""
    corr_id = "trace-correlation-error-99"

    response = client.get(
        "/api/v1/sessions/non-existent-session-id",
        headers={"X-Correlation-ID": corr_id},
    )
    assert response.status_code == 404
    assert response.headers["X-Correlation-ID"] == corr_id
    assert "X-Request-ID" in response.headers

    data = response.json()
    assert "error" in data
    assert data["error"]["correlation_id"] == corr_id
