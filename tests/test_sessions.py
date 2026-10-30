"""Comprehensive tests for session lifecycle, in-memory repository, and mock route."""
from starlette.testclient import TestClient


def test_create_session_defaults(client: TestClient):
    """Verifies that a new session defaults to 'created' state."""
    response = client.post("/api/v1/sessions")
    assert response.status_code == 201
    data = response.json()
    assert data["state"] == "created"
    assert data["session_id"].startswith("session-")
    assert data["events_count"] == 1
    assert data["events"][0]["event_type"] == "session_created"


def test_create_session_custom_id_and_metadata(client: TestClient):
    """Verifies creating a session with explicit ID and metadata."""
    payload = {
        "session_id": "session-custom-001",
        "metadata": {"user": "Vaishnavi", "environment": "test"},
    }
    response = client.post("/api/v1/sessions", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["session_id"] == "session-custom-001"
    assert data["state"] == "created"
    assert data["metadata"]["user"] == "Vaishnavi"


def test_create_session_duplicate_id_failure(client: TestClient):
    """Verifies that duplicate session ID raises 409 Conflict."""
    payload = {"session_id": "session-duplicate-id"}
    client.post("/api/v1/sessions", json=payload)
    response = client.post("/api/v1/sessions", json=payload)
    assert response.status_code == 409
    data = response.json()
    assert data["error"]["code"] == "SESSION_ALREADY_EXISTS"


def test_get_session_by_id_success(client: TestClient):
    """Verifies retrieving session by session_id."""
    create_res = client.post("/api/v1/sessions", json={"session_id": "session-get-1"})
    assert create_res.status_code == 201

    get_res = client.get("/api/v1/sessions/session-get-1")
    assert get_res.status_code == 200
    assert get_res.json()["session_id"] == "session-get-1"


def test_get_session_not_found(client: TestClient):
    """Verifies 404 response for unknown session."""
    response = client.get("/api/v1/sessions/non-existent-sid")
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["code"] == "SESSION_NOT_FOUND"


def test_list_sessions_and_filtering(client: TestClient):
    """Verifies listing sessions and filtering by state query parameter."""
    s1 = client.post("/api/v1/sessions").json()["session_id"]
    s2 = client.post("/api/v1/sessions").json()["session_id"]

    # Transition s2 to active
    client.post(f"/api/v1/sessions/{s2}/transition", json={"to_state": "active"})

    # List all
    all_res = client.get("/api/v1/sessions")
    assert all_res.status_code == 200
    assert all_res.json()["total"] == 2

    # Filter by created
    created_res = client.get("/api/v1/sessions?state=created")
    assert created_res.json()["total"] == 1
    assert created_res.json()["sessions"][0]["session_id"] == s1

    # Filter by active
    active_res = client.get("/api/v1/sessions?state=active")
    assert active_res.json()["total"] == 1
    assert active_res.json()["sessions"][0]["session_id"] == s2


def test_full_normal_lifecycle_transitions(client: TestClient):
    """Verifies valid normal progression:
    created -> active -> paused -> active -> stopping -> completed.
    """
    create_res = client.post("/api/v1/sessions")
    sid = create_res.json()["session_id"]
    assert create_res.json()["state"] == "created"

    # created -> active
    r1 = client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "active", "reason": "User started"})
    assert r1.status_code == 200
    assert r1.json()["state"] == "active"

    # active -> paused
    r2 = client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "paused", "reason": "User paused"})
    assert r2.status_code == 200
    assert r2.json()["state"] == "paused"

    # paused -> active
    r3 = client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "active", "reason": "User resumed"})
    assert r3.status_code == 200
    assert r3.json()["state"] == "active"

    # active -> stopping
    r4 = client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "stopping", "reason": "Shutdown requested"})
    assert r4.status_code == 200
    assert r4.json()["state"] == "stopping"

    # stopping -> completed
    r5 = client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "completed", "reason": "Session finished cleanly"})
    assert r5.status_code == 200
    assert r5.json()["state"] == "completed"


def test_illegal_transition_created_to_completed_failure(client: TestClient):
    """Verifies that jumping from created -> completed directly is rejected with 409."""
    create_res = client.post("/api/v1/sessions")
    sid = create_res.json()["session_id"]

    res = client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "completed"})
    assert res.status_code == 409
    data = res.json()
    assert data["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_illegal_transition_same_state_failure(client: TestClient):
    """Verifies that transitioning to the current state is rejected."""
    create_res = client.post("/api/v1/sessions")
    sid = create_res.json()["session_id"]

    res = client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "created"})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_terminal_state_completed_cannot_transition(client: TestClient):
    """Verifies that a completed session cannot transition to any other state."""
    create_res = client.post("/api/v1/sessions")
    sid = create_res.json()["session_id"]

    client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "active"})
    client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "stopping"})
    client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "completed"})

    res = client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "active"})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_terminal_state_failed_cannot_transition(client: TestClient):
    """Verifies that a failed session cannot transition to any other state."""
    create_res = client.post("/api/v1/sessions")
    sid = create_res.json()["session_id"]

    client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "failed", "reason": "Initialization failed"})

    res = client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "active"})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_record_mock_events_in_session(client: TestClient):
    """Verifies adding mock events to an active session."""
    create_res = client.post("/api/v1/sessions")
    sid = create_res.json()["session_id"]
    client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "active"})

    # Record mock speech-to-text event
    event_payload = {
        "event_type": "mock_voice_transcript",
        "payload": {
            "transcript": "Find my project report",
            "confidence": 0.96,
        },
    }
    event_res = client.post(f"/api/v1/sessions/{sid}/events", json=event_payload)
    assert event_res.status_code == 201
    event_data = event_res.json()
    assert event_data["event_type"] == "mock_voice_transcript"
    assert event_data["payload"]["transcript"] == "Find my project report"

    # Verify session now reflects the event
    session_res = client.get(f"/api/v1/sessions/{sid}")
    session_data = session_res.json()
    event_types = [e["event_type"] for e in session_data["events"]]
    assert "mock_voice_transcript" in event_types


def test_record_event_on_failed_session_rejected(client: TestClient):
    """Verifies that adding events to a failed session is rejected."""
    create_res = client.post("/api/v1/sessions")
    sid = create_res.json()["session_id"]
    client.post(f"/api/v1/sessions/{sid}/transition", json={"to_state": "failed"})

    res = client.post(
        f"/api/v1/sessions/{sid}/events",
        json={"event_type": "some_event", "payload": {}},
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_quickstart_mock_session_route(client: TestClient):
    """Verifies quickstart mock helper creates an active session with an initial mock event."""
    response = client.post("/api/v1/sessions/mock/quickstart")
    assert response.status_code == 201
    data = response.json()
    assert data["state"] == "active"
    assert data["events_count"] >= 3  # created, transition to active, mock_voice_transcript
    event_types = [e["event_type"] for e in data["events"]]
    assert "mock_voice_transcript" in event_types
