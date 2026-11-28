"""Automated tests for Content and Query Dispatcher and Reasoning Integration."""
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
from src.repositories.approval_repository import approval_repository
from src.repositories.session_repository import session_repository


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_state():
    session_repository.clear()
    approval_repository.clear()
    yield
    session_repository.clear()
    approval_repository.clear()


def test_dispatcher_valid_query_execution(client: TestClient):
    resp = client.post(
        "/api/dispatcher/query",
        json={"query": "Check system tasks and compile status", "session_id": "sess-disp-01"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("completed", "requires_approval")
    assert "plan" in data
    assert "verification" in data
    assert "final_response" in data
    assert len(data["plan"]["steps"]) >= 1


def test_dispatcher_v1_route_alias(client: TestClient):
    resp = client.post(
        "/api/v1/dispatcher/query",
        json={"query": "Explain what this document says", "session_id": "sess-disp-v1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "Explain what this document says"
    assert data["status"] == "completed"


def test_dispatcher_empty_query_rejected(client: TestClient):
    resp = client.post(
        "/api/dispatcher/query",
        json={"query": "   ", "session_id": "sess-disp-empty"},
    )
    assert resp.status_code == 400
    err_msg = resp.json().get("detail") or resp.json().get("error", {}).get("message", "")
    assert "empty" in err_msg.lower()


def test_dispatcher_with_context_items(client: TestClient):
    context = [
        {
            "item_id": "ctx-disp-01",
            "context_type": "document",
            "source": "readme.md",
            "content": "Deployment target is production AWS cluster.",
        }
    ]
    resp = client.post(
        "/api/dispatcher/query",
        json={
            "query": "Where is the deployment target?",
            "session_id": "sess-disp-ctx",
            "context_items": context,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["verification"]["is_verified"] is True


def test_dispatcher_approval_gate_for_sensitive_action(client: TestClient):
    resp = client.post(
        "/api/dispatcher/query",
        json={"query": "Delete all obsolete backup files", "session_id": "sess-disp-gate"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "requires_approval"
    assert data["approval_id"] is not None


def test_reasoning_endpoint_returns_agent_orchestration(client: TestClient):
    resp = client.post(
        "/api/reason",
        json={"scenario": "error", "user_query": "Why is this application failing?", "prompt_version": "v1.0.0"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "agent_orchestration" in data
    assert "response_text" in data
    assert data["status"] == "success"
