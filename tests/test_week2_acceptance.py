
"""Week 2 Acceptance Tests for AI Voice Co-Pilot Backend (Workstream W5).

Comprehensive acceptance test suite validating:
1. Lifecycle transitions & typed error envelopes on illegal transitions.
2. Idempotency-Key support and duplicate command suppression.
3. Event stream monotonic ordering and reconnection via Last-Event-ID.
4. Request validation (malformed JSON, wrong types, payload limits) and correlation ID propagation.
5. Configuration validation and default mock mode.
6. Structured JSON logging, correlation IDs, and credential protection.
7. Schema uniqueness verification (no duplicate model names).
"""

from __future__ import annotations

import ast
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
import pytest
from starlette.testclient import TestClient

from src.config import Settings, settings, validate_configuration
from src.core.idempotency import idempotency_manager
from src.models.session import SessionState
from src.repositories.session_repository import session_repository


# ---------------------------------------------------------------------------
# 1. Lifecycle transitions & error envelopes
# ---------------------------------------------------------------------------

def test_acceptance_01_lifecycle_transitions_and_typed_error_envelope(client: TestClient):
    """Asserts full legal lifecycle flow and typed error envelope on illegal transitions."""
    # Create
    res = client.post("/api/v1/sessions", json={"metadata": {"test": "acc_01"}})
    assert res.status_code == 201
    sid = res.json()["session_id"]
    assert res.json()["state"] == "created"

    # Transition -> active
    res = client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "active"})
    assert res.status_code == 200
    assert res.json()["state"] == "active"

    # Pause -> paused
    res = client.post(f"/api/v1/sessions/{sid}/pause")
    assert res.status_code == 200
    assert res.json()["state"] == "paused"

    # Resume -> active
    res = client.post(f"/api/v1/sessions/{sid}/resume")
    assert res.status_code == 200
    assert res.json()["state"] == "active"

    # Stop -> stopped
    res = client.post(f"/api/v1/sessions/{sid}/stop")
    assert res.status_code == 200
    assert res.json()["state"] == "stopped"

    # Illegal transition: stopped -> active
    res = client.post(
        f"/api/v1/sessions/{sid}/resume",
        headers={"X-Correlation-ID": "corr-illegal-01", "X-Request-ID": "req-illegal-01"},
    )
    assert res.status_code == 409
    body = res.json()
    assert "error" in body
    err = body["error"]
    assert err["code"] == "INVALID_STATE_TRANSITION"
    assert "message" in err
    assert "request_id" in err
    assert err["request_id"] == "req-illegal-01"
    assert err["correlation_id"] == "corr-illegal-01"

    # Expiry verification
    res = client.post("/api/v1/sessions")
    sid_exp = res.json()["session_id"]
    past_time = (datetime.now(timezone.utc) - timedelta(seconds=settings.session_ttl_seconds + 60)).isoformat()
    session = session_repository._sessions[sid_exp]
    session.updated_at = past_time

    # Query triggers expiry
    get_res = client.get(f"/api/v1/sessions/{sid_exp}")
    assert get_res.status_code == 200
    assert get_res.json()["state"] == "expired"
    assert any(e["event_type"] == "session_expired" for e in get_res.json()["events"])

    # Commands on expired session return 409 with typed error envelope
    res = client.post(f"/api/v1/sessions/{sid_exp}/pause")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


# ---------------------------------------------------------------------------
# 2. Idempotency & duplicate command handling
# ---------------------------------------------------------------------------

def test_acceptance_02_idempotency_duplicate_command_handling(client: TestClient):
    """Asserts that identical idempotency keys return identical cached responses without duplication."""
    idem_key = "idem-acceptance-key-001"
    payload = {"metadata": {"agent": "copilot-test"}}

    # First execution
    res1 = client.post(
        "/api/v1/sessions",
        json=payload,
        headers={"Idempotency-Key": idem_key, "X-Correlation-ID": "corr-idem-1"},
    )
    assert res1.status_code == 201
    sid1 = res1.json()["session_id"]

    # Re-sending identical request with same key returns cached response
    res2 = client.post(
        "/api/v1/sessions",
        json=payload,
        headers={"Idempotency-Key": idem_key, "X-Correlation-ID": "corr-idem-2"},
    )
    assert res2.status_code == 201
    assert res2.json()["session_id"] == sid1

    # Sending different body with the same key triggers 409 IDEMPOTENCY_CONFLICT
    res3 = client.post(
        "/api/v1/sessions",
        json={"metadata": {"different": "payload"}},
        headers={"Idempotency-Key": idem_key},
    )
    assert res3.status_code == 409
    assert res3.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


# ---------------------------------------------------------------------------
# 3. Event streaming, monotonic ordering & Last-Event-ID resumption
# ---------------------------------------------------------------------------

def test_acceptance_03_event_streaming_order_and_reconnection(client: TestClient):
    """Asserts monotonic event IDs and seamless replay with Last-Event-ID."""
    # Create session and generate several state events
    res = client.post("/api/v1/sessions")
    sid = res.json()["session_id"]
    client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "active"})
    client.post(f"/api/v1/sessions/{sid}/pause")
    client.post(f"/api/v1/sessions/{sid}/resume")
    client.post(f"/api/v1/sessions/{sid}/stop")

    # Fetch events history
    res = client.get(f"/api/v1/sessions/{sid}/events")
    assert res.status_code == 200
    events = res.json()["events"]
    assert len(events) >= 5

    # Check monotonic sequence numbers
    seq_nums = [e["sequence_number"] for e in events]
    assert seq_nums == sorted(seq_nums)
    assert seq_nums == list(range(1, len(events) + 1))

    # Test reconnection from 2nd event via Last-Event-ID using stream
    midpoint_event_id = events[1]["event_id"]
    headers = {"Last-Event-ID": midpoint_event_id, "Accept": "text/event-stream"}
    with client.stream("GET", f"/api/v1/sessions/{sid}/events/stream", headers=headers) as stream:
        reconnected_events = []
        for line in stream.iter_lines():
            if line and line.startswith("event:"):
                reconnected_events.append(line.replace("event:", "").strip())
            if len(reconnected_events) >= 2:
                break
        # First event after midpoint should be present
        assert len(reconnected_events) >= 2
        assert reconnected_events[0] == events[2]["event_type"]


