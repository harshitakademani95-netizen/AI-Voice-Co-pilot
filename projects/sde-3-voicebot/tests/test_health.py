"""Tests for health and readiness endpoints."""
from unittest.mock import patch
from starlette.testclient import TestClient


def test_health_endpoint_root(client: TestClient):
    """Verifies that /health returns 200, healthy status, and mock mode flag."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "service" in data
    assert "version" in data
    assert data["mock_mode"] is True
    assert "timestamp" in data


def test_health_endpoint_api_prefix(client: TestClient):
    """Verifies /api/v1/health responds correctly per interface contract."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["mock_mode"] is True


def test_readiness_endpoint_root_healthy(client: TestClient):
    """Verifies /ready returns 200 when repository is operational."""
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["checks"]["session_repository"] == "ok"
    assert data["checks"]["mock_mode"] is True


def test_readiness_endpoint_api_prefix(client: TestClient):
    """Verifies /api/v1/ready responds correctly."""
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["checks"]["session_repository"] == "ok"


def test_readiness_endpoint_unhealthy_repository(client: TestClient):
    """Verifies /ready returns 503 if repository check fails."""
    with patch("src.repositories.session_repository.session_repository.is_healthy", return_value=False):
        response = client.get("/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["checks"]["session_repository"] == "error"
