# Week 2 AI Voice Co-Pilot Backend API Documentation (Workstream W5)

**Repository**: https://github.com/harshitakademani95-netizen/AI-Voice-Co-pilot  
**Branch**: `feature/w5-backend-1`  
**Base URL**: `http://127.0.0.1:8000` (or `http://localhost:8000`)  
**API Prefix**: `/api/v1` (endpoints are mounted at both `/api/v1` and `/`)  
**Interactive Docs**: `/docs` (Swagger UI) and `/redoc` (ReDoc)  

---

## 1. Overview & Architecture

The Week 2 Backend service (Workstream W5) provides centralized session lifecycle management, ordered event streaming via Server-Sent Events (SSE), thread-safe idempotency guarantees, payload limits, correlation ID tracking, and structured JSON logging for the AI Voice Co-Pilot.

---

## 2. Startup Configuration & Safe Mock Mode

The backend evaluates settings at startup and fails fast on invalid configurations. By default, it operates in safe mock mode without requiring external credentials.

### Configuration Parameters

| Environment Variable | Type | Default | Description |
| :--- | :---: | :---: | :--- |
| `MOCK_MODE` | Boolean | `true` | When `true`, all reasoning, STT, and voice tools operate using local deterministic fixtures. |
| `HOST` | String | `127.0.0.1` | Network interface for binding the server. |
| `PORT` | Integer | `8000` | Port number (must be 1–65535). |
| `ENVIRONMENT` | String | `development` | Environment tier (`development`, `testing`, `staging`, `production`). |
| `MAX_PAYLOAD_SIZE_BYTES` | Integer | `1048576` (1MB) | Maximum permitted request body size in bytes. |
| `SESSION_TTL_SECONDS` | Integer | `3600` (1 hour) | Session idle time before automatic expiration. |
| `LOG_LEVEL` | String | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). |
| `STREAM_TIMEOUT_SECONDS` | Float | `30.0` | Server-side SSE idle timeout safeguard. |

### Startup Command (Safe Mock Mode)

```powershell
# Starts the backend in safe mock mode on http://127.0.0.1:8000
python -m uvicorn src.app:app --host 127.0.0.1 --port 8000 --reload
```

---

## 3. Session Lifecycle Management

### Lifecycle States & Legal Transitions

Sessions transition deterministically through defined lifecycle states:

```
[created] ---> [active] <---> [paused]
                   |             |
                   v             v
                [stopped]     [expired]
```

* **Legal State Transitions:**
  - `created` $\to$ `active`
  - `active` $\to$ `paused`
  - `active` $\to$ `stopped`
  - `paused` $\to$ `active`
  - `paused` $\to$ `stopped`
  - `created`, `active`, `paused` $\to$ `expired` (via TTL elapsed)
* **Terminal States:** `stopped`, `expired`, `completed`, `failed`. No further transitions or commands are accepted once terminal.

---

### Endpoints

#### 1. Create Session
* **Method & Path:** `POST /api/v1/sessions`
* **Headers:**
  - `Idempotency-Key` (Optional): Unique UUID string.
  - `X-Correlation-ID` (Optional): Client correlation ID.
* **Request Body:**
  ```json
  {
    "metadata": {
      "user_id": "usr-12345",
      "device": "desktop"
    }
  }
  ```
* **Success Response (201 Created):**
  ```json
  {
    "session_id": "sess-a1b2c3d4e5f6",
    "state": "created",
    "created_at": "2026-11-23T21:00:00Z",
    "updated_at": "2026-11-23T21:00:00Z",
    "expires_at": "2026-11-23T22:00:00Z",
    "metadata": { "user_id": "usr-12345" },
    "events_count": 1,
    "events": [
      {
        "event_id": "evt-7890abcd",
        "session_id": "sess-a1b2c3d4e5f6",
        "sequence_number": 1,
        "event_type": "session_created",
        "timestamp": "2026-11-23T21:00:00Z",
        "payload": { "initial_state": "created" }
      }
    ]
  }
  ```

#### 2. Get Session Details
* **Method & Path:** `GET /api/v1/sessions/{session_id}`
* **Success Response (200 OK):** Returns current session object and event list.
* **Error Response (404 Not Found):** If session ID is not recognized.

#### 3. List Sessions
* **Method & Path:** `GET /api/v1/sessions`
* **Query Parameters:**
  - `state` (Optional): Filter by state (`created`, `active`, `paused`, `stopped`, `expired`).
  - `limit` (Optional, default 50): Max items to return.
  - `offset` (Optional, default 0): Items to skip.
* **Success Response (200 OK):**
  ```json
  {
    "total": 1,
    "sessions": [ ... ]
  }
  ```

