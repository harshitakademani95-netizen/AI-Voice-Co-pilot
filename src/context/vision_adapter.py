"""
Workstream W3: Context & Reasoning (Week 2 - Day 9)
OCR / Vision Adapter Interface & Mock Implementation

Author: Amruta A J (Team SDE 3)
Module: src.context.vision_adapter
Description:
    Provides an OCR / Vision adapter contract and its deterministic mock implementation.
    Consumes synthetic ScreenContext frames and transforms them into schema-compliant
    ContextItem representations ready for Context Engine reasoning.

    Safety & Architectural Guarantees:
    1. Purely Synthetic: Only processes validated synthetic ScreenContext frames
       (is_synthetic=True, capture_enabled=False).
    2. Zero External Vision Dependencies: Requires zero OCR binaries (Tesseract) or
       heavy CV libraries (OpenCV, TorchVision). Operates 100% offline and locally.
    3. Contract Reusability: Reuses Week 1 ScreenContext, ContextItem, and ContextType schemas.
    4. Determinism: Calling adapter methods twice with identical inputs produces identical outputs.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from src.context.schemas import ContextItem, ContextType, ScreenContext


class BaseVisionAdapter(ABC):
    """
    Abstract contract for OCR and Vision processing adapters.
    
    Transforms raw or simulated visual screen context into structured text
    and downstream ContextItem objects.
    """

    @abstractmethod
    def extract_text(self, frame: ScreenContext) -> str:
        """
        Extract visible text or simulated OCR representations from a ScreenContext frame.

        Args:
            frame: A validated synthetic ScreenContext instance.

        Returns:
            Extracted text content as a string.
        """
        pass

    @abstractmethod
    def to_context_item(
        self,
        frame: ScreenContext,
        item_id: Optional[str] = None,
    ) -> ContextItem:
        """
        Transform a ScreenContext frame into an ingested ContextItem.

        Args:
            frame: A validated synthetic ScreenContext instance.
            item_id: Optional explicit context item identifier.

        Returns:
            Validated ContextItem of type ContextType.SCREEN.
        """
        pass


class MockVisionAdapter(BaseVisionAdapter):
    """
    Deterministic mock implementation of BaseVisionAdapter.
    
    Extracts simulated OCR text from synthetic ScreenContext.visible_text and builds
    schema-validated ContextItem objects without invoking any physical cameras,
    screen capture APIs, or cloud vision services.
    """

    def __init__(self, fallback_text: str = "[No text visible on screen]"):
        """
        Initialize the mock vision adapter.

        Args:
            fallback_text: Default placeholder text when frame.visible_text is None or empty.
        """
        self.fallback_text = fallback_text

    def _validate_frame(self, frame: ScreenContext) -> None:
        """Enforce synthetic-only invariants on incoming frames."""
        if not isinstance(frame, ScreenContext):
            raise TypeError(f"Expected ScreenContext instance, got {type(frame).__name__}")
        if not frame.is_synthetic or frame.capture_enabled:
            raise ValueError(
                "MockVisionAdapter requires synthetic frames only (is_synthetic=True, capture_enabled=False)."
            )

    def extract_text(self, frame: ScreenContext) -> str:
        """
        Extract simulated OCR text from the synthetic frame.
        
        Handles None, empty string, or whitespace-only visible_text safely
        by returning the configured fallback text or cleaned text.
        """
        self._validate_frame(frame)
        if frame.visible_text is not None and frame.visible_text.strip():
            return frame.visible_text.strip()
        return self.fallback_text

    def to_context_item(
        self,
        frame: ScreenContext,
        item_id: Optional[str] = None,
    ) -> ContextItem:
        """
        Convert a ScreenContext frame into a validated ContextItem of type ContextType.SCREEN.
        
        - item_id: Deterministically defaults to f"ctx-vision-{frame.frame_id}".
        - context_type: Strictly ContextType.SCREEN.
        - source: Derived from active_window_title or active_application, defaulting to "Primary Display".
        - content: Cleanly extracted text from extract_text().
        - screen_context: References the validated ScreenContext.
        - timestamp: Preserves frame.captured_at.
        - metadata: Preserves frame metadata, enriched with vision provenance.
        """
        self._validate_frame(frame)

        # 1. Determine Source Name
        source = (
            frame.active_window_title
            or frame.active_application
            or "Primary Display"
        ).strip()
        if not source:
            source = "Primary Display"

        # 2. Extract Content Text
        content = self.extract_text(frame)

        # 3. Construct Metadata (preserving existing keys and adding vision provenance)
        enriched_metadata: Dict[str, Any] = dict(frame.metadata)
        enriched_metadata.update({
            "vision_adapter": "MockVisionAdapter",
            "frame_width": frame.width,
            "frame_height": frame.height,
            "active_application": frame.active_application,
            "active_window_title": frame.active_window_title,
        })

        # 4. Generate Deterministic Item ID
        actual_item_id = item_id or f"ctx-vision-{frame.frame_id}"

        return ContextItem(
            item_id=actual_item_id,
            context_type=ContextType.SCREEN,
            source=source,
            content=content,
            screen_context=frame,
            timestamp=frame.captured_at,
            metadata=enriched_metadata,
        )

