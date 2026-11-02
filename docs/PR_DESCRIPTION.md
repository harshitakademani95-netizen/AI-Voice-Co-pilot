# Pull Request: W5 – Backend Foundation, Session States, and Mock Launcher

**Workstream:** W5 – Backend and sessions  
**Engineer:** Vaishnavi G (SDE 3)  
**Branch:** `feature/w5-backend-sessions` -> `main`

---

## Summary of Changes

This PR implements the complete foundation and first vertical slice for the **AI Voice Co-Pilot Backend (W5)**. The implementation strictly adheres to the API Interface Contracts and Technical Architecture specifications:

1. **App Skeleton & Health Probes**:
   - Structured FastAPI application skeleton with environment configuration.
   - `/health` and `/api/v1/health`: Vitality probe reporting status, version, and active mock mode.
   - `/ready` and `/api/v1/ready`: Readiness probe inspecting in-memory repository health.
2. **Typed Error Envelope**:
   - Conforms to specification with required fields: `code`, `message_safe_for_user`, `retryable`, `correlation_id`, `details_redacted`.
   - Automated redaction of sensitive credentials, Bearer tokens, and secrets (`src/core/security.py`).
   - Concealment of internal 500 server stack traces.
3. **Request & Correlation-ID Middleware**:
   - `RequestCorrelationMiddleware` guarantees every request and response carries `X-Request-ID` and `X-Correlation-ID`.
   - Propagates IDs into all error responses for end-to-end tracing.
4. **Session Lifecycle & In-Memory Repository**:
   - Enforces 7 discrete lifecycle states: `created`, `active`, `paused`, `stopping`, `completed`, `failed`, `expired`.
   - Thread-safe repository (`threading.RLock`) managing session state transitions, rejection of illegal jumps, and terminal state protection.
   - Audit trail and mock event stream recording.
5. **One-Command Mock Launcher**:
   - Starts the backend in mock mode (`MOCK_MODE=True`) with zero external API dependencies or paid credentials required.
   - Single command: `python run_mock.py` (or `.\scripts\run_mock.bat`).
6. **Comprehensive Route Tests & Day 7 Demo**:
   - 27 unit and integration tests covering normal, boundary, and failure scenarios.
   - Standalone live demonstration script: `python scripts/demo_day7.py`.

---

## Acceptance Criteria Checklist

- [x] **Health and readiness endpoints respond correctly**:
  - `/api/v1/health` returns `200 OK` with service name, version, and `mock_mode: true`.
  - `/api/v1/ready` returns `200 OK` when repository is operational; `503` if degraded.
- [x] **Errors use the typed envelope and expose no sensitive details**:
  - Validated by `tests/test_errors.py` (404, 422, 409, 500).
  - All sensitive tokens and keys are sanitized via `redact_sensitive_data`.
- [x] **Every request carries a request ID and correlation ID**:
  - Enforced by `RequestCorrelationMiddleware`.
  - Headers `X-Request-ID` and `X-Correlation-ID` present on all 200, 201, 4xx, and 5xx responses.
- [x] **Session states and transitions are enforced; repository is in-memory**:
  - Thread-safe `InMemorySessionRepository` strictly enforces state transitions.
  - Terminal states (`completed`, `failed`, `expired`) cannot transition.
- [x] **Launcher starts the backend in mock mode with one documented command**:
  - `python run_mock.py` boots Uvicorn with interactive docs at `http://127.0.0.1:8000/docs`.
- [x] **Route tests pass (normal, boundary and failure cases)**:
  - 27/27 tests pass with 100% clean output.
- [x] **Work is on a feature branch; no direct pushes to main**:
  - Developed on `feature/w5-backend-sessions`.
- [x] **PR is reviewed, includes test output, and no secrets/recordings/personal data are committed**:
  - `.gitignore` configured; verified no secrets or audio data.
- [x] **Day 7 demo completed**:
  - Validated via `scripts/demo_day7.py`.

---

## Test Execution Output

