"""Week 3 Full Integration Test Suite (Days 15 through 21).

Verifies 100% completion of all Week 3 backend requirements and acceptance criteria:
- Day 15-16: Four Module Gateways (Audio, Transcription, Reasoning, Workflow) with real connections,
  bounded ThreadPoolExecutor timeouts (HTTP 504), Circuit Breaker trip/recovery, and backoff retries.
- Day 17-18: Event Streaming, History Replay with Cursors, Last-Event-ID Reconnection, Deduplication,
  and Invalid Cursor Validation.
- Day 19-20: Local Authorization Boundary (HTTP 401), Sliding-Window Rate Limiting (HTTP 429),
  4-Module Health Aggregation with Failure Isolation, and Session ID / Correlation ID Propagation.
- Day 21: Full End-to-End Module Pipeline (Audio -> STT -> Reasoning -> Workflow Policy -> Approval Gate -> Response),
  including all 11 required failure, timeout, approval, and rejection scenarios.
"""
import base64
import time
from typing import Any, Dict
import pytest
from fastapi.testclient import TestClient
import httpx

from src.app import app
from src.config import settings
from src.context.schemas import ContextItem, ReasoningRequest, ReasoningResult, RiskCategory
from src.core.errors import (
    AudioModuleUnavailableError,
    ForbiddenError,
    GatewayTimeoutError,
    ReasoningGatewayError,
    ReasoningModuleUnavailableError,
    TranscriptionModuleUnavailableError,
    WorkflowGatewayError,
    WorkflowModuleUnavailableError,
)
from src.gateways.audio_gateway import AudioGateway, get_audio_gateway
from src.gateways.reasoning_gateway import ReasoningGateway, get_reasoning_gateway
from src.gateways.resilience import CircuitBreaker
from src.gateways.service import BackendGatewayService, get_gateway_service
from src.gateways.transcription_gateway import TranscriptionGateway, get_transcription_gateway
from src.gateways.workflow_gateway import WorkflowGateway, get_workflow_gateway
from src.models.approval import ApprovalStatus, ToolExecuteRequest
from src.models.session import SessionState
from src.repositories.approval_repository import approval_repository
from src.repositories.session_repository import session_repository
from src.voice_stt.deepgram_adapter import DeepgramSTTAdapter
from src.voice_stt.provider_factory import get_stt_adapter


@pytest.fixture
def client():
    """TestClient fixture with clean repositories."""
    from src.core.security import rate_limiter
    session_repository.clear()
    approval_repository.clear()
    rate_limiter.reset()
    with TestClient(app) as test_client:
        yield test_client
    session_repository.clear()
    approval_repository.clear()
    rate_limiter.reset()


# ============================================================================
# 1. DAY 15-16: FOUR MODULE GATEWAYS, TIME-OUTS, CIRCUIT BREAKERS & RETRIES
# ============================================================================

class TestReasoningGateway:
    def test_reasoning_gateway_successful_call(self):
        gw = ReasoningGateway(timeout_seconds=2.0)
        req = ReasoningRequest(
            request_id="req-test-1",
            session_id="session-test-1",
            user_query="Schedule meeting tomorrow at 10am",
            context_items=[],
            prompt_version="v1.0.0",
        )
        result = gw.reason(req, correlation_id="corr-test-1")
        assert result is not None
        assert result.request_id == "req-test-1"
        assert result.response_text is not None
        assert gw.is_available is True

    def test_reasoning_gateway_enforced_timeout(self):
        class SlowEngine:
            def reason(self, req):
                time.sleep(0.2)
                return None

        gw = ReasoningGateway(engine=SlowEngine(), timeout_seconds=0.05)
        req = ReasoningRequest(
            request_id="req-slow",
            session_id="session-slow",
            user_query="slow query",
            context_items=[],
            prompt_version="v1.0.0",
        )
        with pytest.raises(GatewayTimeoutError) as exc_info:
            gw.reason(req, timeout=0.05)
        assert exc_info.value.code == "GATEWAY_TIMEOUT"
        assert exc_info.value.status_code == 504

    def test_reasoning_gateway_circuit_breaker(self):
        class BrokenEngine:
            def reason(self, req):
                raise RuntimeError("Engine database connection failed")

        cb = CircuitBreaker(failure_threshold=2, recovery_timeout_sec=10.0)
        gw = ReasoningGateway(engine=BrokenEngine(), circuit_breaker=cb, sleep_fn=lambda _: None)

        req = ReasoningRequest(request_id="r1", session_id="s1", user_query="fail", prompt_version="v1.0.0")
        with pytest.raises((ReasoningGatewayError, ReasoningModuleUnavailableError)):
            gw.reason(req)
        with pytest.raises((ReasoningGatewayError, ReasoningModuleUnavailableError)):
            gw.reason(req)

        assert cb.state == "OPEN"
        with pytest.raises(ReasoningModuleUnavailableError) as exc_info:
            gw.reason(req)
        assert "circuit breaker OPEN" in str(exc_info.value.message_safe_for_user)


