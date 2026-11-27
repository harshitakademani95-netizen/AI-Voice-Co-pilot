"""
Tests for HTTP Security Guardrails in server.py (W4 Agentic Workflow Engine).

Tests the actual do_POST() request-processing logic by constructing the handler
directly — without a real network socket — using the standard mock pattern for
BaseHTTPRequestHandler. This approach is necessary in environments where
loopback TCP connections between threads are restricted by the OS network layer.

Covers:
- Requests missing X-Session-Token header return HTTP 403.
- Requests with an empty X-Session-Token return HTTP 403.
- Requests with an incorrect X-Session-Token value return HTTP 403.
- Requests with Content-Type != application/json return HTTP 415.
- Requests with no Content-Type header at all return HTTP 415.
- Content-Type check fires BEFORE CSRF check (415 wins when both are wrong).
- Checks apply to all five W4 POST endpoints.
- W3 endpoints (/api/reason, /api/preview) are excluded from CSRF enforcement.
- A request with correct Content-Type AND correct session token is accepted (200).
- Error response bodies contain the expected diagnostic strings.
"""

import io
import json
from unittest.mock import MagicMock

import pytest

import server
# pyrefly: ignore[missing-module-attribute]
from server import SESSION_TOKEN, WorkflowHTTPHandler, init_demo_plan


# ---------------------------------------------------------------------------
# Shared test infrastructure
# ---------------------------------------------------------------------------

class _FakeHeaders(dict):
    """
    Minimal case-insensitive header mapping matching the interface used by
    WorkflowHTTPHandler (which calls self.headers.get(key, default)).
    """
    def get(self, key: str, default=None):
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


def _run_handler(path: str, headers: _FakeHeaders, body: bytes = b"{}"):
    """
    Build a WorkflowHTTPHandler instance without a real network socket,
    invoke do_POST(), and return (status_code, response_body_dict).

    The handler is constructed via __new__ so the socket-bound __init__ is
    skipped. All I/O is wired to in-process BytesIO buffers.  The
    send_response / send_header / end_headers methods are replaced with
    lightweight captures so that _send_json() can run end-to-end, including
    writing the JSON payload to wfile.
    """
    captured_status: dict = {}
    written_chunks: list = []

    handler = WorkflowHTTPHandler.__new__(WorkflowHTTPHandler)
    handler.path = path
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.headers = headers
    handler.server = MagicMock()
    handler.client_address = ("127.0.0.1", 0)
    handler.requestline = f"POST {path} HTTP/1.1"
    # Required by BaseHTTPRequestHandler.send_response in some Python builds
    handler.log_date_time_string = lambda: "00/Jan/2000 00:00:00"

    handler.send_response = lambda code, msg=None: captured_status.update(status=code)
    handler.send_header = lambda k, v: None
    handler.end_headers = lambda: None
    # pyrefly: ignore[bad-assignment]
    handler.wfile.write = lambda b: written_chunks.append(b)

    handler.do_POST()

    raw = b"".join(written_chunks).decode("utf-8") if written_chunks else "{}"
    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    return captured_status.get("status"), data


# ---------------------------------------------------------------------------
# Parametrised constants
# ---------------------------------------------------------------------------

#: All five W4 POST endpoints that require CSRF + Content-Type enforcement
_W4_ENDPOINTS = [
    "/api/v1/agent/run",
    "/api/v1/agent/pause",
    "/api/v1/agent/reset",
    "/api/v1/agent/failing_scenario",
    "/api/v1/approvals",
]

#: W3 endpoints that are intentionally excluded from CSRF enforcement
_W3_EXEMPT_ENDPOINTS = ["/api/reason", "/api/preview"]


# ---------------------------------------------------------------------------
# Fixture: ensure a valid plan exists before each test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_server_state():
    """Re-initialise the demo plan before every test for isolation."""
    init_demo_plan()


# ---------------------------------------------------------------------------
# Content-Type enforcement (HTTP 415)
# ---------------------------------------------------------------------------

