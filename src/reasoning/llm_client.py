"""
Workstream W3: Context & Reasoning (Week 2 - Days 12–13)
LLM Client Adapter & Deterministic Mock Provider

Author: Amruta A J (Team SDE 3)
Module: src.reasoning.llm_client
Description:
    Provides an extensible, resilient LLM client adapter with:
    1. Adapter Interface: BaseLLMClient defining the generation contract.
    2. Deterministic Mock Provider: MockLLMClient operating 100% offline without API keys.
    3. Timeout Handling: Configurable per-request timeout ceiling with clear error reporting.
    4. Retry Handling: Exponential backoff retrying ONLY transient network/server failures.
    5. Structured Output Validation: Strict enforcement of the ReasoningResult schema.
    6. Security & Safety Invariants:
       - Mock mode is the default; real providers are disabled by default.
       - Zero automatic screen capture.
       - Trusted system instructions strictly isolated from untrusted contextual data.
       - API keys and private context are never exposed in logs, repr, or error messages.
"""

from abc import ABC, abstractmethod
import concurrent.futures
import json
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from src.context.schemas import (
    ReasoningRequest,
    ReasoningResult,
    RiskCategory,
    SourceReference,
)
from src.prompts.versioned_prompts import (
    DEFAULT_REGISTRY,
    PromptRegistry,
    build_versioned_prompt,
)
from src.reasoning.mock_engine import MockReasoningEngine


# =============================================================================
# Custom Exception Hierarchy
# =============================================================================

class LLMClientError(Exception):
    """Base exception for all LLM client adapter failures."""
    pass


class LLMTimeoutError(LLMClientError):
    """Raised when a request exceeds the configured request timeout ceiling."""
    pass


class LLMTransientError(LLMClientError):
    """
    Raised on transient network or provider-side failures (e.g. rate limits, 5xx errors).
    Eligible for retry according to the retry policy.
    """
    pass


class LLMValidationError(LLMClientError):
    """
    Raised when provider output fails structured schema validation.
    Non-transient; must NOT be retried.
    """
    pass


class LLMAuthenticationError(LLMClientError):
    """
    Raised when authentication credentials or API keys are invalid.
    Non-transient; must NOT be retried.
    """
    pass


class LLMConfigurationError(LLMClientError):
    """
    Raised on invalid client configuration (e.g. attempting to enable real providers offline).
    Non-transient; must NOT be retried.
    """
    pass


# =============================================================================
# Configuration Model
# =============================================================================

class LLMClientConfig(BaseModel):
    """
    Configuration options for the LLM Client Adapter.
    Enforces strict typing, sensible defaults, and credential protection.
    """
    model_config = ConfigDict(extra="forbid")

    max_response_text_length: int = Field(
        10_000,
        gt=0,
        description="Maximum allowed length for response_text in provider output. Outputs exceeding this raise LLMValidationError."
    )
    provider: str = Field(
        "mock",
        description="Target provider backend. Defaults to 'mock' for local, offline execution."
    )
    model_name: str = Field(
        "mock-reasoning-v1",
        min_length=1,
        description="Model identifier passed to provider."
    )
    timeout_seconds: float = Field(
        30.0,
        gt=0.0,
        description="Per-request execution timeout ceiling in seconds."
    )
    max_retries: int = Field(
        3,
        ge=0,
        le=10,
        description="Maximum retry attempts on transient failures."
    )
    retry_delay_seconds: float = Field(
        0.05,
        ge=0.0,
        description="Initial delay in seconds before first retry."
    )
    backoff_multiplier: float = Field(
        2.0,
        ge=1.0,
        description="Exponential backoff multiplier applied on successive retries."
    )
    retry_on_timeout: bool = Field(
        True,
        description="Whether request timeouts are treated as retryable transient errors."
    )
    api_key: Optional[str] = Field(
        None,
        description="Optional API key. Redacted in representations; never logged or exposed."
    )

    def __repr__(self) -> str:
        masked_key = "'[REDACTED]'" if self.api_key else "None"
        return (
            f"LLMClientConfig(provider='{self.provider}', model_name='{self.model_name}', "
            f"timeout_seconds={self.timeout_seconds}, max_retries={self.max_retries}, "
            f"retry_delay_seconds={self.retry_delay_seconds}, backoff_multiplier={self.backoff_multiplier}, "
            f"retry_on_timeout={self.retry_on_timeout}, api_key={masked_key})"
        )

    def __str__(self) -> str:
        return self.__repr__()


