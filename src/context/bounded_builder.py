"""
Workstream W3: Context & Reasoning (Week 2 - Day 10)
Bounded Context Builder

Author: Amruta A J (Team SDE 3)
Module: src.context.bounded_builder
Description:
    Provides deterministic context window budgeting, scoring, filtering, and bounding.
    Given candidate ContextItems and a user query, selects a bounded subset prioritizing:
    1. Freshness (drops stale items exceeding max_age_seconds relative to reference_time).
    2. Relevance (deterministic keyword frequency & location scoring).
    3. Recency (newer items prioritized on tied relevance).
    4. Deterministic Tie-Breaking (stable alphanumeric item_id ordering).
    5. Hard Limits: Never exceeds configured token_budget or 50 items (ReasoningRequest ceiling).

    Safety & Architectural Invariants:
    - 100% deterministic and offline; zero external network or tokenizer dependencies.
    - Transparent token estimation heuristic (approximately 1 token per 4 characters).
    - Preserves existing ContextItem instances without mutating content or timestamps.
    - Reuses existing ContextItem and ReasoningRequest contracts from src.context.schemas.
"""

import math
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple
from pydantic import BaseModel, ConfigDict, Field

from src.context.schemas import ContextItem


class BoundedContextConfig(BaseModel):
    """
    Configuration options for the BoundedContextBuilder.
    """
    model_config = ConfigDict(extra="forbid")

    max_items: int = Field(
        50,
        gt=0,
        le=50,
        description="Maximum number of context items allowed (enforces ReasoningRequest max 50 limit)."
    )
    token_budget: int = Field(
        2000,
        gt=0,
        description="Approximate token budget ceiling for selected context items."
    )
    max_age_seconds: Optional[float] = Field(
        None,
        gt=0.0,
        description="Maximum age in seconds relative to reference_time. Items older than this are dropped as stale."
    )
    chars_per_token: float = Field(
        4.0,
        gt=0.0,
        description="Deterministic character-to-token heuristic ratio (default: 4.0 chars/token)."
    )
    min_relevance: float = Field(
        0.0,
        ge=0.0,
        description=(
            "Minimum relevance score threshold. Items scoring strictly below this value are excluded. "
            "Default 0.0 preserves current behaviour (no relevance filtering)."
        )
    )


