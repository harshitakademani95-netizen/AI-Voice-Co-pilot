"""
Workstream W3: Context & Reasoning (Week 3 - Day 15)
Observation Generator: Source-Linked Timestamped Observations

Author: Amruta A J (Team SDE 3)
Module: src.context.observation_generator
Description:
    Transforms ScreenContext frames and ingested ContextItems into strictly-typed,
    timestamped Observation instances linked to verifiable SourceReferences.

    Safety & Architectural Guarantees:
    1. Mandatory Grounding: Every Observation has a valid, non-fabricated SourceReference.
    2. Timezone-Aware Timestamps: Strictly rejects naive timestamps.
    3. Duplicate Observation Guard: Deterministic fingerprinting prevents processing
       identical frames repeatedly.
    4. Freshness Guard: Filters out frames older than a configured freshness threshold.
    5. Purely Local & Synthetic: Operates 100% offline without external services.
"""

from datetime import datetime, timezone
import hashlib
from typing import Any, Callable, Dict, List, Optional, Set

from src.context.schemas import (
    ContextItem,
    ContextType,
    Observation,
    ScreenContext,
    SourceReference,
)


def compute_frame_fingerprint(
    visible_text: Optional[str],
    active_window_title: Optional[str],
    active_application: Optional[str],
) -> str:
    """
    Compute a deterministic SHA-256 fingerprint from the visible text,
    active window title, and active application name.
    """
    raw = f"{visible_text or ''}::{active_window_title or ''}::{active_application or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ObservationGenerationError(Exception):
    """Base exception for observation generation failures."""
    pass


class StaleObservationError(ObservationGenerationError):
    """Raised when an incoming frame or context item is too old to produce an observation."""
    pass


class DuplicateObservationError(ObservationGenerationError):
    """Raised when an identical observation has already been recorded."""
    pass