# ---------------------------------------------------------------------------
# 4. Request validation, payload size limits, and correlation headers
# ---------------------------------------------------------------------------

def test_acceptance_04_request_validation_and_payload_limits(client: TestClient):
    """Asserts 400/413/422 status codes with correlation ID header and error body."""
    # 1. Malformed JSON syntax (HTTP 400/422)
    res = client.post(
        "/api/v1/sessions",
        content=b"{invalid-json: none",
        headers={"Content-Type": "application/json", "X-Correlation-ID": "corr-malformed"},
    )
    assert res.status_code in (400, 422)
    assert res.headers.get("X-Correlation-ID") == "corr-malformed"
    assert res.json()["error"]["correlation_id"] == "corr-malformed"
    assert "request_id" in res.json()["error"]

    # 2. Wrong field types (HTTP 422)
    res = client.post("/api/v1/sessions")
    sid = res.json()["session_id"]
    res = client.post(
        f"/api/v1/sessions/{sid}/transition",
        json={"to_state": 12345},  # wrong type
        headers={"X-Correlation-ID": "corr-bad-type"},
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"
    assert res.headers.get("X-Correlation-ID") == "corr-bad-type"
    assert res.json()["error"]["correlation_id"] == "corr-bad-type"

    # 3. Oversized payload (HTTP 413)
    oversized = "A" * (1024 * 1024 + 500)  # > 1MB
    res = client.post(
        "/api/v1/sessions",
        content=oversized.encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Correlation-ID": "corr-oversized"},
    )
    assert res.status_code == 413
    assert res.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert res.headers.get("X-Correlation-ID") == "corr-oversized"
    assert res.json()["error"]["correlation_id"] == "corr-oversized"


# ---------------------------------------------------------------------------
# 5. Configuration validation and default mock mode
# ---------------------------------------------------------------------------

def test_acceptance_05_configuration_validation_and_default_mock_mode(monkeypatch):
    """Asserts invalid config fails startup fast and mock mode is active by default."""
    for key in ("OPENAI_API_KEY", "DEEPGRAM_API_KEY", "ANTHROPIC_API_KEY", "BACKEND_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    # Default config has mock_mode enabled
    cfg = Settings()
    assert cfg.mock_mode is True

    # Bad port (< 1 or > 65535)
    with pytest.raises(ValueError, match="(?i)port"):
        validate_configuration(Settings(port=70000))

    # Negative session TTL
    with pytest.raises(ValueError, match="(?i)session_ttl"):
        validate_configuration(Settings(session_ttl_seconds=-10))

    # Payload limit too low (< 1024)
    with pytest.raises(ValueError, match="(?i)payload_size"):
        validate_configuration(Settings(max_payload_size_bytes=-500))

    # Prod mode without API keys fails startup
    with pytest.raises(ValueError, match="(?i)credentials"):
        validate_configuration(Settings(mock_mode=False))


# ---------------------------------------------------------------------------
# 6. Structured JSON logging, correlation IDs & credential protection
# ---------------------------------------------------------------------------

def test_acceptance_06_structured_json_logging_and_credential_protection(client: TestClient, capsys: pytest.CaptureFixture):
    """Asserts structured JSON logs with correlation ID and zero secret leakage."""
    from src.core.logging_config import configure_logging
    configure_logging("INFO")
    capsys.readouterr()

    secret_key = "sk-supersecretkey999"
    secret_pass = "topsecretpassword456"

    res = client.post(
        "/api/v1/sessions",
        json={"api_key": secret_key, "password": secret_pass},
        headers={"X-Correlation-ID": "corr-log-test-123"},
    )
    assert res.status_code == 201

    # Inspect structured log output written to stdout
    out, err = capsys.readouterr()
    assert secret_key not in out
    assert secret_pass not in out
    assert secret_key not in err
    assert secret_pass not in err

    # Validate JSON structure and correlation ID presence
    found_json = False
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if data.get("correlation_id") == "corr-log-test-123":
                found_json = True
                assert "request_id" in data
                assert "duration_ms" in data
                assert secret_key not in line
                assert secret_pass not in line
        except json.JSONDecodeError:
            pass

    assert found_json is True


# ---------------------------------------------------------------------------
# 7. No duplicate schemas across modules
# ---------------------------------------------------------------------------

def test_acceptance_07_no_duplicate_pydantic_schemas():
    """Asserts that no Pydantic model name is defined in more than one module in src/models."""
    src_models_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "models"
    )

    models_by_name: dict[str, list[str]] = {}

    for root, _, files in os.walk(src_models_dir):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=path)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        # Track class definition
                        models_by_name.setdefault(node.name, []).append(f)

    duplicates = {name: files for name, files in models_by_name.items() if len(files) > 1}
    assert duplicates == {}, f"Duplicate schema models found in src/models: {duplicates}"
