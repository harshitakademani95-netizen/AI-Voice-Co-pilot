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
       in this project. The capture_enabled field on ScreenContext is always False
       as a safety marker; it does not gate real OS capture (which is never called).
    6. Contract Decoupling: Adapter consent state (is_opted_in) is decoupled from
       ScreenContext.capture_enabled, which remains False at all times as a safety
       marker required by the ScreenContext schema.
"""

import time
from datetime import datetime
from typing import Any, Callable, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field

from src.context.fixtures import create_synthetic_screen_frame
from src.context.schemas import ScreenContext


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
    ):
        """
        Initialize the capture adapter with safe defaults.
        
        Args:
            config: Optional CaptureConfig instance. Defaults to safe baseline.
            clock_fn: Optional monotonic clock function for deterministic rate-limit testing.
        """
        self.config = config or CaptureConfig()
        self._is_opted_in: bool = self.config.enabled_by_default
        self._clock_fn: Callable[[], float] = clock_fn or time.monotonic
        self._last_capture_time: Optional[float] = None
        self._capture_count: int = 0

    @property
    def is_opted_in(self) -> bool:
        """Return True if user has explicitly granted capture consent."""
        return self._is_opted_in

    @property
    def capture_count(self) -> int:
        """Return the total number of frames captured in the current session."""
        return self._capture_count

    def opt_in(self) -> None:
        """
        Explicitly grant user consent for screen context capture.
        Must be called prior to invoking capture_frame().
        """
        self._is_opted_in = True

    def opt_out(self) -> None:
        """
        Revoke screen context capture consent immediately.
        Subsequent capture_frame() calls will fail with CapturePermissionError.
        """
        self._is_opted_in = False

    def reset_rate_limit(self) -> None:
        """Reset the rate-limit timer for testing or session reset."""
        self._last_capture_time = None

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
        3. Dimension Boundaries: Validates or clamps width/height to max_width/max_height.
        4. Synthetic Safety: Produces a strictly synthetic ScreenContext where
           capture_enabled is False (a safety schema marker; real hardware capture
           is never engaged in this project) and is_synthetic is True.
        
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

        # 3. Dimension & Text Boundary Gate
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

        # 4. Generate Synthetic Frame
        actual_frame_id = frame_id or f"frame-optin-{self._capture_count + 1:04d}"
        frame = create_synthetic_screen_frame(
            frame_id=actual_frame_id,
            active_app=active_app,
            window_title=window_title,
            visible_text=visible_text,
            width=width,
            height=height,
            captured_at=captured_at,
        )

        # Merge custom metadata if provided while preserving synthetic generator provenance
        if metadata:
            frame.metadata.update(metadata)
        frame.metadata["adapter"] = "OptInCaptureAdapter"
        frame.metadata["max_fps_configured"] = self.config.max_fps

        # Update adapter internal bookkeeping
        self._last_capture_time = now
        self._capture_count += 1

        return frame

