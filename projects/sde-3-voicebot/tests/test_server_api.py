"""
Tests for Server REST API and HTTP Security Guardrails (Fix 2).

Covers:
- Server binds to 127.0.0.1.
- Rejection of POST requests without Content-Type: application/json (HTTP 415).
- Rejection of POST requests without valid X-Session-Token (HTTP 403).
- Strict validation of approval decision (missing decision returns HTTP 400).
- Resilience against double-click without crashing handler (HTTP 400).
- Full end-to-end HTTP execution and approval flow.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
import pytest

import server
from server import SESSION_TOKEN, WorkflowHTTPHandler, init_demo_plan, executor


@pytest.fixture(scope="module")
def live_server():
    """Start the test server on an ephemeral loopback port."""
    init_demo_plan()
    httpd = HTTPServer(("127.0.0.1", 0), WorkflowHTTPHandler)
    port = httpd.server_port
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    base_url = f"http://127.0.0.1:{port}"

    yield base_url

    httpd.shutdown()
    httpd.server_close()


def make_request(url: str, method: str = "GET", data: dict = None, headers: dict = None):
    req_headers = headers or {}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        if "Content-Type" not in req_headers:
            req_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(err_body)
        except Exception:
            return e.code, {"error": err_body}


class TestServerAPI:
    """Test suite validating server API endpoints and safety guardrails."""

    def test_health_endpoint(self, live_server):
        status, data = make_request(f"{live_server}/api/v1/health")
        assert status == 200
        assert data["status"] == "healthy"

    def test_missing_csrf_token_returns_403(self, live_server):
        """Fix 2: Missing or invalid X-Session-Token header returns HTTP 403."""
        status, data = make_request(
            f"{live_server}/api/v1/agent/run",
            method="POST",
            data={},
            headers={"Content-Type": "application/json"}  # No X-Session-Token
        )
        assert status == 403
        assert "Forbidden" in data["error"]

    def test_wrong_content_type_returns_415(self, live_server):
        """Fix 2: POST requests without application/json return HTTP 415."""
        status, data = make_request(
            f"{live_server}/api/v1/agent/run",
            method="POST",
            data={},
            headers={
                "Content-Type": "text/plain",
                "X-Session-Token": SESSION_TOKEN,
            }
        )
        assert status == 415
        assert "Unsupported Media Type" in data["error"]

    def test_missing_decision_returns_400(self, live_server):
        """Fix 2: Missing decision parameter in approval returns HTTP 400."""
        # Ensure plan is initialized
        make_request(
            f"{live_server}/api/v1/agent/reset",
            method="POST",
            data={},
            headers={"Content-Type": "application/json", "X-Session-Token": SESSION_TOKEN}
        )
        # Run until awaiting_approval
        make_request(
            f"{live_server}/api/v1/agent/run",
            method="POST",
            data={},
            headers={"Content-Type": "application/json", "X-Session-Token": SESSION_TOKEN}
        )

        status, state_data = make_request(f"{live_server}/api/v1/state")
        pending_req = state_data["pending_approval"]
        assert pending_req is not None

        # Send request with invalid / missing decision
        status, err_data = make_request(
            f"{live_server}/api/v1/approvals",
            method="POST",
            data={"approval_id": pending_req["approval_id"], "decision": "invalid_choice"},
            headers={"Content-Type": "application/json", "X-Session-Token": SESSION_TOKEN}
        )
        assert status == 400
        assert "must be exactly 'approve' or 'reject'" in err_data["error"]

    def test_double_click_approval_does_not_crash(self, live_server):
        """Fix 2: Double-click approval does not crash server; returns HTTP 400 error."""
        # Reset and run to gate
        make_request(
            f"{live_server}/api/v1/agent/reset",
            method="POST",
            data={},
            headers={"Content-Type": "application/json", "X-Session-Token": SESSION_TOKEN}
        )
        make_request(
            f"{live_server}/api/v1/agent/run",
            method="POST",
            data={},
            headers={"Content-Type": "application/json", "X-Session-Token": SESSION_TOKEN}
        )

        _, state_data = make_request(f"{live_server}/api/v1/state")
        approval_id = state_data["pending_approval"]["approval_id"]

        # First click: successfully approved
        status1, data1 = make_request(
            f"{live_server}/api/v1/approvals",
            method="POST",
            data={"approval_id": approval_id, "decision": "approve", "by": "Suhani A (SDE 3)"},
            headers={"Content-Type": "application/json", "X-Session-Token": SESSION_TOKEN}
        )
        assert status1 == 200
        assert data1["result"]["final_state"] == "succeeded"

        # Second click: must return HTTP 400 and not crash the handler
        status2, data2 = make_request(
            f"{live_server}/api/v1/approvals",
            method="POST",
            data={"approval_id": approval_id, "decision": "approve", "by": "Suhani A (SDE 3)"},
            headers={"Content-Type": "application/json", "X-Session-Token": SESSION_TOKEN}
        )
        assert status2 == 400
        assert "already been resolved" in data2["error"]

    def test_full_approval_flow_end_to_end_http(self, live_server):
        """Fix 1 & Fix 2: Full HTTP workflow run -> awaiting_approval -> approved -> succeeded."""
        # 1. Reset
        status, _ = make_request(
            f"{live_server}/api/v1/agent/reset",
            method="POST",
            data={},
            headers={"Content-Type": "application/json", "X-Session-Token": SESSION_TOKEN}
        )
        assert status == 200

        # 2. Run phase 1
        status, run_data = make_request(
            f"{live_server}/api/v1/agent/run",
            method="POST",
            data={},
            headers={"Content-Type": "application/json", "X-Session-Token": SESSION_TOKEN}
        )
        assert status == 200
        assert run_data["final_state"] == "awaiting_approval"

        # 3. Approve via HTTP
        status, state_data = make_request(f"{live_server}/api/v1/state")
        approval_id = state_data["pending_approval"]["approval_id"]

        status, app_data = make_request(
            f"{live_server}/api/v1/approvals",
            method="POST",
            data={
                "approval_id": approval_id,
                "decision": "approve",
                "by": "Suhani A (SDE 3)",
                "comment": "HTTP verified"
            },
            headers={"Content-Type": "application/json", "X-Session-Token": SESSION_TOKEN}
        )
        assert status == 200
        assert app_data["result"]["final_state"] == "succeeded"
        assert "step-002" in app_data["result"]["executed_step_ids"]

    def test_failing_scenario_deliberate_error_and_state_failed(self, live_server):
        """Fix 5: Failing demonstration scenario deliberately uses invalid input and sets FAILED."""
        # 1. Load failing scenario
        status, load_data = make_request(
            f"{live_server}/api/v1/agent/failing_scenario",
            method="POST",
            data={},
            headers={"Content-Type": "application/json", "X-Session-Token": SESSION_TOKEN}
        )
        assert status == 200
        assert "Failing scenario initialized" in load_data["message"]

        # Check state is DRAFT
        status, state_data = make_request(f"{live_server}/api/v1/state")
        assert state_data["state"] == "draft"
        assert state_data["plan"]["workflow_id"] == "plan-fail-scenario"

        # 2. Run failing scenario
        status, run_data = make_request(
            f"{live_server}/api/v1/agent/run",
            method="POST",
            data={},
            headers={"Content-Type": "application/json", "X-Session-Token": SESSION_TOKEN}
        )
        assert status == 200
        assert run_data["final_state"] == "failed"
        assert "task_id" in (run_data["error"] or "")

        # 3. Check state reflects FAILED and has clear error diagnostic
        status, state_after = make_request(f"{live_server}/api/v1/state")
        assert state_after["state"] == "failed"
        assert "task_id" in (state_after["error_message"] or "")
        failed_step = state_after["plan"]["steps"][0]
        assert failed_step["status"] == "failed"
        assert "task_id" in (failed_step["error"] or "")

    def test_reset_clears_previous_run_state_and_outputs(self, live_server):
        """Fix 5 & Requirement 6: Resetting the plan clears the previous run's state and outputs correctly."""
        # 1. Reset
        status, reset_data = make_request(
            f"{live_server}/api/v1/agent/reset",
            method="POST",
            data={},
            headers={"Content-Type": "application/json", "X-Session-Token": SESSION_TOKEN}
        )
        assert status == 200
        assert "Plan reset to DRAFT" in reset_data["message"]

        # 2. Verify state is completely reset to DRAFT
        status, state_data = make_request(f"{live_server}/api/v1/state")
        assert state_data["state"] == "draft"
        assert state_data["pending_approval"] is None
        assert state_data["error_message"] is None
        assert state_data["plan"]["workflow_id"] == "plan-web-001"

        # All steps must be PENDING with no output or error
        for step in state_data["plan"]["steps"]:
            assert step["status"] == "pending"
            assert step["output"] is None
            assert step["error"] is None

