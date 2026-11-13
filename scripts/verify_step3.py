import urllib.request
import urllib.error
import json
import sys

base = "http://127.0.0.1:8000"

def req(method, path, body=None, headers=None):
    url = f"{base}{path}"
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    data = None
    if body is not None:
        data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
    req_obj = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req_obj) as resp:
            return resp.status, dict(resp.headers), resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8")

def filter_hdrs(h):
    return {k: v for k, v in h.items() if k.lower() in ("x-request-id", "x-correlation-id", "content-type")}

print("=== 3a: CREATE, ACTIVATE, PAUSE, RESUME, STOP ===")
s, h, b = req("POST", "/api/v1/sessions", {"metadata": {"client": "check"}}, {"X-Correlation-ID": "corr-3a-create"})
print(f"1. Create:\nStatus Code: {s}\nHeaders: {json.dumps(filter_hdrs(h))}\nBody: {b}\n")
sid = json.loads(b)["session_id"]

s, h, b = req("POST", f"/api/v1/sessions/{sid}/transition", {"to_state": "active"}, {"X-Correlation-ID": "corr-3a-active"})
print(f"2. Activate:\nStatus Code: {s}\nHeaders: {json.dumps(filter_hdrs(h))}\nBody: {b}\n")

s, h, b = req("POST", f"/api/v1/sessions/{sid}/pause", headers={"X-Correlation-ID": "corr-3a-pause"})
print(f"3. Pause:\nStatus Code: {s}\nHeaders: {json.dumps(filter_hdrs(h))}\nBody: {b}\n")

s, h, b = req("POST", f"/api/v1/sessions/{sid}/resume", headers={"X-Correlation-ID": "corr-3a-resume"})
print(f"4. Resume:\nStatus Code: {s}\nHeaders: {json.dumps(filter_hdrs(h))}\nBody: {b}\n")

s, h, b = req("POST", f"/api/v1/sessions/{sid}/stop", headers={"X-Correlation-ID": "corr-3a-stop"})
print(f"5. Stop:\nStatus Code: {s}\nHeaders: {json.dumps(filter_hdrs(h))}\nBody: {b}\n")

print("=== 3b: ILLEGAL TRANSITION ===")
s, h, b = req("POST", f"/api/v1/sessions/{sid}/resume", headers={"X-Correlation-ID": "corr-illegal-resume"})
print(f"Resume Stopped Session:\nStatus Code: {s}\nHeaders: {json.dumps(filter_hdrs(h))}\nBody: {b}\n")

print("=== 3c: IDEMPOTENCY KEY HANDLING ===")
idem_key = "idem-unique-key-999"
s, h, b1 = req("POST", "/api/v1/sessions", {"metadata": {"attempt": 1}}, {"Idempotency-Key": idem_key, "X-Correlation-ID": "corr-idem-1"})
print(f"Attempt 1 (Key={idem_key}):\nStatus Code: {s}\nHeaders: {json.dumps(filter_hdrs(h))}\nBody: {b1}\n")

s, h, b2 = req("POST", "/api/v1/sessions", {"metadata": {"attempt": 1}}, {"Idempotency-Key": idem_key, "X-Correlation-ID": "corr-idem-2"})
print(f"Attempt 2 (Same Key={idem_key}, Identical Payload):\nStatus Code: {s}\nHeaders: {json.dumps(filter_hdrs(h))}\nBody: {b2}\n")

diff_key = "idem-unique-key-888"
s, h, b3 = req("POST", "/api/v1/sessions", {"metadata": {"attempt": 1}}, {"Idempotency-Key": diff_key, "X-Correlation-ID": "corr-diff-key"})
print(f"Attempt 3 (Different Key={diff_key}):\nStatus Code: {s}\nHeaders: {json.dumps(filter_hdrs(h))}\nBody: {b3}\n")

print("=== 3d: MALFORMED JSON AND OVERSIZED PAYLOAD ===")
s, h, b = req("POST", "/api/v1/sessions", "{bad_json_not_valid", {"X-Correlation-ID": "corr-malformed"})
print(f"Malformed JSON:\nStatus Code: {s}\nHeaders: {json.dumps(filter_hdrs(h))}\nBody: {b}\n")

big_payload = "A" * (1024 * 1024 + 100)
s, h, b = req("POST", "/api/v1/sessions", big_payload, {"X-Correlation-ID": "corr-oversized"})
print(f"Oversized Payload:\nStatus Code: {s}\nHeaders: {json.dumps(filter_hdrs(h))}\nBody: {b}\n")

print("=== 3e: INVALID SESSION ID ===")
s, h, b = req("GET", "/api/v1/sessions/session-nonexistent-uuid-000", headers={"X-Correlation-ID": "corr-not-found"})
print(f"Invalid Session ID:\nStatus Code: {s}\nHeaders: {json.dumps(filter_hdrs(h))}\nBody: {b}\n")

print("=== 3f: EVENT STREAM AND RECONNECTION ===")
s, h, b = req("GET", f"/api/v1/sessions/{sid}/events")
events_data = json.loads(b)
print(f"Events History (Total Events: {events_data.get('events_count', len(events_data['events']))}):")
for evt in events_data["events"]:
    print(f"  Seq={evt['sequence_number']}: ID={evt['event_id']}, Type={evt['event_type']}")

second_evt_id = events_data["events"][1]["event_id"]
print(f"\nReconnecting to SSE stream with Last-Event-ID: {second_evt_id}...")
req_stream = urllib.request.Request(
    f"{base}/api/v1/sessions/{sid}/events/stream",
    headers={"Last-Event-ID": second_evt_id, "Accept": "text/event-stream"}
)
with urllib.request.urlopen(req_stream, timeout=2.0) as stream_resp:
    lines = []
    try:
        while len(lines) < 8:
            line = stream_resp.readline().decode("utf-8")
            if not line:
                break
            lines.append(line.strip())
            # Stop once we have captured the replayed events
            if len([l for l in lines if l.startswith("event:")]) >= 2:
                break
    except Exception:
        pass

print("Stream Output Replayed After Midpoint:")
for l in lines:
    if l.startswith("id:") or l.startswith("event:"):
        print(f"  {l}")
