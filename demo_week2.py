"""
Workstream W3: Context & Reasoning (Week 2 - Day 14)
End-to-End Pipeline Demonstration

Author: Amruta A J (Team SDE 3)
Module: demo_week2
Description:
    Demonstrates the complete end-to-end Week 2 Context & Reasoning architecture:
    1. Opt-In Screen Capture (OptInCaptureAdapter) with permission, rate, and dimension gating.
    2. OCR/Vision Frame Conversion (MockVisionAdapter) into typed ContextItems.
    3. Bounded Context Budgeting, Staleness Filtering, and Keyword Scoring (BoundedContextBuilder).
    4. Versioned Prompt Hardening & Untrusted Context Boundary Isolation.
    5. Structured Reasoning & Bounded Retry Handling with LLM Client Adapter (LLMClientAdapter).
    6. Safety Rejection of Malformed Provider Output (LLMValidationError).
    7. Resilient Safe Fallback Execution (reason_safe).

All demonstrations are 100% offline, deterministic, and use purely synthetic data.
"""

import sys
from datetime import timedelta

from src.context.schemas import (
    ContextItem,
    ContextType,
    DEFAULT_FRAME_TIMESTAMP,
    ReasoningRequest,
)
from src.context.capture_adapter import (
    CaptureConfig,
    CapturePermissionError,
    OptInCaptureAdapter,
    ResolutionLimitError,
    SamplingLimitError,
)
from src.context.vision_adapter import MockVisionAdapter
from src.context.bounded_builder import (
    BoundedContextBuilder,
    BoundedContextConfig,
)
from src.reasoning.llm_client import (
    LLMClientAdapter,
    LLMClientConfig,
    LLMTimeoutError,
    LLMValidationError,
    MockLLMClient,
)
from src.context.fixtures import get_synthetic_error_scenario


def print_header(title: str, step_num: int) -> None:
    print("\n" + "=" * 78)
    print(f"  STEP {step_num}: {title.upper()}")
    print("=" * 78)


def print_substep(text: str) -> None:
    print(f"\n[+] {text}")


