"""
Workstream W3: Context & Reasoning Engine
Server HTTP API Endpoint Validation & WorkflowProposal Handoff Tests

Author: Amruta A J (Team SDE 3)
Module: tests.test_server_api_validation
Description:
    Validates server.py HTTP endpoints (/api/reason and /api/preview):
    1. Content-Type header validation (enforces application/json, returns 415 otherwise).
    2. Payload validation (non-string query -> 400, empty/whitespace query -> 400).
    3. Scenario validation (unknown scenario -> 400).
    4. Successful /api/reason returning status, sources, and validated workflow_proposal.
    5. Successful /api/preview returning rendered prompt preview.
"""

from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

# Ensure project root, web, and src are in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WEB_DIR = _PROJECT_ROOT / "web"
_SRC_DIR = _PROJECT_ROOT / "src"
for p in (_WEB_DIR, _SRC_DIR, _PROJECT_ROOT):
    p_str = str(p)
    if p_str not in sys.path:
        sys.path.insert(0, p_str)

_server_path = _PROJECT_ROOT / "server.py"
_spec = importlib.util.spec_from_file_location("root_server", _server_path)
# pyrefly: ignore[bad-argument-type]
_server_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_server_mod)
WorkflowHTTPHandler = _server_mod.WorkflowHTTPHandler


class TestServerAPIValidation(unittest.TestCase):
    """Validation test suite for HTTP API endpoints."""

    def _call_post(self, path: str, headers: dict, payload: dict | bytes) -> tuple[int, dict]:
        if isinstance(payload, dict):
            body = json.dumps(payload).encode("utf-8")
        else:
            body = payload
        req_headers = dict(headers)
        req_headers["Content-Length"] = str(len(body))
        handler = WorkflowHTTPHandler.__new__(WorkflowHTTPHandler)
        handler.path = path
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.headers = req_headers
        handler.server = MagicMock()
        handler.client_address = ("127.0.0.1", 0)
        handler.requestline = f"POST {path} HTTP/1.1"

        captured_status = {}
        handler.send_response = lambda code: captured_status.update({"code": code})
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None

        handler.do_POST()
        code = captured_status.get("code", 500)
        handler.wfile.seek(0)
        raw = handler.wfile.read()
        data = json.loads(raw.decode("utf-8")) if raw else {}
        return code, data

    def test_content_type_enforcement_returns_415(self) -> None:
        """Endpoints must reject non-JSON Content-Type with HTTP 415."""
        code, data = self._call_post("/api/reason", {"Content-Type": "text/plain"}, b'{"user_query": "test"}')
        self.assertEqual(code, 415)
        self.assertIn("application/json", str(data))

        code, data = self._call_post("/api/preview", {"Content-Type": "text/plain"}, b'{"user_query": "test"}')
        self.assertEqual(code, 415)
        self.assertIn("application/json", str(data))

    def test_invalid_user_query_returns_400(self) -> None:
        """Non-string or empty queries must be rejected with HTTP 400."""
        json_headers = {"Content-Type": "application/json"}

        # Non-string query
        code, data = self._call_post("/api/reason", json_headers, {"user_query": 999})
        self.assertEqual(code, 400)
        self.assertIn("must be a non-empty string", str(data))

        # Empty/whitespace query
        code, data = self._call_post("/api/reason", json_headers, {"user_query": "   \n\t  "})
        self.assertEqual(code, 400)
        self.assertIn("cannot be empty", str(data))

    def test_unknown_scenario_returns_400(self) -> None:
        """Unrecognized scenario parameter must be rejected with HTTP 400."""
        json_headers = {"Content-Type": "application/json"}
        code, data = self._call_post(
            "/api/reason",
            json_headers,
            {"user_query": "audit task", "scenario": "nonexistent_scenario"},
        )
        self.assertEqual(code, 400)
        self.assertIn("Unknown scenario", str(data))

        code, data = self._call_post(
            "/api/preview",
            json_headers,
            {"user_query": "audit task", "scenario": "nonexistent_scenario"},
        )
        self.assertEqual(code, 400)
        self.assertIn("Unknown scenario", str(data))

    def test_api_reason_happy_path_with_proposal(self) -> None:
        """Valid /api/reason query must return 200, sources, status, and validated workflow_proposal."""
        json_headers = {"Content-Type": "application/json"}
        code, data = self._call_post("/api/reason", json_headers, {
            "user_query": "check task status for audit",
            "scenario": "error",
        })
        self.assertEqual(code, 200)
        self.assertIn("status", data)
        self.assertIn("sources", data)
        self.assertIn("workflow_proposal", data)
        self.assertIsNotNone(data["workflow_proposal"])
        self.assertEqual(data["workflow_proposal"]["status"], "validated")

    def test_api_preview_happy_path(self) -> None:
        """Valid /api/preview query must return 200 with rendered prompt preview."""
        json_headers = {"Content-Type": "application/json"}
        code, data = self._call_post("/api/preview", json_headers, {
            "user_query": "check task status for audit",
            "scenario": "error",
        })
        self.assertEqual(code, 200)
        self.assertIn("rendered_prompt", data)


if __name__ == "__main__":
    unittest.main()
