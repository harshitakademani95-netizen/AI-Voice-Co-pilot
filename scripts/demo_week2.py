"""Week 2 Live Demonstration: Full Session Lifecycle, Idempotency, SSE, and Payload Limits.

This script executes the complete Week 2 verification workflow:
1. Health and Readiness verification
2. Correlation ID & Request ID tracking
3. Session Creation (state: 'created')
4. Session Activation (state: 'active')
5. Session Pause (state: 'paused' with 'session_paused' event)
6. Session Resume (state: 'active' with 'session_resumed' event)
7. Idempotent Command Replay (identical key returns cached response without duplication)
8. Idempotent Command Conflict Detection (reused key with different payload returns 409)
9. Session Stop (state: 'stopped' with 'session_stopped' event)
10. Terminal State Protection (verifies further mutations are rejected)
11. Server-Sent Events (SSE) Stream Verification
12. Payload Size Limit Rejection (payload > MAX_PAYLOAD_SIZE_BYTES returns 413)
"""
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore", message=".*Using `httpx` with `starlette.testclient` is deprecated.*")

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from starlette.testclient import TestClient
from src.app import create_app
from src.config import settings


def run_week_2_demonstration():
    print("=" * 80)
    print("      AI VOICE CO-PILOT BACKEND - WEEK 2 SESSION SERVICE DEMONSTRATION")
    print("=" * 80)

    app = create_app()
    client = TestClient(app)

    correlation_id = "corr-week2-demo-vaishnavi"
    headers = {"X-Correlation-ID": correlation_id}

    # Step 1: Health & Readiness
    print("\n[Step 1] Health & Readiness Probes")
    h_resp = client.get("/api/v1/health", headers=headers)
    print(f"  GET /api/v1/health -> HTTP {h_resp.status_code}")
    print(f"  Response: {h_resp.json()}")
    assert h_resp.status_code == 200

    r_resp = client.get("/api/v1/ready", headers=headers)
    print(f"  GET /api/v1/ready  -> HTTP {r_resp.status_code}")
    print(f"  Response: {r_resp.json()}")
    assert r_resp.status_code == 200

    # Step 2: Create Session
    print("\n[Step 2] Creating Session (Lifecycle Initial: 'created')")
    create_payload = {
        "metadata": {
            "user": "Vaishnavi",
            "feature": "week2-session-service",
            "environment": "development",
        }
    }
    create_resp = client.post("/api/v1/sessions", json=create_payload, headers=headers)
    print(f"  POST /api/v1/sessions -> HTTP {create_resp.status_code}")
    session_data = create_resp.json()
    sid = session_data["session_id"]
    print(f"  Session Created: ID={sid}, State={session_data['state']}, Events={session_data['events_count']}")
    assert create_resp.status_code == 201
    assert session_data["state"] == "created"

    # Step 3: Activate Session
    print("\n[Step 3] Activating Session ('created' -> 'active')")
    act_resp = client.post(
        f"/api/v1/sessions/{sid}/transition",
        json={"to_state": "active", "reason": "Voice interaction activated"},
        headers=headers,
    )
    print(f"  POST /api/v1/sessions/{sid}/transition -> HTTP {act_resp.status_code}")
    print(f"  Current State: {act_resp.json()['state']}")
    assert act_resp.json()["state"] == "active"

    # Step 4: Pause Session
    print("\n[Step 4] Pausing Session ('active' -> 'paused')")
    pause_resp = client.post(
        f"/api/v1/sessions/{sid}/pause",
        json={"reason": "User placed voice stream on hold"},
        headers=headers,
    )
    print(f"  POST /api/v1/sessions/{sid}/pause -> HTTP {pause_resp.status_code}")
    pause_data = pause_resp.json()
    print(f"  Current State: {pause_data['state']}")
    assert pause_data["state"] == "paused"
    assert any(e["event_type"] == "session_paused" for e in pause_data["events"])

    # Step 5: Resume Session
    print("\n[Step 5] Resuming Session ('paused' -> 'active')")
    resume_resp = client.post(
        f"/api/v1/sessions/{sid}/resume",
        json={"reason": "User unmuted and resumed conversation"},
        headers=headers,
    )
    print(f"  POST /api/v1/sessions/{sid}/resume -> HTTP {resume_resp.status_code}")
    resume_data = resume_resp.json()
    print(f"  Current State: {resume_data['state']}")
    assert resume_data["state"] == "active"
    assert any(e["event_type"] == "session_resumed" for e in resume_data["events"])

    # Step 6: Idempotent Command Replay & Conflict
    print("\n[Step 6] Testing Idempotent Command Handling")
    idem_key = "demo-idem-key-999"
    idem_headers = {**headers, "Idempotency-Key": idem_key}
    idem_payload = {"metadata": {"source": "demo-client-agent"}}

    # 6a: First call executes
    res_exec = client.post("/api/v1/sessions", json=idem_payload, headers=idem_headers)
    print(f"  [First Call]  POST /api/v1/sessions [Idempotency-Key: {idem_key}] -> HTTP {res_exec.status_code}")
    idem_sid = res_exec.json()["session_id"]
    print(f"  Created Session: {idem_sid}")

    # 6b: Exact replay returns cached response without duplicate creation
    res_replay = client.post("/api/v1/sessions", json=idem_payload, headers=idem_headers)
    print(f"  [Replay Call] POST /api/v1/sessions [Idempotency-Key: {idem_key}] -> HTTP {res_replay.status_code}")
    assert res_replay.json()["session_id"] == idem_sid
    print(f"  Successfully verified cached response match (No duplicate session created).")

    # 6c: Reusing same key with different payload produces 409 Conflict
    conflict_payload = {"metadata": {"source": "DIFFERENT_PAYLOAD"}}
    res_conflict = client.post("/api/v1/sessions", json=conflict_payload, headers=idem_headers)
    print(f"  [Conflict]    POST /api/v1/sessions [Reused Key + Different Body] -> HTTP {res_conflict.status_code}")
    print(f"  Conflict Error: {res_conflict.json()['error']['code']} - {res_conflict.json()['error']['message_safe_for_user']}")
    assert res_conflict.status_code == 409

    # Step 7: Stop Session
    print("\n[Step 7] Stopping Session ('active' -> 'stopped')")
    stop_resp = client.post(
        f"/api/v1/sessions/{sid}/stop",
        json={"reason": "Voice session completed gracefully"},
        headers=headers,
    )
    print(f"  POST /api/v1/sessions/{sid}/stop -> HTTP {stop_resp.status_code}")
    stop_data = stop_resp.json()
    print(f"  Final State: {stop_data['state']}")
    assert stop_data["state"] == "stopped"

    # Step 8: Terminal State Protection
    print("\n[Step 8] Verifying Terminal State Protection")
    bad_trans = client.post(
        f"/api/v1/sessions/{sid}/transition",
        json={"to_state": "active"},
        headers=headers,
    )
    print(f"  Attempting transition from 'stopped' -> 'active' -> HTTP {bad_trans.status_code}")
    print(f"  Enforced Error: {bad_trans.json()['error']['code']}")
    assert bad_trans.status_code == 409

    # Step 9: Server-Sent Events (SSE) Event Stream
    print("\n[Step 9] Verifying Server-Sent Events (SSE) Stream")
    with client.stream("GET", f"/api/v1/sessions/{sid}/events/stream") as sse_stream:
        print(f"  GET /api/v1/sessions/{sid}/events/stream -> HTTP {sse_stream.status_code}")
        print(f"  Content-Type: {sse_stream.headers.get('content-type')}")
        assert sse_stream.status_code == 200

        received_events = []
        for line in sse_stream.iter_lines():
            if line and line.startswith("event:"):
                received_events.append(line.replace("event:", "").strip())
            if len(received_events) >= 4:
                break
        print(f"  SSE Streamed Event Types: {received_events}")

    # Step 10: Payload Size Limits
    print("\n[Step 10] Verifying Request Payload Size Limit (413 PAYLOAD_TOO_LARGE)")
    orig_limit = settings.max_payload_size_bytes
    settings.max_payload_size_bytes = 200  # Set temporary threshold for demo
    try:
        large_payload = {"metadata": {"bulk_padding": "A" * 500}}
        large_resp = client.post("/api/v1/sessions", json=large_payload, headers=headers)
        print(f"  POST with oversized body -> HTTP {large_resp.status_code}")
        print(f"  Error Response: {large_resp.json()['error']['code']} - {large_resp.json()['error']['message_safe_for_user']}")
        assert large_resp.status_code == 413
    finally:
        settings.max_payload_size_bytes = orig_limit

    print("\n" + "=" * 80)
    print("  ALL WEEK 2 VERIFICATION SCENARIOS COMPLETED SUCCESSFULLY!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_week_2_demonstration()