def main() -> int:
    print("*" * 78)
    print("  WORKSTREAM W3: CONTEXT & REASONING - WEEK 2 PIPELINE DEMONSTRATION")
    print("  Student: Amruta A J | Team: SDE 3 | Mode: 100% Local & Offline")
    print("*" * 78)

    # =========================================================================
    # STEP 1: Opt-In Screen Capture Adapter
    # =========================================================================
    print_header("Opt-In Screen Capture Adapter (Day 8)", 1)
    simulated_clock = 1000.0
    capture_adapter = OptInCaptureAdapter(
        CaptureConfig(max_fps=5.0, max_width=1920, max_height=1080),
        clock_fn=lambda: simulated_clock,
    )

    print_substep("1.1 Verifying default permission gate (Disabled by Default)...")
    print(f"    adapter.is_opted_in: {capture_adapter.is_opted_in}")

    print_substep("1.2 Attempting capture prior to user consent...")
    try:
        capture_adapter.capture_frame(
            window_title="calculator.py - Visual Studio Code",
            active_app="VS Code",
            visible_text="def divide(a, b): return a / b\nZeroDivisionError",
        )
        print("    [FAIL] Capture should have been blocked!")
        return 1
    except CapturePermissionError as e:
        print(f"    [PASSED] Blocked as expected: '{e}'")

    print_substep("1.3 Explicit user opt-in and synthetic frame capture...")
    capture_adapter.opt_in()
    print(f"    adapter.is_opted_in: {capture_adapter.is_opted_in}")

    screen_frame = capture_adapter.capture_frame(
        window_title="calculator.py - Visual Studio Code",
        active_app="VS Code",
        visible_text="def divide(a, b): return a / b\nZeroDivisionError: division by zero on line 12",
        width=1920,
        height=1080,
    )
    print(f"    Captured Frame ID:    {screen_frame.frame_id}")
    print(f"    Active Window:        {screen_frame.active_window_title}")
    print(f"    Active Application:   {screen_frame.active_application}")
    print(f"    Safety Checks:        is_synthetic={screen_frame.is_synthetic}, capture_enabled={screen_frame.capture_enabled}")

    print_substep("1.4 Demonstrating sampling rate limit and dimension limit gating...")
    # Sampling limit: 2nd capture at t=1000.05s (< 0.2s minimum interval for max_fps=5.0)
    simulated_clock = 1000.05
    try:
        capture_adapter.capture_frame(
            window_title="calculator.py - Visual Studio Code",
            active_app="VS Code",
            visible_text="def divide(a, b): return a / b",
        )
        print("    [FAIL] Rapid second capture should have been blocked!")
        return 1
    except SamplingLimitError as e:
        print(f"    [PASSED] Sampling rate limit enforced: '{e}'")

    # Dimension limit: capture with width=3840 (exceeds max_width=1920) after rate limit window has elapsed
    simulated_clock = 1001.0
    try:
        capture_adapter.capture_frame(
            window_title="calculator.py - Visual Studio Code",
            active_app="VS Code",
            visible_text="def divide(a, b): return a / b",
            width=3840,
            height=2160,
        )
        print("    [FAIL] Oversized frame should have been rejected!")
        return 1
    except ResolutionLimitError as e:
        print(f"    [PASSED] Resolution limit enforced: '{e}'")

    # =========================================================================
    # STEP 2: Mock Vision Adapter
    # =========================================================================
    print_header("OCR / Vision Adapter Transformation (Day 9)", 2)
    # Note: OptInCaptureAdapter requires CaptureConfig for rate limits and dimension boundaries,
    # whereas MockVisionAdapter is stateless and accepts optional direct fallback kwargs.
    vision_adapter = MockVisionAdapter()

    print_substep("2.1 Extracting simulated OCR text from synthetic frame...")
    extracted_text = vision_adapter.extract_text(screen_frame)
    print(f"    Extracted Text:       '{extracted_text}'")

    print_substep("2.2 Transforming frame into typed ContextItem...")
    screen_context_item = vision_adapter.to_context_item(screen_frame)
    print(f"    Item ID:              {screen_context_item.item_id}")
    print(f"    Context Type:         {screen_context_item.context_type.value}")
    print(f"    Source Pointer:       {screen_context_item.source}")
    print(f"    Content Length:       {len(screen_context_item.content)} characters")

    # =========================================================================
    # STEP 3: Bounded Context Builder
    # =========================================================================
    print_header("Bounded Context Window & Relevance Prioritization (Day 10)", 3)

    # Aggregate candidate pool: screen item + synthetic error scenario items
    scenario_items = get_synthetic_error_scenario()
    candidate_pool = [screen_context_item] + scenario_items
    print(f"    Candidate Pool Size:  {len(candidate_pool)} items")

    config = BoundedContextConfig(
        max_items=4,
        token_budget=400,
        max_age_seconds=3600.0,
        chars_per_token=4.0,
    )
    builder = BoundedContextBuilder(
        config=config,
        clock_fn=lambda: DEFAULT_FRAME_TIMESTAMP,
    )
    user_query = "Why is my application throwing ZeroDivisionError in calculator.py?"

    print_substep(f"3.1 Prioritizing candidates for query: '{user_query}'...")
    bounded_items = builder.build_context(
        user_query=user_query,
        context_items=candidate_pool,
        reference_time=DEFAULT_FRAME_TIMESTAMP,
    )

    print(f"    Admitted Items:       {len(bounded_items)} ({'at ceiling of ' + str(config.max_items) if len(bounded_items) == config.max_items else 'within ceiling of ' + str(config.max_items)})")
    for idx, item in enumerate(bounded_items, start=1):
        tokens = builder.estimate_item_tokens(item)
        score = builder.score_relevance(item, builder.extract_keywords(user_query))
        print(f"      [{idx}] ID: {item.item_id:<16} Type: {item.context_type.value:<10} Score: {score:>4.1f} Est.Tokens: {tokens:>3} Source: {item.source}")

    print_substep("3.2 Demonstrating staleness filtering and token budget exclusion...")
    # Deliberately stale item with query-relevant keywords: age 7200s > max_age_seconds=3600s
    stale_item = ContextItem(
        item_id="ctx-stale-001",
        context_type=ContextType.SCREEN,
        source="stale_calculator.py",
        content="ZeroDivisionError calculator.py: prior crash traceback on line 12",
        timestamp=DEFAULT_FRAME_TIMESTAMP - timedelta(seconds=7200),
    )
    # Deliberately oversized item (exceeds 400 token budget)
    oversized_item = ContextItem(
        item_id="ctx-oversized-001",
        context_type=ContextType.DOCUMENT,
        source="huge_dump.log",
        content="ZeroDivisionError dump " * 100,
        timestamp=DEFAULT_FRAME_TIMESTAMP,
    )
    edge_pool = [stale_item, oversized_item] + bounded_items

    # (a) Demo builder: max_age=3600s, token_budget=400, max_items=4
    filtered_a = builder.build_context(
        user_query=user_query,
        context_items=edge_pool,
        reference_time=DEFAULT_FRAME_TIMESTAMP,
    )
    stale_in_a = any(it.item_id == "ctx-stale-001" for it in filtered_a)
    oversized_in_a = any(it.item_id == "ctx-oversized-001" for it in filtered_a)

    # (b) Comparison builder: max_age=86400s, token_budget=5000, max_items=10
    comparison_builder = BoundedContextBuilder(
        config=BoundedContextConfig(
            max_items=10,
            token_budget=5000,
            max_age_seconds=86400.0,
            chars_per_token=4.0,
        ),
        clock_fn=lambda: DEFAULT_FRAME_TIMESTAMP,
    )
    filtered_b = comparison_builder.build_context(
        user_query=user_query,
        context_items=edge_pool,
        reference_time=DEFAULT_FRAME_TIMESTAMP,
    )
    stale_in_b = any(it.item_id == "ctx-stale-001" for it in filtered_b)
    oversized_in_b = any(it.item_id == "ctx-oversized-001" for it in filtered_b)

    stale_reason = f"excluded at max_age={config.max_age_seconds:.0f}s (Included={stale_in_a}), included at max_age=86400s (Included={stale_in_b})"
    print(f"    Stale Item (ctx-stale-001):        Included={stale_in_a} (Proof: {stale_reason})")

    oversized_tokens = builder.estimate_item_tokens(oversized_item)
    oversized_reason = f"excluded at token_budget={config.token_budget} (Included={oversized_in_a}), included at token_budget=5000 (Included={oversized_in_b})"
    print(f"    Oversized Item (ctx-oversized-001): Included={oversized_in_a} (Proof: ~{oversized_tokens} tokens, {oversized_reason})")

    if stale_in_a or not stale_in_b:
        print("    [FAIL] Stale item filtering comparison proof failed!")
        return 1
    if oversized_in_a or not oversized_in_b:
        print("    [FAIL] Oversized item budget filtering comparison proof failed!")
        return 1

    print_substep("3.3 Diagnostics report via build_context_with_report()...")
    _, diag_report = builder.build_context_with_report(
        user_query=user_query,
        context_items=edge_pool,
        reference_time=DEFAULT_FRAME_TIMESTAMP,
    )
    print(f"    Exclusion report ({len(diag_report)} entries):")
    for entry in diag_report:
        print(f"      item_id={entry['item_id']!r:30s}  reason={entry['reason']!r}")

    print_substep("3.4 min_relevance=2.0 filters zero-score items...")
    min_rel_config = BoundedContextConfig(
        max_items=10,
        token_budget=5000,
        max_age_seconds=86400.0,
        min_relevance=2.0,
    )
    min_rel_builder = BoundedContextBuilder(
        config=min_rel_config,
        clock_fn=lambda: DEFAULT_FRAME_TIMESTAMP,
    )
    keywords = min_rel_builder.extract_keywords(user_query)
    min_rel_items, min_rel_report = min_rel_builder.build_context_with_report(
        user_query=user_query,
        context_items=candidate_pool,
        reference_time=DEFAULT_FRAME_TIMESTAMP,
    )
    below_entries = [r for r in min_rel_report if r["reason"] == "below_min_relevance"]
    print(f"    Admitted (score >= 2.0): {len(min_rel_items)} items")
    print(f"    Below min_relevance:     {len(below_entries)} items excluded")
    for item in min_rel_items:
        score = min_rel_builder.score_relevance(item, keywords)
        print(f"      Admitted  ID: {item.item_id:<18} Score: {score:.2f}")
    for entry in below_entries:
        print(f"      Excluded  ID: {entry['item_id']:<18} Reason: {entry['reason']}")
    if any(min_rel_builder.score_relevance(it, keywords) < 2.0 for it in min_rel_items):
        print("    [FAIL] min_relevance filter admitted a below-threshold item!")
        return 1
    print("    [PASSED] min_relevance=2.0 filter verified correctly.")

    # =========================================================================
    # STEP 4: Versioned Prompt Hardening & Untrusted Isolation
    # =========================================================================
    print_header("Versioned Prompts & Security Boundary Isolation", 4)
    client = LLMClientAdapter(config=LLMClientConfig(provider="mock"))

    reasoning_req = ReasoningRequest(
        request_id="req-demo-w2",
        session_id="sess-demo-1",
        user_query=user_query,
        context_items=bounded_items,
        prompt_version="v1.0.0",
        created_at=DEFAULT_FRAME_TIMESTAMP,
    )

    assembled_prompt = client.build_prompt(reasoning_req)
    print_substep("4.1 Inspecting hardened prompt structure...")
    prompt_lines = assembled_prompt.splitlines()

    # Search dynamically for section boundary markers
    trusted_marker = "### SYSTEM INSTRUCTIONS (TRUSTED) ###"
    untrusted_marker_start = "<untrusted_context>"

    trusted_idx = next((i for i, line in enumerate(prompt_lines) if trusted_marker in line), -1)
    untrusted_idx = next((i for i, line in enumerate(prompt_lines) if untrusted_marker_start in line), -1)

    if trusted_idx == -1:
        print(f"    [FAIL] Trusted instructions marker '{trusted_marker}' not found in prompt!")
        return 1
    if untrusted_idx == -1:
        print(f"    [FAIL] Untrusted context marker '{untrusted_marker_start}' not found in prompt!")
        return 1

    print("    [Top Section Snippet - Trusted Instructions]:")
    for line in prompt_lines[trusted_idx : trusted_idx + 7]:
        print(f"      | {line}")
    print("      | ...")
    print("    [Middle Section Snippet - Untrusted Context Boundary]:")
    # Show lines around the untrusted boundary tag
    untrusted_start_show = max(0, untrusted_idx - 3)
    for line in prompt_lines[untrusted_start_show : untrusted_idx + 4]:
        print(f"      | {line}")
    print("      | ...")
    print(f"    Total Prompt Characters: {len(assembled_prompt)}")

    # =========================================================================
    # STEP 5: Structured Reasoning Execution & Bounded Retry
    # =========================================================================
    print_header("LLM Client Adapter Generation & Structured Output (Days 12–13)", 5)
    print_substep("5.1 Executing reasoning request through LLMClientAdapter...")
    reasoning_result = client.generate(reasoning_req)

    print(f"    Request ID:           {reasoning_result.request_id}")
    print(f"    Outcome Status:       {reasoning_result.status}")
    print(f"    Risk Category:        Category {reasoning_result.risk_level.value}")
    print(f"    Requires Approval:    {reasoning_result.requires_approval}")
    print(f"    Simulated latency (mock, hash-derived): {reasoning_result.latency_ms:.2f} ms")
    print(f"    Response Text:\n      \"{reasoning_result.response_text}\"")
    print("    Grounded Sources Cited:")
    for src in reasoning_result.sources:
        print(f"      - ID: {src.source_id:<12} Type: {src.source_type:<10} Location: {src.reference_location or 'N/A'}")

    print_substep("5.2 Demonstrating bounded retry with exponential backoff on transient failure...")
    # Case 1: Single transient failure
    retry_mock_provider = MockLLMClient()
    retry_mock_provider.transient_failures_remaining = 1
    simulated_sleeps = []
    retry_client = LLMClientAdapter(
        config=LLMClientConfig(
            provider="mock",
            max_retries=2,
            retry_delay_seconds=0.05,
            backoff_multiplier=2.0,
        ),
        provider=retry_mock_provider,
        sleeper=simulated_sleeps.append,
    )
    retry_result = retry_client.generate(reasoning_req)
    print("    Case 1 (1 transient failure):")
    print(f"      Simulated Transient Failures: 1 (e.g. HTTP 503 Service Unavailable)")
    print(f"      Simulated Sleep Backoffs:     {simulated_sleeps}")
    print(f"      Outcome Status After Retry:   {retry_result.status}")
    print(f"      Request ID Correlated:        {retry_result.request_id}")
    if (
        retry_result.status != "success"
        or simulated_sleeps != [0.05]
        or retry_mock_provider.transient_failures_remaining != 0
    ):
        print("    [FAIL] Case 1 retry assertion failed!")
        return 1
    print("    [PASSED] Case 1: Successfully recovered after bounded retry with backoff.")

    # Case 2: Two transient failures showing exponential backoff [0.05, 0.1]
    retry_mock_provider_2 = MockLLMClient()
    retry_mock_provider_2.transient_failures_remaining = 2
    simulated_sleeps_2 = []
    retry_client_2 = LLMClientAdapter(
        config=LLMClientConfig(
            provider="mock",
            max_retries=2,
            retry_delay_seconds=0.05,
            backoff_multiplier=2.0,
        ),
        provider=retry_mock_provider_2,
        sleeper=simulated_sleeps_2.append,
    )
    retry_result_2 = retry_client_2.generate(reasoning_req)
    print("    Case 2 (2 transient failures with exponential backoff):")
    print(f"      Simulated Transient Failures: 2")
    print(f"      Simulated Sleep Backoffs:     {simulated_sleeps_2}")
    print(f"      Outcome Status After Retry:   {retry_result_2.status}")
    print(f"      Request ID Correlated:        {retry_result_2.request_id}")
    if (
        retry_result_2.status != "success"
        or simulated_sleeps_2 != [0.05, 0.1]
        or retry_mock_provider_2.transient_failures_remaining != 0
    ):
        print("    [FAIL] Case 2 exponential retry assertion failed!")
        return 1
    print("    [PASSED] Case 2: Successfully recovered after exponential backoff [0.05s, 0.1s].")

    print_substep("5.3 Demonstrating timeout fast-fail ceiling and safe fallback...")
    timeout_mock = MockLLMClient()
    timeout_mock.simulated_latency_sec = 1.0
    timeout_client = LLMClientAdapter(
        config=LLMClientConfig(
            provider="mock",
            timeout_seconds=0.05,
            max_retries=0,
            retry_on_timeout=False,
        ),
        provider=timeout_mock,
    )
    try:
        timeout_client.generate(reasoning_req)
        print("    [FAIL] Expected LLMTimeoutError was not raised!")
        return 1
    except LLMTimeoutError as e:
        print(f"    Caught Exception Class:       {type(e).__name__}")
        print("    [PASSED] Request fast-failed upon exceeding timeout ceiling without blocking.")

    safe_timeout_res = timeout_client.reason_safe(reasoning_req)
    print(f"    reason_safe Outcome Status:   {safe_timeout_res.status}")
    print(f"    reason_safe Confidence:       {safe_timeout_res.confidence}")
    if safe_timeout_res.status != "error":
        print("    [FAIL] reason_safe did not convert timeout to status='error'!")
        return 1
    print("    [PASSED] reason_safe cleanly converted timeout failure into structured error response.")

    # =========================================================================
    # STEP 6: Malformed Output Rejection (Day 14)
    # =========================================================================
    print_header("Malformed Provider Output Rejection & Validation (Day 14)", 6)
    mock_prov = MockLLMClient()
    mock_prov.simulated_malformed_output = {
        "request_id": "req-demo-w2",
        "status": "success",
        # response_text is deliberately missing
        "prompt_version": "v1.0.0",
    }
    strict_client = LLMClientAdapter(provider=mock_prov)

    print_substep("6.1 Injecting malformed provider output (missing required fields)...")
    try:
        strict_client.generate(reasoning_req)
        print("    [FAIL] Malformed output was not rejected!")
        return 1
    except LLMValidationError as e:
        err_msg = str(e)
        missing_field = "response_text" if "response_text" in err_msg else None
        if not missing_field:
            print("    [FAIL] Expected 'response_text' missing field not identified in error!")
            return 1
        print("    [PASSED] LLMValidationError caught as expected:")
        print("      Error Class:      LLMValidationError")
        print(f"      Field Identified: {missing_field}")

    # =========================================================================
    # STEP 7: Resilient Safe Execution (reason_safe)
    # =========================================================================
    print_header("Resilient Safe Fallback Execution (reason_safe)", 7)
    print_substep("7.1 Submitting invalid payload to reason_safe()...")
    safe_result = client.reason_safe({"invalid_key": "not a valid reasoning request"})

    print(f"    Request ID:           {safe_result.request_id}")
    print(f"    Outcome Status:       {safe_result.status}")
    print(f"    Confidence:           {safe_result.confidence}")
    print(f"    Error Response Text:  \"{safe_result.response_text}\"")

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n" + "=" * 78)
    print("  WEEK 2 DEMONSTRATION COMPLETE: ALL 7 PIPELINE PHASES VERIFIED [OK]")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