# =============================================================================
# Adapter Interface
# =============================================================================

class BaseLLMClient(ABC):
    """
    Abstract Base Class defining the contract for LLM client adapters.
    Compatible with existing MockReasoningEngine architecture.
    """

    @abstractmethod
    def generate(self, request: ReasoningRequest) -> ReasoningResult:
        """
        Generate a validated ReasoningResult from a ReasoningRequest.

        Args:
            request: Validated ReasoningRequest instance.

        Returns:
            Validated ReasoningResult conforming to schemas and PRD Section 18 policies.
        """
        pass

    def reason(self, request: ReasoningRequest) -> ReasoningResult:
        """
        Alias for generate() to maintain drop-in compatibility with MockReasoningEngine.
        """
        return self.generate(request)

    def call_raw(self, request: ReasoningRequest) -> Any:
        """
        Execute raw provider invocation returning unvalidated result/payload.
        Default implementation delegates to generate(request).
        """
        return self.generate(request)


# =============================================================================
# Mock Provider Implementation
# =============================================================================

class MockLLMClient(BaseLLMClient):
    """
    Deterministic mock LLM provider implementation for local, offline reasoning.
    Wraps and preserves 100% compatibility with MockReasoningEngine.
    Note: Output latency_ms is simulated and deterministic (derived from query hashing
    in MockReasoningEngine), guaranteeing repeatable execution offline without real timers.

    Provides controllable simulation hooks for testing resilience:
    - simulated_latency_sec: Delays response execution.
    - simulated_timeout: Triggers an immediate timeout error.
    - transient_failures_remaining: Raises LLMTransientError for N calls before succeeding.
    - simulated_malformed_output: Returns invalid structured payload to verify validation.
    - simulated_auth_failure: Raises LLMAuthenticationError.
    """

    def __init__(
        self,
        prompt_registry: Optional[PromptRegistry] = None,
        mock_engine: Optional[MockReasoningEngine] = None,
        sleeper: Optional[Callable[[float], None]] = None,
    ):
        self.registry = prompt_registry or DEFAULT_REGISTRY
        self.engine = mock_engine or MockReasoningEngine(prompt_registry=self.registry)
        self._sleeper: Callable[[float], None] = sleeper or time.sleep

        # Simulation hooks for deterministic testing
        self.simulated_latency_sec: float = 0.0
        self.simulated_timeout: bool = False
        self.transient_failures_remaining: int = 0
        self.simulated_malformed_output: Optional[Any] = None
        self.simulated_auth_failure: bool = False

    def reset_simulation(self) -> None:
        """Reset all simulation hooks to default neutral state."""
        self.simulated_latency_sec = 0.0
        self.simulated_timeout = False
        self.transient_failures_remaining = 0
        self.simulated_malformed_output = None
        self.simulated_auth_failure = False

    def call_raw(self, request: ReasoningRequest) -> Any:
        """
        Produce raw output honoring simulation hooks.
        """
        if self.simulated_auth_failure:
            raise LLMAuthenticationError("Authentication failed: invalid or unauthorized API credentials.")

        if self.transient_failures_remaining > 0:
            self.transient_failures_remaining -= 1
            raise LLMTransientError("Simulated transient service failure (e.g. HTTP 503 or 429).")

        if self.simulated_timeout:
            raise LLMTimeoutError("Simulated request execution timeout.")

        if self.simulated_latency_sec > 0:
            self._sleeper(self.simulated_latency_sec)

        if self.simulated_malformed_output is not None:
            return self.simulated_malformed_output

        # Delegate to deterministic MockReasoningEngine
        return self.engine.reason(request)

    def generate(self, request: ReasoningRequest) -> ReasoningResult:
        """
        Execute deterministic mock reasoning and return a validated ReasoningResult.
        """
        raw = self.call_raw(request)
        if isinstance(raw, ReasoningResult):
            return raw
        # If simulation returned raw dict/str, let MockReasoningEngine reason normally
        return self.engine.reason(request)


# =============================================================================
# Primary LLM Client Adapter
# =============================================================================


