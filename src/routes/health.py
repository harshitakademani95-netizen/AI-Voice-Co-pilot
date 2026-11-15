"""Health and readiness probe route handlers."""
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from src.config import settings
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
    description="Returns service vitality and mock-mode state.",
)
async def get_health() -> HealthResponse:
    """Returns basic service health status."""
    return HealthResponse(
        status="healthy",
        service=settings.app_name,
        version=settings.version,
        mock_mode=settings.mock_mode,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description="Validates that internal in-memory repository and settings are initialized.",
)
async def get_readiness() -> JSONResponse:
    """Returns readiness check indicating if the server can accept requests."""
    repo_ok = session_repository.is_healthy()
    status_text = "ready" if repo_ok else "not_ready"
    http_status = status.HTTP_200_OK if repo_ok else status.HTTP_503_SERVICE_UNAVAILABLE

    payload = ReadinessResponse(
        status=status_text,
        checks={
            "session_repository": "ok" if repo_ok else "error",
            "mock_mode": settings.mock_mode,
            "environment": settings.environment,
        },
    )
    return JSONResponse(status_code=http_status, content=payload.model_dump())