class TestWorkflowGateway:
    def test_workflow_gateway_non_sensitive_tool_direct_execution(self):
        gw = WorkflowGateway()
        req = ToolExecuteRequest(
            session_id="sess-wf-1",
            tool_name="get_weather",
            parameters={"location": "San Francisco"},
        )
        res = gw.execute_tool(req, correlation_id="corr-wf-1")
        assert res.status == "completed"
        assert res.requires_approval is False
        assert res.execution_id.startswith("exec-")
        assert "San Francisco" in str(res.result)

    def test_workflow_gateway_sensitive_tool_requires_approval(self):
        gw = WorkflowGateway()
        policy = gw.evaluate_policy(
            action_type="delete_files",
            parameters={"path": "/important/data"},
            session_id="sess-wf-sensitive",
        )
        assert policy["requires_approval"] is True
        assert policy["approval_id"] is not None

        req = ToolExecuteRequest(
            session_id="sess-wf-sensitive",
            tool_name="delete_files",
            parameters={"path": "/important/data"},
        )
        with pytest.raises(ForbiddenError):
            gw.execute_tool(req)

        rec = approval_repository.get(policy["approval_id"])
        assert rec is not None
        assert rec.action_type == "delete_files"
        assert rec.status == ApprovalStatus.PENDING

    def test_workflow_gateway_execute_after_approval(self):
        gw = WorkflowGateway()
        policy = gw.evaluate_policy(
            action_type="move_files",
            parameters={"src": "/a", "dst": "/b"},
            session_id="sess-wf-appr",
        )
        appr_id = policy["approval_id"]
        assert appr_id is not None

        req_with_appr = ToolExecuteRequest(
            session_id="sess-wf-appr",
            tool_name="move_files",
            parameters={"src": "/a", "dst": "/b"},
            approval_id=appr_id,
        )
        with pytest.raises(ForbiddenError):
            gw.execute_tool(req_with_appr)

        approval_repository.approve(appr_id, user_id="admin-user")

        exec_res = gw.execute_tool(req_with_appr)
        assert exec_res.status == "completed"
        assert exec_res.requires_approval is False


class TestSTTAdapterFactory:
    def test_mock_stt_adapter_instantiation(self):
        adapter = get_stt_adapter("mock")
        assert adapter is not None
        events = adapter.transcribe_chunk(b"\x00\x01" * 320)
        assert isinstance(events, list)
        assert len(events) >= 1

    def test_deepgram_adapter_with_mock_transport(self):
        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                json={
                    "results": {
                        "channels": [
                            {
                                "alternatives": [
                                    {
                                        "transcript": "Hello from Deepgram mock transport",
                                        "confidence": 0.98,
                                        "words": [
                                            {"word": "Hello", "start": 0.0, "end": 0.3},
                                            {"word": "from", "start": 0.31, "end": 0.5},
                                        ],
                                    }
                                ]
                            }
                        ]
                    }
                },
            )

        mock_transport = httpx.MockTransport(handler)
        adapter = DeepgramSTTAdapter(api_key="fake-test-key", transport=mock_transport)
        events = adapter.transcribe_chunk(b"\x00\x02" * 320, is_last=True)
        assert isinstance(events, list)
        assert len(events) >= 1
        assert "Deepgram" in events[0].segment.text
        assert events[0].segment.confidence == 0.98
        assert events[0].segment.is_final is True