def _sanitize_pydantic_error(exc: Exception) -> str:
    """
    Extract only field names and error types from a Pydantic validation error,
    never echoing raw input values into the returned message.
    """
    try:
        if hasattr(exc, "errors") and callable(exc.errors):
            raw_errors = exc.errors()
            parts = []
            for err in raw_errors:
                loc = " -> ".join(str(l) for l in err.get("loc", ())) or "root"
                err_type = err.get("type", "unknown")
                parts.append(f"field '{loc}' [{err_type}]")
            return "; ".join(parts) if parts else "schema constraint violation"
    except Exception:
        pass
    return f"{type(exc).__name__}: schema constraint violation"


def _format_safe_error_summary(exc: Exception) -> str:
    """
    Format a safe, non-echoing, bounded error summary for reason_safe.

    Guarantees:
    - Never echoes raw input values (extracts error count and field names only).
    - Hard-bounds string length to <= 10,000 characters, appending '[truncated]' if needed.
    - Always non-empty.
    """
    max_len = 9980
    try:
        if hasattr(exc, "errors") and callable(exc.errors):
            raw_errors = exc.errors()
            err_count = len(raw_errors)
            field_names = []
            seen = set()
            for err in raw_errors:
                loc = err.get("loc", ())
                fld = str(loc[0]) if loc else "root"
                if fld not in seen:
                    seen.add(fld)
                    field_names.append(fld)
            fields_str = ", ".join(sorted(field_names)) if field_names else "general"
            summary = f"Validation failed ({err_count} error{'s' if err_count != 1 else ''} in fields: {fields_str})"
            return summary[:max_len]
    except Exception:
        pass

    msg = f"Reasoning failure: {type(exc).__name__}: {str(exc)}"
    if len(msg) > max_len:
        msg = msg[:max_len] + "... [truncated]"
    return msg or "Reasoning failure: unknown error."


