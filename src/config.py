"""Application configuration, environment settings, and startup validation."""
import os
from typing import Set
from pydantic import BaseModel, Field


def read_int_env(var_name: str, default: int) -> int:
    """Reads an integer environment variable, raising a clear ValueError on non-integer input."""
    raw = os.getenv(var_name)
    if raw is None or raw.strip() == "":
        return default
    raw_stripped = raw.strip()
    try:
        return int(raw_stripped)
    except ValueError:
        raise ValueError(f"Invalid {var_name}: '{raw_stripped}' is not an integer.")


def read_bool_env(var_name: str, default: bool = True) -> bool:
    """Reads a boolean environment variable, accepting true/false/1/0/yes/no (case-insensitive)."""
    raw = os.getenv(var_name)
    if raw is None or raw.strip() == "":
        return default
    raw_clean = raw.strip().lower()
    if raw_clean in ("true", "1", "yes"):
        return True
    if raw_clean in ("false", "0", "no"):
        return False
    raise ValueError(f"Invalid {var_name}: '{raw.strip()}'. Use true or false.")


class Settings(BaseModel):
    """Core settings for backend service."""
    app_name: str = Field(default="AI Voice Co-Pilot Backend", description="Service name")
    version: str = Field(default="1.0.0", description="API Version")
    api_prefix: str = Field(default="/api/v1", description="API route prefix")
    mock_mode: bool = Field(
        default_factory=lambda: read_bool_env("MOCK_MODE", True),
        description="Whether mock mode is enabled (default is True; no API keys needed)"
    )
    host: str = Field(default_factory=lambda: os.getenv("HOST", "127.0.0.1"))
    port: int = Field(default_factory=lambda: read_int_env("PORT", 8000))
    environment: str = Field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    max_payload_size_bytes: int = Field(
        default_factory=lambda: read_int_env("MAX_PAYLOAD_SIZE_BYTES", 1024 * 1024),
        description="Maximum permitted request body size in bytes (default 1MB)"
    )
    session_ttl_seconds: int = Field(
        default_factory=lambda: read_int_env("SESSION_TTL_SECONDS", 3600),
        description="Session idle TTL in seconds before considered expired (default 1 hour)"
    )
    log_level: str = Field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )


VALID_ENVIRONMENTS: Set[str] = {"development", "testing", "staging", "production"}
VALID_LOG_LEVELS: Set[str] = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def validate_configuration(cfg: Settings) -> None:
    """Validates configuration parameters at application startup.
    
    Raises:
        ValueError: if any configuration parameter violates domain bounds.
    """
    if not (1 <= cfg.port <= 65535):
        raise ValueError(
            f"Invalid PORT: {cfg.port}. Port must be an integer between 1 and 65535."
        )

    if cfg.max_payload_size_bytes <= 0:
        raise ValueError(
            f"Invalid MAX_PAYLOAD_SIZE_BYTES: {cfg.max_payload_size_bytes}. "
            "Payload size limit must be a positive integer."
        )

    if cfg.session_ttl_seconds <= 0:
        raise ValueError(
            f"Invalid SESSION_TTL_SECONDS: {cfg.session_ttl_seconds}. "
            "Session TTL must be a positive integer."
        )

    if cfg.log_level not in VALID_LOG_LEVELS:
        raise ValueError(
            f"Invalid LOG_LEVEL: '{cfg.log_level}'. "
            f"Permitted values are: {sorted(VALID_LOG_LEVELS)}."
        )

    if cfg.environment.lower() not in VALID_ENVIRONMENTS:
        raise ValueError(
            f"Invalid ENVIRONMENT: '{cfg.environment}'. "
            f"Permitted values are: {sorted(VALID_ENVIRONMENTS)}."
        )

    if not cfg.mock_mode:
        # When mock mode is disabled, require production provider credentials
        has_creds = bool(
            os.getenv("OPENAI_API_KEY")
            or os.getenv("DEEPGRAM_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("BACKEND_API_KEY")
        )
        if not has_creds:
            raise ValueError(
                "Production credentials missing: Mock mode is disabled (MOCK_MODE=false), "
                "but no valid API credentials (OPENAI_API_KEY, DEEPGRAM_API_KEY, ANTHROPIC_API_KEY, "
                "or BACKEND_API_KEY) were found in the environment."
            )


# Singleton instance
settings = Settings()
validate_configuration(settings)
