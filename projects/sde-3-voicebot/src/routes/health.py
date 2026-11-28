"""Health and readiness probe route handlers with multi-module aggregation."""
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from src.config import settings
from src.models.health import HealthResponse, ReadinessResponse
from src.repositories.session_repository import session_repository

router = APIRouter(tags=["Health & Readiness"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health probe",
    description="Returns aggregated service vitality across backend and gateway subsystems.",
)
async def get_health() -> HealthResponse:
    """Returns basic service health status with optional module aggregation."""
    overall_status = "healthy"
    try:
        from src.gateways.service import get_gateway_service
        gw_svc = get_gateway_service()
        h = gw_svc.health_check()
        if h.get("status") in ("degraded", "unhealthy"):
            overall_status = h.get("status")
    except Exception:
        pass

    return HealthResponse(
        status=overall_status,
        service=settings.app_name,
        version=settings.version,
        mock_mode=settings.mock_mode,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description="Validates that internal in-memory repository, settings, and all four modules are healthy.",
)
async def get_readiness() -> JSONResponse:
    """Returns readiness check indicating if the server and all subsystems can accept requests."""
    repo_ok = session_repository.is_healthy()
    checks = {
        "session_repository": "ok" if repo_ok else "error",
        "mock_mode": settings.mock_mode,
        "environment": settings.environment,
    }

    modules_ok = True
    try:
        from src.gateways.service import get_gateway_service
        gw_svc = get_gateway_service()
        h = gw_svc.health_check()
        checks["audio_module"] = "healthy" if h.get("audio_gateway", {}).get("status") == "healthy" else "unhealthy"
        checks["transcription_module"] = "healthy" if h.get("transcription_gateway", {}).get("status") == "healthy" else "unhealthy"
        checks["reasoning_module"] = "healthy" if h.get("reasoning_gateway", {}).get("status") == "healthy" else "unhealthy"
        checks["workflow_module"] = "healthy" if h.get("workflow_gateway", {}).get("status") == "healthy" else "unhealthy"
        if any(v == "unhealthy" for k, v in checks.items() if k.endswith("_module")):
            modules_ok = False
    except Exception:
        pass

    all_ready = repo_ok and modules_ok
    status_text = "ready" if all_ready else "not_ready"
    http_status = status.HTTP_200_OK if all_ready else status.HTTP_503_SERVICE_UNAVAILABLE

    payload = ReadinessResponse(
        status=status_text,
        checks=checks,
    )
    return JSONResponse(status_code=http_status, content=payload.model_dump())
