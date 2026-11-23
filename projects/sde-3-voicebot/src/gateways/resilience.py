"""Resilience utilities for backend gateways: exponential backoff retries and circuit breaker."""
from __future__ import annotations

from enum import Enum
import logging
import threading
import time
from typing import Any, Callable, Optional, Tuple, Type, TypeVar

from src.core.errors import (
    AppError,
    AudioModuleUnavailableError,
    CircuitBreakerOpenError,
    GatewayTimeoutError,
    ReasoningModuleUnavailableError,
    TranscriptionModuleUnavailableError,
    WorkflowModuleUnavailableError,
)

logger = logging.getLogger("backend.gateways.resilience")

T = TypeVar("T")

DEFAULT_RETRYABLE_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    GatewayTimeoutError,
    AudioModuleUnavailableError,
    TranscriptionModuleUnavailableError,
    ReasoningModuleUnavailableError,
    WorkflowModuleUnavailableError,
)


def is_transient_error(exc: Exception) -> bool:
    """Determines whether an exception represents a transient, retryable failure."""
    if isinstance(exc, DEFAULT_RETRYABLE_EXCEPTIONS):
        return True
    if isinstance(exc, AppError):
        # Only retry if explicitly marked retryable AND is a server-side/network error (>= 500)
        return bool(exc.retryable and exc.status_code >= 500)
    return False


def retry_with_backoff(
    fn: Callable[[], T],
    max_attempts: int = 3,
    base_delay: float = 0.05,
    max_delay: float = 1.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = DEFAULT_RETRYABLE_EXCEPTIONS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> T:
    """Executes a callable with exponential backoff retries for transient errors.
    
    Guarantees:
    - Retries only transient exceptions (timeouts, unavailable services).
    - Never retries validation errors or permanent client errors (status < 500).
    - Preserves the original final exception when all retry attempts are exhausted.
    - Uses injectable sleep_fn for zero-delay deterministic testing.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except Exception as exc:
            # Check if this exception is retryable
            can_retry = is_transient_error(exc) or isinstance(exc, retryable_exceptions)
            if not can_retry or attempt >= max_attempts:
                # Re-raise the original exception without masking
                raise exc

            # Calculate exponential backoff delay: base_delay * 2^(attempt - 1)
            backoff_delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            logger.warning(
                f"Transient error on attempt {attempt}/{max_attempts}: {exc}. "
                f"Retrying in {backoff_delay:.3f}s..."
            )
            sleep_fn(backoff_delay)


class CircuitState(str, Enum):
    """Permitted circuit breaker states."""
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF-OPEN"


class CircuitBreaker:
    """Thread-safe circuit breaker protecting downstream module integrations.
    
    Guarantees:
    - CLOSED: Normal pass-through operation.
    - OPEN: Opens after consecutive transient failures meet threshold; fast-fails incoming requests.
    - HALF-OPEN: After recovery timeout, permits exactly one trial probe request.
    - Prevents concurrent trial executions in HALF-OPEN.
    - Validation errors (client errors) never trigger circuit breaker failures.
    - Injectable clock function enables fast, deterministic testing without real sleep.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_sec: float = 30.0,
        clock_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        self.clock_fn = clock_fn

        self._state = CircuitState.CLOSED
        self._consecutive_failures: int = 0
        self._opened_at: Optional[float] = None
        self._half_open_in_flight: bool = False
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        """Returns the current evaluated state of the circuit breaker."""
        with self._lock:
            self._evaluate_state_locked()
            return self._state.value

    @property
    def consecutive_failures(self) -> int:
        """Returns the current count of consecutive failures."""
        with self._lock:
            return self._consecutive_failures

    @property
    def failure_count(self) -> int:
        """Alias for consecutive_failures."""
        return self.consecutive_failures

    def _evaluate_state_locked(self) -> None:
        """Transitions from OPEN to HALF_OPEN if the recovery timeout has elapsed."""
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            now = self.clock_fn()
            if (now - self._opened_at) >= self.recovery_timeout_sec:
                self._state = CircuitState.HALF_OPEN
                self._half_open_in_flight = False
                logger.info("Circuit breaker transitioned from OPEN to HALF-OPEN.")

    def execute(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Executes the given callable under the protection of the circuit breaker."""
        with self._lock:
            self._evaluate_state_locked()

            if self._state == CircuitState.OPEN:
                raise CircuitBreakerOpenError(
                    message=f"Circuit breaker is OPEN. Service unavailable (threshold: {self.failure_threshold} failures).",
                    details={
                        "state": self._state.value,
                        "consecutive_failures": self._consecutive_failures,
                        "recovery_timeout_sec": self.recovery_timeout_sec,
                    },
                )

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_in_flight:
                    raise CircuitBreakerOpenError(
                        message="Circuit breaker is HALF-OPEN: trial request already in flight.",
                        details={"state": self._state.value},
                    )
                self._half_open_in_flight = True

        # Execute call outside lock to allow concurrency in CLOSED state
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            # Only count transient/system failures towards circuit breaker
            if is_transient_error(exc) or (isinstance(exc, AppError) and exc.status_code >= 500):
                self._record_failure()
            elif not isinstance(exc, AppError):
                # Unknown/unhandled exceptions are treated as system failures
                self._record_failure()
            else:
                # Validation error (status < 500); if in HALF-OPEN, clear probe in-flight
                with self._lock:
                    if self._state == CircuitState.HALF_OPEN:
                        self._half_open_in_flight = False
            raise exc

        # Success path
        self._record_success()
        return result

    def _record_failure(self) -> None:
        """Records a transient failure and transitions state if necessary."""
        with self._lock:
            self._consecutive_failures += 1
            if self._state == CircuitState.HALF_OPEN:
                # Trial probe failed; trip back to OPEN immediately
                self._state = CircuitState.OPEN
                self._opened_at = self.clock_fn()
                self._half_open_in_flight = False
                logger.warning(
                    "Trial call in HALF-OPEN failed. Circuit breaker returned to OPEN."
                )
            elif self._state == CircuitState.CLOSED:
                if self._consecutive_failures >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._opened_at = self.clock_fn()
                    logger.warning(
                        f"Circuit breaker tripped to OPEN after {self._consecutive_failures} consecutive failures."
                    )

    def _record_success(self) -> None:
        """Records a successful call and resets failure count / closes circuit."""
        with self._lock:
            if self._state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
                logger.info("Circuit breaker trial call succeeded. Transitioned to CLOSED.")
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._opened_at = None
            self._half_open_in_flight = False

    def reset(self) -> None:
        """Manually resets the circuit breaker to CLOSED."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._opened_at = None
            self._half_open_in_flight = False

