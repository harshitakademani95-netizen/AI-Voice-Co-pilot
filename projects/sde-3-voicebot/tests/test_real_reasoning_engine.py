"""Automated tests for Real Reasoning Engine and Engine Status."""
from pathlib import Path
import sys

_project_dir = Path(__file__).resolve().parent.parent
_src_dir = _project_dir / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))
if str(_project_dir) not in sys.path:
    sys.path.insert(0, str(_project_dir))

import pytest
from starlette.testclient import TestClient

from src.app import create_app
from src.context.schemas import ContextItem, ReasoningRequest, RiskCategory
from src.gateways.reasoning_gateway import ReasoningGateway
from src.reasoning.real_engine import RealReasoningEngine, get_reasoning_engine


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_real_reasoning_engine_initialization():
    engine = RealReasoningEngine()
    info = engine.get_info()
    assert info["engine"] == "RealReasoningEngine"
    assert info["supports_local"] is True
    assert info["supports_live"] is True
    assert info["active_mode"] in ("real_local", "live_llm")


def test_real_reasoning_engine_processes_query():
    engine = RealReasoningEngine()
    req = ReasoningRequest(
        request_id="req-real-01",
        session_id="sess-real-01",
        user_query="Why is this application failing?",
        context_items=[
            ContextItem(
                item_id="ctx-01",
                context_type="screen",
                source="terminal",
                content="ZeroDivisionError: division by zero in calculate_metrics()",
            )
        ],
        prompt_version="v1.0.0",
    )
    res = engine.reason(req)
    assert res is not None
    assert res.response_text != ""
    assert res.confidence > 0.5
    assert len(res.sources) >= 1
    assert res.sources[0].source_id == "ctx-01"


def test_real_reasoning_engine_risk_classification():
    engine = RealReasoningEngine()
    # Sensitive file operation
    req = ReasoningRequest(
        request_id="req-real-02",
        session_id="sess-real-02",
        user_query="Delete all logs and wipe database",
        context_items=[],
        prompt_version="v1.0.0",
    )
    res = engine.reason(req)
    assert res.risk_level in (RiskCategory.CATEGORY_C, RiskCategory.CATEGORY_D)
    assert res.requires_approval is True


def test_reasoning_gateway_uses_real_engine():
    gateway = ReasoningGateway()
    status = gateway.get_status()
    assert "engine_info" in status
    assert status["engine_info"]["engine"] == "RealReasoningEngine"


def test_api_reasoning_engine_status_endpoint(client: TestClient):
    resp = client.get("/api/reasoning/engine-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["gateway"] == "ReasoningGateway"
    assert "engine_info" in data
    assert data["engine_info"]["supports_local"] is True


def test_api_reason_endpoint_includes_engine_info(client: TestClient):
    resp = client.post(
        "/api/reason",
        json={"scenario": "error", "user_query": "Explain ZeroDivisionError", "prompt_version": "v1.0.0"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "engine_info" in data
    assert "agent_orchestration" in data
    assert "response_text" in data