#### 4. Transition Session State
* **Method & Path:** `POST /api/v1/sessions/{session_id}/transition`
* **Request Body:**
  ```json
  {
    "to_state": "active",
    "reason": "User started audio stream"
  }
  ```
* **Success Response (200 OK):** Returns updated session.
* **Error Response (400 Bad Request):** If transition is illegal (e.g., `created` $\to$ `paused`).

#### 5. Convenience Pause, Resume & Stop Endpoints
* `POST /api/v1/sessions/{session_id}/pause` $\to$ Transitions to `paused`
* `POST /api/v1/sessions/{session_id}/resume` $\to$ Transitions to `active`
* `POST /api/v1/sessions/{session_id}/stop` $\to$ Transitions to terminal `stopped`

---

## 4. Idempotency Guarantees

All state-mutating commands (`POST /sessions`, `POST /transition`, `POST /pause`, `POST /resume`, `POST /stop`) support idempotency keys via:
- `Idempotency-Key` or `X-Idempotency-Key` HTTP headers.

### Behavior:
1. **Identical Repeated Requests:** Returns identical cached response without repeating side effects or generating duplicate events.
2. **Conflicting Requests:** If the same `Idempotency-Key` is re-used with a different request payload or target path, the backend immediately rejects it with HTTP 409 `IDEMPOTENCY_CONFLICT`.
3. **Concurrent Duplicate Requests:** Coordinated via thread locks; subsequent concurrent threads safely wait for the first executor to complete and receive the cached result.

---

## 5. Event Streaming (SSE), Replay & Reconnection

The backend supports real-time Server-Sent Events (SSE) streaming and historical event replay with monotonic sequence numbers.

### Streaming Endpoints

1. **Dedicated SSE Route:** `GET /api/v1/sessions/{session_id}/events/stream`
2. **Content-Negotiated Route:** `GET /api/v1/sessions/{session_id}/events` with `Accept: text/event-stream`

### Query Parameters

| Parameter | Type | Default | Description |
| :--- | :---: | :---: | :--- |
| `limit` / `max_events` | Integer | `None` | Max events to yield before closing the stream. |
| `timeout` / `idle_timeout`| Float | `30.0` | Max idle duration in seconds before terminating. |
| `last_event_id` / `cursor`| String | `None` | Reconnect point; streams only events after this ID or sequence number. |
| `live` | Boolean | `true` | If `false`, stops after replaying historical events. |
| `replay_only` | Boolean | `false` | Replays historical events and closes immediately without listening to live queue. |

### SSE Frame Format

```text
id: evt-c0123456789a
event: session_activated
data: {"event_id":"evt-c0123456789a","session_id":"sess-a1b2c3d4e5f6","sequence_number":2,"event_type":"session_activated","timestamp":"2026-11-23T21:01:00Z","payload":{"reason":"User speech detected"}}

```

### Reconnection via `Last-Event-ID`
When a disconnected client reconnects:
1. Pass the header `Last-Event-ID: evt-c0123456789a` or query `?last_event_id=evt-c0123456789a`.
2. The server scans history, locates the event, and resumes strictly from the next sequential event.
3. Earlier events are skipped (no duplicates).

---

## 6. Request Validation & Payload Limits

* **Max Payload Middleware:** Enforced by `PayloadSizeLimitMiddleware`. Any request exceeding `MAX_PAYLOAD_SIZE_BYTES` (default 1MB) is rejected before processing with:
  ```json
  {
    "error": {
      "code": "PAYLOAD_TOO_LARGE",
      "message": "Request body exceeds maximum permitted size of 1048576 bytes.",
      "retryable": false,
      "details": { "max_bytes": 1048576 }
    }
  }
  ```
* **Validation Errors:** Malformed payloads return HTTP 422 with typed error envelopes containing field-level validation details.

---

## 7. Correlation IDs & Structured JSON Logging

* **Correlation Middleware:** Enforced by `RequestCorrelationMiddleware`.
  - Inbound `X-Correlation-ID` header is respected and propagated.
  - If omitted, a unique `corr-<uuid>` is generated and attached to request state and response headers.
* **Structured Logs:** Emits single-line JSON entries to `stdout`:
  ```json
  {
    "timestamp": "2026-11-23T21:05:00.123Z",
    "level": "INFO",
    "logger": "backend",
    "event": "http_request",
    "method": "POST",
    "path": "/api/v1/sessions",
    "status_code": 201,
    "duration_ms": 3.42,
    "correlation_id": "corr-f9a8b7c6d5e4"
  }
  ```
* **Sensitive Field Masking:** Tokens, keys, and authorization secrets are masked automatically in logs.
