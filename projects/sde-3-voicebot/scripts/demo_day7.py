"""Day 7 Demonstration: Starting a session through to a mock event.

This script executes the complete Day 7 verification workflow:
1. Health and Readiness verification
2. Request and Correlation-ID tracking
3. Session creation (state: 'created')
4. Lifecycle transition ('created' -> 'active')
5. Dispatching a mock voice transcript event
6. Dispatching a mock AI response event
7. Session state query and audit log inspection
8. Graceful completion ('active' -> 'stopping' -> 'completed')
"""
import json
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from starlette.testclient import TestClient
from src.app import create_app


def run_day_7_demonstration():
    print("=" * 80)
    print("       AI VOICE CO-PILOT (W5) - DAY 7 VERTICAL SLICE DEMONSTRATION")
    print("=" * 80)

    app = create_app()
    client = TestClient(app)

    correlation_id = "corr-demo-day7-001"
    headers = {"X-Correlation-ID": correlation_id}

    # Step 1: Health & Readiness Probe
    print("\n[Step 1] Checking Service Health & Readiness Probes...")
    health_resp = client.get("/api/v1/health", headers=headers)
    print(f"  GET /api/v1/health -> HTTP {health_resp.status_code}")
    print(f"  Response: {health_resp.json()}")

    ready_resp = client.get("/api/v1/ready", headers=headers)
    print(f"  GET /api/v1/ready  -> HTTP {ready_resp.status_code}")
    print(f"  Response: {ready_resp.json()}")

    # Step 2: Initialize Session
    print("\n[Step 2] Initializing Session (Default State: 'created')...")
    create_payload = {
        "metadata": {
            "user_id": "vaishnavi-sde3",
            "active_app": "VS Code",
            "workstream": "W5-Backend-Sessions",
        }
    }
    create_resp = client.post("/api/v1/sessions", json=create_payload, headers=headers)
    session_data = create_resp.json()
    session_id = session_data["session_id"]
    print(f"  POST /api/v1/sessions -> HTTP {create_resp.status_code}")
    print(f"  Created Session ID: {session_id}")
    print(f"  Initial State:      {session_data['state']}")
    print(f"  X-Request-ID:       {create_resp.headers.get('X-Request-ID')}")
    print(f"  X-Correlation-ID:   {create_resp.headers.get('X-Correlation-ID')}")

    # Step 3: Transition State: 'created' -> 'active'
    print(f"\n[Step 3] Transitioning Session '{session_id}' from 'created' to 'active'...")
    transition_payload = {
        "to_state": "active",
        "reason": "User started voice interaction",
    }
    trans_resp = client.post(
        f"/api/v1/sessions/{session_id}/transition",
        json=transition_payload,
        headers=headers,
    )
    print(f"  POST /api/v1/sessions/{session_id}/transition -> HTTP {trans_resp.status_code}")
    print(f"  New State: {trans_resp.json()['state']}")

    # Step 4: Dispatch Mock Event (Voice Transcription)
    print(f"\n[Step 4] Dispatching Mock Event: 'mock_voice_transcript'...")
    mock_voice_event = {
        "event_type": "mock_voice_transcript",
        "payload": {
            "transcript": "Explain this syntax error on line 42",
            "language": "en-US",
            "confidence": 0.985,
        },
    }
    event_resp1 = client.post(
        f"/api/v1/sessions/{session_id}/events",
        json=mock_voice_event,
        headers=headers,
    )
    print(f"  POST /api/v1/sessions/{session_id}/events -> HTTP {event_resp1.status_code}")
    print(f"  Event Recorded: {event_resp1.json()}")

    # Step 5: Dispatch Mock Event (AI Action Plan)
    print(f"\n[Step 5] Dispatching Mock Event: 'mock_ai_agent_plan'...")
    mock_agent_event = {
        "event_type": "mock_ai_agent_plan",
        "payload": {
            "intent": "code_explanation",
            "recommended_action": "Inspect line 42 for missing closing parenthesis",
            "requires_approval": False,
        },
    }
    event_resp2 = client.post(
        f"/api/v1/sessions/{session_id}/events",
        json=mock_agent_event,
        headers=headers,
    )
    print(f"  POST /api/v1/sessions/{session_id}/events -> HTTP {event_resp2.status_code}")
    print(f"  Event Recorded: {event_resp2.json()}")

    # Step 6: Query Session Information & Event History
    print(f"\n[Step 6] Retrieving Full Session Summary for '{session_id}'...")
    get_resp = client.get(f"/api/v1/sessions/{session_id}", headers=headers)
    session_summary = get_resp.json()
    print(f"  GET /api/v1/sessions/{session_id} -> HTTP {get_resp.status_code}")
    print(f"  Total Events in History: {session_summary['events_count']}")
    for idx, evt in enumerate(session_summary["events"], 1):
        print(f"    Event {idx}: [{evt['event_type']}] - timestamp: {evt['timestamp']}")

    # Step 7: Transition to Terminal State: 'active' -> 'stopping' -> 'completed'
    print(f"\n[Step 7] Gracefully Stopping & Completing Session...")
    client.post(
        f"/api/v1/sessions/{session_id}/transition",
        json={"to_state": "stopping", "reason": "User completed task"},
        headers=headers,
    )
    final_resp = client.post(
        f"/api/v1/sessions/{session_id}/transition",
        json={"to_state": "completed", "reason": "All tasks finished cleanly"},
        headers=headers,
    )
    print(f"  Final State: {final_resp.json()['state']}")

    print("\n" + "=" * 80)
    print("             DAY 7 DEMONSTRATION COMPLETED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    run_day_7_demonstration()