class BoundedContextBuilder:
    """
    Selects, scores, filters, and bounds ContextItem collections for downstream reasoning.
    """

    def __init__(
        self,
        config: Optional[BoundedContextConfig] = None,
        clock_fn: Optional[Callable[[], datetime]] = None,
    ):
        """
        Initialize the bounded context builder.

        Args:
            config: Optional BoundedContextConfig. Defaults to baseline configuration.
            clock_fn: Optional callable returning a timezone-aware datetime for deterministic freshness calculation.
        """
        self.config = config or BoundedContextConfig()
        self._clock_fn: Callable[[], datetime] = clock_fn or (lambda: datetime.now(timezone.utc))

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count using a transparent, deterministic character heuristic.
        Formula: ceil(len(text) / chars_per_token).
        
        Args:
            text: Input string.
            
        Returns:
            Non-negative integer token estimate.
        """
        if not text:
            return 0
        return max(1, math.ceil(len(text) / self.config.chars_per_token))

    def estimate_item_tokens(self, item: ContextItem) -> int:
        """
        Estimate the total token footprint of a ContextItem.
        Accounts for content text and structural source overhead.
        """
        content_tokens = self.estimate_tokens(item.content)
        source_tokens = self.estimate_tokens(item.source)
        # 2 tokens overhead for XML boundary markup
        return content_tokens + source_tokens + 2

    @staticmethod
    def extract_keywords(query: str) -> List[str]:
        """
        Extract unique lowercase alphanumeric keywords of length >= 2 from query.
        """
        if not query or not isinstance(query, str):
            return []
        tokens = re.findall(r"\b[A-Za-z0-9_]{2,}\b", query.lower())
        # Preserve order while deduping
        seen: Set[str] = set()
        unique_tokens: List[str] = []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                unique_tokens.append(t)
        return unique_tokens

    def score_relevance(self, item: ContextItem, keywords: Sequence[str]) -> float:
        """
        Compute deterministic keyword-based relevance score.
        
        Scoring Policy:
        - 0.0 if no keywords provided.
        - +1.0 for each unique query keyword present in item.content.
        - +0.1 for each additional occurrence of a keyword in content (capped at +1.0 per keyword).
        - +2.0 for each keyword present in item.source (e.g. matching filename or window title).
        
        Returns:
            Float relevance score rounded to 4 decimal places.
        """
        if not keywords:
            return 0.0

        score = 0.0
        content_lower = item.content.lower()
        source_lower = item.source.lower()

        for kw in keywords:
            kw_lower = kw.lower()
            pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(kw_lower) + r"(?![A-Za-z0-9])")
            content_matches = len(pattern.findall(content_lower))
            if content_matches > 0:
                # Primary hit + frequency weight capped at 1.0
                score += 1.0 + min((content_matches - 1) * 0.1, 1.0)

            if pattern.search(source_lower):
                score += 2.0

        return round(score, 4)

    def filter_stale(
        self,
        items: Sequence[ContextItem],
        reference_time: datetime,
    ) -> List[ContextItem]:
        """
        Filter out items whose timestamp is older than max_age_seconds relative to reference_time.
        If max_age_seconds is None, returns all valid items without time filtering.
        """
        if self.config.max_age_seconds is None:
            return list(items)

        fresh_items: List[ContextItem] = []
        for item in items:
            age = (reference_time - item.timestamp).total_seconds()
            if age <= self.config.max_age_seconds:
                fresh_items.append(item)

        return fresh_items

    def _resolve_ref_time(self, reference_time: Optional[datetime]) -> datetime:
        """Resolve and normalize reference_time to a timezone-aware datetime."""
        if reference_time is not None:
            if not isinstance(reference_time, datetime):
                raise TypeError(
                    f"reference_time must be a datetime instance or None, got {type(reference_time).__name__}"
                )
            return reference_time if reference_time.tzinfo is not None else reference_time.replace(tzinfo=timezone.utc)
        raw_ref = self._clock_fn()
        return raw_ref if raw_ref.tzinfo is not None else raw_ref.replace(tzinfo=timezone.utc)

    def _validate_items(self, context_items: Sequence[ContextItem]) -> None:
        """Raise TypeError if any element is not a ContextItem instance."""
        for idx, item in enumerate(context_items):
            if not isinstance(item, ContextItem):
                raise TypeError(
                    f"Invalid item at index {idx}: expected ContextItem, got {type(item).__name__}"
                )

    def build_context(
        self,
        user_query: Optional[str],
        context_items: Optional[Sequence[ContextItem]],
        reference_time: Optional[datetime] = None,
    ) -> List[ContextItem]:
        """
        Select and return a bounded, prioritized subset of context items.

        Pipeline:
        1. Input Validation: Safely handles None, empty collections, and validates types.
        2. Staleness Filtering: Drops items older than config.max_age_seconds.
        3. Relevance Scoring: Deterministic keyword frequency and source pointer scoring.
        4. Prioritization & Sorting:
           - Primary: Relevance score (descending)
           - Secondary: Recency / item.timestamp epoch (descending)
           - Tertiary: item.item_id (ascending alphanumeric tie-breaker)
        5. Budget & Count Bounding:
           Greedily admits items under both token_budget and max_items (<= 50).

        Args:
            user_query: User spoken or typed query.
            context_items: Collection of candidate ContextItems.
            reference_time: Optional timezone-aware reference datetime (defaults to UTC now).

        Returns:
            Bounded List[ContextItem] ready for ReasoningRequest.
        """
        items, _ = self.build_context_with_report(
            user_query=user_query,
            context_items=context_items,
            reference_time=reference_time,
        )
        return items

    def build_context_with_report(
        self,
        user_query: Optional[str],
        context_items: Optional[Sequence[ContextItem]],
        reference_time: Optional[datetime] = None,
    ) -> Tuple[List[ContextItem], List[Dict[str, str]]]:
        """
        Select a bounded subset of context items and return a diagnostics report.

        Returns:
            (selected_items, report) where report is a list of dicts describing each
            excluded item with keys:
              - "item_id": the excluded item's ID
              - "reason": one of "stale" | "below_min_relevance" | "over_token_budget" |
                          "max_items_reached"
        """
        if not context_items:
            return [], []

        cleaned_query = (user_query or "").strip()
        ref_time = self._resolve_ref_time(reference_time)
        self._validate_items(context_items)

        report: List[Dict[str, str]] = []

        # 2. Staleness Filtering
        active_candidates: List[ContextItem] = []
        for item in context_items:
            if self.config.max_age_seconds is not None:
                age = (ref_time - item.timestamp).total_seconds()
                if age > self.config.max_age_seconds:
                    report.append({"item_id": item.item_id, "reason": "stale"})
                    continue
            active_candidates.append(item)

        if not active_candidates:
            return [], report

        # 3. Relevance Scoring & min_relevance Filtering
        keywords = self.extract_keywords(cleaned_query)
        scored_candidates = []
        for item in active_candidates:
            rel_score = self.score_relevance(item, keywords)
            if self.config.min_relevance > 0.0 and rel_score < self.config.min_relevance:
                report.append({"item_id": item.item_id, "reason": "below_min_relevance"})
                continue
            ts_epoch = item.timestamp.timestamp()
            scored_candidates.append((rel_score, ts_epoch, item.item_id, item))

        # Stable, deterministic multi-criteria sort
        scored_candidates.sort(key=lambda entry: (-entry[0], -entry[1], entry[2]))

        # 4. Budget & Count Bounding
        selected: List[ContextItem] = []
        accumulated_tokens = 0
        limit_items = min(self.config.max_items, 50)

        for _, _, _, item in scored_candidates:
            if len(selected) >= limit_items:
                report.append({"item_id": item.item_id, "reason": "max_items_reached"})
                continue

            item_tokens = self.estimate_item_tokens(item)
            if accumulated_tokens + item_tokens <= self.config.token_budget:
                selected.append(item)
                accumulated_tokens += item_tokens
            else:
                if not selected and item_tokens > self.config.token_budget:
                    # Single item exceeds entire budget — skip silently (never include)
                    report.append({"item_id": item.item_id, "reason": "over_token_budget"})
                    continue
                report.append({"item_id": item.item_id, "reason": "over_token_budget"})

        return selected, report

