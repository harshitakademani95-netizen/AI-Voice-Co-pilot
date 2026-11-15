"""Live end-to-end verification script against the running AI Voice Co-Pilot backend."""
import json
import urllib.request
import urllib.error
import time

BASE_URL = "http://127.0.0.1:8000"

def make_request(method: str, path: str, body: dict = None, headers: dict = None) -> dict:
    url = f"{BASE_URL}{path}"
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            status_code = resp.status
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if "json" in content_type:
                res_body = json.loads(raw.decode("utf-8"))
            else:
                res_body = raw.decode("utf-8")
            return {
                "method": method,
                "url": url,
                "request_body": body,
                "status_code": status_code,
                "response_body": res_body,
            }
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            res_body = json.loads(raw.decode("utf-8"))
        except Exception:
            res_body = raw.decode("utf-8")
        return {
            "method": method,
            "url": url,
            "request_body": body,
            "status_code": err.code,
            "response_body": res_body,
        }

def test_sse_stream(session_id: str):
    url = f"{BASE_URL}/api/v1/sessions/{session_id}/events/stream"
    req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    events_received = []
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            lines = []
            for _ in range(15):
                line = resp.readline().decode("utf-8")
                if not line:
                    break
                lines.append(line)
                if line.startswith("data: "):
                    events_received.append(line.strip())
                if len(events_received) >= 2:
                    break
    except Exception as e:
        # Expected on timeout
        pass
    return {"url": url, "events_captured": events_received}

def run_suite():
    print("=== STARTING LIVE SESSION LIFECYCLE VERIFICATION ===")
    
    # 1. Inspect initial sessions
    r1 = make_request("GET", "/api/v1/sessions")
    print(f"\n[1] GET /api/v1/sessions -> HTTP {r1['status_code']}")
    print(json.dumps(r1['response_body'], indent=2))
    
    # 2. POST /api/v1/sessions (Create Session)
    create_payload = {
        "metadata": {
            "user_id": "vaishnavi",
            "agent_mode": "voice-copilot",
            "locale": "en-US",
            "environment": "demo"
        }
    }
    r2 = make_request("POST", "/api/v1/sessions", body=create_payload)
    print(f"\n[2] POST /api/v1/sessions -> HTTP {r2['status_code']}")
    print(json.dumps(r2['response_body'], indent=2))
    session_id = r2['response_body']['session_id']
    
    # 3. GET /api/v1/sessions (Verify session appears in list)
    r3 = make_request("GET", "/api/v1/sessions")
    print(f"\n[3] GET /api/v1/sessions -> HTTP {r3['status_code']}")
    print(json.dumps(r3['response_body'], indent=2))
    
    # 4. GET /api/v1/sessions/{session_id} (Retrieve by ID)
    r4 = make_request("GET", f"/api/v1/sessions/{session_id}")
    print(f"\n[4] GET /api/v1/sessions/{session_id} -> HTTP {r4['status_code']}")
    print(json.dumps(r4['response_body'], indent=2))
    
    # 5. POST /api/v1/sessions/{session_id}/transition (Transition to active)
    trans_payload = {"to_state": "active", "reason": "User started speaking"}
    r5 = make_request("POST", f"/api/v1/sessions/{session_id}/transition", body=trans_payload)
    print(f"\n[5] POST /api/v1/sessions/{session_id}/transition -> HTTP {r5['status_code']}")
    print(json.dumps(r5['response_body'], indent=2))
    
    # 6. POST /api/v1/sessions/{session_id}/pause (Pause session)
    pause_payload = {"reason": "User muted audio"}
    r6 = make_request("POST", f"/api/v1/sessions/{session_id}/pause", body=pause_payload)
    print(f"\n[6] POST /api/v1/sessions/{session_id}/pause -> HTTP {r6['status_code']}")
    print(json.dumps(r6['response_body'], indent=2))
    
    # 7. POST /api/v1/sessions/{session_id}/resume (Resume session)
    resume_payload = {"reason": "User unmuted audio"}
    r7 = make_request("POST", f"/api/v1/sessions/{session_id}/resume", body=resume_payload)
    print(f"\n[7] POST /api/v1/sessions/{session_id}/resume -> HTTP {r7['status_code']}")
    print(json.dumps(r7['response_body'], indent=2))
    
    # 8. POST /api/v1/sessions/{session_id}/events (Record custom event)
    event_payload = {
        "event_type": "user_speech_recognized",
        "payload": {
            "transcript": "Hello, how can I configure FastAPI sessions?",
            "confidence": 0.98,
            "stt_model": "whisper-mock"
        }
    }
    r8 = make_request("POST", f"/api/v1/sessions/{session_id}/events", body=event_payload)
    print(f"\n[8] POST /api/v1/sessions/{session_id}/events -> HTTP {r8['status_code']}")
    print(json.dumps(r8['response_body'], indent=2))
    
    # 9. GET /api/v1/sessions/{session_id}/events (Retrieve events history)
    r9 = make_request("GET", f"/api/v1/sessions/{session_id}/events")
    print(f"\n[9] GET /api/v1/sessions/{session_id}/events -> HTTP {r9['status_code']}")
    print(json.dumps(r9['response_body'], indent=2))
    
    # 10. GET /api/v1/sessions/{session_id}/events/stream (SSE Stream verification)
    r10 = test_sse_stream(session_id)
    print(f"\n[10] GET /api/v1/sessions/{session_id}/events/stream (SSE Stream)")
    print(json.dumps(r10, indent=2))
    
    # 11. POST /api/v1/sessions/{session_id}/stop (Stop session)
    stop_payload = {"reason": "User closed session gracefully"}
    r11 = make_request("POST", f"/api/v1/sessions/{session_id}/stop", body=stop_payload)
    print(f"\n[11] POST /api/v1/sessions/{session_id}/stop -> HTTP {r11['status_code']}")
    print(json.dumps(r11['response_body'], indent=2))
    
    # 12. POST /api/v1/sessions/mock/quickstart (Create an active quickstart session)
    r12 = make_request("POST", "/api/v1/sessions/mock/quickstart")
    print(f"\n[12] POST /api/v1/sessions/mock/quickstart -> HTTP {r12['status_code']}")
    print(json.dumps(r12['response_body'], indent=2))
    
    # 13. GET /api/v1/sessions (Final listing showing multiple sessions)
    r13 = make_request("GET", "/api/v1/sessions")
    print(f"\n[13] FINAL GET /api/v1/sessions -> HTTP {r13['status_code']}")
    print(json.dumps(r13['response_body'], indent=2))

if __name__ == "__main__":
    run_suite()

