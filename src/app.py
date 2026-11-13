"""FastAPI Application factory, lifecycle validation, and route configuration."""
from pathlib import Path
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.config import settings, validate_configuration
from src.core.errors import AppError
from src.core.logging_config import configure_logging
from src.core.middleware import (
    PayloadSizeLimitMiddleware,
    RequestCorrelationMiddleware,
    app_error_handler,
    handle_unhandled_exception,
    http_exception_handler,
    validation_exception_handler,
)
from src.routes.approvals import router as approvals_router
from src.routes.health import router as health_router
from src.routes.reasoning import router as reasoning_router
from src.routes.sessions import router as sessions_router


def create_app() -> FastAPI:
    """Builds and configures the FastAPI application instance."""
    # Configure structured logging
    configure_logging()

    # Validate startup configuration (fail fast)
    validate_configuration(settings)

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="AI Voice Co-Pilot Backend & Session Management (Week 2 Session Service)",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # 1. Register Middlewares (LIFO order: RequestCorrelationMiddleware runs first, wrapping PayloadSizeLimitMiddleware)
    app.add_middleware(PayloadSizeLimitMiddleware)
    app.add_middleware(RequestCorrelationMiddleware)

    # 2. Register exception handlers for typed error envelopes
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, handle_unhandled_exception)

    # 3. Mount routes under both root and /api/v1
    # Health and readiness routes
    app.include_router(health_router)
    app.include_router(health_router, prefix=settings.api_prefix)

    # Session routes
    app.include_router(sessions_router)
    app.include_router(sessions_router, prefix=settings.api_prefix)

    # Reasoning and Interactive Dashboard routes (Workstream W3 integration)
    app.include_router(reasoning_router)

    # Approvals & Tool Safety Gate routes
    app.include_router(approvals_router)
    app.include_router(approvals_router, prefix=settings.api_prefix)

    # 4. Mount optional frontend web dashboard
    web_dir = Path(__file__).resolve().parent.parent / "web"
    if web_dir.exists():
        app.mount("/ui", StaticFiles(directory=str(web_dir), html=True), name="ui")

    return app


app = create_app()
