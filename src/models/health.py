"""Health and Readiness response models."""
from datetime import datetime, timezone
from typing import Any, Dict
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Payload returned by the health check endpoint."""
    status: str = Field(default="healthy", description="Service health state")
    service: str = Field(..., description="Service identifier")
    version: str = Field(..., description="Service version")
    mock_mode: bool = Field(..., description="Indicates if mock mode is enabled")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC timestamp",
    )


class ReadinessResponse(BaseModel):
    """Payload returned by the readiness probe endpoint."""
    status: str = Field(default="ready", description="Readiness state (ready/not_ready)")
    checks: Dict[str, Any] = Field(..., description="Subsystem health checks status")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC timestamp",
    )
