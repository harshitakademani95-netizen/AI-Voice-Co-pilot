"""FastAPI Application factory and configuration."""
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.config import settings
from src.core.errors import AppError
from src.core.middleware import (
    RequestCorrelationMiddleware,
    app_error_handler,
    handle_unhandled_exception,
    http_exception_handler,
    validation_exception_handler,
)
from src.routes.health import router as health_router
from src.routes.sessions import router as sessions_router


def create_app() -> FastAPI:
    """Builds and configures the FastAPI application instance."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="AI Voice Co-Pilot Backend & Session Management (W5 Workstream)",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # 1. Register Request and Correlation ID middleware
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

    return app


app = create_app()
