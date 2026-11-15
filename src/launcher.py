"""CLI Launcher for running the backend in mock mode."""
import os
import sys
import uvicorn


def print_banner(cfg):
    banner = f"""
================================================================================
           AI Voice Co-Pilot Backend - Week 2 Session Service (W5)
================================================================================
 Mode:        {'MOCK MODE (Active - No paid credentials needed)' if cfg.mock_mode else 'LIVE MODE'}
 Service:     {cfg.app_name}
 Version:     {cfg.version}
 Environment: {cfg.environment}
 Host:        http://{cfg.host}:{cfg.port}
 API Docs:    http://{cfg.host}:{cfg.port}/docs
 Health:      http://{cfg.host}:{cfg.port}/api/v1/health
 Readiness:   http://{cfg.host}:{cfg.port}/api/v1/ready
 Sessions:    http://{cfg.host}:{cfg.port}/api/v1/sessions
================================================================================
"""
    print(banner)


def main():
    """Starts the Uvicorn ASGI server with mock mode enabled by default."""
    # Ensure mock mode is explicitly set to true if not specified
    if "MOCK_MODE" not in os.environ:
        os.environ["MOCK_MODE"] = "true"

    try:
        from src.config import settings, validate_configuration
        validate_configuration(settings)
    except ValueError as err:
        print(f"CONFIG ERROR: {err}")
        sys.exit(1)

    print_banner(settings)
    uvicorn.run(
        "src.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
