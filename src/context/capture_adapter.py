"""
Workstream W3: Context & Reasoning (Week 2 - Day 8)
Opt-In Capture Adapter

Author: Amruta A J (Team SDE 3)
Module: src.context.capture_adapter
Description:
    Provides a safety-gated, opt-in screen capture adapter interface.

    Safety & Architectural Invariants:
    1. Disabled by Default: Capture permission is disabled on initialization.
    2. Explicit User Consent: Requires an explicit opt_in() invocation.
    3. Sampling Limits: Enforces max_fps rate-limiting to prevent runaway polling.
    4. Resolution Limits: Enforces maximum width and height bounds.
    5. Purely Synthetic: Generates 100% fictional synthetic ScreenContext frames
       via create_synthetic_screen_frame(). Real hardware capture is never engaged
       in this project. capture_enabled=False means real OS screen capture is never
       engaged in this project; is_opted_in tracks user consent.
    6. Contract Decoupling: Adapter consent state (is_opted_in) is decoupled from
       ScreenContext.capture_enabled, which remains False at all times as a safety
       marker required by the ScreenContext schema.
"""

import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from src.context.fixtures import create_synthetic_screen_frame
from src.context.schemas import Observation, ScreenContext
from src.context.observation_generator import (
    ObservationGenerator,
    compute_frame_fingerprint,
)


class CapturePermissionError(RuntimeError):
    """Raised when screen capture is attempted without explicit user opt-in."""
    pass


class SamplingLimitError(RuntimeError):
    """Raised when frame capture exceeds the configured max_fps sampling rate."""
    pass


class ResolutionLimitError(ValueError):
    """Raised when requested frame dimensions exceed maximum configured boundaries."""
    pass


class TextLimitError(ValueError):
    """Raised when requested visible text length exceeds maximum configured boundaries."""
    pass


class StaleFrameError(ValueError):
    """Raised when frame timestamp exceeds the configured freshness window."""
    pass


class FutureTimestampError(ValueError):
    """Raised when frame timestamp is in the future relative to the reference clock."""
    pass


class DuplicateFrameError(ValueError):
    """Raised when consecutive or buffered frames have identical visual/text state."""
    pass


class CaptureConfig(BaseModel):
    """
    Configuration for OptInCaptureAdapter sampling and dimension boundaries.
    """
    model_config = ConfigDict(extra="forbid")

    enabled_by_default: bool = Field(
        False,
        description="Initial permission state. Must be False by default for safety."
    )
    max_fps: float = Field(
        2.0,
        gt=0.0,
        le=30.0,
        description="Maximum sampling rate allowed in frames per second (e.g. 2.0 = at most 1 frame per 0.5s)."
    )
    max_width: int = Field(
        1920,
        gt=0,
        description="Maximum allowable screen width in pixels."
    )
    max_height: int = Field(
        1080,
        gt=0,
        description="Maximum allowable screen height in pixels."
    )
    max_text_length: int = Field(
        100_000,
        gt=0,
        description="Maximum allowable visible text length in characters."
    )
    clamp_dimensions: bool = Field(
        False,
        description="If True, dimensions exceeding max bounds are automatically clamped rather than raising an error."
    )
    max_frame_age_seconds: Optional[float] = Field(
        None,
        gt=0.0,
        description="Maximum allowable frame age in seconds. Frames older than this are rejected as stale."
    )
    reject_duplicates: bool = Field(
        False,
        description="If True, consecutive frames with identical visual content are rejected as duplicates."
    )
    future_tolerance_seconds: float = Field(
        1.0,
        ge=0.0,
        description="Permissible clock skew tolerance for future timestamps in seconds."
    )


