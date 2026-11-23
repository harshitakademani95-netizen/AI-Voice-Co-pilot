"""Reasoning Gateway connecting backend services to the Reasoning Module (Workstream W3).

Guarantees:
- Dispatches reasoning requests to the underlying ReasoningEngine with bounded thread pool timeouts.
- Circuit breaker protection preventing cascading failures during upstream/engine slowdowns.
- Automatic exponential retry for transient errors.
- Telemetry tracking (call counts, errors, latencies, circuit states).
- Clean lifecycle shutdown without orphaned thread exhaustion.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from src.context.schemas import ContextItem, ReasoningRequest, ReasoningResult
from src.core.errors import (
    GatewayTimeoutError,
    ReasoningGatewayError,
    ReasoningModuleUnavailableError,
)
from src.gateways.resilience import CircuitBreaker, CircuitBreakerOpenError, retry_with_backoff
from src.reasoning.mock_engine import MockReasoningEngine

logger = logging.getLogger("backend.gateways.reasoning")


class ReasoningGateway:
    """Backend gateway managing communication with the Context & Reasoning module."""

    def __init__(
        self,
        engine: Optional[MockReasoningEngine] = None,
        timeout_seconds: float = 10.0,
        max_workers: int = 4,
        circuit_breaker: Optional[CircuitBreaker] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.engine = engine or MockReasoningEngine()
        self.timeout_seconds = timeout_seconds
        self.sleep_fn = sleep_fn
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=5,
            recovery_timeout_sec=30.0,
        )

        self._is_available: bool = True
        self._last_error: Optional[str] = None
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="reason-gw-")

        # Telemetry
        self._lock = threading.Lock()
        self._total_calls: int = 0
        self._error_count: int = 0
        self._total_latency_ms: float = 0.0
        self._last_success_at: Optional[str] = None

    @property
    def is_available(self) -> bool:
        return self._is_available and (self.circuit_breaker.state != "OPEN")

    def set_available(self, available: bool) -> None:
        self._is_available = available

    def _record_telemetry(self, success: bool, latency_ms: float) -> None:
        with self._lock:
            self._total_calls += 1
            self._total_latency_ms += latency_ms
            if success:
                self._last_success_at = datetime.now(timezone.utc).isoformat()
            else:
                self._error_count += 1

    def reason(
        self,
        request: ReasoningRequest,
        timeout: Optional[float] = None,
        correlation_id: Optional[str] = None,
    ) -> ReasoningResult:
        """Processes a reasoning request through the Reasoning Engine with enforced timeout and resilience."""
        start_time = time.monotonic()
        effective_timeout = timeout if timeout is not None else self.timeout_seconds

        if not self._is_available:
            self._last_error = "Reasoning module is currently marked unavailable"
            self._record_telemetry(success=False, latency_ms=0.0)
            raise ReasoningModuleUnavailableError(
                message="Reasoning module is currently unavailable.",
                details={"correlation_id": correlation_id},
            )

        if not request.user_query or not request.user_query.strip():
            self._record_telemetry(success=False, latency_ms=0.0)
            raise ReasoningGatewayError(
                message="user_query cannot be empty in ReasoningRequest.",
                details={"field": "user_query", "correlation_id": correlation_id},
            )

        def _call_engine() -> ReasoningResult:
            fut = self._executor.submit(self.engine.reason, request)
            try:
                return fut.result(timeout=effective_timeout)
            except FutureTimeoutError:
                fut.cancel()
                el = time.monotonic() - start_time
                raise GatewayTimeoutError(
                    message=f"Reasoning exceeded deadline of {effective_timeout:.2f}s (elapsed: {el:.2f}s).",
                    details={"elapsed_seconds": el, "timeout_seconds": effective_timeout, "correlation_id": correlation_id},
                )
            except Exception as exc:
                if isinstance(exc, (GatewayTimeoutError, ReasoningGatewayError, ReasoningModuleUnavailableError)):
                    raise exc
                raise ReasoningGatewayError(
                    message=f"Reasoning engine failed: {str(exc)}",
                    details={"error": str(exc), "correlation_id": correlation_id},
                    status_code=500,
                ) from exc

        def _execute_with_retry() -> ReasoningResult:
            return retry_with_backoff(
                _call_engine,
                max_attempts=3,
                base_delay=0.05,
                sleep_fn=self.sleep_fn,
            )

        try:
            result = self.circuit_breaker.execute(_execute_with_retry)
        except CircuitBreakerOpenError as exc:
            total_elapsed = time.monotonic() - start_time
            self._last_error = str(exc)
            self._record_telemetry(success=False, latency_ms=total_elapsed * 1000.0)
            raise ReasoningModuleUnavailableError(
                message="Reasoning module is unavailable (circuit breaker OPEN).",
                details={"circuit_state": self.circuit_breaker.state, "correlation_id": correlation_id},
            ) from exc
        except Exception as exc:
            total_elapsed = time.monotonic() - start_time
            self._last_error = str(exc)
            self._record_telemetry(success=False, latency_ms=total_elapsed * 1000.0)
            raise

        total_elapsed = time.monotonic() - start_time
        if total_elapsed >= effective_timeout:
            self._record_telemetry(success=False, latency_ms=total_elapsed * 1000.0)
            raise GatewayTimeoutError(
                message=f"Reasoning exceeded deadline of {effective_timeout:.2f}s (elapsed: {total_elapsed:.2f}s).",
                details={"elapsed_seconds": total_elapsed, "timeout_seconds": effective_timeout, "correlation_id": correlation_id},
            )

        self._record_telemetry(success=True, latency_ms=total_elapsed * 1000.0)
        self._last_error = None
        return result

    def health_check(self) -> bool:
        if not self._is_available:
            return False
        try:
            req = ReasoningRequest(
                request_id="health-check-req",
                session_id="health-session",
                user_query="ping health",
                context_items=[],
                prompt_version="v1.0.0",
            )
            res = self.engine.reason(req)
            return res is not None
        except Exception:
            return False

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            avg_lat = (self._total_latency_ms / self._total_calls) if self._total_calls > 0 else 0.0
            return {
                "gateway": "ReasoningGateway",
                "is_available": self.is_available,
                "circuit_state": self.circuit_breaker.state,
                "total_calls": self._total_calls,
                "error_count": self._error_count,
                "avg_latency_ms": round(avg_lat, 2),
                "last_success_at": self._last_success_at,
                "last_error": self._last_error,
            }

    def close(self) -> None:
        self._is_available = False
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


_reasoning_gateway_instance: Optional[ReasoningGateway] = None


def get_reasoning_gateway() -> ReasoningGateway:
    global _reasoning_gateway_instance
    if _reasoning_gateway_instance is None:
        _reasoning_gateway_instance = ReasoningGateway()
    return _reasoning_gateway_instance
