"""Application configuration and environment settings."""
import os
from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Core settings for backend service."""
    app_name: str = Field(default="AI Voice Co-Pilot Backend", description="Service name")
    version: str = Field(default="1.0.0", description="API Version")
    api_prefix: str = Field(default="/api/v1", description="API route prefix")
    mock_mode: bool = Field(
        default_factory=lambda: os.getenv("MOCK_MODE", "true").strip().lower() in ("1", "true", "yes"),
        description="Whether mock mode is enabled (default is True; no API keys needed)"
    )
    host: str = Field(default_factory=lambda: os.getenv("HOST", "127.0.0.1"))
    port: int = Field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    environment: str = Field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))


# Singleton instance
settings = Settings()
