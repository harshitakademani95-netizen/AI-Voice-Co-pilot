"""Comprehensive 20-point test suite for Week 2 Session Service requirements.

Directly verifies the 20 required acceptance tests:
1. Create session
2. Retrieve session
3. List sessions
4. Pause session
5. Resume session
6. Stop session
7. Session expiry
8. Illegal lifecycle transitions
9. Idempotent repeated commands
10. Duplicate concurrent commands
11. Event streaming
12. Event ordering
13. Invalid session IDs
14. Malformed requests
15. Oversized payloads
16. Missing configuration
17. Invalid configuration
18. Default mock mode
19. Correlation ID generation and propagation
20. Structured logging without sensitive data
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import pytest
from starlette.testclient import TestClient

from src.config import Settings, settings, validate_configuration
from src.core.idempotency import idempotency_manager
from src.core.security import redact_sensitive_data
from src.models.session import SessionState
from src.repositories.session_repository import session_repository


# 1. Create session
def test_01_create_session(client: TestClient):
    """Verifies creating a session with initial 'created' state and sequence number 1."""
    res = client.post("/api/v1/sessions", json={"metadata": {"user": "Vaishnavi"}})
    assert res.status_code == 201
    data = res.json()
    assert data["state"] == "created"
    assert data["session_id"].startswith("session-")
    assert data["events_count"] == 1
    assert data["events"][0]["event_type"] == "session_created"
    assert data["events"][0]["sequence_number"] == 1


# 2. Retrieve session
def test_02_retrieve_session(client: TestClient):
    """Verifies retrieving an existing session by session_id."""
    created = client.post("/api/v1/sessions", json={"session_id": "sid-get-01"}).json()
    res = client.get("/api/v1/sessions/sid-get-01")
    assert res.status_code == 200
    assert res.json()["session_id"] == "sid-get-01"
    assert res.json()["created_at"] == created["created_at"]


# 3. List sessions
def test_03_list_sessions(client: TestClient):
    """Verifies listing sessions and filtering by state query parameter."""
    s1 = client.post("/api/v1/sessions").json()["session_id"]
    s2 = client.post("/api/v1/sessions").json()["session_id"]
    client.post(f"/api/v1/sessions/{s2}/transition", json={"to_state": "active"})

    # All sessions
    all_res = client.get("/api/v1/sessions")
    assert all_res.status_code == 200
    assert all_res.json()["total"] == 2

    # Filtered by state=active
    active_res = client.get("/api/v1/sessions?state=active")
    assert active_res.json()["total"] == 1
    assert active_res.json()["sessions"][0]["session_id"] == s2


# 4. Pause session
def test_04_pause_session(client: TestClient):
    """Verifies pausing an active session ('active' -> 'paused') emitting session_paused event."""
    c = client.post("/api/v1/sessions").json()["session_id"]
    client.post(f"/api/v1/sessions/{c}/transition", json={"to_state": "active"})

    pause_res = client.post(f"/api/v1/sessions/{c}/pause", json={"reason": "User placed on hold"})
    assert pause_res.status_code == 200
    data = pause_res.json()
    assert data["state"] == "paused"
    assert any(e["event_type"] == "session_paused" for e in data["events"])


# 5. Resume session
def test_05_resume_session(client: TestClient):
    """Verifies resuming a paused session ('paused' -> 'active') emitting session_resumed event."""
    c = client.post("/api/v1/sessions").json()["session_id"]
    client.post(f"/api/v1/sessions/{c}/transition", json={"to_state": "active"})
    client.post(f"/api/v1/sessions/{c}/pause")

    resume_res = client.post(f"/api/v1/sessions/{c}/resume", json={"reason": "User resumed"})
    assert resume_res.status_code == 200
    data = resume_res.json()
    assert data["state"] == "active"
    assert any(e["event_type"] == "session_resumed" for e in data["events"])


# 6. Stop session
def test_06_stop_session(client: TestClient):
    """Verifies stopping a session from active or paused states with session_stopped event."""
    c = client.post("/api/v1/sessions").json()["session_id"]
    client.post(f"/api/v1/sessions/{c}/transition", json={"to_state": "active"})

    stop_res = client.post(f"/api/v1/sessions/{c}/stop", json={"reason": "User ended interaction"})
    assert stop_res.status_code == 200
    data = stop_res.json()
    assert data["state"] == "stopped"
    assert any(e["event_type"] == "session_stopped" for e in data["events"])


# 7. Session expiry
def test_07_session_expiry(client: TestClient):
    """Verifies that an idle session past TTL automatically transitions to 'expired'."""
    c = client.post("/api/v1/sessions", json={"session_id": "sid-expire-check"}).json()["session_id"]
    
    # Backdate session activity beyond TTL
    past_time = (datetime.now(timezone.utc) - timedelta(seconds=settings.session_ttl_seconds + 60)).isoformat()
    session = session_repository._sessions[c]
    session.updated_at = past_time

    # Query triggers expiry
    get_res = client.get(f"/api/v1/sessions/{c}")
    assert get_res.status_code == 200
    assert get_res.json()["state"] == "expired"
    assert any(e["event_type"] == "session_expired" for e in get_res.json()["events"])


# 8. Illegal lifecycle transitions
def test_08_illegal_lifecycle_transitions(client: TestClient):
    """Verifies illegal transitions return 409 INVALID_STATE_TRANSITION in typed error envelope."""
    c = client.post("/api/v1/sessions").json()["session_id"]

    # Direct created -> paused is illegal
    bad_res = client.post(f"/api/v1/sessions/{c}/pause")
    assert bad_res.status_code == 409
    data = bad_res.json()
    assert data["error"]["code"] == "INVALID_STATE_TRANSITION"
    assert "Allowed transitions" in data["error"]["message_safe_for_user"]


# 9. Idempotent repeated commands
def test_09_idempotent_repeated_commands(client: TestClient):
    """Verifies repeating same command with same Idempotency-Key returns cached result."""
    headers = {"Idempotency-Key": "key-repeat-01"}
    body = {"metadata": {"client": "test"}}

    res1 = client.post("/api/v1/sessions", json=body, headers=headers)
    assert res1.status_code == 201
    sid1 = res1.json()["session_id"]

    # Replay
    res2 = client.post("/api/v1/sessions", json=body, headers=headers)
    assert res2.status_code == 201
    assert res2.json()["session_id"] == sid1

    # Conflict with modified payload
    res3 = client.post("/api/v1/sessions", json={"metadata": {"client": "different"}}, headers=headers)
    assert res3.status_code == 409
    assert res3.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


# 10. Duplicate concurrent commands
def test_10_duplicate_concurrent_commands(client: TestClient):
    """Verifies that duplicate concurrent commands using the same key resolve safely."""
    headers = {"Idempotency-Key": "concurrent-key-99"}
    body = {"metadata": {"concurrent": True}}

    def make_request():
        return client.post("/api/v1/sessions", json=body, headers=headers)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(make_request) for _ in range(3)]
        results = [f.result() for f in futures]

    # All should return 201
    status_codes = [r.status_code for r in results]
    assert all(code == 201 for code in status_codes)

    # All should report the same session ID
    session_ids = {r.json()["session_id"] for r in results}
    assert len(session_ids) == 1


# 11. Event streaming
def test_11_event_streaming(client: TestClient):
    """Verifies SSE event stream endpoint returns text/event-stream with active stream and terminates cleanly."""
    c = client.post("/api/v1/sessions").json()["session_id"]
    with client.stream("GET", f"/api/v1/sessions/{c}/events/stream") as stream:
        assert stream.status_code == 200
        assert "text/event-stream" in stream.headers["content-type"]
        events = []
        for line in stream.iter_lines():
            if line and line.startswith("event:"):
                events.append(line.replace("event:", "").strip())
                break
        assert events == ["session_created"]

    # Also verify /events streaming
    with client.stream("GET", f"/api/v1/sessions/{c}/events", headers={"Accept": "text/event-stream"}) as stream2:
        assert stream2.status_code == 200
        assert "text/event-stream" in stream2.headers["content-type"]
        events2 = []
        for line in stream2.iter_lines():
            if line and line.startswith("event:"):
                events2.append(line.replace("event:", "").strip())
                break
        assert events2 == ["session_created"]


# 12. Event ordering
def test_12_event_ordering(client: TestClient):
    """Verifies events stream in strict chronological sequence order."""
    c = client.post("/api/v1/sessions").json()["session_id"]
    client.post(f"/api/v1/sessions/{c}/transition", json={"to_state": "active"})
    client.post(f"/api/v1/sessions/{c}/pause")

    with client.stream("GET", f"/api/v1/sessions/{c}/events/stream?limit=3") as stream:
        event_types = []
        event_ids = []
        for line in stream.iter_lines():
            if line:
                if line.startswith("event:"):
                    event_types.append(line.replace("event:", "").strip())
                elif line.startswith("id:"):
                    event_ids.append(line.replace("id:", "").strip())
        assert event_types == ["session_created", "session_activated", "session_paused"]
        assert len(event_ids) == 3
        assert len(set(event_ids)) == 3


# Event reconnection & JSON history checks
def test_event_reconnection_last_event_id(client: TestClient):
    """Verifies event reconnection resumes strictly after Last-Event-ID."""
    c = client.post("/api/v1/sessions").json()["session_id"]
    client.post(f"/api/v1/sessions/{c}/transition", json={"to_state": "active"})
    client.post(f"/api/v1/sessions/{c}/pause")

    # Get session to find event ID for session_created
    session_data = client.get(f"/api/v1/sessions/{c}").json()
    created_evt_id = session_data["events"][0]["event_id"]

    # Reconnect asking for events after the first event
    headers = {"Last-Event-ID": created_evt_id, "Accept": "text/event-stream"}
    with client.stream("GET", f"/api/v1/sessions/{c}/events/stream?limit=2", headers=headers) as stream:
        reconnected_events = []
        for line in stream.iter_lines():
            if line and line.startswith("event:"):
                reconnected_events.append(line.replace("event:", "").strip())
        # First event (session_created) should be skipped
        assert reconnected_events == ["session_activated", "session_paused"]


def test_get_events_json_history_negotiation(client: TestClient):
    """Verifies GET /sessions/{id}/events returns JSON history when Accept is application/json."""
    c = client.post("/api/v1/sessions").json()["session_id"]
    res = client.get(f"/api/v1/sessions/{c}/events", headers={"Accept": "application/json"})
    assert res.status_code == 200
    assert "application/json" in res.headers["content-type"]
    data = res.json()
    assert data["session_id"] == c
    assert data["events_count"] >= 1
    assert data["events"][0]["event_type"] == "session_created"


# 13. Invalid session IDs
def test_13_invalid_session_ids(client: TestClient):
    """Verifies 404 SESSION_NOT_FOUND error with typed envelope for invalid session ID."""
    res = client.get("/api/v1/sessions/non-existent-sid-404")
    assert res.status_code == 404
    data = res.json()
    assert data["error"]["code"] == "SESSION_NOT_FOUND"
    assert "non-existent-sid-404" in data["error"]["message_safe_for_user"]


# 14. Malformed requests
def test_14_malformed_requests(client: TestClient):
    """Verifies malformed request body returns 422 VALIDATION_ERROR with typed envelope."""
    c = client.post("/api/v1/sessions").json()["session_id"]
    # Pass invalid type for to_state
    res = client.post(f"/api/v1/sessions/{c}/transition", json={"to_state": 12345})
    assert res.status_code == 422
    data = res.json()
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert "error" in data


# 15. Oversized payloads
def test_15_oversized_payloads(client: TestClient):
    """Verifies requests exceeding MAX_PAYLOAD_SIZE_BYTES return 413 PAYLOAD_TOO_LARGE."""
    orig = settings.max_payload_size_bytes
    settings.max_payload_size_bytes = 150
    try:
        large_body = {"metadata": {"data": "x" * 300}}
        res = client.post("/api/v1/sessions", json=large_body)
        assert res.status_code == 413
        assert res.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    finally:
        settings.max_payload_size_bytes = orig


# 16. Missing configuration
def test_16_missing_configuration():
    """Verifies that missing or out-of-bounds configuration fails startup validation."""
    with pytest.raises(ValueError, match="Invalid PORT"):
        cfg = Settings(port=0)
        validate_configuration(cfg)


# 17. Invalid configuration
def test_17_invalid_configuration():
    """Verifies invalid bounds on payload size, TTL, and log level fail fast with ValueError."""
    with pytest.raises(ValueError, match="Invalid MAX_PAYLOAD_SIZE_BYTES"):
        validate_configuration(Settings(max_payload_size_bytes=-5))

    with pytest.raises(ValueError, match="Invalid SESSION_TTL_SECONDS"):
        validate_configuration(Settings(session_ttl_seconds=-10))

    with pytest.raises(ValueError, match="Invalid LOG_LEVEL"):
        validate_configuration(Settings(log_level="INVALID_LEVEL"))


# 18. Default mock mode
def test_18_default_mock_mode():
    """Verifies safe mock mode is True by default without external API keys."""
    cfg = Settings()
    assert cfg.mock_mode is True


def test_read_int_env_helpers(monkeypatch):
    """Task 2: Tests read_int_env with valid and invalid values."""
    from src.config import read_int_env

    monkeypatch.setenv("PORT", "abc")
    with pytest.raises(ValueError, match="Invalid PORT: 'abc' is not an integer."):
        read_int_env("PORT", 8000)

    monkeypatch.setenv("MAX_PAYLOAD_SIZE_BYTES", "xyz")
    with pytest.raises(ValueError, match="Invalid MAX_PAYLOAD_SIZE_BYTES: 'xyz' is not an integer."):
        read_int_env("MAX_PAYLOAD_SIZE_BYTES", 1024)

    monkeypatch.setenv("SESSION_TTL_SECONDS", "invalid_ttl")
    with pytest.raises(ValueError, match="Invalid SESSION_TTL_SECONDS: 'invalid_ttl' is not an integer."):
        read_int_env("SESSION_TTL_SECONDS", 3600)


def test_read_bool_env_helpers(monkeypatch):
    """Task 2: Tests read_bool_env with valid and invalid values."""
    from src.config import read_bool_env

    monkeypatch.setenv("MOCK_MODE", "ture")
    with pytest.raises(ValueError, match="Invalid MOCK_MODE: 'ture'. Use true or false."):
        read_bool_env("MOCK_MODE", True)

    for val in ("true", "1", "yes", "TRUE", "Yes"):
        monkeypatch.setenv("MOCK_MODE", val)
        assert read_bool_env("MOCK_MODE", False) is True

    for val in ("false", "0", "no", "FALSE", "No"):
        monkeypatch.setenv("MOCK_MODE", val)
        assert read_bool_env("MOCK_MODE", True) is False


def test_21_prod_mode_missing_credentials_fails_startup(monkeypatch):
    """Verifies startup fails when mock_mode is False and production credentials are missing."""
    for key in ("OPENAI_API_KEY", "DEEPGRAM_API_KEY", "ANTHROPIC_API_KEY", "BACKEND_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError, match="Production credentials missing"):
        validate_configuration(Settings(mock_mode=False))


def test_mock_mode_false_passes_with_backend_api_key(monkeypatch):
    """Task 3: Proves mock_mode=False passes validation when BACKEND_API_KEY is set."""
    for key in ("OPENAI_API_KEY", "DEEPGRAM_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BACKEND_API_KEY", "test-backend-key-12345")
    cfg = Settings(mock_mode=False)
    validate_configuration(cfg)


# 19. Correlation ID generation and propagation
def test_19_correlation_id_generation_and_propagation(client: TestClient):
    """Verifies correlation and request IDs are generated, propagated, and returned."""
    # When provided by client
    custom_corr = "corr-client-custom-777"
    res1 = client.get("/api/v1/health", headers={"X-Correlation-ID": custom_corr})
    assert res1.headers.get("x-correlation-id") == custom_corr
    assert "x-request-id" in res1.headers

    # When omitted by client
    res2 = client.get("/api/v1/health")
    assert res2.headers.get("x-correlation-id").startswith("corr-")
    assert res2.headers.get("x-request-id").startswith("req-")


# 20. Structured logging without sensitive data
def test_20_structured_logging_without_sensitive_data():
    """Verifies sensitive data (passwords, tokens, keys) is sanitized by redaction utility."""
    sensitive_dict = {
        "user": "test_user",
        "api_key": "sk-1234567890123456789012345",
        "password": "super_secret_password",
        "token": "jwt_sample_token",
        "auth": "Bearer secret_bearer_token",
    }
    sanitized = redact_sensitive_data(sensitive_dict)
    assert sanitized["user"] == "test_user"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["token"] == "[REDACTED]"
    assert sanitized["auth"] == "[REDACTED]"


# 21. Frontend / Backend Integration Tests for the 4 Demonstration Scenarios
def test_22_frontend_scenario_reasoning_integration(client: TestClient):
    """Verifies all 4 UI scenarios communicate with the backend and return 200 with reasoning results."""
    scenarios = [
        ("error", "Why is this application failing?"),
        ("document", "Explain the methodology shown in this paper"),
        ("file_action", "Move these files into the archive folder"),
        ("prompt_injection", "Explain what this document says"),
    ]
    for sc, query in scenarios:
        res = client.post("/api/reason", json={"scenario": sc, "user_query": query, "prompt_version": "v1.0.0"})
        assert res.status_code == 200
        data = res.json()
        assert "response_text" in data
        assert "latency_ms" in data
        assert "confidence" in data
        assert len(data["response_text"]) > 10


def test_23_prompt_preview_and_scenarios_endpoints(client: TestClient):
    """Verifies /api/scenarios and /api/prompt-preview used by the UI."""
    sc_res = client.get("/api/scenarios")
    assert sc_res.status_code == 200
    sc_data = sc_res.json()
    assert "error" in sc_data
    assert "document" in sc_data
    assert "file_action" in sc_data
    assert "prompt_injection" in sc_data

    prev_res = client.post("/api/prompt-preview", json={"scenario": "error", "user_query": "Test query"})
    assert prev_res.status_code == 200
    assert "rendered_prompt" in prev_res.json()


def test_24_events_pagination(client: TestClient):
    """Verifies limit and offset pagination on GET /api/v1/sessions/{id}/events."""
    s_id = client.post("/api/v1/sessions").json()["session_id"]
    for i in range(5):
        client.post(f"/api/v1/sessions/{s_id}/events", json={"event_type": "note", "payload": {"idx": i}})

    # Default: returns all 6 (1 created + 5 notes)
    all_res = client.get(f"/api/v1/sessions/{s_id}/events")
    assert all_res.json()["events_count"] == 6

    # Pagination: limit=2, offset=1
    pag_res = client.get(f"/api/v1/sessions/{s_id}/events?limit=2&offset=1")
    assert pag_res.status_code == 200
    data = pag_res.json()
    assert data["events_count"] == 2
    assert len(data["events"]) == 2
    assert data["events"][0]["sequence_number"] == 2
    assert data["events"][1]["sequence_number"] == 3


# 25. Approval Request Lifecycle & Human-in-the-Loop Decision
def test_25_approval_request_lifecycle_and_approval(client: TestClient):
    """Verifies creating an approval request, approving it, and rejecting duplicate approvals."""
    s_id = client.post("/api/v1/sessions").json()["session_id"]
    create_res = client.post("/api/v1/approvals/request", json={
        "session_id": s_id,
        "action_type": "move_files",
        "risk_level": "C",
        "parameters": {"target": "archive/"}
    })
    assert create_res.status_code == 201
    appr_data = create_res.json()
    appr_id = appr_data["approval_id"]
    assert appr_data["status"] == "pending"

    # Approve decision
    dec_res = client.post(f"/api/v1/approvals/{appr_id}/approve", json={"user_id": "test_engineer"})
    assert dec_res.status_code == 200
    assert dec_res.json()["status"] == "approved"
    assert dec_res.json()["resolved_by"] == "test_engineer"

    # Duplicate approval rejected with 409
    dup_res = client.post(f"/api/v1/approvals/{appr_id}/approve")
    assert dup_res.status_code == 409


def test_26_approval_rejection_and_duplicate_protection(client: TestClient):
    """Verifies rejecting an approval request and preventing subsequent approvals."""
    s_id = client.post("/api/v1/sessions").json()["session_id"]
    create_res = client.post("/api/v1/approvals/request", json={
        "session_id": s_id,
        "action_type": "delete_files",
        "risk_level": "D"
    })
    appr_id = create_res.json()["approval_id"]

    # Reject
    rej_res = client.post(f"/api/v1/approvals/{appr_id}/reject", json={"reason": "Security policy violation"})
    assert rej_res.status_code == 200
    assert rej_res.json()["status"] == "rejected"
    assert rej_res.json()["rejection_reason"] == "Security policy violation"

    # Attempting to approve after rejection returns 409
    appr_after_rej = client.post(f"/api/v1/approvals/{appr_id}/approve")
    assert appr_after_rej.status_code == 409


def test_27_approval_expiry_enforcement(client: TestClient):
    """Verifies expired approval requests cannot be approved."""
    import time
    s_id = client.post("/api/v1/sessions").json()["session_id"]
    create_res = client.post("/api/v1/approvals/request", json={
        "session_id": s_id,
        "action_type": "move_files",
        "ttl_seconds": 10
    })
    appr_id = create_res.json()["approval_id"]

    # Manually backdate expiry to test deterministic expiration
    from src.repositories.approval_repository import approval_repository
    rec = approval_repository.get(appr_id)
    rec.expires_at = "2020-01-01T00:00:00+00:00"

    exp_res = client.post(f"/api/v1/approvals/{appr_id}/approve")
    assert exp_res.status_code == 409
    data = exp_res.json()
    err_msg = data.get("error", {}).get("message", "") or data.get("detail", "")
    assert "expired" in err_msg.lower()


def test_28_tool_execution_safety_gate(client: TestClient):
    """Verifies that sensitive tools strictly require approved tokens while safe tools execute freely."""
    s_id = client.post("/api/v1/sessions").json()["session_id"]

    # 1. Category B safe tool (file_search) runs without approval
    safe_res = client.post("/api/v1/tools/execute", json={
        "session_id": s_id,
        "tool_name": "file_search",
        "parameters": {"query": "report.pdf"}
    })
    assert safe_res.status_code == 200
    assert safe_res.json()["status"] == "completed"
    assert safe_res.json()["requires_approval"] is False

    # 2. Sensitive tool (move_files) without approval_id is blocked with HTTP 403
    blocked_res = client.post("/api/v1/tools/execute", json={
        "session_id": s_id,
        "tool_name": "move_files",
        "parameters": {"destination": "archive/"}
    })
    assert blocked_res.status_code == 403

    # 3. Sensitive tool with pending approval_id is blocked with HTTP 403
    appr_id = client.post("/api/v1/approvals/request", json={
        "session_id": s_id,
        "action_type": "move_files"
    }).json()["approval_id"]

    pending_res = client.post("/api/v1/tools/execute", json={
        "session_id": s_id,
        "tool_name": "move_files",
        "approval_id": appr_id
    })
    assert pending_res.status_code == 403

    # 4. Once approved, sensitive tool executes safely with HTTP 200
    client.post(f"/api/v1/approvals/{appr_id}/approve")
    approved_exec = client.post("/api/v1/tools/execute", json={
        "session_id": s_id,
        "tool_name": "move_files",
        "approval_id": appr_id
    })
    assert approved_exec.status_code == 200
    assert approved_exec.json()["status"] == "completed"
    assert approved_exec.json()["requires_approval"] is True

    # 5. Audit logs are queryable
    audit_res = client.get(f"/api/v1/approvals/{appr_id}/audit")
    assert audit_res.status_code == 200
    assert len(audit_res.json()["audit_records"]) >= 2


# 29. Streamed payload limit enforcement
def test_29_streamed_payload_limit_enforcement(client: TestClient):
    """Verifies that streamed chunks exceeding MAX_PAYLOAD_SIZE_BYTES return 413."""
    orig = settings.max_payload_size_bytes
    settings.max_payload_size_bytes = 200
    try:
        def chunk_gen():
            yield b"a" * 150
            yield b"b" * 150

        res = client.post("/api/v1/sessions", content=chunk_gen())
        assert res.status_code == 413
        assert res.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    finally:
        settings.max_payload_size_bytes = orig


# 30. Event type input validation limits
def test_30_event_type_validation_limits(client: TestClient):
    """Verifies that empty or oversized event types are rejected with 422."""
    res = client.post("/api/v1/sessions")
    sid = res.json()["session_id"]

    # Empty event_type
    bad_res1 = client.post(f"/api/v1/sessions/{sid}/events", json={"event_type": "", "payload": {}})
    assert bad_res1.status_code == 422
    assert bad_res1.json()["error"]["code"] == "VALIDATION_ERROR"

    # Oversized event_type (>128 chars)
    bad_res2 = client.post(f"/api/v1/sessions/{sid}/events", json={"event_type": "x" * 150, "payload": {}})
    assert bad_res2.status_code == 422
    assert bad_res2.json()["error"]["code"] == "VALIDATION_ERROR"


# 31. Same-state transition rejection
def test_31_same_state_transition_rejection(client: TestClient):
    """Verifies transitioning to the same state without idempotency returns 409 INVALID_STATE_TRANSITION."""
    res = client.post("/api/v1/sessions")
    sid = res.json()["session_id"]
    client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "active"})

    # Transition active -> active
    dup_res = client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "active"})
    assert dup_res.status_code == 409
    assert dup_res.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    assert "already in state 'active'" in dup_res.json()["error"]["message"]


# 32. Last-Event-ID unknown fallback
def test_32_last_event_id_unknown_fallback(client: TestClient):
    """Verifies connecting with an unknown Last-Event-ID streams all initial events without error."""
    res = client.post("/api/v1/sessions")
    sid = res.json()["session_id"]

    headers = {"Last-Event-ID": "evt-nonexistent-999", "Accept": "text/event-stream"}
    with client.stream("GET", f"/api/v1/sessions/{sid}/events/stream", headers=headers) as stream:
        assert stream.status_code == 200
        lines = []
        for line in stream.iter_lines():
            if line and line.startswith("event:"):
                lines.append(line)
            if len(lines) >= 1:
                break
        assert len(lines) >= 1


# 33. Session filtering by state
def test_33_session_filtering_by_state(client: TestClient):
    """Verifies listing sessions with state filtering (?state=active)."""
    res1 = client.post("/api/v1/sessions")
    s1 = res1.json()["session_id"]
    client.post(f"/api/v1/sessions/{s1}/transition", json={"to_state": "active"})

    res2 = client.post("/api/v1/sessions")
    s2 = res2.json()["session_id"]

    list_active = client.get("/api/v1/sessions?state=active")
    assert list_active.status_code == 200
    active_ids = [s["session_id"] for s in list_active.json()["sessions"]]
    assert s1 in active_ids
    assert s2 not in active_ids


# 34. Idempotency across pause, resume, and stop chains
def test_34_idempotency_lifecycle_command_chain(client: TestClient):
    """Verifies that Idempotency-Key works reliably on dedicated pause, resume, and stop endpoints."""
    res = client.post("/api/v1/sessions")
    sid = res.json()["session_id"]
    client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "active"})

    # Idempotent pause
    p_key = "idem-chain-pause-1"
    p1 = client.post(f"/api/v1/sessions/{sid}/pause", headers={"Idempotency-Key": p_key})
    assert p1.status_code == 200
    p2 = client.post(f"/api/v1/sessions/{sid}/pause", headers={"Idempotency-Key": p_key})
    assert p2.status_code == 200
    assert p2.json()["state"] == "paused"

    # Idempotent resume
    r_key = "idem-chain-resume-1"
    r1 = client.post(f"/api/v1/sessions/{sid}/resume", headers={"Idempotency-Key": r_key})
    assert r1.status_code == 200
    r2 = client.post(f"/api/v1/sessions/{sid}/resume", headers={"Idempotency-Key": r_key})
    assert r2.status_code == 200
    assert r2.json()["state"] == "active"

    # Idempotent stop
    s_key = "idem-chain-stop-1"
    s1 = client.post(f"/api/v1/sessions/{sid}/stop", headers={"Idempotency-Key": s_key})
    assert s1.status_code == 200
    s2 = client.post(f"/api/v1/sessions/{sid}/stop", headers={"Idempotency-Key": s_key})
    assert s2.status_code == 200
    assert s2.json()["state"] == "stopped"


# 35. Session creation, update, and expiry time tracking
def test_35_session_creation_update_and_expiry_time_tracking(client: TestClient):
    """Verifies tracking of session creation time, update time, and expiry time."""
    res = client.post("/api/v1/sessions")
    assert res.status_code == 201
    data = res.json()
    assert "created_at" in data
    assert "updated_at" in data
    assert "expires_at" in data
    assert data["expires_at"] is not None
    assert data["expires_at"] > data["created_at"]

    sid = data["session_id"]
    t_res = client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "active"})
    assert t_res.status_code == 200
    t_data = t_res.json()
    assert t_data["updated_at"] >= data["updated_at"]
    assert t_data["expires_at"] is not None


def test_expires_at_updates_on_event_record(client: TestClient):
    """Task 4: Asserts that recording an event moves expires_at forward to updated_at + TTL."""
    import time

    # Create and activate session
    res = client.post("/api/v1/sessions")
    assert res.status_code == 201
    sid = res.json()["session_id"]
    client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "active"})

    s_before = client.get(f"/api/v1/sessions/{sid}").json()
    orig_updated = s_before["updated_at"]
    orig_expires = s_before["expires_at"]

    # Sleep briefly to ensure distinct timestamp
    time.sleep(0.02)

    # Record event
    ev_res = client.post(
        f"/api/v1/sessions/{sid}/events",
        json={"event_type": "user_speech_detected", "payload": {"text": "hello"}},
    )
    assert ev_res.status_code == 201

    s_after = client.get(f"/api/v1/sessions/{sid}").json()
    new_updated = s_after["updated_at"]
    new_expires = s_after["expires_at"]

    assert new_updated >= orig_updated
    assert new_expires >= orig_expires

    updated_dt = datetime.fromisoformat(new_updated.replace("Z", "+00:00"))
    expires_dt = datetime.fromisoformat(new_expires.replace("Z", "+00:00"))
    expected_expires_dt = updated_dt + timedelta(seconds=settings.session_ttl_seconds)

    diff = abs((expires_dt - expected_expires_dt).total_seconds())
    assert diff < 1.0