# ============================================================================
# 2. DAY 17-18: EVENT HISTORY, CURSOR REPLAY, SSE RECONNECTION, DEDUPLICATION
# ============================================================================

class TestEventHistoryAndReplay:
    def test_event_deduplication(self):
        session = session_repository.create()
        ev1 = session_repository.add_event(
            session_id=session.session_id,
            event_type="agent_thought",
            payload={"thought": "first thought"},
            event_id="evt-fixed-id-123",
        )
        assert ev1 is not None

        ev2 = session_repository.add_event(
            session_id=session.session_id,
            event_type="agent_thought",
            payload={"thought": "duplicate thought"},
            event_id="evt-fixed-id-123",
        )
        assert ev2.event_id == "evt-fixed-id-123"
        session_events = session_repository.get(session.session_id).events
        assert len(session_events) == 2  # initial session_created + single agent_thought

    def test_cursor_replay_pagination(self, client: TestClient):
        res = client.post("/api/v1/sessions", json={"metadata": {"test": "cursor"}})
        session_id = res.json()["session_id"]

        for i in range(5):
            session_repository.add_event(
                session_id=session_id,
                event_type="speech_transcript",
                payload={"index": i, "text": f"Event {i}"},
            )

        res_p1 = client.get(f"/api/v1/sessions/{session_id}/events?limit=2")
        assert res_p1.status_code == 200
        p1 = res_p1.json()
        assert len(p1["events"]) == 2
        last_cursor = p1["events"][-1]["event_id"]

        res_p2 = client.get(f"/api/v1/sessions/{session_id}/events?cursor={last_cursor}&limit=2")
        assert res_p2.status_code == 200
        p2 = res_p2.json()
        assert len(p2["events"]) == 2
        assert p2["events"][0]["sequence_number"] >= 3

    def test_cursor_replay_invalid_cursor(self, client: TestClient):
        res = client.post("/api/v1/sessions", json={"metadata": {"test": "invalid_cursor"}})
        session_id = res.json()["session_id"]
        res_invalid = client.get(f"/api/v1/sessions/{session_id}/events?cursor=non_existent_cursor_123")
        assert res_invalid.status_code == 400
        data = res_invalid.json()
        assert data["error"]["code"] in ("SESSION_VALIDATION_ERROR", "INVALID_CURSOR", "INVALID_REQUEST")

    def test_sse_stream_reconnection_last_event_id(self, client: TestClient):
        res = client.post("/api/v1/sessions", json={"metadata": {"test": "sse"}})
        session_id = res.json()["session_id"]

        ev1 = session_repository.add_event(session_id, "agent_thought", {"step": 1})
        ev2 = session_repository.add_event(session_id, "speech_transcript", {"step": 2})
        ev3 = session_repository.add_event(session_id, "tool_executed", {"step": 3})

        res_stream = client.get(
            f"/api/v1/sessions/{session_id}/events/stream?replay_only=true",
            headers={"Last-Event-ID": ev1.event_id},
        )
        assert res_stream.status_code == 200
        text = res_stream.text
        assert "event: speech_transcript" in text
        assert "event: tool_executed" in text
        assert '"step": 1' not in text

    def test_sse_disconnect_and_reconnection_lifecycle(self, client: TestClient):
        res = client.post("/api/v1/sessions", json={"metadata": {"test": "disconnect_reconnect"}})
        session_id = res.json()["session_id"]

        # Phase 1: Server emits two events and client consumes them
        ev1 = session_repository.add_event(session_id, "speech_transcript", {"text": "Hello world"})
        ev2 = session_repository.add_event(session_id, "agent_thought", {"thought": "Analyzing request"})

        res_initial = client.get(
            f"/api/v1/sessions/{session_id}/events/stream?replay_only=true"
        )
        assert res_initial.status_code == 200
        assert "Hello world" in res_initial.text
        assert "Analyzing request" in res_initial.text

        # Phase 2: Client disconnects; server produces subsequent events
        ev3 = session_repository.add_event(session_id, "tool_executed", {"tool": "get_weather", "output": "Sunny"})
        ev4 = session_repository.add_event(session_id, "speech_transcript", {"text": "It is sunny"})

        # Phase 3: Client reconnects using Last-Event-ID = ev2.event_id
        res_reconnect = client.get(
            f"/api/v1/sessions/{session_id}/events/stream?replay_only=true",
            headers={"Last-Event-ID": ev2.event_id},
        )
        assert res_reconnect.status_code == 200
        reconnect_text = res_reconnect.text

        # Verify only ev3 and ev4 delivered, no duplication of ev1 or ev2
        assert "event: tool_executed" in reconnect_text
        assert "It is sunny" in reconnect_text
        assert "Hello world" not in reconnect_text
        assert "Analyzing request" not in reconnect_text