class TestContentTypeEnforcement:
    """POST requests with an unsupported Content-Type must return HTTP 415."""

    def test_no_content_type_returns_415(self):
        """Omitting Content-Type entirely triggers 415 Unsupported Media Type."""
        status, data = _run_handler(
            "/api/v1/agent/run",
            _FakeHeaders({"X-Session-Token": SESSION_TOKEN}),
        )
        assert status == 415
        assert "Unsupported Media Type" in data["error"]

    def test_text_plain_content_type_returns_415(self):
        """Content-Type: text/plain triggers 415."""
        status, data = _run_handler(
            "/api/v1/agent/run",
            _FakeHeaders({
                "Content-Type": "text/plain",
                "X-Session-Token": SESSION_TOKEN,
            }),
        )
        assert status == 415
        assert "Unsupported Media Type" in data["error"]

    def test_form_urlencoded_content_type_returns_415(self):
        """Content-Type: application/x-www-form-urlencoded triggers 415."""
        status, data = _run_handler(
            "/api/v1/agent/run",
            _FakeHeaders({
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Session-Token": SESSION_TOKEN,
            }),
        )
        assert status == 415
        assert "Unsupported Media Type" in data["error"]

    def test_text_html_content_type_returns_415(self):
        """Content-Type: text/html triggers 415."""
        status, data = _run_handler(
            "/api/v1/agent/run",
            _FakeHeaders({
                "Content-Type": "text/html",
                "X-Session-Token": SESSION_TOKEN,
            }),
        )
        assert status == 415
        assert "Unsupported Media Type" in data["error"]

    def test_415_check_fires_before_csrf_check(self):
        """
        Content-Type is validated BEFORE the CSRF token.
        A request with a wrong Content-Type AND no session token must return
        415, not 403 — confirming the documented check ordering in do_POST().
        """
        status, data = _run_handler(
            "/api/v1/agent/run",
            _FakeHeaders({"Content-Type": "text/html"}),  # bad CT, no CSRF
        )
        assert status == 415, (
            "Expected 415 (Content-Type checked before CSRF) but got " + str(status)
        )

    @pytest.mark.parametrize("endpoint", _W4_ENDPOINTS)
    def test_wrong_content_type_on_all_w4_endpoints_returns_415(self, endpoint):
        """All five W4 endpoints reject unsupported Content-Type with 415."""
        status, data = _run_handler(
            endpoint,
            _FakeHeaders({
                "Content-Type": "text/plain",
                "X-Session-Token": SESSION_TOKEN,
            }),
        )
        assert status == 415, (
            f"Expected 415 on {endpoint} but got {status}"
        )
        assert "Unsupported Media Type" in data["error"]


# ---------------------------------------------------------------------------
# CSRF token enforcement (HTTP 403)
# ---------------------------------------------------------------------------

class TestCSRFTokenEnforcement:
    """POST requests with an invalid or absent X-Session-Token must return 403."""

    def test_missing_csrf_token_returns_403(self):
        """Omitting X-Session-Token entirely returns HTTP 403 Forbidden."""
        status, data = _run_handler(
            "/api/v1/agent/run",
            _FakeHeaders({"Content-Type": "application/json"}),
        )
        assert status == 403
        assert "Forbidden" in data["error"]
        assert "X-Session-Token" in data["error"]

    def test_empty_csrf_token_returns_403(self):
        """An empty X-Session-Token value is treated as absent and returns 403."""
        status, data = _run_handler(
            "/api/v1/agent/run",
            _FakeHeaders({
                "Content-Type": "application/json",
                "X-Session-Token": "",
            }),
        )
        assert status == 403
        assert "Forbidden" in data["error"]

    def test_wrong_csrf_token_returns_403(self):
        """An incorrect X-Session-Token value returns HTTP 403."""
        status, data = _run_handler(
            "/api/v1/agent/run",
            _FakeHeaders({
                "Content-Type": "application/json",
                "X-Session-Token": "completely-wrong-token-value",
            }),
        )
        assert status == 403
        assert "Forbidden" in data["error"]

    def test_near_miss_csrf_token_returns_403(self):
        """A token that is nearly correct (off by one character) is rejected."""
        # Flip the last character of the real token
        near_miss = SESSION_TOKEN[:-1] + ("x" if SESSION_TOKEN[-1] != "x" else "y")
        status, data = _run_handler(
            "/api/v1/agent/run",
            _FakeHeaders({
                "Content-Type": "application/json",
                "X-Session-Token": near_miss,
            }),
        )
        assert status == 403

    @pytest.mark.parametrize("endpoint", _W4_ENDPOINTS)
    def test_missing_csrf_on_all_w4_endpoints_returns_403(self, endpoint):
        """All five W4 endpoints enforce the CSRF check and return 403."""
        status, data = _run_handler(
            endpoint,
            _FakeHeaders({"Content-Type": "application/json"}),
        )
        assert status == 403, (
            f"Expected 403 on {endpoint} but got {status}"
        )
        assert "Forbidden" in data["error"]


