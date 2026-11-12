"""
Workstream W3: Context & Reasoning (Week 2 - Day 11)
Unit Tests for Bounded Context Builder

Author: Amruta A J (Team SDE 3)
Module: tests.test_bounded_builder
Description:
    Comprehensive, deterministic unit tests for BoundedContextBuilder covering:
    A. Configuration validation and constraints.
    B. Transparent character-heuristic token estimation.
    C. Keyword relevance scoring and term matching.
    D. Recency ranking, TTL staleness filtering, and tie-breaking.
    E. Budget and item count ceilings.
    F. Safe handling of empty, invalid, and edge-case inputs.
    G. Strict determinism and object reference preservation.
"""

from datetime import datetime, timedelta, timezone
import unittest
from pydantic import ValidationError

from src.context.bounded_builder import BoundedContextBuilder, BoundedContextConfig
from src.context.fixtures import (
    get_synthetic_document_scenario,
    get_synthetic_error_scenario,
    get_synthetic_file_action_scenario,
)
from src.context.schemas import ContextItem, ContextType, DEFAULT_FRAME_TIMESTAMP


class TestBoundedContextBuilder(unittest.TestCase):

    def setUp(self):
        self.builder = BoundedContextBuilder()
        self.ref_time = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)

    # =========================================================================
    # A. Configuration
    # =========================================================================

    def test_default_configuration_values(self):
        """Verify default configuration values match documented specifications."""
        config = BoundedContextConfig()
        self.assertEqual(config.max_items, 50)
        self.assertEqual(config.token_budget, 2000)
        self.assertIsNone(config.max_age_seconds)
        self.assertEqual(config.chars_per_token, 4.0)

    def test_reject_zero_or_negative_token_budgets(self):
        """Reject token_budget <= 0."""
        with self.assertRaises(ValidationError):
            # pyrefly: ignore[bad-argument-type]
            BoundedContextConfig(token_budget=0)
        with self.assertRaises(ValidationError):
            # pyrefly: ignore[bad-argument-type]
            BoundedContextConfig(token_budget=-500)

    def test_reject_max_items_greater_than_50(self):
        """Reject max_items > 50 or <= 0 per ReasoningRequest contract."""
        with self.assertRaises(ValidationError):
            # pyrefly: ignore[bad-argument-type]
            BoundedContextConfig(max_items=51)
        with self.assertRaises(ValidationError):
            # pyrefly: ignore[bad-argument-type]
            BoundedContextConfig(max_items=100)
        with self.assertRaises(ValidationError):
            # pyrefly: ignore[bad-argument-type]
            BoundedContextConfig(max_items=0)

    def test_reject_invalid_chars_per_token(self):
        """Reject chars_per_token <= 0."""
        with self.assertRaises(ValidationError):
            BoundedContextConfig(chars_per_token=0.0)
        with self.assertRaises(ValidationError):
            BoundedContextConfig(chars_per_token=-2.0)

    def test_reject_invalid_max_age_seconds(self):
        """Reject max_age_seconds <= 0."""
        with self.assertRaises(ValidationError):
            BoundedContextConfig(max_age_seconds=0.0)
        with self.assertRaises(ValidationError):
            BoundedContextConfig(max_age_seconds=-10.0)

    # =========================================================================
    # B. Token Estimation
    # =========================================================================

    def test_estimate_tokens_empty_string(self):
        """Empty or None text must estimate to 0 tokens."""
        self.assertEqual(self.builder.estimate_tokens(""), 0)

    def test_estimate_tokens_short_string(self):
        """Short strings (1-3 chars) round up to 1 token."""
        self.assertEqual(self.builder.estimate_tokens("a"), 1)
        self.assertEqual(self.builder.estimate_tokens("hi"), 1)
        self.assertEqual(self.builder.estimate_tokens("cat"), 1)

    def test_estimate_tokens_exact_multiple(self):
        """Strings exactly divisible by chars_per_token."""
        # 16 chars with 4.0 chars/token = 4 tokens
        self.assertEqual(self.builder.estimate_tokens("1234567812345678"), 4)

    def test_estimate_tokens_rounding_up(self):
        """Strings requiring ceil() rounding up."""
        # 17 chars with 4.0 chars/token -> ceil(4.25) = 5 tokens
        self.assertEqual(self.builder.estimate_tokens("12345678123456789"), 5)

    def test_estimate_item_tokens_includes_documented_overhead(self):
        """Item token estimation includes content, source, and 2 markup overhead tokens."""
        item = ContextItem(
            item_id="ctx-ovh",
            context_type=ContextType.CODE,
            source="main.py",
            content="print(1)",
            timestamp=DEFAULT_FRAME_TIMESTAMP,
        )
        content_tokens = self.builder.estimate_tokens("print(1)")
        source_tokens = self.builder.estimate_tokens("main.py")
        expected_total = content_tokens + source_tokens + 2
        self.assertEqual(self.builder.estimate_item_tokens(item), expected_total)

    # =========================================================================
    # C. Keyword Relevance
    # =========================================================================

    def test_keyword_relevance_case_insensitive(self):
        """Relevance scoring matches case-insensitively across upper and lower queries."""
        item = ContextItem(
            item_id="c-case",
            context_type=ContextType.TERMINAL,
            source="term",
            content="ZeroDivisionError occurred in calculation",
            timestamp=DEFAULT_FRAME_TIMESTAMP,
        )
        res_upper = self.builder.build_context("ZERODIVISIONERROR", [item], reference_time=self.ref_time)
        res_lower = self.builder.build_context("zerodivisionerror", [item], reference_time=self.ref_time)
        self.assertEqual(len(res_upper), 1)
        self.assertEqual(len(res_lower), 1)
        self.assertEqual(res_upper[0].item_id, res_lower[0].item_id)

    def test_keyword_relevance_duplicate_query_keywords(self):
        """Duplicate query keywords are deduped by extract_keywords."""
        keywords = self.builder.extract_keywords("error error ERROR error")
        self.assertEqual(keywords, ["error"])

    def test_keyword_relevance_multiple_matching_keywords(self):
        """Multiple unique matching keywords yield higher scores than single matches."""
        item_multi = ContextItem(
            item_id="c-multi",
            context_type=ContextType.CODE,
            source="calc.py",
            content="def calculate_ratio(num, den): return num / den",
            timestamp=DEFAULT_FRAME_TIMESTAMP,
        )
        score_one = self.builder.score_relevance(item_multi, ["calculate"])
        score_two = self.builder.score_relevance(item_multi, ["calculate", "ratio"])
        self.assertGreater(score_two, score_one)

    def test_keyword_relevance_source_matches(self):
        """Keywords matching item.source receive a +2.0 weight bonus."""
        item_source = ContextItem(
            item_id="c-src",
            context_type=ContextType.CODE,
            source="calculator_module.py",
            content="generic logic without keyword",
            timestamp=DEFAULT_FRAME_TIMESTAMP,
        )
        item_content = ContextItem(
            item_id="c-cnt",
            context_type=ContextType.CODE,
            source="other.py",
            content="calculator logic here",
            timestamp=DEFAULT_FRAME_TIMESTAMP,
        )
        score_source = self.builder.score_relevance(item_source, ["calculator"])
        score_content = self.builder.score_relevance(item_content, ["calculator"])
        # Source match gives 2.0; content single hit gives 1.0
        self.assertGreater(score_source, score_content)
        self.assertEqual(score_source, 2.0)

    def test_keyword_relevance_empty_and_punctuation_only_query(self):
        """Empty query or query with only punctuation scores 0.0 for all items."""
        item = ContextItem(
            item_id="c-punc",
            context_type=ContextType.DOCUMENT,
            source="doc.txt",
            content="Some informative text",
            timestamp=DEFAULT_FRAME_TIMESTAMP,
        )
        self.assertEqual(self.builder.score_relevance(item, []), 0.0)
        keywords_punc = self.builder.extract_keywords("!@#$%^&*()_+=-{}[]:;'<>,.?/")
        self.assertEqual(keywords_punc, [])
        self.assertEqual(self.builder.score_relevance(item, keywords_punc), 0.0)

    def test_keyword_relevance_partial_word_not_matched(self):
        """
        Verify that a query keyword does NOT match as a substring inside a larger word.
        'cat' must not match 'concatenate'.
        """
        item = ContextItem(
            item_id="c-sub",
            context_type=ContextType.DOCUMENT,
            source="doc.txt",
            content="concatenate two strings together",
            timestamp=DEFAULT_FRAME_TIMESTAMP,
        )
        score = self.builder.score_relevance(item, ["cat"])
        self.assertEqual(score, 0.0)

    def test_keyword_relevance_standalone_word_matched(self):
        """Verify that 'cat' matches the standalone word 'cat'."""
        item = ContextItem(
            item_id="c-word",
            context_type=ContextType.DOCUMENT,
            source="doc.txt",
            content="the quick cat jumped over the fence",
            timestamp=DEFAULT_FRAME_TIMESTAMP,
        )
        score = self.builder.score_relevance(item, ["cat"])
        self.assertEqual(score, 1.0)

    def test_keyword_relevance_case_insensitive_whole_word_matching(self):
        """Verify case-insensitive whole-word matching ('CAT' matches 'cat' and vice-versa)."""
        item = ContextItem(
            item_id="c-case-word",
            context_type=ContextType.DOCUMENT,
            source="doc.txt",
            content="The Cat is sleeping",
            timestamp=DEFAULT_FRAME_TIMESTAMP,
        )
        self.assertEqual(self.builder.score_relevance(item, ["cat"]), 1.0)
        self.assertEqual(self.builder.score_relevance(item, ["CAT"]), 1.0)
        self.assertEqual(self.builder.score_relevance(item, ["cAt"]), 1.0)

    # =========================================================================
    # D. Recency and Stale Filtering
    # =========================================================================

    def test_recency_prioritizes_newer_on_tied_relevance(self):
        """When relevance scores are identical, newer timestamps are prioritized."""
        item_older = ContextItem(
            item_id="c-old",
            context_type=ContextType.CODE,
            source="a.py",
            content="common text",
            timestamp=self.ref_time - timedelta(minutes=10),
        )
        item_newer = ContextItem(
            item_id="c-new",
            context_type=ContextType.CODE,
            source="b.py",
            content="common text",
            timestamp=self.ref_time - timedelta(minutes=1),
        )
        result = self.builder.build_context("common", [item_older, item_newer], reference_time=self.ref_time)
        self.assertEqual([i.item_id for i in result], ["c-new", "c-old"])

    def test_stale_filtering_exact_ttl_boundary(self):
        """Items exactly at the TTL boundary (age == max_age_seconds) are preserved."""
        builder_ttl = BoundedContextBuilder(BoundedContextConfig(max_age_seconds=60.0))
        item_boundary = ContextItem(
            item_id="c-boundary",
            context_type=ContextType.CODE,
            source="boundary.py",
            content="boundary task",
            timestamp=self.ref_time - timedelta(seconds=60),
        )
        result = builder_ttl.build_context("task", [item_boundary], reference_time=self.ref_time)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].item_id, "c-boundary")

    def test_stale_filtering_older_than_ttl_dropped(self):
        """Items strictly older than max_age_seconds are filtered out."""
        builder_ttl = BoundedContextBuilder(BoundedContextConfig(max_age_seconds=60.0))
        item_fresh = ContextItem(
            item_id="c-fresh",
            context_type=ContextType.CODE,
            source="fresh.py",
            content="fresh task",
            timestamp=self.ref_time - timedelta(seconds=59),
        )
        item_stale = ContextItem(
            item_id="c-stale",
            context_type=ContextType.CODE,
            source="stale.py",
            content="stale task",
            timestamp=self.ref_time - timedelta(seconds=61),
        )
        result = builder_ttl.build_context("task", [item_fresh, item_stale], reference_time=self.ref_time)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].item_id, "c-fresh")

    def test_stale_filtering_future_timestamps(self):
        """Future timestamps (negative age due to minor clock offset) are not dropped."""
        builder_ttl = BoundedContextBuilder(BoundedContextConfig(max_age_seconds=60.0))
        item_future = ContextItem(
            item_id="c-future",
            context_type=ContextType.CODE,
            source="future.py",
            content="future task",
            timestamp=self.ref_time + timedelta(seconds=10),
        )
        result = builder_ttl.build_context("task", [item_future], reference_time=self.ref_time)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].item_id, "c-future")

    def test_deterministic_item_id_tie_breaking(self):
        """When relevance and timestamps are equal, item_id tie-breaks in ascending alphanumeric order."""
        item_z = ContextItem(
            item_id="c-zzz",
            context_type=ContextType.DOCUMENT,
            source="same.txt",
            content="same content",
            timestamp=self.ref_time,
        )
        item_a = ContextItem(
            item_id="c-aaa",
            context_type=ContextType.DOCUMENT,
            source="same.txt",
            content="same content",
            timestamp=self.ref_time,
        )
        item_m = ContextItem(
            item_id="c-mmm",
            context_type=ContextType.DOCUMENT,
            source="same.txt",
            content="same content",
            timestamp=self.ref_time,
        )
        result = self.builder.build_context("content", [item_z, item_a, item_m], reference_time=self.ref_time)
        self.assertEqual([i.item_id for i in result], ["c-aaa", "c-mmm", "c-zzz"])

    # =========================================================================
    # E. Budget and Item Limits
    # =========================================================================

    def test_never_exceeds_token_budget(self):
        """Total estimated tokens of admitted items never exceeds configured token_budget."""
        builder_budget = BoundedContextBuilder(BoundedContextConfig(token_budget=100))
        items = [
            ContextItem(
                item_id=f"c-{i}",
                context_type=ContextType.CODE,
                source=f"file{i}.py",
                content="var = 1234567890",
                timestamp=self.ref_time,
            )
            for i in range(30)
        ]
        result = builder_budget.build_context("var", items, reference_time=self.ref_time)
        total_tokens = sum(builder_budget.estimate_item_tokens(it) for it in result)
        self.assertLessEqual(total_tokens, 100)

    def test_never_exceeds_50_items(self):
        """Enforces a hard maximum limit of 50 items even if budget is large."""
        builder_large = BoundedContextBuilder(BoundedContextConfig(max_items=50, token_budget=50000))
        items = [
            ContextItem(
                item_id=f"item-{i:03d}",
                context_type=ContextType.CODE,
                source="test.py",
                content="x = 1",
                timestamp=self.ref_time,
            )
            for i in range(75)
        ]
        result = builder_large.build_context("test", items, reference_time=self.ref_time)
        self.assertEqual(len(result), 50)

    def test_skip_oversized_item_admits_later_smaller_item(self):
        """Greedy bounding skips a high-priority oversized item and admits subsequent smaller items."""
        builder_fit = BoundedContextBuilder(BoundedContextConfig(token_budget=30))
        item_large = ContextItem(
            item_id="c-big",
            context_type=ContextType.CODE,
            source="big.py",
            content="high priority keyword " * 20,  # ~105 tokens
            timestamp=self.ref_time,
        )
        item_small = ContextItem(
            item_id="c-small",
            context_type=ContextType.CODE,
            source="small.py",
            content="keyword fit",  # ~5 tokens
            timestamp=self.ref_time,
        )
        result = builder_fit.build_context("keyword", [item_large, item_small], reference_time=self.ref_time)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].item_id, "c-small")

    def test_item_cost_equals_remaining_budget(self):
        """An item whose cost exactly matches the remaining budget is admitted."""
        # Content "1234" (1 token) + source "s" (1 token) + overhead (2) = 4 tokens
        item = ContextItem(
            item_id="c-exact",
            context_type=ContextType.CODE,
            source="s",
            content="1234",
            timestamp=self.ref_time,
        )
        exact_tokens = self.builder.estimate_item_tokens(item)
        builder_exact = BoundedContextBuilder(BoundedContextConfig(token_budget=exact_tokens))
        result = builder_exact.build_context("test", [item], reference_time=self.ref_time)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].item_id, "c-exact")

    def test_single_item_larger_than_entire_budget(self):
        """When candidate item exceeds the entire budget on its own, it is skipped."""
        item = ContextItem(
            item_id="c-oversized",
            context_type=ContextType.DOCUMENT,
            source="large_report.pdf",
            content="massive content text " * 100,
            timestamp=self.ref_time,
        )
        builder_tiny = BoundedContextBuilder(BoundedContextConfig(token_budget=10))
        result = builder_tiny.build_context("report", [item], reference_time=self.ref_time)
        self.assertEqual(result, [])

    # =========================================================================
    # F. Input Handling
    # =========================================================================

    def test_empty_query_prioritizes_by_recency(self):
        """Empty query assigns 0.0 relevance and orders all valid candidates by recency."""
        item_old = ContextItem(
            item_id="c-1",
            context_type=ContextType.CODE,
            source="a.py",
            content="first",
            timestamp=self.ref_time - timedelta(hours=1),
        )
        item_new = ContextItem(
            item_id="c-2",
            context_type=ContextType.CODE,
            source="b.py",
            content="second",
            timestamp=self.ref_time,
        )
        result_empty_str = self.builder.build_context("", [item_old, item_new], reference_time=self.ref_time)
        result_none = self.builder.build_context(None, [item_old, item_new], reference_time=self.ref_time)
        self.assertEqual([i.item_id for i in result_empty_str], ["c-2", "c-1"])
        self.assertEqual([i.item_id for i in result_none], ["c-2", "c-1"])

    def test_empty_item_collection(self):
        """Empty collection or None returns empty list."""
        self.assertEqual(self.builder.build_context("query", []), [])
        self.assertEqual(self.builder.build_context("query", None), [])

    def test_item_with_empty_content(self):
        """Items with empty string content are processed without errors."""
        item_empty = ContextItem(
            item_id="c-empty",
            context_type=ContextType.CODE,
            source="empty.py",
            content="",
            timestamp=self.ref_time,
        )
        result = self.builder.build_context("empty", [item_empty], reference_time=self.ref_time)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].item_id, "c-empty")

    def test_invalid_item_types_raise_type_error(self):
        """Passing non-ContextItem elements raises TypeError."""
        with self.assertRaises(TypeError):
            # pyrefly: ignore[bad-argument-type]
            self.builder.build_context("query", ["not_a_context_item"])
        with self.assertRaises(TypeError):
            # pyrefly: ignore[bad-argument-type]
            self.builder.build_context("query", [12345])

    def test_timezone_aware_and_naive_reference_time(self):
        """Naive reference_time is automatically localized to UTC without errors."""
        naive_time = datetime(2026, 3, 1, 12, 0, 0)
        item = ContextItem(
            item_id="c-tz",
            context_type=ContextType.DOCUMENT,
            source="doc.txt",
            content="content",
            timestamp=self.ref_time,
        )
        result = self.builder.build_context("content", [item], reference_time=naive_time)
        self.assertEqual(len(result), 1)

    # =========================================================================
    # G. Determinism and Preservation
    # =========================================================================

    def test_deterministic_selection_and_ordering(self):
        """Running build_context twice on identical inputs yields strictly identical outputs."""
        scenario_items = (
            get_synthetic_error_scenario()
            + get_synthetic_document_scenario()
            + get_synthetic_file_action_scenario()
        )
        run_1 = self.builder.build_context("error distributed report", scenario_items, reference_time=DEFAULT_FRAME_TIMESTAMP)
        run_2 = self.builder.build_context("error distributed report", scenario_items, reference_time=DEFAULT_FRAME_TIMESTAMP)

        self.assertEqual([i.model_dump() for i in run_1], [i.model_dump() for i in run_2])

    def test_returned_objects_are_original_references(self):
        """Returned list contains original ContextItem instances, not deep-cloned mutations."""
        item = ContextItem(
            item_id="c-ref",
            context_type=ContextType.CODE,
            source="ref.py",
            content="ref content",
            timestamp=self.ref_time,
        )
        result = self.builder.build_context("ref", [item], reference_time=self.ref_time)
        self.assertEqual(len(result), 1)
        self.assertIs(result[0], item)

    def test_original_items_remain_unmutated(self):
        """Original item content, timestamp, and metadata are not mutated by builder."""
        original_metadata = {"tag": "immutable", "count": 42}
        item = ContextItem(
            item_id="c-imm",
            context_type=ContextType.DOCUMENT,
            source="imm.txt",
            content="Original unmutated text.",
            timestamp=self.ref_time,
            metadata=dict(original_metadata),
        )
        before_dump = item.model_dump()
        self.builder.build_context("Original text", [item], reference_time=self.ref_time)
        after_dump = item.model_dump()
        self.assertEqual(before_dump, after_dump)