class ObservationGenerator:
    """
    Transforms perception inputs (ScreenContext, ContextItem) into verifiable Observations.
    """

    def __init__(
        self,
        clock_fn: Optional[Callable[[], datetime]] = None,
        max_age_seconds: Optional[float] = None,
        reject_duplicates: bool = True,
        consent_verifier: Optional[Callable[[], bool]] = None,
    ):
        """
        Initialize the observation generator.

        Args:
            clock_fn: Optional callable returning timezone-aware current UTC time.
            max_age_seconds: Optional maximum allowable age in seconds for observed inputs.
            reject_duplicates: Whether to drop/reject consecutive or identical observations.
            consent_verifier: Optional callable returning True if consent is currently active.
        """
        self._clock_fn = clock_fn or (lambda: datetime.now(timezone.utc))
        self.max_age_seconds = max_age_seconds
        self.reject_duplicates = reject_duplicates
        self._consent_verifier = consent_verifier
        self._seen_fingerprints: Set[str] = set()
        self._last_fingerprint: Optional[str] = None
        self._observation_count: int = 0
        self._history: List[Observation] = []

    @property
    def observation_count(self) -> int:
        """Total number of observations generated."""
        return self._observation_count

    @property
    def history(self) -> List[Observation]:
        """Return a copy of the observation history."""
        return list(self._history)

    def reset(self) -> None:
        """Clear internal caches and observation history."""
        self._seen_fingerprints.clear()
        self._last_fingerprint = None
        self._observation_count = 0
        self._history.clear()

    def generate_from_screen_frame(
        self,
        frame: ScreenContext,
        observation_id: Optional[str] = None,
        content: Optional[str] = None,
        confidence_score: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Observation:
        """
        Generate a timestamped Observation grounded in a synthetic ScreenContext frame.

        Args:
            frame: Validated synthetic ScreenContext instance.
            observation_id: Optional explicit identifier. Defaults to deterministic counter.
            content: Optional explicit summary. Defaults to formatted window/OCR description.
            confidence_score: Confidence probability [0.0, 1.0].
            metadata: Optional additional metadata dictionary.

        Returns:
            Validated Observation instance with linked SourceReference.
        """
        if not isinstance(frame, ScreenContext):
            raise TypeError(f"Expected ScreenContext, got {type(frame).__name__}")

        # 0. Consent check
        if self._consent_verifier is not None and not self._consent_verifier():
            from src.context.capture_adapter import CapturePermissionError
            raise CapturePermissionError(
                "Consent has been withdrawn or not granted. Observation generation blocked."
            )

        # 1. Timestamp validation & freshness check
        ref_time = self._clock_fn()
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        frame_time = frame.captured_at
        if frame_time.tzinfo is None:
            raise ValueError("Frame captured_at timestamp must be timezone-aware.")

        future_diff = (frame_time - ref_time).total_seconds()
        if future_diff > 1.0:
            raise ValueError(
                f"Frame timestamp is in the future ({future_diff:.2f}s ahead of reference clock)."
            )

        if self.max_age_seconds is not None:
            age = (ref_time - frame_time).total_seconds()
            if age > self.max_age_seconds:
                raise StaleObservationError(
                    f"Frame age ({age:.2f}s) exceeds maximum allowed age ({self.max_age_seconds:.2f}s)."
                )

        # 2. Duplicate detection
        fingerprint = compute_frame_fingerprint(
            frame.visible_text,
            frame.active_window_title,
            frame.active_application,
        )
        if self.reject_duplicates and (
            fingerprint == self._last_fingerprint or fingerprint in self._seen_fingerprints
        ):
            raise DuplicateObservationError(
                f"Duplicate screen state detected for application '{frame.active_application}'."
            )

        # 3. Construct SourceReference
        excerpt = None
        if frame.visible_text:
            cleaned = frame.visible_text.strip()
            excerpt = cleaned[:160] + "..." if len(cleaned) > 160 else cleaned

        source_ref = SourceReference(
            source_id=frame.frame_id,
            source_type="screen",
            reference_location=frame.active_window_title,
            excerpt=excerpt,
            confidence_score=confidence_score,
        )

        # 4. Construct Observation content
        self._observation_count += 1
        obs_id = observation_id or f"obs-{self._observation_count:04d}"

        if content:
            obs_content = content
        else:
            win = frame.active_window_title or "Unknown Window"
            app = frame.active_application or "Unknown App"
            vis = frame.visible_text.strip() if frame.visible_text else "No visible text"
            obs_content = f"Visual state of {app} [{win}]: {vis}"

        obs_metadata = dict(frame.metadata)
        if metadata:
            obs_metadata.update(metadata)
        obs_metadata["fingerprint"] = fingerprint
        obs_metadata["frame_id"] = frame.frame_id

        observation = Observation(
            observation_id=obs_id,
            timestamp=frame.captured_at,
            source=source_ref,
            content=obs_content,
            metadata=obs_metadata,
        )

        # Update bookkeeping
        self._last_fingerprint = fingerprint
        self._seen_fingerprints.add(fingerprint)
        self._history.append(observation)

        return observation

    def generate_from_context_item(
        self,
        item: ContextItem,
        observation_id: Optional[str] = None,
        confidence_score: float = 1.0,
    ) -> Observation:
        """
        Generate a timestamped Observation grounded in a generic ContextItem.
        """
        if not isinstance(item, ContextItem):
            raise TypeError(f"Expected ContextItem, got {type(item).__name__}")

        if self._consent_verifier is not None and not self._consent_verifier():
            from src.context.capture_adapter import CapturePermissionError
            raise CapturePermissionError(
                "Consent has been withdrawn or not granted. Observation generation blocked."
            )

        if item.screen_context is not None:
            return self.generate_from_screen_frame(
                frame=item.screen_context,
                observation_id=observation_id,
                confidence_score=confidence_score,
            )

        self._observation_count += 1
        obs_id = observation_id or f"obs-{self._observation_count:04d}"

        excerpt = item.content.strip()[:160] if item.content else None
        source_ref = SourceReference(
            source_id=item.item_id,
            source_type=item.context_type.value,
            reference_location=item.source,
            excerpt=excerpt,
            confidence_score=confidence_score,
        )

        observation = Observation(
            observation_id=obs_id,
            timestamp=item.timestamp,
            source=source_ref,
            content=f"Observed {item.context_type.value} item from '{item.source}': {item.content[:200]}",
            metadata=dict(item.metadata),
        )
        self._history.append(observation)
        return observation

    def to_context_item(
        self,
        observation: Observation,
        item_id: Optional[str] = None,
    ) -> ContextItem:
        """
        Convert an Observation into an ingested ContextItem ready for
        BoundedContextBuilder budgeting, freshness, and relevance scoring.
        """
        return observation.to_context_item(item_id=item_id)