class LLMClientAdapter(BaseLLMClient):
    """
    Main LLM Client Adapter providing:
    - Compatibility with existing reasoning architecture.
    - Configurable request timeout with thread-level ceiling enforcement.
    - Exponential backoff retry loop targeting only transient failures.
    - Strict structured output validation against the ReasoningResult schema.
    - Security invariants: offline by default, credential masking, context isolation.
    """

    def __init__(
        self,
        config: Optional[LLMClientConfig] = None,
        provider: Optional[BaseLLMClient] = None,
        prompt_registry: Optional[PromptRegistry] = None,
        sleeper: Optional[Callable[[float], None]] = None,
    ):
        self._config = config or LLMClientConfig()
        self._registry = prompt_registry or DEFAULT_REGISTRY
        self._sleeper = sleeper or time.sleep

        # Safety: Enforce offline mock mode by default; reject unconfigured real providers
        if self._config.provider != "mock":
            raise LLMConfigurationError(
                f"Provider '{self._config.provider}' is not enabled. "
                "Only deterministic mock provider ('mock') is supported in this offline environment."
            )

        self._provider = provider or MockLLMClient(prompt_registry=self._registry)

    @property
    def config(self) -> LLMClientConfig:
        """Active client configuration."""
        return self._config

    @property
    def provider(self) -> BaseLLMClient:
        """Active underlying LLM provider."""
        return self._provider

    @property
    def registry(self) -> PromptRegistry:
        """Active prompt registry."""
        return self._registry

    def build_prompt(self, request: ReasoningRequest) -> str:
        """
        Assemble the secure versioned prompt separating trusted instructions
        from untrusted context boundaries.
        """
        return build_versioned_prompt(
            version=request.prompt_version,
            user_query=request.user_query,
            context_items=request.context_items,
            registry=self._registry,
        )

    def validate_output(self, raw_output: Any, request: ReasoningRequest) -> ReasoningResult:
        """
        Validate provider output against the ReasoningResult schema.

        Accepts:
        - ReasoningResult instance (verified for schema integrity and matching request_id).
        - dict (parsed and validated via ReasoningResult(**raw_output)).
        - JSON string (deserialized and validated via ReasoningResult).

        Rejects:
        - Empty or None responses.
        - Non-dict / non-JSON / unsupported types.
        - Dicts missing required fields (request_id, status, response_text, prompt_version, etc.).
        - Objects with mismatched correlation request_id.
        - Whitespace-only or over-length response_text.
        - Sources whose source_id is not present in request's context_items (grounding check).
        - Payloads violating PRD Section 18 safety policies.

        Raises:
            LLMValidationError: If validation fails for any reason.
        """
        if raw_output is None:
            raise LLMValidationError("Provider returned empty/None response.")

        parsed_obj = raw_output
        if isinstance(parsed_obj, str):
            clean_str = parsed_obj.strip()
            # Strip markdown json code block fences if present
            if clean_str.startswith("```json") and clean_str.endswith("```"):
                clean_str = clean_str[7:-3].strip()
            elif clean_str.startswith("```") and clean_str.endswith("```"):
                clean_str = clean_str[3:-3].strip()
            try:
                parsed_obj = json.loads(clean_str)
            except Exception as e:
                raise LLMValidationError(f"Provider output is not valid JSON: {str(e)}") from e

        if isinstance(parsed_obj, dict):
            try:
                result = ReasoningResult(**parsed_obj)
            except Exception as e:
                # Sanitize: extract only field names and error types, never raw input values
                safe_msg = _sanitize_pydantic_error(e)
                raise LLMValidationError(f"Output failed ReasoningResult schema validation: {safe_msg}") from e
        elif isinstance(parsed_obj, ReasoningResult):
            result = parsed_obj
        else:
            raise LLMValidationError(
                f"Unsupported output type: expected ReasoningResult, dict, or JSON string, got {type(parsed_obj).__name__}."
            )

        # Enforce correlation ID matching
        if result.request_id != request.request_id:
            raise LLMValidationError(
                f"Correlation mismatch: expected request_id '{request.request_id}', got '{result.request_id}'."
            )

        # Enforce whitespace-only response_text rejection
        if not result.response_text.strip():
            raise LLMValidationError(
                "Provider response_text is empty or whitespace-only."
            )

        # Enforce max response_text length
        max_len = self._config.max_response_text_length
        if len(result.response_text) > max_len:
            raise LLMValidationError(
                f"Provider response_text length ({len(result.response_text)}) exceeds maximum allowed ({max_len})."
            )

        # Grounding check: each cited source_id must correspond to a context_item in the request
        if result.sources:
            valid_ids = {item.item_id for item in request.context_items}
            ungrounded = [
                s.source_id for s in result.sources
                if s.source_id not in valid_ids
            ]
            if ungrounded:
                raise LLMValidationError(
                    f"Provider cited source_id(s) not present in request context_items: {ungrounded}. "
                    "All cited sources must be grounded in provided context."
                )

        return result

    def _execute_with_timeout(
        self,
        func: Callable[[ReasoningRequest], Any],
        request: ReasoningRequest,
        timeout_seconds: float,
    ) -> Any:
        """
        Execute a provider function within the specified timeout ceiling.

        Runs the provider call on a daemon worker thread so that a timed-out
        call is abandoned (not cancelled) and never blocks interpreter exit.
        Bounded retries (max_retries <= 10) limit the number of abandoned calls.
        """
        # Check simulation hooks if available on provider
        if getattr(self._provider, "simulated_timeout", False):
            raise LLMTimeoutError(f"Request timed out after {timeout_seconds:.2f}s (simulated).")

        sim_latency = getattr(self._provider, "simulated_latency_sec", 0.0)
        if sim_latency > 0 and sim_latency > timeout_seconds:
            raise LLMTimeoutError(
                f"Request exceeded timeout ceiling of {timeout_seconds:.2f}s (simulated latency: {sim_latency:.2f}s)."
            )

        container: Dict[str, Any] = {}
        exception_container: List[BaseException] = []

        def worker() -> None:
            try:
                container["result"] = func(request)
            except BaseException as exc:
                exception_container.append(exc)

        worker_thread = threading.Thread(
            target=worker,
            name=f"llm-worker-{request.request_id}",
            daemon=True,
        )
        worker_thread.start()
        worker_thread.join(timeout=timeout_seconds)

        if worker_thread.is_alive():
            raise LLMTimeoutError(
                f"Request execution timed out after {timeout_seconds:.2f}s."
            )

        if exception_container:
            exc = exception_container[0]
            if isinstance(exc, (TimeoutError, socket.timeout)):
                raise LLMTimeoutError(f"Socket/connection timed out: {exc}") from exc
            raise exc

        return container.get("result")

    def generate(self, request: ReasoningRequest) -> ReasoningResult:
        """
        Generate a validated ReasoningResult from a ReasoningRequest.

        Pipeline:
        1. Input Validation: Verifies request instance and prompt_version registration.
        2. Execution with Timeout & Transient Retry:
           - Executes provider invocation wrapped in configured timeout ceiling.
           - Retries transient errors (LLMTransientError, timeouts if configured)
             up to max_retries with exponential backoff.
           - Fast-fails non-transient errors (LLMValidationError, LLMAuthenticationError, etc.).
        3. Structured Output Validation:
           - Validates raw provider response against ReasoningResult schema.
           - Enforces correlation (matching request_id) and PRD Section 18 safety policies.
           - Rejects malformed or untyped outputs.
        """
        if not isinstance(request, ReasoningRequest):
            raise TypeError(f"Expected ReasoningRequest instance, got {type(request).__name__}")

        # Validate that prompt template exists in registry
        self._registry.get(request.prompt_version)

        attempt = 0
        delay = self._config.retry_delay_seconds

        target_func = (
            self._provider.call_raw
            if hasattr(self._provider, "call_raw")
            else self._provider.generate
        )

        while True:
            attempt += 1
            try:
                raw_output = self._execute_with_timeout(
                    target_func,
                    request,
                    self._config.timeout_seconds,
                )
                return self.validate_output(raw_output, request)

            except (LLMTransientError, LLMTimeoutError) as exc:
                is_timeout = isinstance(exc, LLMTimeoutError)

                # Check if timeout is configured as retryable
                if is_timeout and not self._config.retry_on_timeout:
                    raise exc

                if attempt > self._config.max_retries:
                    if is_timeout:
                        raise LLMTimeoutError(
                            f"Request timed out after {attempt} attempt(s) "
                            f"(timeout ceiling: {self._config.timeout_seconds:.2f}s): {exc}"
                        ) from exc
                    raise LLMTransientError(
                        f"Request failed after {attempt} attempt(s) "
                        f"(max retries: {self._config.max_retries}): {exc}"
                    ) from exc

                # Sleep before retrying
                if delay > 0:
                    self._sleeper(delay)
                    delay *= self._config.backoff_multiplier

            except (
                LLMValidationError,
                LLMAuthenticationError,
                LLMConfigurationError,
                TypeError,
                ValueError,
                KeyError,
            ):
                # Non-transient errors: fast-fail without retrying
                raise
            except Exception as exc:
                # Unexpected errors wrapped cleanly
                raise LLMClientError(f"Unexpected provider error: {exc}") from exc

    def reason_safe(self, request_or_dict: Any) -> ReasoningResult:
        """
        Safe execution entrypoint that never raises unhandled exceptions.
        Maintains drop-in compatibility with MockReasoningEngine.reason_safe().
        Returns a structured ReasoningResult with status='error' on failure.
        """
        req_id = "req-unknown"
        p_version = "unknown"
        try:
            if isinstance(request_or_dict, dict):
                req_id = request_or_dict.get("request_id", "req-dict")
                p_version = request_or_dict.get("prompt_version", "unknown")
                req = ReasoningRequest(**request_or_dict)
            elif isinstance(request_or_dict, ReasoningRequest):
                req_id = request_or_dict.request_id
                p_version = request_or_dict.prompt_version
                req = request_or_dict
            else:
                return ReasoningResult(
                    request_id=req_id,
                    status="error",
                    response_text=(
                        f"Invalid request input type: expected ReasoningRequest or dict, "
                        f"got {type(request_or_dict).__name__}."
                    ),
                    sources=[],
                    action_required=False,
                    risk_level=RiskCategory.CATEGORY_A,
                    requires_approval=False,
                    confidence=0.0,
                    latency_ms=0.0,
                    prompt_version="unknown",
                )

            return self.generate(req)
        except Exception as e:
            safe_text = _format_safe_error_summary(e)
            try:
                return ReasoningResult(
                    request_id=req_id,
                    status="error",
                    response_text=safe_text,
                    sources=[],
                    action_required=False,
                    risk_level=RiskCategory.CATEGORY_A,
                    requires_approval=False,
                    confidence=0.0,
                    latency_ms=0.0,
                    prompt_version="unknown",
                )
            except Exception:
                return ReasoningResult(
                    request_id="req-unknown",
                    status="error",
                    response_text="Reasoning failure: unhandled exception.",
                    sources=[],
                    action_required=False,
                    risk_level=RiskCategory.CATEGORY_A,
                    requires_approval=False,
                    confidence=0.0,
                    latency_ms=0.0,
                    prompt_version="unknown",
                )

