"""Health and readiness probe route handlers."""
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from src.config import settings
from src.gateways.service import get_gateway_service
from src.models.health import HealthResponse, ReadinessResponse
from src.repositories.session_repository import session_repository

router = APIRouter(tags=["Health & Readiness"])


@router.get("/", include_in_schema=False)
async def root(request: Request):
    """Redirects browser requests to the UI dashboard and others to Swagger UI."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return RedirectResponse(url="/ui/")
    return RedirectResponse(url="/docs")


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health probe",
    description="Returns aggregated service vitality across all four modules and mock-mode state.",
)
async def get_health() -> HealthResponse:
    """Returns aggregated backend service health status across all four modules."""
    svc = get_gateway_service()
    gw_health = svc.health_check()
    overall_status = "healthy" if gw_health.get("status") == "healthy" else "degraded"
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
    description="Validates that all four module gateways, in-memory repository, and settings are operational.",
)
async def get_readiness() -> JSONResponse:
    """Returns readiness check indicating if the server can accept requests."""
    svc = get_gateway_service()
    gw_health = svc.health_check()
    repo_ok = session_repository.is_healthy()
    all_ok = (gw_health.get("status") == "healthy") and repo_ok

    status_text = "ready" if all_ok else "not_ready"
    http_status = status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE

    payload = ReadinessResponse(
        status=status_text,
        checks={
            "session_repository": "ok" if repo_ok else "error",
            "audio_module": gw_health.get("audio_gateway", {}).get("status", "unknown"),
            "transcription_module": gw_health.get("transcription_gateway", {}).get("status", "unknown"),
            "reasoning_module": gw_health.get("reasoning_gateway", {}).get("status", "unknown"),
            "workflow_module": gw_health.get("workflow_gateway", {}).get("status", "unknown"),
            "mock_mode": settings.mock_mode,
            "environment": settings.environment,
        },
    )
    return JSONResponse(status_code=http_status, content=payload.model_dump())
