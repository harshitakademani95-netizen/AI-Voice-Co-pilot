"""
Workstream W3: Context & Reasoning Engine
No-Evidence & Honest Uncertainty Reasoning Responses Unit Tests

Author: Amruta A J (Team SDE 3)
Module: tests.test_no_evidence_responses
Description:
    Validates evidence-bounded honest responses across missing, irrelevant, or partial evidence:
    1. Empty context: returns needs_clarification, empty sources, explicit statement of absence
       of supporting evidence, and helpful suggestions on what could help.
    2. Irrelevant context: returns needs_clarification, empty sources, explicit statement that context
       does not support the query.
    3. Corrupted or invalid provenance context: returns needs_clarification, empty sources.
    4. Partial evidence: cites ONLY supported sources, explicitly identifies unsupported aspects in
       response_text, keeps action_required=False.
"""

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

# Ensure project root and src are in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PROJECT_ROOT / "src"
for p in (_SRC_DIR, _PROJECT_ROOT):
    p_str = str(p)
    if p_str not in sys.path:
        sys.path.insert(0, p_str)

from src.context.schemas import (
    ContextItem,
    ContextType,
    ReasoningRequest,
    ReasoningResult,
    RiskCategory,
)
from src.reasoning.llm_client import LLMClientAdapter, LLMClientConfig, MockLLMClient


class TestNoEvidenceResponses(unittest.TestCase):
    """Validation test suite for evidence-bounded uncertainty and no-evidence reasoning."""

    def setUp(self) -> None:
        self.simulated_time = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.adapter = LLMClientAdapter(
            config=LLMClientConfig(max_retries=0),
            provider=MockLLMClient(),
        )

    def test_empty_context_explicit_no_evidence_wording(self) -> None:
        """When context is completely empty, engine must return needs_clarification with explicit no-evidence explanation."""
        req = ReasoningRequest(
            request_id="req-no-evid-01",
            session_id="sess-no-evid",
            user_query="What is the database connection pool status?",
            context_items=[],
            prompt_version="v1.0.0",
            created_at=self.simulated_time,
        )
        res = self.adapter.generate(req)

        self.assertEqual(res.status, "needs_clarification")
        self.assertEqual(len(res.sources), 0, "Must cite zero sources when evidence is absent.")
        self.assertFalse(res.action_required)
        self.assertIn("absence of evidence does not indicate falsehood", res.response_text.lower())
        self.assertTrue(
            "absence of supporting evidence" in res.response_text.lower()
            or "no workspace context was provided" in res.response_text.lower()
        )
        self.assertIn("please provide", res.response_text.lower())

    def test_irrelevant_context_explicit_no_evidence_wording(self) -> None:
        """When context items exist but none support the query, engine must return needs_clarification with zero sources."""
        unrelated_item = ContextItem(
            item_id="ctx-unrelated-01",
            context_type=ContextType.DOCUMENT,
            source="recipes.txt",
            content="To bake sourdough bread, mix flour, water, salt, and levain.",
            timestamp=self.simulated_time,
        )
        req = ReasoningRequest(
            request_id="req-no-evid-02",
            session_id="sess-no-evid",
            user_query="What is the Kubernetes ingress controller status?",
            context_items=[unrelated_item],
            prompt_version="v1.0.0",
            created_at=self.simulated_time,
        )
        res = self.adapter.generate(req)

        self.assertEqual(res.status, "needs_clarification")
        self.assertEqual(len(res.sources), 0, "No sources should be cited when context is irrelevant.")
        self.assertFalse(res.action_required)
        self.assertTrue(
            "does not contain information to support" in res.response_text.lower()
            or "absence of supporting evidence" in res.response_text.lower()
        )

    def test_partial_evidence_cites_only_supported_sources(self) -> None:
        """
        When query has multiple clauses and context supports only one,
        engine must cite ONLY supported sources and state what is unevidenced.
        """
        db_item = ContextItem(
            item_id="ctx-db-01",
            context_type=ContextType.SCREEN,
            source="Database Console",
            content="PostgreSQL service is active and listening on port 5432.",
            metadata={"source_id": "frame-db-01"},
            timestamp=self.simulated_time,
        )
        req = ReasoningRequest(
            request_id="req-partial-01",
            session_id="sess-partial",
            user_query="Is the PostgreSQL service active and is the Redis cache cluster running?",
            context_items=[db_item],
            prompt_version="v1.0.0",
            created_at=self.simulated_time,
        )
        res = self.adapter.generate(req)

        self.assertEqual(res.status, "needs_clarification")
        self.assertEqual(len(res.sources), 1, "Must cite ONLY the supported source.")
        self.assertEqual(res.sources[0].source_id, "frame-db-01")
        self.assertFalse(res.action_required)
        self.assertIn("partial evidence found", res.response_text.lower())
        self.assertIn("evidence supports", res.response_text.lower())
        self.assertIn("no evidence was found regarding", res.response_text.lower())
        self.assertIn("absence of evidence does not indicate falsehood", res.response_text.lower())

    def test_corrupted_provenance_returns_needs_clarification(self) -> None:
        """When all context items have corrupted or contradictory provenance, no sources are cited."""
        corrupted_item = ContextItem(
            item_id="ctx-corrupted-01",
            context_type=ContextType.SCREEN,
            source="screen",
            content="Audit task is completed.",
            metadata={"source_reference": {"source_id": "frame-A", "source_type": "screen"}, "source_id": "frame-B"},
            timestamp=self.simulated_time,
        )
        req = ReasoningRequest(
            request_id="req-corrupt-01",
            session_id="sess-corrupt",
            user_query="What is the current system status?",
            context_items=[corrupted_item],
            prompt_version="v1.0.0",
            created_at=self.simulated_time,
        )
        res = self.adapter.generate(req)

        self.assertEqual(res.status, "needs_clarification")
        self.assertEqual(len(res.sources), 0)
        self.assertFalse(res.action_required)
        self.assertIn("corrupted or contradictory", res.response_text.lower())


if __name__ == "__main__":
    unittest.main()