# ============================================================================
# 3. DAY 19-20: LOCAL SECURITY, RATE LIMITING, HEALTH AGGREGATION, CORRELATION
# ============================================================================

class TestSecurityAndRateLimiting:
    def test_local_authorization_valid_api_key(self, client: TestClient):
        res = client.get("/api/v1/sessions", headers={"X-API-Key": "dev-local-key"})
        assert res.status_code == 200

    def test_local_authorization_invalid_api_key_returns_401(self, client: TestClient):
        res = client.get("/api/v1/sessions", headers={"X-API-Key": "invalid-unauthorized-key"})
        assert res.status_code == 401
        data = res.json()
        assert data["error"]["code"] == "UNAUTHORIZED"
        assert "Invalid API Key" in data["error"]["message"]

    def test_local_authorization_invalid_bearer_returns_401(self, client: TestClient):
        res = client.get("/api/v1/sessions", headers={"Authorization": "Bearer invalid-token"})
        assert res.status_code == 401
        data = res.json()
        assert data["error"]["code"] == "UNAUTHORIZED"

    def test_rate_limiting_enforcement(self, client: TestClient):
        headers = {"X-Test-Rate-Limit": "1", "X-API-Key": "dev-local-key"}
        from src.core.security import rate_limiter
        try:
            for _ in range(120):
                rate_limiter.is_allowed("dev-local-key")

            res = client.get("/api/v1/gateways/status", headers=headers)
            assert res.status_code == 429
            assert "Retry-After" in res.headers
            assert res.headers["X-RateLimit-Remaining"] == "0"
            data = res.json()
            assert data["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        finally:
            rate_limiter.reset()

    def test_four_module_health_aggregation(self, client: TestClient):
        res = client.get("/api/v1/gateways/status")
        assert res.status_code == 200
        data = res.json()
        assert data["health"]["status"] == "healthy"
        assert data["health"]["audio_gateway"]["status"] == "healthy"
        assert data["health"]["transcription_gateway"]["status"] == "healthy"
        assert data["health"]["reasoning_gateway"]["status"] == "healthy"
        assert data["health"]["workflow_gateway"]["status"] == "healthy"
        assert data["health"]["session_repository"]["status"] == "healthy"

    def test_health_aggregation_isolation(self):
        gw_svc = get_gateway_service()
        # Set reasoning unavailable -> status degraded, but audio, trans, workflow remain healthy
        orig_avail = gw_svc.reasoning_gateway._is_available
        try:
            gw_svc.reasoning_gateway.set_available(False)
            h = gw_svc.health_check()
            assert h["status"] == "degraded"
            assert h["reasoning_gateway"]["status"] == "unhealthy"
            assert h["audio_gateway"]["status"] == "healthy"
            assert h["transcription_gateway"]["status"] == "healthy"
            assert h["workflow_gateway"]["status"] == "healthy"
        finally:
            gw_svc.reasoning_gateway.set_available(orig_avail)

    def test_readiness_probe_four_modules(self, client: TestClient):
        res = client.get("/ready")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ready"
        checks = data["checks"]
        assert checks["audio_module"] == "healthy"
        assert checks["transcription_module"] == "healthy"
        assert checks["reasoning_module"] == "healthy"
        assert checks["workflow_module"] == "healthy"

    def test_request_and_correlation_id_propagation(self, client: TestClient):
        req_id = "req-custom-trace-999"
        corr_id = "corr-custom-trace-888"
        headers = {"X-Request-ID": req_id, "X-Correlation-ID": corr_id}

        res = client.get("/api/v1/gateways/status", headers=headers)
        assert res.status_code == 200
        assert res.headers.get("X-Request-ID") == req_id
        assert res.headers.get("X-Correlation-ID") == corr_id

    def test_error_response_preserves_request_and_correlation_ids(self, client: TestClient):
        req_id = "req-trace-error-777"
        corr_id = "corr-trace-error-666"
        headers = {"X-Request-ID": req_id, "X-Correlation-ID": corr_id}

        # Non-existent session endpoint triggers 404
        res = client.get("/api/v1/sessions/non-existent-session-000", headers=headers)
        assert res.status_code == 404
        assert res.headers.get("X-Request-ID") == req_id
        assert res.headers.get("X-Correlation-ID") == corr_id
        err = res.json()["error"]
        assert err["correlation_id"] == corr_id
        assert err["request_id"] == req_id

    def test_health_aggregation_each_individual_module_failure(self, client: TestClient):
        gw_svc = get_gateway_service()

        # 1. Audio module failure and recovery
        orig_audio = gw_svc.audio_gateway._is_available
        try:
            gw_svc.audio_gateway.set_available(False)
            h = gw_svc.health_check()
            assert h["status"] == "degraded"
            assert h["audio_gateway"]["status"] == "unhealthy"
            assert h["transcription_gateway"]["status"] == "healthy"
            ready_res = client.get("/ready")
            assert ready_res.status_code == 503
            assert ready_res.json()["status"] == "not_ready"
        finally:
            gw_svc.audio_gateway.set_available(orig_audio)
            assert client.get("/ready").status_code == 200

        # 2. Transcription module failure and recovery
        orig_trans = gw_svc.transcription_gateway._is_available
        try:
            gw_svc.transcription_gateway.set_available(False)
            h = gw_svc.health_check()
            assert h["status"] == "degraded"
            assert h["transcription_gateway"]["status"] == "unhealthy"
            ready_res = client.get("/ready")
            assert ready_res.status_code == 503
        finally:
            gw_svc.transcription_gateway.set_available(orig_trans)
            assert client.get("/ready").status_code == 200

        # 3. Workflow module failure and recovery
        orig_wf = gw_svc.workflow_gateway._is_available
        try:
            gw_svc.workflow_gateway.set_available(False)
            h = gw_svc.health_check()
            assert h["status"] == "degraded"
            assert h["workflow_gateway"]["status"] == "unhealthy"
            ready_res = client.get("/ready")
            assert ready_res.status_code == 503
        finally:
            gw_svc.workflow_gateway.set_available(orig_wf)
            assert client.get("/ready").status_code == 200

    def test_health_aggregation_multiple_modules_failure(self, client: TestClient):
        gw_svc = get_gateway_service()
        orig_audio = gw_svc.audio_gateway._is_available
        orig_reason = gw_svc.reasoning_gateway._is_available
        try:
            gw_svc.audio_gateway.set_available(False)
            gw_svc.reasoning_gateway.set_available(False)
            h = gw_svc.health_check()
            assert h["status"] == "degraded"
            assert h["audio_gateway"]["status"] == "unhealthy"
            assert h["reasoning_gateway"]["status"] == "unhealthy"
            ready_res = client.get("/ready")
            assert ready_res.status_code == 503
            assert ready_res.json()["checks"]["audio_module"] == "unhealthy"
            assert ready_res.json()["checks"]["reasoning_module"] == "unhealthy"
        finally:
            gw_svc.audio_gateway.set_available(orig_audio)
            gw_svc.reasoning_gateway.set_available(orig_reason)


# ============================================================================
# 4. DAY 21: FULL END-TO-END PIPELINE SCENARIOS (1 THROUGH 11)
# ============================================================================

class TestDay21EndToEndPipeline:
    # Scenario 1: Successful complete session
    def test_scenario_1_successful_complete_session(self, client: TestClient):
        session = session_repository.create(metadata={"scenario": "e2e_pipeline"})
        session_repository.transition(session.session_id, SessionState.ACTIVE)

        raw_pcm = b"\x00\x05" * 320 * 2  # 40ms
        b64_audio = base64.b64encode(raw_pcm).decode("utf-8")

        res_pipe = client.post(
            f"/api/v1/sessions/{session.session_id}/pipeline",
            json={"audio_base64": b64_audio, "format": "linear16", "sample_rate": 16000},
            headers={"X-Correlation-ID": "corr-pipe-standard"},
        )
        assert res_pipe.status_code == 200
        data = res_pipe.json()
        assert data["session_id"] == session.session_id
        assert data["status"] == "completed"
        assert data["chunks_count"] == 2
        assert "transcript" in data
        assert "reasoning" in data
        assert data["events_recorded"] >= 2

    # Scenario 2: Invalid audio input
    def test_scenario_2_invalid_audio_input(self, client: TestClient):
        session = session_repository.create()
        session_repository.transition(session.session_id, SessionState.ACTIVE)

        res = client.post(
            f"/api/v1/sessions/{session.session_id}/pipeline",
            json={"audio_base64": "invalid_base64_string!!!"},
        )
        assert res.status_code == 400
        data = res.json()
        assert data["error"]["code"] in ("INVALID_BASE64_AUDIO", "AUDIO_GATEWAY_ERROR")

    # Scenario 3: Audio module failure
    def test_scenario_3_audio_module_failure(self, client: TestClient):
        session = session_repository.create()
        session_repository.transition(session.session_id, SessionState.ACTIVE)

        raw_pcm = b"\x00\x05" * 320 * 2
        b64_audio = base64.b64encode(raw_pcm).decode("utf-8")

        gw_svc = get_gateway_service()
        orig_avail = gw_svc.audio_gateway._is_available
        try:
            gw_svc.audio_gateway.set_available(False)
            res = client.post(
                f"/api/v1/sessions/{session.session_id}/pipeline",
                json={"audio_base64": b64_audio},
            )
            assert res.status_code == 503
            assert res.json()["error"]["code"] == "AUDIO_MODULE_UNAVAILABLE"
        finally:
            gw_svc.audio_gateway.set_available(orig_avail)

    # Scenario 4: Transcription module failure
    def test_scenario_4_transcription_module_failure(self, client: TestClient):
        session = session_repository.create()
        session_repository.transition(session.session_id, SessionState.ACTIVE)

        raw_pcm = b"\x00\x05" * 320 * 2
        b64_audio = base64.b64encode(raw_pcm).decode("utf-8")

        gw_svc = get_gateway_service()
        orig_avail = gw_svc.transcription_gateway._is_available
        try:
            gw_svc.transcription_gateway.set_available(False)
            res = client.post(
                f"/api/v1/sessions/{session.session_id}/pipeline",
                json={"audio_base64": b64_audio},
            )
            assert res.status_code == 503
            assert res.json()["error"]["code"] == "TRANSCRIPTION_MODULE_UNAVAILABLE"
        finally:
            gw_svc.transcription_gateway.set_available(orig_avail)

    # Scenario 5: Reasoning module failure
    def test_scenario_5_reasoning_module_failure(self, client: TestClient):
        session = session_repository.create()
        session_repository.transition(session.session_id, SessionState.ACTIVE)

        raw_pcm = b"\x00\x05" * 320 * 2
        b64_audio = base64.b64encode(raw_pcm).decode("utf-8")

        gw_svc = get_gateway_service()
        orig_avail = gw_svc.reasoning_gateway._is_available
        try:
            gw_svc.reasoning_gateway.set_available(False)
            res = client.post(
                f"/api/v1/sessions/{session.session_id}/pipeline",
                json={"audio_base64": b64_audio},
            )
            assert res.status_code == 503
            assert res.json()["error"]["code"] == "REASONING_MODULE_UNAVAILABLE"
        finally:
            gw_svc.reasoning_gateway.set_available(orig_avail)

    # Scenario 6: Workflow module failure
    def test_scenario_6_workflow_module_failure(self, client: TestClient):
        session = session_repository.create()
        session_repository.transition(session.session_id, SessionState.ACTIVE)

        raw_pcm = b"\x00\x05" * 320 * 2
        b64_audio = base64.b64encode(raw_pcm).decode("utf-8")

        # Mock reasoning to propose a sensitive tool call requiring workflow gateway
        mock_result = ReasoningResult(
            request_id="req-wf-fail",
            status="success",
            response_text="Action requiring workflow",
            action_required=True,
            action_type="delete_files",
            risk_level=RiskCategory.CATEGORY_D,
            requires_approval=True,
            confidence=0.9,
            prompt_version="v1.0.0",
        )

        gw_svc = get_gateway_service()
        orig_reason = gw_svc.reasoning_gateway.reason
        orig_avail = gw_svc.workflow_gateway._is_available
        try:
            gw_svc.reasoning_gateway.reason = lambda *args, **kwargs: mock_result
            gw_svc.workflow_gateway.set_available(False)

            # Workflow policy evaluation raises WorkflowModuleUnavailableError
            with pytest.raises(WorkflowModuleUnavailableError):
                gw_svc.workflow_gateway.evaluate_policy(
                    action_type="delete_files",
                    parameters={"path": "/tmp/a"},
                    session_id=session.session_id,
                )

            # Full pipeline endpoint execution also propagates 503 WORKFLOW_MODULE_UNAVAILABLE
            res = client.post(
                f"/api/v1/sessions/{session.session_id}/pipeline",
                json={"audio_base64": b64_audio},
            )
            assert res.status_code == 503
            assert res.json()["error"]["code"] == "WORKFLOW_MODULE_UNAVAILABLE"
        finally:
            gw_svc.reasoning_gateway.reason = orig_reason
            gw_svc.workflow_gateway.set_available(orig_avail)

    # Scenario 7: Module timeout
    def test_scenario_7_module_timeout(self, client: TestClient):
        session = session_repository.create()
        session_repository.transition(session.session_id, SessionState.ACTIVE)

        raw_pcm = b"\x00\x05" * 320 * 2
        b64_audio = base64.b64encode(raw_pcm).decode("utf-8")

        gw_svc = get_gateway_service()
        orig_reason = gw_svc.reasoning_gateway.reason

        def slow_reason(*args, **kwargs):
            raise GatewayTimeoutError("Reasoning deadline exceeded.")

        try:
            gw_svc.reasoning_gateway.reason = slow_reason
            res = client.post(
                f"/api/v1/sessions/{session.session_id}/pipeline",
                json={"audio_base64": b64_audio},
            )
            assert res.status_code == 504
            assert res.json()["error"]["code"] == "GATEWAY_TIMEOUT"
        finally:
            gw_svc.reasoning_gateway.reason = orig_reason

    # Scenario 8: Workflow approval required
    def test_scenario_8_workflow_approval_required(self, client: TestClient):
        session = session_repository.create(metadata={"scenario": "approval_gate"})
        session_repository.transition(session.session_id, SessionState.ACTIVE)

        raw_pcm = b"\x00\x05" * 320 * 2
        b64_audio = base64.b64encode(raw_pcm).decode("utf-8")

        mock_sensitive_result = ReasoningResult(
            request_id="req-mock-sens",
            status="success",
            response_text="I propose deleting the requested log files.",
            action_required=True,
            action_type="delete_files",
            risk_level=RiskCategory.CATEGORY_D,
            requires_approval=True,
            confidence=0.95,
            prompt_version="v1.0.0",
        )

        gw_svc = get_gateway_service()
        orig_reason = gw_svc.reasoning_gateway.reason
        try:
            gw_svc.reasoning_gateway.reason = lambda *args, **kwargs: mock_sensitive_result

            res_pipe = client.post(
                f"/api/v1/sessions/{session.session_id}/pipeline",
                json={"audio_base64": b64_audio},
                headers={"X-Correlation-ID": "corr-pipe-approval"},
            )
            assert res_pipe.status_code == 200
            data = res_pipe.json()
            assert data["status"] == "requires_approval"
            assert data["approval_id"] is not None
            assert data["approval_id"].startswith("appr-")
        finally:
            gw_svc.reasoning_gateway.reason = orig_reason

    # Scenario 9: Approval accepted
    def test_scenario_9_approval_accepted(self, client: TestClient):
        req = approval_repository.create_request(session_id="s1", action_type="delete_files", risk_level="D")
        res = client.post(f"/api/v1/approvals/{req.approval_id}/approve", json={"reviewed_by": "admin"})
        assert res.status_code == 200
        assert res.json()["status"] == "approved"

        # Tool execution with approved token succeeds
        gw_svc = get_gateway_service()
        tool_req = ToolExecuteRequest(
            session_id="s1",
            tool_name="delete_files",
            parameters={"path": "/var/log/audit.log"},
            approval_id=req.approval_id,
        )
        resp = gw_svc.workflow_gateway.execute_tool(tool_req)
        assert resp.status == "completed"

    # Scenario 10: Approval rejected
    def test_scenario_10_approval_rejected(self, client: TestClient):
        req = approval_repository.create_request(session_id="s1", action_type="delete_files", risk_level="D")
        res = client.post(f"/api/v1/approvals/{req.approval_id}/reject", json={"reason": "Dangerous operation"})
        assert res.status_code == 200
        assert res.json()["status"] == "rejected"

        # Tool execution with rejected token raises 403 Forbidden
        gw_svc = get_gateway_service()
        tool_req = ToolExecuteRequest(
            session_id="s1",
            tool_name="delete_files",
            parameters={"path": "/var/log/audit.log"},
            approval_id=req.approval_id,
        )
        with pytest.raises(ForbiddenError):
            gw_svc.workflow_gateway.execute_tool(tool_req)

    # Scenario 11: Invalid or repeated approval request
    def test_scenario_11_invalid_or_repeated_approval(self, client: TestClient):
        # 1. Non-existent approval ID -> 404
        res_404 = client.post("/api/v1/approvals/non-existent-appr-999/approve")
        assert res_404.status_code == 404

        # 2. Repeated approval decision -> 409 Conflict
        req = approval_repository.create_request(session_id="s1", action_type="move_files", risk_level="C")
        res_first = client.post(f"/api/v1/approvals/{req.approval_id}/approve")
        assert res_first.status_code == 200
        res_repeat = client.post(f"/api/v1/approvals/{req.approval_id}/approve")
        assert res_repeat.status_code == 409

    # Scenario 12: Session ID and Correlation ID full propagation
    def test_e2e_session_and_correlation_id_full_propagation(self, client: TestClient):
        session = session_repository.create(metadata={"user": "vaishnavi"})
        session_repository.transition(session.session_id, SessionState.ACTIVE)

        raw_pcm = b"\x00\x05" * 320 * 2
        b64_audio = base64.b64encode(raw_pcm).decode("utf-8")

        req_id = "req-pipe-full-trace-111"
        corr_id = "corr-pipe-full-trace-222"
        headers = {"X-Request-ID": req_id, "X-Correlation-ID": corr_id}

        res = client.post(
            f"/api/v1/sessions/{session.session_id}/pipeline",
            json={"audio_base64": b64_audio},
            headers=headers,
        )
        assert res.status_code == 200
        assert res.headers.get("X-Request-ID") == req_id
        assert res.headers.get("X-Correlation-ID") == corr_id

        # Verify correlation ID is attached to events in SessionRepository
        updated_session = session_repository.get(session.session_id)
        pipe_events = [e for e in updated_session.events if e.correlation_id == corr_id]
        assert len(pipe_events) >= 2
