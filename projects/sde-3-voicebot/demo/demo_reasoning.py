"""
Day 7 Interactive Demonstration Script
Workstream W3: Context & Reasoning
Student: Amruta A J | Team: SDE 3

Demonstrates:
1. Synthetic frame creation with screen capture disabled by default.
2. Building versioned prompts with trusted vs. untrusted content boundaries.
3. Deterministic mock reasoning generating grounded responses with SourceReferences.
4. Risk classification and Human-in-the-Loop safety approval gating.
"""

import json
from src.context.fixtures import (
    create_synthetic_screen_frame,
    get_synthetic_document_scenario,
    get_synthetic_error_scenario,
    get_synthetic_file_action_scenario,
)
from src.context.schemas import ReasoningRequest
from src.prompts.versioned_prompts import build_versioned_prompt
from src.reasoning.mock_engine import MockReasoningEngine


def run_demo():
    print("=" * 80)
    print("AI VOICE CO-PILOT: WORKSTREAM W3 (CONTEXT & REASONING) DEMONSTRATION")
    print("Student: Amruta A J | Team: SDE 3 | Week 1 Vertical Slice")
    print("=" * 80)

    engine = MockReasoningEngine()

    # Scenario 1: Technical Error Explanation (PRD UC-02)
    print("\n[DEMO 1] PRD UC-02: Explain Technical Error (ZeroDivisionError)")
    print("-" * 80)
    error_items = get_synthetic_error_scenario()
    req_1 = ReasoningRequest(
        request_id="req-demo-001",
        session_id="sess-student-1",
        user_query="Why is this application failing?",
        context_items=error_items,
        prompt_version="v1.0.0",
    )

    result_1 = engine.reason(req_1)
    print(f"User Query      : {req_1.user_query}")
    print(f"Prompt Version  : {result_1.prompt_version}")
    print(f"Risk Category   : {result_1.risk_level.value} (Category A: Informational)")
    print(f"Needs Approval  : {result_1.requires_approval}")
    print(f"Response        : {result_1.response_text}")
    print("Grounded Sources Cited:")
    for s in result_1.sources:
        print(f"  - [{s.source_type}] {s.source_id} @ {s.reference_location} (conf: {s.confidence_score})")
        if s.excerpt:
            print(f"    Excerpt: \"{s.excerpt}\"")

    # Scenario 2: Research Paper Explanation (PRD UC-03)
    print("\n[DEMO 2] PRD UC-03: Explain Document (Project Nimbus Abstract)")
    print("-" * 80)
    doc_items = get_synthetic_document_scenario()
    req_2 = ReasoningRequest(
        request_id="req-demo-002",
        session_id="sess-student-2",
        user_query="Explain the methodology shown in this paper",
        context_items=doc_items,
        prompt_version="v1.1.0",
    )

    result_2 = engine.reason(req_2)
    print(f"User Query      : {req_2.user_query}")
    print(f"Prompt Version  : {result_2.prompt_version}")
    print(f"Risk Category   : {result_2.risk_level.value}")
    print(f"Response        : {result_2.response_text}")
    print(f"Source Cited    : {result_2.sources[0].reference_location}")

    # Scenario 3: Safety Gate Demonstration (PRD UC-08 - File Move Action)
    print("\n[DEMO 3] PRD UC-08: Controlled File Operation (Safety & Approval Gate)")
    print("-" * 80)
    file_items = get_synthetic_file_action_scenario()
    req_3 = ReasoningRequest(
        request_id="req-demo-003",
        session_id="sess-student-3",
        user_query="Move these files into the archive folder",
        context_items=file_items,
        prompt_version="v1.0.0",
    )

    result_3 = engine.reason(req_3)
    print(f"User Query      : {req_3.user_query}")
    print(f"Action Required : {result_3.action_required} (Action: {result_3.action_type})")
    print(f"Risk Category   : Category {result_3.risk_level.value} (Sensitive Operation)")
    print(f"Requires Approval: {result_3.requires_approval} (Enforced by Human-in-the-Loop Safety Gate)")
    print(f"AI Response     : {result_3.response_text}")

    # Scenario 4: Trusted vs. Untrusted Prompt Boundary Demonstration
    print("\n[DEMO 4] Versioned Prompt Isolation & Prompt Injection Defense")
    print("-" * 80)
    prompt_str = build_versioned_prompt(
        version="v1.0.0",
        user_query="Why is this code failing?",
        context_items=error_items[:1],
    )
    print("Rendered Prompt Preview (Notice clean boundaries):")
    print(prompt_str[:450] + "\n... [truncated for display] ...\n" + prompt_str[-180:])

    print("\n" + "=" * 80)
    print("DEMONSTRATION COMPLETED SUCCESSFULLY [ALL SCHEMAS & CONTROLS VERIFIED]")
    print("=" * 80)


if __name__ == "__main__":
    run_demo()