```
============================= test session starts =============================
platform win32 -- Python 3.13.14, pytest-9.2.0, pluggy-1.7.0
rootdir: C:\Users\vaish\Desktop\AI voicebot
plugins: anyio-4.15.1
collected 27 items

tests/test_errors.py::test_typed_error_envelope_structure PASSED         [  3%]
tests/test_errors.py::test_validation_error_envelope PASSED              [  7%]
tests/test_errors.py::test_redact_sensitive_data_keys PASSED             [ 11%]
tests/test_errors.py::test_redact_sensitive_data_strings PASSED          [ 14%]
tests/test_errors.py::test_unhandled_exception_does_not_leak_internals PASSED [ 18%]
tests/test_health.py::test_health_endpoint_root PASSED                   [ 22%]
tests/test_health.py::test_health_endpoint_api_prefix PASSED             [ 25%]
tests/test_health.py::test_readiness_endpoint_root_healthy PASSED        [ 29%]
tests/test_health.py::test_readiness_endpoint_api_prefix PASSED          [ 33%]
tests/test_health.py::test_readiness_endpoint_unhealthy_repository PASSED [ 37%]
tests/test_middleware.py::test_middleware_generates_request_and_correlation_ids PASSED [ 40%]
tests/test_middleware.py::test_middleware_preserves_client_provided_ids PASSED [ 44%]
tests/test_middleware.py::test_middleware_preserves_ids_on_error_responses PASSED [ 48%]
tests/test_sessions.py::test_create_session_defaults PASSED              [ 51%]
tests/test_sessions.py::test_create_session_custom_id_and_metadata PASSED [ 55%]
tests/test_sessions.py::test_create_session_duplicate_id_failure PASSED  [ 59%]
tests/test_sessions.py::test_get_session_by_id_success PASSED            [ 62%]
tests/test_sessions.py::test_get_session_not_found PASSED                [ 66%]
tests/test_sessions.py::test_list_sessions_and_filtering PASSED          [ 70%]
tests/test_sessions.py::test_full_normal_lifecycle_transitions PASSED    [ 74%]
tests/test_sessions.py::test_illegal_transition_created_to_completed_failure PASSED [ 77%]
tests/test_sessions.py::test_illegal_transition_same_state_failure PASSED [ 81%]
tests/test_sessions.py::test_terminal_state_completed_cannot_transition PASSED [ 85%]
tests/test_sessions.py::test_terminal_state_failed_cannot_transition PASSED [ 88%]
tests/test_sessions.py::test_record_mock_events_in_session PASSED        [ 92%]
tests/test_sessions.py::test_record_event_on_failed_session_rejected PASSED [ 96%]
tests/test_sessions.py::test_quickstart_mock_session_route PASSED        [100%]

======================== 27 passed in 0.73s ========================
```

---

## Live Demonstration Output (`scripts/demo_day7.py`)

```
================================================================================
       AI VOICE CO-PILOT (W5) - DAY 7 VERTICAL SLICE DEMONSTRATION
================================================================================

[Step 1] Checking Service Health & Readiness Probes...
  GET /api/v1/health -> HTTP 200
  Response: {'status': 'healthy', 'service': 'AI Voice Co-Pilot Backend', 'version': '1.0.0', 'mock_mode': True, 'timestamp': '2026-10-28T14:02:10.188466+00:00'}
  GET /api/v1/ready  -> HTTP 200
  Response: {'status': 'ready', 'checks': {'session_repository': 'ok', 'mock_mode': True, 'environment': 'development'}, 'timestamp': '2026-10-28T14:02:10.196604+00:00'}

[Step 2] Initializing Session (Default State: 'created')...
  POST /api/v1/sessions -> HTTP 201
  Created Session ID: session-ad8072c4
  Initial State:      created
  X-Request-ID:       req-fa7331abc332
  X-Correlation-ID:   corr-demo-day7-001

[Step 3] Transitioning Session 'session-ad8072c4' from 'created' to 'active'...
  POST /api/v1/sessions/session-ad8072c4/transition -> HTTP 200
  New State: active

[Step 4] Dispatching Mock Event: 'mock_voice_transcript'...
  POST /api/v1/sessions/session-ad8072c4/events -> HTTP 201
  Event Recorded: {'event_id': 'evt-e0dc9a374d', 'event_type': 'mock_voice_transcript', 'payload': {'transcript': 'Explain this syntax error on line 42', 'language': 'en-US', 'confidence': 0.985}, 'timestamp': '2026-10-28T14:02:10.229967+00:00'}

[Step 5] Dispatching Mock Event: 'mock_ai_agent_plan'...
  POST /api/v1/sessions/session-ad8072c4/events -> HTTP 201
  Event Recorded: {'event_id': 'evt-c3d08e2ec9', 'event_type': 'mock_ai_agent_plan', 'payload': {'intent': 'code_explanation', 'recommended_action': 'Inspect line 42 for missing closing parenthesis', 'requires_approval': False}, 'timestamp': '2026-10-28T14:02:10.236069+00:00'}

[Step 6] Retrieving Full Session Summary for 'session-ad8072c4'...
  GET /api/v1/sessions/session-ad8072c4 -> HTTP 200
  Total Events in History: 4
    Event 1: [session_created] - timestamp: 2026-10-28T14:02:10.215065+00:00
    Event 2: [state_transition] - timestamp: 2026-10-28T14:02:10.222896+00:00
    Event 3: [mock_voice_transcript] - timestamp: 2026-10-28T14:02:10.229967+00:00
    Event 4: [mock_ai_agent_plan] - timestamp: 2026-10-28T14:02:10.236069+00:00

[Step 7] Gracefully Stopping & Completing Session...
  Final State: completed

================================================================================
             DAY 7 DEMONSTRATION COMPLETED SUCCESSFULLY
================================================================================
```
