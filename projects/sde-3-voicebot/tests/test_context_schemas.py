"""
Unit tests for the 5 core W3 Context Schemas:
- ScreenContext
- ContextItem
- SourceReference
- ReasoningRequest
- ReasoningResult
"""

import unittest
from datetime import datetime
from pydantic import ValidationError
from src.context.schemas import (
    ContextItem,
    ContextType,
    ReasoningRequest,
    ReasoningResult,
    RiskCategory,
    ScreenContext,
    SourceReference,
)


class TestSchemas(unittest.TestCase):

    def test_source_reference_valid(self):
        ref = SourceReference(
            source_id="src-001",
            source_type="code",
            reference_location="calculator.py:L14",
            excerpt="def divide(a, b): return a / b",
            confidence_score=0.95,
        )
        self.assertEqual(ref.source_id, "src-001")
        self.assertEqual(ref.source_type, "code")
        self.assertEqual(ref.confidence_score, 0.95)

    def test_source_reference_invalid_confidence(self):
        with self.assertRaises(ValidationError):
            SourceReference(
                source_id="src-002",
                source_type="code",
                confidence_score=1.5,  # > 1.0 is invalid
            )
        with self.assertRaises(ValidationError):
            SourceReference(
                source_id="src-003",
                source_type="code",
                confidence_score=-0.1,  # < 0.0 is invalid
            )

    def test_screen_context_defaults(self):
        """Verify screen capture is explicitly disabled by default and frame is synthetic."""
        sc = ScreenContext(frame_id="frame-default")
        self.assertFalse(sc.capture_enabled, "capture_enabled must be False by default")
        self.assertTrue(sc.is_synthetic, "is_synthetic must be True for safe synthetic frames")
        self.assertEqual(sc.width, 1920)
        self.assertEqual(sc.height, 1080)
        self.assertIsInstance(sc.captured_at, datetime)

    def test_screen_context_invalid_dimensions(self):
        with self.assertRaises(ValidationError):
            ScreenContext(frame_id="f1", width=0, height=1080)
        with self.assertRaises(ValidationError):
            ScreenContext(frame_id="f2", width=1920, height=-100)

    def test_context_item_valid(self):
        item = ContextItem(
            item_id="item-001",
            context_type=ContextType.CODE,
            source="src/main.py",
            content="print('Hello World')",
            metadata={"lines": 1},
        )
        self.assertEqual(item.context_type, ContextType.CODE)
        self.assertEqual(item.source, "src/main.py")
        self.assertIsNone(item.screen_context)

    def test_context_item_invalid_type(self):
        with self.assertRaises(ValidationError):
            ContextItem(
                item_id="item-002",
                context_type="invalid_type",  # type: ignore
                source="src/main.py",
                content="some content",
            )

    def test_reasoning_request_valid(self):
        req = ReasoningRequest(
            request_id="req-101",
            session_id="sess-001",
            user_query="Why is this failing?",
            prompt_version="v1.0.0",
        )
        self.assertEqual(req.request_id, "req-101")
        self.assertEqual(req.user_query, "Why is this failing?")
        self.assertEqual(len(req.context_items), 0)

    def test_reasoning_request_empty_query_rejected(self):
        with self.assertRaises(ValidationError):
            ReasoningRequest(
                request_id="req-102",
                session_id="sess-001",
                user_query="   ",  # whitespace only must be rejected
            )

    def test_reasoning_result_safety_approval_enforcement(self):
        """
        Category C (Sensitive) and Category D (Destructive) must automatically enforce
        requires_approval = True as per PRD Section 18 safety-by-design.
        """
        # Category A does not require approval
        res_a = ReasoningResult(
            request_id="res-a",
            response_text="Informational answer",
            risk_level=RiskCategory.CATEGORY_A,
            requires_approval=False,
            prompt_version="v1.0.0",
        )
        self.assertFalse(res_a.requires_approval)

        # Category C automatically enforces requires_approval=True and requires action_required=True
        res_c = ReasoningResult(
            request_id="res-c",
            response_text="Modify files",
            risk_level=RiskCategory.CATEGORY_C,
            action_required=True,
            action_type="move_files",
            requires_approval=False,  # validator must override to True
            prompt_version="v1.0.0",
        )
        self.assertTrue(res_c.requires_approval, "Category C must enforce requires_approval=True")

        # Category D automatically enforces requires_approval=True and requires action_required=True
        res_d = ReasoningResult(
            request_id="res-d",
            response_text="Delete files",
            risk_level=RiskCategory.CATEGORY_D,
            action_required=True,
            action_type="delete_files",
            requires_approval=False,
            prompt_version="v1.0.0",
        )
        self.assertTrue(res_d.requires_approval, "Category D must enforce requires_approval=True")

    def test_reasoning_result_invalid_latency(self):
        with self.assertRaises(ValidationError):
            ReasoningResult(
                request_id="res-inv",
                response_text="Test",
                latency_ms=-5.0,  # negative latency is invalid
                prompt_version="v1.0.0",
            )

    def test_reasoning_result_needs_clarification_status(self):
        """Verify ReasoningResult accepts 'needs_clarification' as a valid schema status."""
        res = ReasoningResult(
            request_id="res-clarify-01",
            status="needs_clarification",
            response_text="Context is insufficient to determine the root cause.",
            prompt_version="v1.0.0",
        )
        self.assertEqual(res.status, "needs_clarification")
        self.assertEqual(res.risk_level, RiskCategory.CATEGORY_A)
        self.assertFalse(res.requires_approval)

    def test_reasoning_result_invalid_status_rejected(self):
        """Verify invalid statuses are rejected by schema validation."""
        with self.assertRaises(ValidationError):
            ReasoningResult(
                request_id="res-bad-status",
                status="completely_unknown_status",  # type: ignore
                response_text="Test",
                prompt_version="v1.0.0",
            )

    def test_extra_fields_forbidden_on_all_schemas(self):
        """Verify ConfigDict(extra='forbid') rejects arbitrary extra fields."""
        with self.assertRaises(ValidationError):
            SourceReference.model_validate({"source_id": "s1", "source_type": "code", "unexpected": "extra"})
        with self.assertRaises(ValidationError):
            ScreenContext.model_validate({"frame_id": "f1", "unexpected": "extra"})
        with self.assertRaises(ValidationError):
            ContextItem.model_validate({"item_id": "i1", "context_type": ContextType.CODE, "source": "s.py", "content": "x", "unexpected": "extra"})
        with self.assertRaises(ValidationError):
            ReasoningRequest.model_validate({"request_id": "r1", "session_id": "s1", "user_query": "q", "unexpected": "extra"})
        with self.assertRaises(ValidationError):
            ReasoningResult.model_validate({"request_id": "r1", "response_text": "ans", "prompt_version": "v1.0.0", "unexpected": "extra"})

    def test_screen_context_rejects_non_synthetic_and_capture_enabled(self):
        """ScreenContext must reject is_synthetic=False and capture_enabled=True."""
        # Non-synthetic rejected
        with self.assertRaises(ValidationError) as ctx1:
            ScreenContext(frame_id="f1", is_synthetic=False)
        self.assertIn("only synthetic frames are allowed", str(ctx1.exception))

        # Active capture rejected
        with self.assertRaises(ValidationError) as ctx2:
            ScreenContext(frame_id="f2", capture_enabled=True)
        self.assertIn("only synthetic frames are allowed", str(ctx2.exception))

    def test_max_length_limits_and_boundaries(self):
        """Verify max length limits for user_query, content, response_text, and context_items."""
        # user_query: max 2000
        valid_q = "a" * 2000
        req_valid = ReasoningRequest(request_id="rq", session_id="sq", user_query=valid_q)
        self.assertEqual(len(req_valid.user_query), 2000)

        invalid_q = "a" * 2001
        with self.assertRaises(ValidationError):
            ReasoningRequest(request_id="rq", session_id="sq", user_query=invalid_q)

        # ContextItem.content: max 100_000
        valid_c = "c" * 100_000
        item_valid = ContextItem(item_id="i-c", context_type=ContextType.CODE, source="test.py", content=valid_c)
        self.assertEqual(len(item_valid.content), 100_000)

        invalid_c = "c" * 100_001
        with self.assertRaises(ValidationError):
            ContextItem(item_id="i-c", context_type=ContextType.CODE, source="test.py", content=invalid_c)

        # response_text: min 1, max 10_000
        with self.assertRaises(ValidationError):
            ReasoningResult(request_id="rr", response_text="", prompt_version="v1.0.0")

        valid_res_text = "r" * 10_000
        res_valid = ReasoningResult(request_id="rr", response_text=valid_res_text, prompt_version="v1.0.0")
        self.assertEqual(len(res_valid.response_text), 10_000)

        invalid_res_text = "r" * 10_001
        with self.assertRaises(ValidationError):
            ReasoningResult(request_id="rr", response_text=invalid_res_text, prompt_version="v1.0.0")

        # context_items: max 50
        items_50 = [
            ContextItem(item_id=f"item-{i}", context_type=ContextType.CODE, source=f"f{i}.py", content=f"x={i}")
            for i in range(50)
        ]
        req_50 = ReasoningRequest(request_id="r-50", session_id="s", user_query="q", context_items=items_50)
        self.assertEqual(len(req_50.context_items), 50)

        items_51 = [
            ContextItem(item_id=f"item-{i}", context_type=ContextType.CODE, source=f"f{i}.py", content=f"x={i}")
            for i in range(51)
        ]
        with self.assertRaises(ValidationError):
            ReasoningRequest(request_id="r-51", session_id="s", user_query="q", context_items=items_51)

    def test_reasoning_request_duplicate_item_id_rejected(self):
        """ReasoningRequest must reject duplicate item_id entries in context_items."""
        item1 = ContextItem(item_id="dup-id", context_type=ContextType.CODE, source="a.py", content="a=1")
        item2 = ContextItem(item_id="dup-id", context_type=ContextType.TERMINAL, source="term", content="err")
        with self.assertRaises(ValidationError) as ctx:
            ReasoningRequest(request_id="r-dup", session_id="s", user_query="q", context_items=[item1, item2])
        self.assertIn("Duplicate item_id 'dup-id'", str(ctx.exception))

    def test_prompt_version_pattern_validation(self):
        """ReasoningRequest prompt_version must match pattern r"^v\\d+\\.\\d+\\.\\d+(-[A-Za-z0-9.]+)?$"."""
        # Valid semantic versions
        ReasoningRequest(request_id="r", session_id="s", user_query="q", prompt_version="v1.0.0")
        ReasoningRequest(request_id="r", session_id="s", user_query="q", prompt_version="v2.1.0-alpha.1")

        # Invalid versions
        with self.assertRaises(ValidationError):
            ReasoningRequest(request_id="r", session_id="s", user_query="q", prompt_version="1.0.0")  # missing v
        with self.assertRaises(ValidationError):
            ReasoningRequest(request_id="r", session_id="s", user_query="q", prompt_version="v1.0")    # missing patch
        with self.assertRaises(ValidationError):
            ReasoningRequest(request_id="r", session_id="s", user_query="q", prompt_version="latest")  # not semver

    def test_action_consistency_and_risk_rules(self):
        """Verify action_required vs action_type consistency and Category C/D requirements."""
        # action_required=True without action_type fails
        with self.assertRaises(ValidationError):
            ReasoningResult(
                request_id="r",
                response_text="Action needed",
                action_required=True,
                action_type=None,
                prompt_version="v1.0.0",
            )

        # action_type set without action_required=True fails
        with self.assertRaises(ValidationError):
            ReasoningResult(
                request_id="r",
                response_text="Action needed",
                action_required=False,
                action_type="some_action",
                prompt_version="v1.0.0",
            )

        # Category C without action_required=True fails
        with self.assertRaises(ValidationError):
            ReasoningResult(
                request_id="r",
                response_text="Move files",
                risk_level=RiskCategory.CATEGORY_C,
                action_required=False,
                prompt_version="v1.0.0",
            )

        # Category D without action_required=True fails
        with self.assertRaises(ValidationError):
            ReasoningResult(
                request_id="r",
                response_text="Delete files",
                risk_level=RiskCategory.CATEGORY_D,
                action_required=False,
                prompt_version="v1.0.0",
            )

        # Status error with confidence > 0.5 fails
        with self.assertRaises(ValidationError):
            ReasoningResult(
                request_id="r",
                status="error",
                response_text="Fatal failure",
                confidence=0.8,
                prompt_version="v1.0.0",
            )

        # Status error with confidence <= 0.5 succeeds
        err_res = ReasoningResult(
            request_id="r",
            status="error",
            response_text="Fatal failure",
            confidence=0.0,
            prompt_version="v1.0.0",
        )
        self.assertEqual(err_res.status, "error")

    def test_timezone_aware_datetime_enforcement(self):
        """Naive datetimes must be rejected across models."""
        naive_dt = datetime(2026, 1, 1, 12, 0, 0)  # naive, no tzinfo

        with self.assertRaises(ValidationError):
            ScreenContext(frame_id="f", captured_at=naive_dt)

        with self.assertRaises(ValidationError):
            ContextItem(item_id="i", context_type=ContextType.CODE, source="s", content="c", timestamp=naive_dt)

        with self.assertRaises(ValidationError):
            ReasoningRequest(request_id="r", session_id="s", user_query="q", created_at=naive_dt)


if __name__ == "__main__":
    unittest.main()