class TestBuildContextWithReport(unittest.TestCase):
    """
    Tests for build_context_with_report() covering each exclusion reason and
    min_relevance threshold, plus backward-compatibility with build_context().
    """

    def setUp(self):
        self.ref_time = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)

    def _make_item(self, item_id: str, content: str, age_seconds: float = 0) -> ContextItem:
        return ContextItem(
            item_id=item_id,
            context_type=ContextType.DOCUMENT,
            source=f"src_{item_id}.txt",
            content=content,
            timestamp=self.ref_time - timedelta(seconds=age_seconds),
        )

    # ------------------------------------------------------------------
    # Exclusion reason: "stale"
    # ------------------------------------------------------------------

    def test_report_reason_stale(self):
        """Items older than max_age_seconds appear in report with reason='stale'."""
        fresh = self._make_item("fresh", "hello world", age_seconds=10)
        stale = self._make_item("stale", "hello world", age_seconds=7200)
        config = BoundedContextConfig(max_age_seconds=3600.0)
        builder = BoundedContextBuilder(config=config)
        items, report = builder.build_context_with_report(
            "hello",
            [fresh, stale],
            reference_time=self.ref_time,
        )
        self.assertIn(fresh, items)  # fresh should be included
        self.assertNotIn(stale, items)  # stale should be excluded
        stale_entries = [r for r in report if r["item_id"] == "stale"]
        self.assertEqual(len(stale_entries), 1)
        self.assertEqual(stale_entries[0]["reason"], "stale")
        # Fresh item is NOT in the report
        fresh_entries = [r for r in report if r["item_id"] == "fresh"]
        self.assertEqual(len(fresh_entries), 0)

    # ------------------------------------------------------------------
    # Exclusion reason: "below_min_relevance"
    # ------------------------------------------------------------------

    def test_report_reason_below_min_relevance(self):
        """Items scoring below min_relevance appear in report with reason='below_min_relevance'."""
        relevant = self._make_item("relevant", "python error traceback")
        irrelevant = self._make_item("irrelevant", "unrelated content abc xyz")
        config = BoundedContextConfig(min_relevance=1.0)
        builder = BoundedContextBuilder(config=config)
        items, report = builder.build_context_with_report(
            "python error",
            [relevant, irrelevant],
            reference_time=self.ref_time,
        )
        self.assertIn(relevant, items)
        self.assertNotIn(irrelevant, items)
        low_entries = [r for r in report if r["item_id"] == "irrelevant"]
        self.assertEqual(len(low_entries), 1)
        self.assertEqual(low_entries[0]["reason"], "below_min_relevance")

    def test_min_relevance_zero_includes_all_non_stale(self):
        """min_relevance=0.0 (default) keeps current behaviour; zero-score items still included."""
        item_a = self._make_item("a", "completely unrelated content zzz")
        item_b = self._make_item("b", "also unrelated yyy")
        config = BoundedContextConfig(min_relevance=0.0)
        builder = BoundedContextBuilder(config=config)
        items, report = builder.build_context_with_report(
            "python error",
            [item_a, item_b],
            reference_time=self.ref_time,
        )
        # Both should be included; no below_min_relevance entries
        self.assertEqual(len(items), 2)
        below_entries = [r for r in report if r["reason"] == "below_min_relevance"]
        self.assertEqual(len(below_entries), 0)

    def test_min_relevance_reproduces_build_context_output(self):
        """build_context_with_report(min_relevance=0.0)[0] == build_context() identically."""
        from src.context.fixtures import get_synthetic_error_scenario
        items_pool = get_synthetic_error_scenario()
        config = BoundedContextConfig(min_relevance=0.0, max_items=5, token_budget=1000)
        builder = BoundedContextBuilder(config=config)
        query = "ZeroDivisionError calculator"
        classic = builder.build_context(query, items_pool, reference_time=self.ref_time)
        report_items, _ = builder.build_context_with_report(query, items_pool, reference_time=self.ref_time)
        self.assertEqual([i.item_id for i in classic], [i.item_id for i in report_items])

    # ------------------------------------------------------------------
    # Exclusion reason: "over_token_budget"
    # ------------------------------------------------------------------

    def test_report_reason_over_token_budget(self):
        """Items that push accumulated tokens over budget appear with reason='over_token_budget'."""
        small = self._make_item("small", "hi " * 10)   # ~8 tokens
        big = self._make_item("big", "x " * 300)        # ~160 tokens
        config = BoundedContextConfig(token_budget=20, min_relevance=0.0)
        builder = BoundedContextBuilder(config=config)
        items, report = builder.build_context_with_report(
            "",
            [small, big],
            reference_time=self.ref_time,
        )
        budget_entries = [r for r in report if r["reason"] == "over_token_budget"]
        self.assertGreater(len(budget_entries), 0)
        self.assertTrue(any(r["item_id"] == "big" for r in budget_entries))

    # ------------------------------------------------------------------
    # Exclusion reason: "max_items_reached"
    # ------------------------------------------------------------------

    def test_report_reason_max_items_reached(self):
        """Items beyond max_items appear in report with reason='max_items_reached'."""
        items_pool = [
            self._make_item(f"item-{i}", f"content number {i} detail")
            for i in range(5)
        ]
        config = BoundedContextConfig(max_items=2, token_budget=5000)
        builder = BoundedContextBuilder(config=config)
        selected, report = builder.build_context_with_report(
            "content",
            items_pool,
            reference_time=self.ref_time,
        )
        self.assertEqual(len(selected), 2)
        maxed_entries = [r for r in report if r["reason"] == "max_items_reached"]
        self.assertEqual(len(maxed_entries), 3)  # 5 items - 2 selected = 3 excluded

    # ------------------------------------------------------------------
    # Empty inputs
    # ------------------------------------------------------------------

    def test_report_empty_input_returns_empty(self):
        """Empty/None inputs return ([], []) without error."""
        builder = BoundedContextBuilder()
        items, report = builder.build_context_with_report("query", [], reference_time=self.ref_time)
        self.assertEqual(items, [])
        self.assertEqual(report, [])

        items2, report2 = builder.build_context_with_report("query", None, reference_time=self.ref_time)
        self.assertEqual(items2, [])
        self.assertEqual(report2, [])

    # ------------------------------------------------------------------
    # min_relevance config validation
    # ------------------------------------------------------------------

    def test_min_relevance_negative_rejected(self):
        """min_relevance < 0.0 is rejected by Pydantic validation."""
        with self.assertRaises(Exception):
            BoundedContextConfig(min_relevance=-0.5)

    def test_min_relevance_default_is_zero(self):
        """Default min_relevance is 0.0."""
        config = BoundedContextConfig()
        self.assertEqual(config.min_relevance, 0.0)


if __name__ == "__main__":
    unittest.main()