# ---------------------------------------------------------------------------
# W3 endpoint exemption (CSRF and Content-Type do not apply)
# ---------------------------------------------------------------------------

class TestW3EndpointsExemptFromCSRF:
    """
    W3 endpoints (/api/reason, /api/preview) pre-date the W4 CSRF gate and
    intentionally bypass it. They must NOT return 403 or 415 due to headers.
    They return 400 when the query body is empty, which is their own validation.
    """

    @pytest.mark.parametrize("endpoint", _W3_EXEMPT_ENDPOINTS)
    def test_w3_endpoints_do_not_require_csrf_token(self, endpoint):
        """W3 endpoints must not reject requests due to a missing session token."""
        # Send with valid JSON Content-Type but no X-Session-Token.
        # They will return 400 (empty user_query) but NOT 403 or 415.
        status, data = _run_handler(
            endpoint,
            _FakeHeaders({"Content-Type": "application/json"}),
            body=b'{"user_query": ""}',
        )
        assert status != 403, (
            f"{endpoint} should not apply CSRF check but returned 403"
        )
        assert status != 415, (
            f"{endpoint} should not apply Content-Type check but returned 415"
        )

    @pytest.mark.parametrize("endpoint", _W3_EXEMPT_ENDPOINTS)
    def test_w3_endpoints_require_application_json(self, endpoint):
        """W3 endpoints now enforce Content-Type: application/json (HTTP 415 on text/plain)."""
        status, data = _run_handler(
            endpoint,
            _FakeHeaders({"Content-Type": "text/plain"}),
            body=b"",
        )
        assert status == 415, (
            f"{endpoint} should enforce Content-Type check and return 415"
        )
        assert status != 403, (
            f"{endpoint} should not apply CSRF check but returned 403"
        )


# ---------------------------------------------------------------------------
# Positive path: valid headers succeed
# ---------------------------------------------------------------------------

class TestValidHeadersAccepted:
    """Requests with the correct Content-Type and session token are accepted."""

    def test_valid_reset_request_returns_200(self):
        """A correctly authenticated reset request returns HTTP 200."""
        status, data = _run_handler(
            "/api/v1/agent/reset",
            _FakeHeaders({
                "Content-Type": "application/json",
                "X-Session-Token": SESSION_TOKEN,
            }),
        )
        assert status == 200
        assert "Plan reset to DRAFT" in data["message"]

    def test_valid_failing_scenario_request_returns_200(self):
        """A correctly authenticated failing-scenario request returns HTTP 200."""
        status, data = _run_handler(
            "/api/v1/agent/failing_scenario",
            _FakeHeaders({
                "Content-Type": "application/json",
                "X-Session-Token": SESSION_TOKEN,
            }),
        )
        assert status == 200
        assert "Failing scenario initialized" in data["message"]

    def test_correct_session_token_is_accepted_not_leaked_in_response(self):
        """The session token is not echoed back in any response body."""
        status, data = _run_handler(
            "/api/v1/agent/reset",
            _FakeHeaders({
                "Content-Type": "application/json",
                "X-Session-Token": SESSION_TOKEN,
            }),
        )
        assert status == 200
        # Ensure the token value does not appear anywhere in the response body
        response_str = json.dumps(data)
        assert SESSION_TOKEN not in response_str, (
            "Session token must not be leaked in HTTP response body"
        )

