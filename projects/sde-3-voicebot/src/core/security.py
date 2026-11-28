"""Security, Local Authorization Boundary, and Rate Limiting utilities."""
from datetime import datetime, timezone
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import Request

from src.config import settings
from src.core.errors import RateLimitExceededError, UnauthorizedError

logger = logging.getLogger("backend.security")

# Sensitive key names to redact
SENSITIVE_KEY_PATTERNS = re.compile(
    r"(token|secret|password|key|auth|credential|jwt|bearer|private|cookie)",
    re.IGNORECASE,
)

# Sensitive string patterns (like Bearer tokens, long hex keys)
SENSITIVE_STRING_PATTERNS = [
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}", re.IGNORECASE), "sk-[REDACTED]"),
    (re.compile(r"(key|secret|password)\s*[:=]\s*['\"]?[^\s'\"]+['\"]?", re.IGNORECASE), r"\1=[REDACTED]"),
]


def redact_sensitive_data(data: Any) -> Any:
    """Recursively redacts sensitive keys and values from dictionaries, lists, or strings."""
    if data is None:
        return None

    if isinstance(data, dict):
        sanitized: Dict[str, Any] = {}
        for key, value in data.items():
            if SENSITIVE_KEY_PATTERNS.search(str(key)):
                sanitized[str(key)] = "[REDACTED]"
            else:
                sanitized[str(key)] = redact_sensitive_data(value)
        return sanitized

    if isinstance(data, list):
        return [redact_sensitive_data(item) for item in data]

    if isinstance(data, str):
        result = data
        for pattern, replacement in SENSITIVE_STRING_PATTERNS:
            result = pattern.sub(replacement, result)
        return result

    return data


# ============================================================================
# LOCAL AUTHORIZATION BOUNDARY
# ============================================================================

LOCAL_HOSTS = {"127.0.0.1", "localhost", "testclient", "::1"}
DEFAULT_LOCAL_KEY = "dev-local-key"


def validate_local_authorization(request: Request) -> bool:
    """Validates that a request falls within the local authorization boundary.

    Rules:
    - If explicit 'X-API-Key' is provided:
      - Valid if it matches BACKEND_API_KEY or default local dev key.
      - If invalid, raises UnauthorizedError (HTTP 401).
    - If explicit 'Authorization: Bearer <token>' is provided:
      - Valid if token matches BACKEND_API_KEY or default local dev key.
      - If invalid, raises UnauthorizedError (HTTP 401).
    - If no auth headers are passed:
      - In mock/development mode (or originating from localhost/testclient), permitted.
      - In strict production mode without mock mode, requires valid key.
    """
    api_key_header = request.headers.get("X-API-Key")
    auth_header = request.headers.get("Authorization")

    expected_key = getattr(settings, "backend_api_key", None) or os.getenv("BACKEND_API_KEY", DEFAULT_LOCAL_KEY)

    # 1. Check explicit X-API-Key
    if api_key_header is not None:
        clean_key = api_key_header.strip()
        if clean_key in (expected_key, DEFAULT_LOCAL_KEY):
            return True
        raise UnauthorizedError(
            message="Invalid API Key provided for local authorization boundary.",
            details={"header": "X-API-Key"},
        )

    # 2. Check explicit Authorization header
    if auth_header is not None:
        clean_auth = auth_header.strip()
        if clean_auth.lower().startswith("bearer "):
            token = clean_auth[7:].strip()
            if token in (expected_key, DEFAULT_LOCAL_KEY):
                return True
            raise UnauthorizedError(
                message="Invalid Bearer token provided for local authorization boundary.",
                details={"header": "Authorization"},
            )

    # 3. Check client host boundary
    client_host = request.client.host if request.client else "testclient"
    if client_host in LOCAL_HOSTS or getattr(settings, "mock_mode", True):
        return True

    # 4. Strict rejection outside local boundary
    raise UnauthorizedError(
        message="Request falls outside local authorization boundary and lacks valid credentials.",
        details={"client_host": client_host},
    )


# ============================================================================
# CONFIGURABLE RATE LIMITER (SLIDING WINDOW)
# ============================================================================

class RateLimiter:
    """Thread-safe in-memory sliding-window rate limiter."""

    def __init__(self, default_limit: int = 120, default_window_sec: int = 60) -> None:
        self.default_limit = default_limit
        self.default_window_sec = default_window_sec
        self._requests: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def is_allowed(
        self,
        key: str,
        limit: Optional[int] = None,
        window_sec: Optional[int] = None,
    ) -> Tuple[bool, int, int]:
        """Checks if a request is permitted under rate limit.

        Returns:
            Tuple[is_allowed: bool, remaining_requests: int, retry_after_sec: int]
        """
        max_reqs = limit if limit is not None else self.default_limit
        window = window_sec if window_sec is not None else self.default_window_sec
        now = time.time()

        with self._lock:
            timestamps = self._requests.setdefault(key, [])
            # Evict timestamps outside the sliding window
            cutoff = now - window
            self._requests[key] = [t for t in timestamps if t > cutoff]
            current_count = len(self._requests[key])

            if current_count >= max_reqs:
                oldest = self._requests[key][0]
                retry_after = max(1, int(oldest + window - now))
                return False, 0, retry_after

            self._requests[key].append(now)
            remaining = max_reqs - (current_count + 1)
            return True, remaining, 0

    def reset(self) -> None:
        """Clears all rate limit tracking records."""
        with self._lock:
            self._requests.clear()


rate_limiter = RateLimiter(default_limit=120, default_window_sec=60)
