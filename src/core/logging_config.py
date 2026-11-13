"""Structured logging configuration for backend services."""
import logging
import sys
from typing import Optional, Union

from src.config import settings

BACKEND_LOGGER_NAME = "backend"


class DynamicStdoutHandler(logging.StreamHandler):
    """StreamHandler that dynamically routes to current sys.stdout for test capture compatibility."""

    @property
    def stream(self):
        return sys.stdout

    @stream.setter
    def stream(self, value):
        pass


def configure_logging(level: Optional[Union[str, int]] = None) -> logging.Logger:
    """Configures structured logging on the 'backend' logger hierarchy.

    Attaches exactly one StreamHandler to write raw log messages to sys.stdout,
    sets propagate=False, and is idempotent (repeated calls do not add duplicate handlers).
    """
    logger = logging.getLogger(BACKEND_LOGGER_NAME)

    # Resolve log level
    lvl = level if level is not None else settings.log_level
    if isinstance(lvl, str):
        numeric_level = getattr(logging, lvl.upper(), logging.INFO)
    else:
        numeric_level = lvl

    logger.setLevel(numeric_level)
    logger.propagate = False

    # Check if a StreamHandler is already present
    existing_handler = None
    for h in logger.handlers:
        if isinstance(h, logging.StreamHandler):
            existing_handler = h
            break

    if existing_handler is not None:
        existing_handler.setLevel(numeric_level)
        logger.handlers = [existing_handler]
    else:
        handler = DynamicStdoutHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.setLevel(numeric_level)
        logger.handlers = [handler]

    return logger

