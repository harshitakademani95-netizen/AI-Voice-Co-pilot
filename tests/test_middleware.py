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


def test_configure_logging_twice_leaves_one_handler():
    """Task 1.a: Calling configure_logging twice leaves exactly one handler."""
    import logging
    from src.core.logging_config import configure_logging

    configure_logging()
    configure_logging()
    backend_logger = logging.getLogger("backend")
    assert len(backend_logger.handlers) == 1


def test_get_health_logs_json_line_with_ids(client: TestClient, capsys):
    """Task 1.b: GET /api/v1/health prints one line that parses as JSON with correlation_id and request_id."""
    import json
    from src.core.logging_config import configure_logging

    configure_logging("INFO")
    capsys.readouterr()
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    out, _ = capsys.readouterr()

    json_lines = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if parsed.get("event") == "http_request":
                json_lines.append(parsed)
        except json.JSONDecodeError:
            pass

    assert len(json_lines) >= 1
    log_entry = json_lines[-1]
    assert "correlation_id" in log_entry
    assert "request_id" in log_entry
    assert log_entry["path"] == "/api/v1/health"
    assert log_entry["status_code"] == 200


def test_request_body_secrets_never_appear_in_log_output(client: TestClient, capsys):
    """Task 1.c: 'sk-supersecretkey999' sent in a request body never appears in the output."""
    from src.core.logging_config import configure_logging

    configure_logging("INFO")
    capsys.readouterr()
    secret = "sk-supersecretkey999"
    res = client.post("/api/v1/sessions", json={"secret_token": secret})
    assert res.status_code == 201
    out, err = capsys.readouterr()

    assert secret not in out
    assert secret not in err


def test_log_level_warning_suppresses_info_access_line(client: TestClient, capsys):
    """Task 1.d: LOG_LEVEL=WARNING suppresses the INFO access line."""
    from src.core.logging_config import configure_logging

    configure_logging("WARNING")
    try:
        capsys.readouterr()
        res = client.get("/api/v1/health")
        assert res.status_code == 200
        out, _ = capsys.readouterr()
        assert "http_request" not in out
    finally:
        configure_logging("INFO")