class OptInCaptureAdapter:
    """
    Safety-governed adapter managing synthetic visual context acquisition.
    
    Guarantees:
    - Never accesses OS screen hardware or external graphics APIs.
    - Yields validated, schema-compliant synthetic ScreenContext instances.
    - Protects user privacy with default-off opt-in gating and rate limiting.
    """

    def __init__(
        self,
        config: Optional[CaptureConfig] = None,
        clock_fn: Optional[Callable[[], float]] = None,
        datetime_clock_fn: Optional[Callable[[], datetime]] = None,
    ):
        """
        Initialize the capture adapter with safe defaults.
        
        Args:
            config: Optional CaptureConfig instance. Defaults to safe baseline.
            clock_fn: Optional monotonic clock function for deterministic rate-limit testing.
            datetime_clock_fn: Optional callable returning a timezone-aware UTC datetime for freshness testing.
        """
        self.config = config or CaptureConfig()
        self._is_opted_in: bool = self.config.enabled_by_default
        self._clock_fn: Callable[[], float] = clock_fn or time.monotonic
        self._datetime_clock_fn: Callable[[], datetime] = (
            datetime_clock_fn or (lambda: datetime.now(timezone.utc))
        )
        self._last_capture_time: Optional[float] = None
        self._capture_count: int = 0
        self._last_frame_fingerprint: Optional[str] = None
        self._seen_frame_fingerprints: set[str] = set()
        self._pending_frames: List[ScreenContext] = []
        self._pending_observations: List[Observation] = []
        self._buffered_context: List[Any] = []
        self._observation_generator = ObservationGenerator(
            clock_fn=self._datetime_clock_fn,
            max_age_seconds=self.config.max_frame_age_seconds,
            reject_duplicates=self.config.reject_duplicates,
            consent_verifier=lambda: self._is_opted_in,
        )

    @property
    def is_opted_in(self) -> bool:
        """Return True if user has explicitly granted capture consent."""
        return self._is_opted_in

    @property
    def capture_count(self) -> int:
        """Return the total number of frames captured in the current session."""
        return self._capture_count

    @property
    def observation_generator(self) -> ObservationGenerator:
        """Return the underlying ObservationGenerator governed by adapter consent."""
        return self._observation_generator

    @property
    def pending_frames(self) -> List[ScreenContext]:
        """Return a copy of currently pending captured frames."""
        return list(self._pending_frames)

    @property
    def pending_observations(self) -> List[Observation]:
        """Return a copy of currently pending observations."""
        return list(self._pending_observations)

    @property
    def buffered_context(self) -> List[Any]:
        """Return a copy of currently buffered context items."""
        return list(self._buffered_context)

    def opt_in(self) -> None:
        """
        Explicitly grant user consent for screen context capture.
        Must be called prior to invoking capture_frame().
        """
        self._is_opted_in = True

    def opt_out(self) -> None:
        """
        Revoke screen context capture consent immediately and clear all pending context.
        Subsequent capture_frame() calls will fail with CapturePermissionError.
        """
        self._is_opted_in = False
        self.clear_pending()

    def withdraw_consent(self) -> None:
        """
        Explicitly withdraw user capture consent and purge all buffered context.
        Immediately blocks capture, clears pending frames, pending observations,
        and associated buffered context. Re-consent via opt_in() is required to resume.
        """
        self.opt_out()

    def clear_pending(self) -> None:
        """
        Purge all pending frames, pending observations, and buffered context items,
        clearing duplicate-detection state, observation generator state, and resetting rate limits.
        """
        self._pending_frames.clear()
        self._pending_observations.clear()
        self._buffered_context.clear()
        self._last_frame_fingerprint = None
        self._seen_frame_fingerprints.clear()
        self._observation_generator.reset()
        self.reset_rate_limit()

    def add_pending_observation(self, observation: Observation) -> None:
        """Buffer a pending observation."""
        self._pending_observations.append(observation)

    def add_buffered_context(self, item: Any) -> None:
        """Buffer a pending context item."""
        self._buffered_context.append(item)

    def buffer_observation_as_context(
        self,
        observation: Observation,
        item_id: Optional[str] = None,
    ) -> Any:
        """
        Convert an observation to a ContextItem and buffer it in buffered_context.
        Raises CapturePermissionError if consent is not granted.
        """
        if not self._is_opted_in:
            raise CapturePermissionError(
                "Consent has been withdrawn or not granted. Cannot buffer context item."
            )
        item = observation.to_context_item(item_id=item_id)
        self._buffered_context.append(item)
        return item

    def reset_rate_limit(self) -> None:
        """
        Reset the rate-limit timer. Test/demo-only utility; not intended for production usage.
        """
        self._last_capture_time = None

    def create_observation(
        self,
        frame: ScreenContext,
        observation_id: Optional[str] = None,
        content: Optional[str] = None,
        confidence_score: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Observation:
        """
        Generate a traceable, timestamped Observation from a ScreenContext frame
        and buffer it in pending observations.
        """
        if not self._is_opted_in:
            raise CapturePermissionError(
                "Consent has been withdrawn or not granted. Cannot generate observation."
            )
        obs = self._observation_generator.generate_from_screen_frame(
            frame=frame,
            observation_id=observation_id,
            content=content,
            confidence_score=confidence_score,
            metadata=metadata,
        )
        self._pending_observations.append(obs)
        return obs

    def capture_frame(
        self,
        frame_id: Optional[str] = None,
        active_app: str = "VS Code",
        window_title: str = "main.py - Project - Visual Studio Code",
        visible_text: str = "def process():\n    return True",
        width: int = 1920,
        height: int = 1080,
        captured_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ScreenContext:
        """
        Capture a synthetic screen context frame under strict safety checks.
        
        Enforcements:
        1. Explicit Opt-In: Raises CapturePermissionError if not opted in.
        2. Sampling Limit: Raises SamplingLimitError if called faster than max_fps.
        3. Duplicate Frame Check: If configured, rejects consecutive or buffered identical frames.
        4. Freshness & Future Check: Rejects stale frames and future timestamps.
        5. Dimension Boundaries: Validates or clamps width/height to max_width/max_height.
        6. Synthetic Safety: Produces a strictly synthetic ScreenContext where
           capture_enabled=False means real OS screen capture is never engaged in this
           project; is_opted_in tracks user consent. is_synthetic is True.
        
        Returns:
            Validated ScreenContext fixture instance.
        """
        # 1. Permission Gate
        if not self._is_opted_in:
            raise CapturePermissionError(
                "Screen capture is disabled by default. "
                "Explicit user consent is required via adapter.opt_in() before capture can proceed."
            )

        # 2. Sampling Rate Gate
        now = self._clock_fn()
        min_interval = 1.0 / self.config.max_fps
        if self._last_capture_time is not None:
            elapsed = now - self._last_capture_time
            if elapsed < min_interval:
                raise SamplingLimitError(
                    f"Sampling rate limit exceeded. Configured max_fps={self.config.max_fps} "
                    f"requires minimum interval of {min_interval:.4f}s; only {elapsed:.4f}s elapsed."
                )

        # 3. Duplicate Detection Gate across buffered frames
        fingerprint = compute_frame_fingerprint(visible_text, window_title, active_app)
        if self.config.reject_duplicates and (
            fingerprint == self._last_frame_fingerprint or fingerprint in self._seen_frame_fingerprints
        ):
            raise DuplicateFrameError(
                f"Duplicate frame rejected: application '{active_app}', window '{window_title}', "
                "and visible content match a previously buffered frame."
            )

        # 4. Freshness and Future Timestamp Gate
        ref_dt = self._datetime_clock_fn()
        if ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=timezone.utc)

        target_captured_at = captured_at if captured_at is not None else ref_dt
        if target_captured_at.tzinfo is None:
            raise ValueError("captured_at must be a timezone-aware datetime.")

        # Future timestamp check
        future_diff = (target_captured_at - ref_dt).total_seconds()
        if future_diff > self.config.future_tolerance_seconds:
            raise FutureTimestampError(
                f"Frame timestamp is in the future ({future_diff:.2f}s ahead of reference clock)."
            )

        # Stale frame check
        if self.config.max_frame_age_seconds is not None:
            age = (ref_dt - target_captured_at).total_seconds()
            if age > self.config.max_frame_age_seconds:
                raise StaleFrameError(
                    f"Frame age ({age:.2f}s) exceeds maximum allowed freshness ({self.config.max_frame_age_seconds:.2f}s)."
                )

        # 5. Dimension & Text Boundary Gate
        if width > self.config.max_width or height > self.config.max_height:
            if self.config.clamp_dimensions:
                width = min(width, self.config.max_width)
                height = min(height, self.config.max_height)
            else:
                raise ResolutionLimitError(
                    f"Requested frame dimensions ({width}x{height}) exceed maximum allowed boundaries "
                    f"({self.config.max_width}x{self.config.max_height})."
                )

        if visible_text is not None and len(visible_text) > self.config.max_text_length:
            raise TextLimitError(
                f"Requested visible text length ({len(visible_text)}) exceeds maximum allowed boundary "
                f"({self.config.max_text_length})."
            )

        # 6. Generate Synthetic Frame
        actual_frame_id = frame_id or f"frame-optin-{self._capture_count + 1:04d}"
        frame = create_synthetic_screen_frame(
            frame_id=actual_frame_id,
            active_app=active_app,
            window_title=window_title,
            visible_text=visible_text,
            width=width,
            height=height,
            captured_at=target_captured_at,
        )

        # Merge custom metadata if provided while preserving synthetic generator provenance
        if metadata:
            frame.metadata.update(metadata)
        frame.metadata["adapter"] = "OptInCaptureAdapter"
        frame.metadata["max_fps_configured"] = self.config.max_fps
        frame.metadata["fingerprint"] = fingerprint

        # Update adapter internal bookkeeping & buffers
        self._last_capture_time = now
        self._capture_count += 1
        self._last_frame_fingerprint = fingerprint
        self._seen_frame_fingerprints.add(fingerprint)
        self._pending_frames.append(frame)

        return frame

