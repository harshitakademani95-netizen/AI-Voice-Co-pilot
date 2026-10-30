"""CLI Launcher for running the backend in mock mode."""
import os
import sys
import uvicorn

from src.config import settings


def print_banner():
    banner = f"""
================================================================================
           AI Voice Co-Pilot Backend - W5 Foundation & Sessions
================================================================================
 Mode:        {'MOCK MODE (Active - No paid credentials needed)' if settings.mock_mode else 'LIVE MODE'}
 Service:     {settings.app_name}
 Version:     {settings.version}
 Environment: {settings.environment}
 Host:        http://{settings.host}:{settings.port}
 API Docs:    http://{settings.host}:{settings.port}/docs
 Health:      http://{settings.host}:{settings.port}/api/v1/health
 Readiness:   http://{settings.host}:{settings.port}/api/v1/ready
 Sessions:    http://{settings.host}:{settings.port}/api/v1/sessions
================================================================================
"""
    print(banner)


def main():
    """Starts the Uvicorn ASGI server with mock mode enabled by default."""
    # Ensure mock mode is explicitly set to true if not specified
    if "MOCK_MODE" not in os.environ:
        os.environ["MOCK_MODE"] = "true"

    print_banner()
    uvicorn.run(
        "src.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
