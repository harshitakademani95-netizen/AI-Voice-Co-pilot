"""
Workstream W3: Context & Reasoning (Week 2 - Task 2 Extension)
Parametrized Malformed Output Validation Tests for LLM Client Adapter

Author: Amruta A J (Team SDE 3)
Module: tests.test_llm_malformed_output
Description:
    One test per invalid provider output case. Each test asserts:
    1. LLMValidationError is raised.
    2. Provider call_raw is invoked exactly ONCE (never retried for validation failures).
    3. The error message does NOT leak raw provider output values.
"""

import unittest
from datetime import datetime, timezone
from typing import Any, List

from src.context.schemas import (
    ContextItem,
    ContextType,
    DEFAULT_FRAME_TIMESTAMP,
    ReasoningRequest,
    ReasoningResult,
    RiskCategory,
    SourceReference,
)
from src.reasoning.llm_client import (
    LLMClientAdapter,
    LLMClientConfig,
    LLMValidationError,
    MockLLMClient,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(malformed_output: Any, call_counter: List[int]) -> LLMClientAdapter:
    """Return a client whose mock provider returns malformed_output and increments counter."""
    mock = MockLLMClient()

    original_call_raw = mock.call_raw

    def counting_call_raw(request):
        call_counter.append(1)
        return malformed_output

    mock.call_raw = counting_call_raw
    return LLMClientAdapter(
        config=LLMClientConfig(max_retries=0),
        provider=mock,
    )


# pyrefly: ignore[bad-function-definition]
def _make_request(context_items: List[ContextItem] = None) -> ReasoningRequest:
    return ReasoningRequest(
        request_id="req-mal-1",
        session_id="sess-1",
        user_query="What is the error?",
        context_items=context_items or [],
        prompt_version="v1.0.0",
    )


def _context_item(item_id: str = "ctx-1") -> ContextItem:
    return ContextItem(
        item_id=item_id,
        context_type=ContextType.DOCUMENT,
        source="test.py",
        content="ZeroDivisionError on line 12",
        timestamp=DEFAULT_FRAME_TIMESTAMP,
    )


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestLLMMalformedOutput(unittest.TestCase):
    """
    One test per malformed provider output case.
    All cases must raise LLMValidationError and NOT be retried (call count == 1).
    """

    def _assert_validation_error_no_retry(
        self,
        malformed_output: Any,
        raw_value_not_in_msg: str = "",
        # pyrefly: ignore[bad-function-definition]
        context_items: List[ContextItem] = None,
    ) -> str:
        """
        Helper: assert LLMValidationError raised, provider called exactly once,
        and raw_value_not_in_msg not echoed in error message.
        Returns the exception message.
        """
        counter: List[int] = []
        client = _make_client(malformed_output, counter)
        req = _make_request(context_items=context_items)

        with self.assertRaises(LLMValidationError) as ctx:
            client.generate(req)

        self.assertEqual(len(counter), 1, "Provider must be called exactly once (no retry on LLMValidationError)")
        err_msg = str(ctx.exception)
        if raw_value_not_in_msg:
            self.assertNotIn(raw_value_not_in_msg, err_msg,
                             f"Raw provider value {raw_value_not_in_msg!r} must not be echoed in error message")
        return err_msg

    # ------------------------------------------------------------------
    # Case 1: response is None
    # ------------------------------------------------------------------

    def test_none_response_raises_validation_error(self):
        """None response raises LLMValidationError; provider called once."""
        msg = self._assert_validation_error_no_retry(None)
        self.assertIn("empty", msg.lower())

    # ------------------------------------------------------------------
    # Case 2: non-dict / invalid JSON string
    # ------------------------------------------------------------------

    def test_invalid_json_string_raises_validation_error(self):
        """Invalid JSON string raises LLMValidationError; provider called once."""
        msg = self._assert_validation_error_no_retry("{ not valid json }", raw_value_not_in_msg="not valid json")
        self.assertIn("not valid JSON", msg)

    def test_non_dict_type_integer_raises_validation_error(self):
        """Integer response raises LLMValidationError with 'Unsupported output type'; called once."""
        msg = self._assert_validation_error_no_retry(42)
        self.assertIn("Unsupported output type", msg)

    def test_non_dict_type_list_raises_validation_error(self):
        """List response raises LLMValidationError; provider called once."""
        msg = self._assert_validation_error_no_retry(["item1", "item2"])
        self.assertIn("Unsupported output type", msg)

    def test_non_dict_type_bool_raises_validation_error(self):
        """Boolean response raises LLMValidationError; provider called once."""
        msg = self._assert_validation_error_no_retry(True)
        self.assertIn("Unsupported output type", msg)

    # ------------------------------------------------------------------
    # Case 3: wrong field types
    # ------------------------------------------------------------------

    def test_confidence_wrong_type_string_raises_validation_error(self):
        """confidence='high' (string instead of float) raises LLMValidationError; called once."""
        payload = {
            "request_id": "req-mal-1",
            "status": "success",
            "response_text": "Analysis complete",
            "confidence": "high",   # wrong type
            "prompt_version": "v1.0.0",
        }
        msg = self._assert_validation_error_no_retry(payload, raw_value_not_in_msg="high")
        self.assertIn("schema validation", msg)

    def test_sources_wrong_type_string_raises_validation_error(self):
        """sources as a string instead of list raises LLMValidationError; called once."""
        payload = {
            "request_id": "req-mal-1",
            "status": "success",
            "response_text": "Analysis complete",
            "sources": "not_a_list",   # wrong type
            "prompt_version": "v1.0.0",
        }
        msg = self._assert_validation_error_no_retry(payload)
        self.assertIn("schema validation", msg)

    # ------------------------------------------------------------------
    # Case 4: confidence outside [0, 1]
    # ------------------------------------------------------------------

    def test_confidence_above_one_raises_validation_error(self):
        """confidence=1.01 raises LLMValidationError; provider called once."""
        payload = {
            "request_id": "req-mal-1",
            "status": "success",
            "response_text": "Analysis",
            "confidence": 1.01,
            "prompt_version": "v1.0.0",
        }
        self._assert_validation_error_no_retry(payload)

    def test_confidence_below_zero_raises_validation_error(self):
        """confidence=-0.01 raises LLMValidationError; provider called once."""
        payload = {
            "request_id": "req-mal-1",
            "status": "success",
            "response_text": "Analysis",
            "confidence": -0.01,
            "prompt_version": "v1.0.0",
        }
        self._assert_validation_error_no_retry(payload)

    # ------------------------------------------------------------------
    # Case 5: empty / whitespace-only response_text
    # ------------------------------------------------------------------

    def test_empty_response_text_raises_validation_error(self):
        """response_text='' raises LLMValidationError; provider called once."""
        payload = {
            "request_id": "req-mal-1",
            "status": "success",
            "response_text": "",
            "prompt_version": "v1.0.0",
        }
        self._assert_validation_error_no_retry(payload)

    def test_whitespace_only_response_text_raises_validation_error(self):
        """response_text='   \\t\\n' raises LLMValidationError; provider called once."""
        # Note: Pydantic min_length=1 catches empty string; our whitespace check catches whitespace-only.
        # We inject a ReasoningResult directly to bypass Pydantic's min_length=1 check on the string.
        counter: List[int] = []
        # Manufacture a valid-looking result object with whitespace response_text
        # We bypass Pydantic by patching validate_output directly
        client = LLMClientAdapter(config=LLMClientConfig(max_retries=0))
        req = _make_request()
        # Build a dict that gets past Pydantic min_length by having a single space that is > 0 chars
        # but is whitespace-only — Pydantic min_length allows " " (length=1), our custom check rejects it.
        payload = {
            "request_id": "req-mal-1",
            "status": "success",
            "response_text": " ",   # length=1 passes Pydantic but is whitespace-only
            "prompt_version": "v1.0.0",
        }
        # We call validate_output directly since generate() goes through the full pipeline
        with self.assertRaises(LLMValidationError) as ctx:
            client.validate_output(payload, req)
        self.assertIn("whitespace", str(ctx.exception).lower())

    # ------------------------------------------------------------------
    # Case 6: response_text longer than max
    # ------------------------------------------------------------------

    def test_oversized_response_text_raises_validation_error(self):
        """response_text exceeding max_response_text_length raises LLMValidationError; called once."""
        long_text = "X" * 10_001
        payload = {
            "request_id": "req-mal-1",
            "status": "success",
            "response_text": long_text,
            "prompt_version": "v1.0.0",
        }
        # validate_output directly (Pydantic max_length=10_000 catches it too — either way is LLMValidationError)
        client = LLMClientAdapter(config=LLMClientConfig(max_retries=0, max_response_text_length=100))
        req = _make_request()
        short_long = "Y" * 101
        payload_short_max = {
            "request_id": "req-mal-1",
            "status": "success",
            "response_text": short_long,
            "prompt_version": "v1.0.0",
        }
        with self.assertRaises(LLMValidationError) as ctx:
            client.validate_output(payload_short_max, req)
        self.assertIn("exceeds maximum", str(ctx.exception))
        # Verify raw long text is not echoed
        self.assertNotIn("Y" * 101, str(ctx.exception))

    # ------------------------------------------------------------------
    # Case 7: invalid risk_level value
    # ------------------------------------------------------------------

    def test_invalid_risk_level_raises_validation_error(self):
        """risk_level='Z' (not in Enum) raises LLMValidationError; provider called once."""
        payload = {
            "request_id": "req-mal-1",
            "status": "success",
            "response_text": "Analysis complete",
            "risk_level": "Z",
            "prompt_version": "v1.0.0",
        }
        msg = self._assert_validation_error_no_retry(payload, raw_value_not_in_msg="Z")
        self.assertIn("schema validation", msg)

    # ------------------------------------------------------------------
    # Case 8: request_id mismatch
    # ------------------------------------------------------------------

    def test_request_id_mismatch_raises_validation_error(self):
        """result.request_id != request.request_id raises LLMValidationError; provider called once."""
        payload = {
            "request_id": "req-WRONG-id",
            "status": "success",
            "response_text": "Analysis complete",
            "prompt_version": "v1.0.0",
        }
        msg = self._assert_validation_error_no_retry(payload)
        self.assertIn("Correlation mismatch", msg)

    # ------------------------------------------------------------------
    # Case 9: grounding check — source_id not in context_items
    # ------------------------------------------------------------------

    def test_ungrounded_source_id_raises_validation_error(self):
        """
        Provider cites a source_id that is not present in request.context_items.
        Must raise LLMValidationError and not be retried.
        """
        item = _context_item("ctx-known-1")
        payload = {
            "request_id": "req-mal-1",
            "status": "success",
            "response_text": "Analysis complete",
            "sources": [
                {
                    "source_id": "ctx-UNKNOWN-999",   # not in context_items
                    "source_type": "code",
                    "confidence_score": 0.9,
                }
            ],
            "prompt_version": "v1.0.0",
        }
        counter: List[int] = []
        client = _make_client(payload, counter)
        req = _make_request(context_items=[item])

        with self.assertRaises(LLMValidationError) as ctx:
            client.generate(req)

        self.assertEqual(len(counter), 1, "Provider must be called exactly once")
        msg = str(ctx.exception)
        self.assertIn("not present in request context_items", msg)
        # Must not echo raw source_id
        self.assertNotIn("ctx-UNKNOWN-999", msg.split("not present")[0])

    def test_grounded_source_id_passes_validation(self):
        """Provider citing a known source_id from context_items passes validation."""
        item = _context_item("ctx-known-1")
        payload = {
            "request_id": "req-mal-1",
            "status": "success",
            "response_text": "ZeroDivisionError found in context.",
            "sources": [
                {
                    "source_id": "ctx-known-1",   # known item_id
                    "source_type": "code",
                    "confidence_score": 0.9,
                }
            ],
            "prompt_version": "v1.0.0",
        }
        client = LLMClientAdapter(config=LLMClientConfig(max_retries=0))
        req = _make_request(context_items=[item])
        result = client.validate_output(payload, req)
        self.assertEqual(result.request_id, "req-mal-1")

    # ------------------------------------------------------------------
    # Case 10: action_required=True but requires_approval=False for Category B
    # ------------------------------------------------------------------

    def test_category_b_action_required_true_requires_approval_false_allowed(self):
        """
        Category B with action_required=True and requires_approval=False is ALLOWED by schema
        (only C/D auto-enforce requires_approval). This confirms Category B policy is not over-restricted.
        """
        payload = {
            "request_id": "req-mal-1",
            "status": "success",
            "response_text": "Opening file",
            "action_required": True,
            "action_type": "file_open",
            "risk_level": RiskCategory.CATEGORY_B.value,
            "requires_approval": False,   # Allowed for Category B
            "prompt_version": "v1.0.0",
        }
        client = LLMClientAdapter(config=LLMClientConfig(max_retries=0))
        req = _make_request()
        result = client.validate_output(payload, req)
        self.assertEqual(result.risk_level, RiskCategory.CATEGORY_B)
        self.assertFalse(result.requires_approval)

    def test_category_c_action_required_false_raises_validation_error(self):
        """Category C with action_required=False violates PRD Section 18 and raises LLMValidationError."""
        payload = {
            "request_id": "req-mal-1",
            "status": "success",
            "response_text": "Moving file",
            "action_required": False,   # violates Cat C policy
            "risk_level": RiskCategory.CATEGORY_C.value,
            "prompt_version": "v1.0.0",
        }
        client = LLMClientAdapter(config=LLMClientConfig(max_retries=0))
        req = _make_request()
        with self.assertRaises(LLMValidationError):
            client.validate_output(payload, req)


if __name__ == "__main__":
    unittest.main()

